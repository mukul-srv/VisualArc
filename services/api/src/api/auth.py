"""Accounts: email+password and GitHub/Google OAuth, with server-side sessions.

Session cookie = random 32-byte token; only its SHA-256 is stored (sessions.id), so a DB
leak cannot be replayed. Logout deletes the row (revocation). `current_user` is the guard
dependency for every other /api/v1 router. Ownership checks are NOT here (subtask 03).
"""

import hashlib
import os
import re
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode, urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select

from api.access import claim_invites
from api.db import OAuthAccountRow, SessionRow, UserRow, session
from api.storage import new_id

router = APIRouter(prefix="/api/v1/auth")

COOKIE = "session"
SESSION_DAYS = 30
MIN_PASSWORD = 10
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_hasher = PasswordHasher()
# verified against when the email is unknown, so timing does not reveal whether it exists
_DUMMY_HASH = _hasher.hash("not-a-real-password")


# ---- sessions ---------------------------------------------------------------------------


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id: str) -> str:
    """Store a new session for the user and return the raw cookie token."""
    token = secrets.token_urlsafe(32)
    with session() as db:
        db.add(
            SessionRow(
                id=_digest(token),
                user_id=user_id,
                expires_at=datetime.now(UTC) + timedelta(days=SESSION_DAYS),
            )
        )
        db.commit()
    return token


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("AUTH_COOKIE_SECURE", "").lower() in ("1", "true", "yes"),
        path="/",
    )


def optional_user(request: Request) -> UserRow | None:
    try:
        return current_user(request)
    except HTTPException:
        return None


def current_user(request: Request) -> UserRow:
    """FastAPI guard: the user owning a live session cookie, else 401."""
    token = request.cookies.get(COOKIE)
    if token:
        with session() as db:
            row = db.get(SessionRow, _digest(token))
            if row is not None and row.expires_at > datetime.now(UTC):
                user = db.get(UserRow, row.user_id)
                if user is not None:
                    return user
            if row is not None:  # expired: tidy up
                db.delete(row)
                db.commit()
    raise HTTPException(401, "not authenticated")

CurrentUser = Annotated[UserRow, Depends(current_user)]


# ---- rate limit -------------------------------------------------------------------------

_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    # The web app proxies /api/* and appends the real client as the LAST X-Forwarded-For
    # entry. Spoofable if the API is exposed directly; fine behind the proxy.
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[-1].strip() if fwd else (request.client.host if request.client else "?")


def rate_limit(request: Request) -> None:
    # shortcut: in-process, per-IP sliding window; each worker counts separately and a
    # restart resets it. Use a shared store (Redis/Postgres) when running several workers.
    limit = int(os.environ.get("AUTH_RATE_LIMIT_PER_MIN", "10"))
    now = time.monotonic()
    hits = _hits[_client_ip(request)]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= limit:
        raise HTTPException(429, "too many attempts; try again in a minute")
    hits.append(now)


# ---- models -----------------------------------------------------------------------------


def _norm_email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 254 or not _EMAIL.match(v):
        raise ValueError("invalid email address")
    return v


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    password: str = Field(max_length=1024)

    _email = field_validator("email")(lambda cls, v: _norm_email(v))


class RegisterRequest(Credentials):
    password: str = Field(min_length=MIN_PASSWORD, max_length=1024)
    display_name: str | None = Field(None, min_length=1, max_length=100)


class ProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(None, min_length=1, max_length=100)
    current_password: str | None = Field(None, max_length=1024)
    new_password: str | None = Field(None, min_length=MIN_PASSWORD, max_length=1024)


def _user_out(u: UserRow) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "display_name": u.display_name,
        "has_password": u.password_hash is not None,
    }


def _login_response(user: UserRow, status_code: int = 200) -> Response:
    resp = JSONResponse(_user_out(user), status_code=status_code)
    _set_cookie(resp, create_session(user.id))
    return resp


