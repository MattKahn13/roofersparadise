"""Resend transactional email. Server-side only; key + verified sender come from env.

Returns True on a 2xx, False on any failure -- it never raises, because the alert poller must
not crash on a send error (it records sent_ok=0 and moves on)."""
from __future__ import annotations
import os
import httpx

API = "https://api.resend.com/emails"


def send_email(to: str, subject: str, body: str) -> bool:
    key = os.environ.get("RESEND_API_KEY")
    sender = os.environ.get("RESEND_FROM")
    if not key or not sender or not to:
        return False
    try:
        r = httpx.post(API,
                       json={"from": sender, "to": [to], "subject": subject, "text": body},
                       headers={"Authorization": f"Bearer {key}"}, timeout=20)
        return 200 <= r.status_code < 300
    except Exception:
        return False
