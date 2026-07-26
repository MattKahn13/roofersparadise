"""Drain fired hail alerts into a send-ready email outbox -- the alert last mile.

Reads alerts.jsonl (written by live_alerts.py), formats each NEW alert into an email for the
subscribed roofer, and appends to outbox.jsonl as {to, subject, body}. A watermark
(_notified.json) prevents re-sending the same alert.

This does NOT send email itself, by design: dispatch is handed to the gmail-selenium-sender
(MattKahn13/gmail-selenium-sender), which sends from matt@jameswaydata via a dedicated Chrome
profile. Separating the formatter from the sender means no message goes out without Matt running
the sender on his own authenticated profile. SMS (the channel roofers actually open) plugs in the
same way -- point a provider at outbox.jsonl.

  python -m roofersparadise.ingest.notify      # drain new alerts -> outbox.jsonl
"""
import os, json, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
ALERTS = os.path.join(DATA, "alerts.jsonl")
OUTBOX = os.path.join(DATA, "outbox.jsonl")
SENT = os.path.join(DATA, "_notified.json")


def _key(a):
    return f"{a.get('sub_id')}|{a.get('fired_at')}"


def format_email(a):
    zip_ = a.get("zip") or "your area"
    subj = f"Hail alert: up to {a['max_in']}\" just hit {zip_}"
    body = (f"Hail up to {a['max_in']} inches was just detected in {zip_} within the last hour "
            f"({a['n_cells']} radar impact cells nearby).\n\n"
            f"This is your window -- get there before the competition does.\n\n"
            f"-- RoofersParadise\nBuilt from free NOAA MRMS radar data. Reply STOP to unsubscribe.")
    return subj, body


def drain():
    if not os.path.exists(ALERTS):
        print("no alerts yet"); return 0
    sent = set(json.load(open(SENT))) if os.path.exists(SENT) else set()
    alerts = [json.loads(l) for l in open(ALERTS, encoding="utf-8") if l.strip()]
    new = 0
    for a in alerts:
        k = _key(a)
        if k in sent or not a.get("email"):
            continue
        subj, body = format_email(a)
        rec = {"to": a["email"], "subject": subj, "body": body, "alert": k,
               "queued_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        open(OUTBOX, "a", encoding="utf-8").write(json.dumps(rec) + "\n")
        sent.add(k); new += 1
    tmp = SENT + ".tmp"; json.dump(sorted(sent), open(tmp, "w")); os.replace(tmp, SENT)
    print(f"queued {new} new email(s) -> {OUTBOX}")
    if new:
        print("NEXT: run the gmail-selenium-sender on outbox.jsonl to deliver (needs Matt's Chrome profile).")
    return new


if __name__ == "__main__":
    drain()