# ---- password endpoints -----------------------------------------------------------------


@router.post("/register", status_code=201, dependencies=[Depends(rate_limit)])
def register(req: RegisterRequest):
    user = UserRow(
        id=new_id(),
        email=req.email,
        password_hash=_hasher.hash(req.password),
        display_name=(req.display_name or req.email.split("@")[0]).strip(),
    )
    with session() as db:
        if db.scalar(select(UserRow.id).where(UserRow.email == req.email)):
            raise HTTPException(409, "an account with this email already exists")
        db.add(user)
        db.flush()
        claim_invites(db, user)
        db.commit()
    return _login_response(user, 201)


@router.post("/login", dependencies=[Depends(rate_limit)])
def login(req: Credentials):
    with session() as db:
        user = db.scalar(select(UserRow).where(UserRow.email == req.email))
    # one generic failure for unknown email, OAuth-only account and wrong password
    stored = user.password_hash if user and user.password_hash else _DUMMY_HASH
    try:
        ok = _hasher.verify(stored, req.password) and stored is not _DUMMY_HASH
    except (VerificationError, InvalidHashError):
        ok = False
    if not ok or user is None:
        raise HTTPException(401, "invalid email or password")
    return _login_response(user)


@router.post("/logout", status_code=204)
def logout(request: Request):
    token = request.cookies.get(COOKIE)
    if token:
        with session() as db:
            db.execute(delete(SessionRow).where(SessionRow.id == _digest(token)))
            db.commit()
    resp = Response(status_code=204)
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router.get("/me")
def me(user: CurrentUser):
    return _user_out(user)


@router.patch("/profile")
def update_profile(req: ProfileRequest, request: Request, user: CurrentUser):
    with session() as db:
        row = db.get(UserRow, user.id)
        if req.new_password is not None:
            # an OAuth-only account has no password to confirm, so it may set its first one
            if row.password_hash is not None:
                try:
                    good = req.current_password is not None and _hasher.verify(
                        row.password_hash, req.current_password
                    )
                except (VerificationError, InvalidHashError):
                    good = False
                if not good:
                    raise HTTPException(400, "current password is incorrect")
            row.password_hash = _hasher.hash(req.new_password)
            # a password change signs out every other device
            keep = _digest(request.cookies.get(COOKIE, ""))
            db.execute(delete(SessionRow).where(SessionRow.user_id == row.id, SessionRow.id != keep))
        if req.display_name is not None:
            row.display_name = req.display_name.strip()
        db.commit()
        return _user_out(row)


# ---- OAuth ------------------------------------------------------------------------------

PROVIDERS = {
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "access_token_url": "https://github.com/login/oauth/access_token",
        "api_base_url": "https://api.github.com/",
        "client_kwargs": {"scope": "read:user user:email"},
    },
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "access_token_url": "https://oauth2.googleapis.com/token",
        "api_base_url": "https://openidconnect.googleapis.com/v1/",
        "client_kwargs": {"scope": "openid email profile"},
    },
}


def _creds(provider: str) -> tuple[str, str] | None:
    p = provider.upper()
    cid, secret = os.environ.get(f"{p}_CLIENT_ID"), os.environ.get(f"{p}_CLIENT_SECRET")
    return (cid, secret) if cid and secret else None


def configured_providers() -> dict[str, bool]:
    return {p: _creds(p) is not None for p in PROVIDERS}


def _web_base() -> str:
    return os.environ.get("WEB_BASE_URL", "http://localhost:3000").rstrip("/")


def _client(provider: str):
    """Authlib client for a configured provider; 404 unknown, 503 not configured."""
    if provider not in PROVIDERS:
        raise HTTPException(404, "unknown provider")
    creds = _creds(provider)
    if creds is None:
        raise HTTPException(
            503,
            f"{provider} login is not configured: set {provider.upper()}_CLIENT_ID and "
            f"{provider.upper()}_CLIENT_SECRET on the API",
        )
    oauth = OAuth()  # cheap; built per request so env changes apply without a restart
    oauth.register(name=provider, client_id=creds[0], client_secret=creds[1], **PROVIDERS[provider])
    return getattr(oauth, provider)


