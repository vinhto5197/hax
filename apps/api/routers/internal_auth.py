import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import internal_only
from apps.api.deps import get_session
from apps.api.redis_client import get_redis
from apps.api.routers.auth import client_ip
from packages.core.auth import rate_limit
from packages.core.auth.passwords import dummy_verify_async, verify_password_async
from packages.core.schemas.auth import AuthUserOut, CredentialsIn
from packages.db.repos import users as users_repo

# 404-camouflaged behind internal_only: only Next's server (holding
# INTERNAL_API_SECRET) can reach these — spec: verify-credentials must not be
# a public password oracle.
router = APIRouter(prefix="/internal/auth", dependencies=[Depends(internal_only)])


def _require_verified() -> bool:
    return os.getenv("AUTH_REQUIRE_EMAIL_VERIFICATION", "false").lower() in (
        "1",
        "true",
    )


@router.post("/verify-credentials")
async def verify_credentials(
    body: CredentialsIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AuthUserOut:
    email = body.email.strip().lower()
    ip_ok = await rate_limit.hit(
        get_redis(), "login_ip", client_ip(request), limit=30, window_s=900
    )
    email_ok = await rate_limit.hit(
        get_redis(), "login_email", email, limit=5, window_s=900
    )
    if not (ip_ok and email_ok):
        raise HTTPException(429, detail={"code": "rate_limited"})

    user = await users_repo.get_by_email(session, email)
    if user is None or user.password_hash is None:
        # Unknown email / passwordless account: burn equivalent argon2 work so
        # response timing can't distinguish "no account" from "wrong password".
        await dummy_verify_async(body.password)
        raise HTTPException(401, detail={"code": "invalid_credentials"})
    if not await verify_password_async(user.password_hash, body.password):
        raise HTTPException(401, detail={"code": "invalid_credentials"})
    if _require_verified() and user.email_verified_at is None:
        raise HTTPException(403, detail={"code": "email_unverified"})
    return AuthUserOut(id=user.id, email=user.email, name=user.name)
