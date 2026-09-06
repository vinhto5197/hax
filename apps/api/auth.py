"""Request authentication for the API.

current_user is the single enforcement point (spec: Flows): cookie (web) or
Authorization: Bearer (tests now, mobile in v1) -> pinned-alg JWT decode ->
revocation check -> CurrentUser. No DB read on the hot path (Redis only;
DB only on cache miss). internal_only guards the server-to-server endpoints
Next calls (verify-credentials) — it 404s, not 403s, so probing can't even
learn the routes exist.
"""

import hmac
import os
import uuid

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
    email: str


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


async def _fetch_sva(user_id: uuid.UUID):
    async with AsyncSessionLocal() as session:
        return await users_repo.get_sessions_valid_after(session, user_id)


async def current_user(request: Request) -> CurrentUser:
    token = extract_token(request)
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