@dataclass
class OAuthProfile:
    provider_user_id: str
    email: str | None
    email_verified: bool
    name: str | None


async def fetch_profile(provider: str, request: Request) -> OAuthProfile:
    """Exchange the callback code for a token and read the provider profile.
    The only network-touching step; tests replace it."""
    client = _client(provider)
    token = await client.authorize_access_token(request)
    if provider == "google":
        info = (await client.get("userinfo", token=token)).json()
        return OAuthProfile(
            str(info["sub"]), info.get("email"), bool(info.get("email_verified")), info.get("name")
        )
    user = (await client.get("user", token=token)).json()
    emails = (await client.get("user/emails", token=token)).json()
    primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
    return OAuthProfile(
        str(user["id"]), primary["email"] if primary else None, primary is not None,
        user.get("name") or user.get("login"),
    )


def _safe_next(value: str | None) -> str:
    # same-site relative path only, so the callback cannot redirect off-site
    if not value or "\\" in value or "%5c" in value.lower() or not value.startswith("/") or value.startswith("//"):
        return "/"
    parts = urlsplit(value)
    return value if not parts.scheme and not parts.netloc else "/"


@router.get("/providers")
def providers():
    return configured_providers()


@router.get("/oauth/{provider}/login")
async def oauth_login(provider: str, request: Request, next: str | None = None):
    client = _client(provider)
    request.session["next"] = _safe_next(next)
    redirect_uri = f"{_web_base()}/api/v1/auth/oauth/{provider}/callback"
    return await client.authorize_redirect(request, redirect_uri)


def _fail(message: str) -> RedirectResponse:
    return RedirectResponse(f"/login?{urlencode({'error': message})}", status_code=302)


def user_for_profile(provider: str, p: OAuthProfile) -> UserRow | str:
    """The account for this provider identity: existing link, else an existing OAuth-only
    user with the same VERIFIED email (linked), else a new OAuth-only user. Returns an
    error code instead when there is no verified email ("no_verified_email") or the email
    belongs to a password account ("email_exists"): register never verifies email, so
    auto-linking there would allow pre-account takeover."""
    with session() as db:
        link = db.scalar(
            select(OAuthAccountRow).where(
                OAuthAccountRow.provider == provider,
                OAuthAccountRow.provider_user_id == p.provider_user_id,
            )
        )
        if link is not None:
            return db.get(UserRow, link.user_id)
        if not p.email or not p.email_verified:
            return "no_verified_email"
        email = p.email.strip().lower()
        user = db.scalar(select(UserRow).where(UserRow.email == email))
        if user is not None and user.password_hash is not None:
            return "email_exists"
        if user is None:
            user = UserRow(
                id=new_id(), email=email, password_hash=None,
                display_name=(p.name or email.split("@")[0]).strip()[:100],
            )
            db.add(user)
            db.flush()
            claim_invites(db, user)
        db.add(OAuthAccountRow(
            id=new_id(), provider=provider, provider_user_id=p.provider_user_id, user_id=user.id
        ))
        db.commit()
        return user


@router.get("/oauth/{provider}/callback", dependencies=[Depends(rate_limit)])
async def oauth_callback(provider: str, request: Request):
    _client(provider)  # 404/503 before anything else
    try:
        profile = await fetch_profile(provider, request)
    except Exception:  # noqa: BLE001  bad/denied/expired code, provider outage: back to the login page
        return _fail(f"{provider} sign-in failed")
    user = user_for_profile(provider, profile)
    if isinstance(user, str):
        return _fail(user)
    resp = RedirectResponse(_safe_next(request.session.pop("next", "/")), status_code=302)
    _set_cookie(resp, create_session(user.id))
    return resp
