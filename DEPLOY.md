# RoofersParadise -- free deploy (no credit card)

The genuinely-free, always-free stack chosen 2026-07-26. Nothing here needs a credit card.
(The old Fly.io path is kept as a fallback at the bottom.)

```
 Render (free web host, Docker)  --reads/writes-->  Turso (free SQLite-compatible DB: accounts + subscriptions)
        ^   serves map + auth + alerts UI                     ^
        |   (hail Parquet baked into image)                   |
 GitHub Actions ---- keep-warm ping every ~12 min ------------+
        |
        +-- alert-poller  (every ~10 min: live MRMS -> Turso subs -> Resend email)
        +-- daily-refresh (06:30 UTC: ingest new day -> commit Parquet -> Render redeploys)
```

Why this shape: free web hosts sleep and have ephemeral disk, so (a) accounts live in Turso, not a local file, and (b) the poller + daily refresh run in GitHub Actions, not in-process. A keep-warm ping stops the host sleeping so the map stays instant.

## What Matt provisions (I open each window; you sign in / paste keys -- I can't create accounts or enter keys)

1. **GitHub repo** -- a public repo holding this `roofersparadise/` folder's contents at the root (code + `data/hail` + `.github/workflows`). Public = unlimited free Actions.
2. **Turso** (turso.tech) -- create a DB; copy its URL (`libsql://...`) and an auth token. No card.
3. **Render** (render.com) -- New > Blueprint, point at the repo (uses `render.yaml`). No card on free.
4. **Google Cloud OAuth client** (console.cloud.google.com) -- OAuth 2.0 Client (Web). Authorized redirect URI: `https://<render-url>/auth/callback`. Copy client ID + secret. No card.
5. **Resend** (already have) -- API key + a verified sending domain -> `RESEND_FROM`.
6. **Domain** -- optional for launch (use the `onrender.com` URL first); needed for Resend's verified sender + a branded URL.

## Secrets to set

**Render** (dashboard > Environment), matching `render.yaml`:
`PUBLIC_BASE_URL` (the Render URL), `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `RESEND_API_KEY`, `RESEND_FROM`. (`SESSION_SECRET` auto-generates; `ENABLE_WORKERS=0` and `DATA_DIR=/data` are preset.)

**GitHub repo** (Settings > Secrets and variables > Actions): `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `RESEND_API_KEY`, `RESEND_FROM`, `PUBLIC_BASE_URL`.

## Deploy sequence

1. Push this folder's contents to the repo root; confirm `data/hail/` is included (committed for the deploy -- see `.gitignore`).
2. In Render, create the Blueprint from the repo; set the env vars above; deploy. First boot runs `start.sh`, seeding `/data` from the baked hail data.
3. Smoke test: `GET /healthz` = ok; the map loads; `GET /api/dates` returns storm days; Google sign-in works; add a ZIP; run the **alert-poller** workflow manually (`workflow_dispatch`) and confirm it polls against Turso.
4. The schedules then run automatically (scheduled workflows fire only on the default branch).

## Local dev / tests

No Turso needed: leave `TURSO_*` blank and `store.py` uses a local SQLite file (`DATA_DIR/app.db`). From `roofersparadise/`: `python -m pytest -q`, or `ENABLE_WORKERS=0 uvicorn app:app --port 8010` for map-only.

## Fallbacks

- Cold starts too slow -> Oracle Cloud Always-Free VM (always-on; a card is required for identity verification only, no charges), running the same container with a bind-mounted `/data` and `ENABLE_WORKERS=1` (then drop the poller/refresh Actions).
- Fly.io (`fly.toml`, ~$2-5/mo always-on): `fly launch --no-deploy` -> `fly volume create rp_data --size 1` -> `fly secrets set ...` -> `fly deploy`. Uses the persistent volume + in-process scheduler.
