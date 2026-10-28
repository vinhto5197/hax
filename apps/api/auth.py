"""Request authentication for the API.

current_user is the single enforcement point: cookie (web) or
Authorization: Bearer (tests and non-browser clients) -> for a cookie write,
the same-origin check -> pinned-alg JWT decode
-> revocation check -> CurrentUser. No DB read on the hot path (Redis only;
DB only on cache miss). internal_only guards the server-to-server endpoints
Next calls (verify-credentials, oauth-upsert, anonymous) — a wrong or missing
secret answers 404, not 403. (The route table itself is public: a wrong
method or a malformed body is answered by the framework before this runs.
In production Caddy never routes /internal/* at all.)
"""

import hmac
import os
import uuid
from urllib.parse import urlsplit

from fastapi import Header, HTTPException, Request
from pydantic import BaseModel

from apps.api.redis_client import get_redis
from packages.core.auth.revocation import session_revoked
from packages.core.auth.tokens import InvalidSessionToken, decode_session_token
from packages.db import AsyncSessionLocal
from packages.db.repos import users as users_repo
from packages.db.user_context import current_user_id

COOKIE_NAME_ENV = "AUTH_COOKIE_NAME"
_DEFAULT_COOKIE = "authjs.session-token"


class CurrentUser(BaseModel):
    id: uuid.UUID
    # None = an anonymous demo visitor (the only marker of one).
    email: str | None


def _auth_secret() -> str:
    secret = os.getenv("AUTH_SECRET", "")
    if not secret:
        # Fail loud on first request rather than quietly accepting nothing.
        raise RuntimeError("AUTH_SECRET is not set")
    return secret


def extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(os.getenv(COOKIE_NAME_ENV, _DEFAULT_COOKIE))


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _allowed_origins() -> set[str]:
    # The origins hax's own pages are served from: the CORS allowlist (dev and
    # the journey stack put the web on another port of the same host) and the
    # app's base URL (production is one origin behind Caddy). Read per request,
    # like the CORS list, so tests and deploys need no restart to change them.
    allowed = {o for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o}
    base = urlsplit(os.getenv("APP_BASE_URL", ""))
    if base.scheme and base.netloc:
        allowed.add(f"{base.scheme}://{base.netloc}")
    return allowed


def _refuse_cross_site_cookie_write(request: Request) -> None:
    """403 for a write the login cookie authenticates unless the browser says it
    came from hax's own pages. SameSite=Lax already keeps the cookie off other
    sites' background requests; this is the second layer, for a page on the
    same site (another subdomain), which Lax lets through. Browsers send
    Sec-Fetch-Site on every request; Origin is the fallback. A cookie write
    with neither signal is refused: no browser sends that, and a non-browser
    client authenticates with a Bearer token, which never reaches here."""
    if request.method in _SAFE_METHODS:
        return
    if request.headers.get("sec-fetch-site") in ("same-origin", "none"):
        return
    origin = request.headers.get("origin")
    if origin and origin in _allowed_origins():
        return
    raise HTTPException(status_code=403, detail="cross-site request refused")


async def _fetch_sva(user_id: uuid.UUID):
    async with AsyncSessionLocal() as session:
        return await users_repo.get_sessions_valid_after(session, user_id)


async def current_user(request: Request) -> CurrentUser:
    token = extract_token(request)
    if token is not None and not request.headers.get(
        "authorization", ""
    ).lower().startswith("bearer "):
        _refuse_cross_site_cookie_write(request)
    if token is None:
        raise HTTPException(
            status_code=401,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_session_token(token, _auth_secret())
    except InvalidSessionToken:
        raise HTTPException(
            status_code=401,
            detail="invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if await session_revoked(get_redis(), claims, _fetch_sva):
        raise HTTPException(
            status_code=401,
            detail="session revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Announce identity for this request's DB work (RLS). Each request runs in
    # its own asyncio task with its own context, so no cross-request bleed and
    # no reset needed; the SSE stream + its finally run in this same task.
    current_user_id.set(claims.sub)
    return CurrentUser(id=claims.sub, email=claims.email)


async def internal_only(x_internal_secret: str = Header(default="")) -> None:
    # Server-to-server auth for endpoints only our Next server may call (e.g.
    # verify-credentials, a password oracle that current_user cannot protect:
    # its callers aren't logged in yet). Identity = possession of
    # INTERNAL_API_SECRET, shared by the two services' environments; rejection
    # is a 404 indistinguishable from a nonexistent route.
    expected = os.getenv("INTERNAL_API_SECRET", "")
    if not expected or not hmac.compare_digest(
        x_internal_secret.encode("latin-1"), expected.encode()
    ):
        raise HTTPException(status_code=404, detail="Not Found")
