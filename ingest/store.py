"""Data access for users, alert subscriptions, and sent-alert dedup.

Backend-pluggable so the SAME code serves local dev and free-cloud hosting:
  - default: a local SQLite file (path passed in, so tests use a temp DB).
  - Turso (libSQL) when TURSO_DATABASE_URL is set -- a free, SQLite-compatible cloud DB the
    web app AND the GitHub Actions alert poller can both reach (free web hosts have ephemeral
    disk, so accounts cannot live in a local file in production).

The SQL is identical either way (libSQL is SQLite). Only the connection differs. Rows are
returned as plain dicts (built from cursor.description) so neither backend needs row_factory.

Accounts are created on first Google sign-in; subscriptions are the ZIPs a roofer watches;
alerts_sent gives the poller its cooldown/dedup and powers each user's alert history.
"""
from __future__ import annotations
import os, sqlite3, secrets, datetime as dt

# --- connection layer (the only backend-specific code) -----------------------------------

def _use_turso() -> bool:
    return bool(os.environ.get("TURSO_DATABASE_URL"))


def _connect(db):
    """A DB-API connection. Turso (libSQL) when TURSO_DATABASE_URL is set, else local SQLite.
    Both expose execute()/commit()/close() and cursors with description + fetchall()."""
    if _use_turso():
        import libsql_experimental as libsql   # optional dep; only imported on the cloud path
        return libsql.connect(database=os.environ["TURSO_DATABASE_URL"],
                              auth_token=os.environ.get("TURSO_AUTH_TOKEN"))
    return sqlite3.connect(db)


def _rows(cur):
    cols = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _write(db, sql, params=()):
    c = _connect(db)
    try:
        c.execute(sql, params)
        c.commit()
    finally:
        c.close()


def _read(db, sql, params=()):
    c = _connect(db)
    try:
        return _rows(c.execute(sql, params))
    finally:
        c.close()


# --- schema ------------------------------------------------------------------------------

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users(
         id TEXT PRIMARY KEY, email TEXT, name TEXT, created_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS subscriptions(
         id TEXT PRIMARY KEY, user_id TEXT, zip TEXT, lat REAL, lng REAL,
         radius_mi REAL DEFAULT 15, channel TEXT DEFAULT 'email',
         active INTEGER DEFAULT 1, created_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS alerts_sent(
         id TEXT PRIMARY KEY, sub_id TEXT, user_id TEXT, fired_at TEXT,
         storm_ts TEXT, max_in REAL, n_cells INTEGER, sent_ok INTEGER)""",
    "CREATE INDEX IF NOT EXISTS ix_subs_user ON subscriptions(user_id, active)",
    "CREATE INDEX IF NOT EXISTS ix_alerts_sub ON alerts_sent(sub_id, fired_at)",
]


def init_db(db: str) -> None:
    c = _connect(db)
    try:
        for stmt in _SCHEMA:      # one statement at a time -- works on SQLite and libSQL alike
            c.execute(stmt)
        c.commit()
    finally:
        c.close()


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


# --- users -------------------------------------------------------------------------------

def upsert_user(db, uid, email, name):
    _write(db, """INSERT INTO users(id,email,name,created_at) VALUES(?,?,?,?)
                  ON CONFLICT(id) DO UPDATE SET email=excluded.email, name=excluded.name""",
           (uid, email, name, _now()))


def user_email(db, user_id):
    r = _read(db, "SELECT email FROM users WHERE id=?", (user_id,))
    return r[0]["email"] if r else None


# --- subscriptions -----------------------------------------------------------------------

def add_subscription(db, user_id, zip_, lat, lng, radius_mi=15.0, channel="email"):
    sid = secrets.token_hex(6)
    _write(db, """INSERT INTO subscriptions(id,user_id,zip,lat,lng,radius_mi,channel,active,created_at)
                  VALUES(?,?,?,?,?,?,?,1,?)""",
           (sid, user_id, zip_, float(lat), float(lng), float(radius_mi), channel, _now()))
    return sid


def subscriptions_for_user(db, user_id):
    return _read(db, "SELECT * FROM subscriptions WHERE user_id=? AND active=1 ORDER BY created_at DESC",
                 (user_id,))


def active_subscriptions(db):
    return _read(db, "SELECT * FROM subscriptions WHERE active=1")


def delete_subscription(db, sid, user_id):
    _write(db, "UPDATE subscriptions SET active=0 WHERE id=? AND user_id=?", (sid, user_id))


# --- alerts ------------------------------------------------------------------------------

def recently_alerted(db, sub_id, now, hours=3.0):
    r = _read(db, "SELECT fired_at FROM alerts_sent WHERE sub_id=? ORDER BY fired_at DESC LIMIT 1",
              (sub_id,))
    if not r or not r[0]["fired_at"]:
        return False
    try:
        last = dt.datetime.fromisoformat(r[0]["fired_at"])
        if last.tzinfo is None:
            last = last.replace(tzinfo=dt.timezone.utc)
        return (now - last).total_seconds() < hours * 3600
    except Exception:
        return False


def record_alert(db, sub_id, user_id, storm_ts, max_in, n_cells, sent_ok, fired_at=None):
    _write(db, """INSERT INTO alerts_sent(id,sub_id,user_id,fired_at,storm_ts,max_in,n_cells,sent_ok)
                  VALUES(?,?,?,?,?,?,?,?)""",
           (secrets.token_hex(8), sub_id, user_id, fired_at or _now(), storm_ts,
            float(max_in), int(n_cells), int(sent_ok)))


def alerts_for_user(db, user_id, limit=25):
    return _read(db, "SELECT * FROM alerts_sent WHERE user_id=? ORDER BY fired_at DESC LIMIT ?",
                 (user_id, int(limit)))
