"""Google OAuth via authlib + Starlette session cookie. First sign-in creates the account
(users table). Only alerts are gated -- the map is always public.

A test-only /auth/dev_login route (guarded by ALLOW_DEV_LOGIN=1, never set in prod) lets the
suite establish a session without a real Google round-trip.
"""
from __future__ import annotations
import os
from authlib.integrations.starlette_client import OAuth
from starlette.responses import RedirectResponse, JSONResponse
from fastapi import APIRouter, Request

try:                                    # top-level when uvicorn runs from roofersparadise/
    from ingest import store
except ImportError:                     # package-qualified when imported as roofersparadise.app
    from roofersparadise.ingest import store

router = APIRouter()

oauth = OAuth()
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    client_kwargs={"scope": "openid email profile"},
)


def current_user(request: Request):
    return request.session.get("user")


def _db():
    data = os.environ.get("DATA_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data")
    return os.environ.get("APP_DB") or os.path.join(data, "app.db")


@router.get("/auth/login")
async def login(request: Request):
    base = os.environ.get("PUBLIC_BASE_URL") or str(request.base_url).rstrip("/")
    return await oauth.google.authorize_redirect(request, base + "/auth/callback")


@router.get("/auth/callback")
async def callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
        info = token.get("userinfo") or {}
    except Exception:
        return RedirectResponse("/?auth=error")
    uid, email, name = info.get("sub"), info.get("email"), info.get("name")
    if not uid:
        return RedirectResponse("/?auth=error")
    store.init_db(_db())
    store.upsert_user(_db(), uid, email, name)
    request.session["user"] = {"id": uid, "email": email, "name": name}
    return RedirectResponse("/?auth=ok")


@router.post("/auth/logout")
async def logout(request: Request):
    request.session.pop("user", None)
    return {"ok": True}


@router.get("/auth/dev_login")
async def dev_login(request: Request, uid: str = "dev", email: str = "dev@example.com", name: str = "Dev"):
    """Test/dev only. Enabled solely when ALLOW_DEV_LOGIN=1. Creates + signs in a user with no
    Google round-trip so the suite can exercise the authed endpoints."""
    if os.environ.get("ALLOW_DEV_LOGIN") != "1":
        return JSONResponse({"error": "disabled"}, status_code=404)
    store.init_db(_db())
    store.upsert_user(_db(), uid, email, name)
    request.session["user"] = {"id": uid, "email": email, "name": name}
    return {"ok": True, "user": request.session["user"]}
