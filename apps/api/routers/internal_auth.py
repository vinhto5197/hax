import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import internal_only
from apps.api.deps import get_session
from apps.api.redis_client import get_redis
from apps.api.routers.auth import client_ip
from packages.core.auth import rate_limit
from packages.core.auth.passwords import dummy_verify_async, verify_password_async
from packages.core.auth.revocation import publish_sva
from packages.core.schemas.auth import (
    AnonymousOut,
    AuthUserOut,
    CredentialsIn,
    OAuthUpsertIn,
)
from packages.db.models import User
from packages.db.repos import accounts as accounts_repo
from packages.db.repos import users as users_repo

# 404 without the secret (internal_only); verify-credentials must never be a
# public password oracle.
router = APIRouter(prefix="/internal/auth", dependencies=[Depends(internal_only)])


def _visitor_ip(request: Request) -> str:
    """The browser's address as Next's server saw it (X-Visitor-IP, from
    Caddy's X-Forwarded-For); trusted because this router is reachable only
    with the internal secret. Without it a per-address limit would key on
    Next's own address and every caller would share one bucket."""
    return request.headers.get("x-visitor-ip") or client_ip(request)


def _require_verified() -> bool:
    return os.getenv("AUTH_REQUIRE_EMAIL_VERIFICATION", "true").lower() in (
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
        get_redis(), "login_ip", _visitor_ip(request), limit=30, window_s=900
    )
    email_ok = await rate_limit.hit(
        get_redis(), "login_email", email, limit=5, window_s=900
    )
    if not (ip_ok and email_ok):
        raise HTTPException(429, detail={"code": "rate_limited"})

    user = await users_repo.get_by_email(session, email)
    found = (
        None
        if user is None
        else AuthUserOut(
            id=user.id, email=users_repo.member_email(user), name=user.name
        )
    )
    password_hash = user.password_hash if user else None
    unverified = user is not None and user.email_verified_at is None
    # The read is done: end its transaction before argon2's tens of
    # milliseconds, so the hash never holds a pooled connection. Rollback
    # expires `user`, hence the copies above.
    await session.rollback()
    if found is None or password_hash is None:
        # Unknown email / passwordless account: burn equivalent argon2 work so
        # response timing can't distinguish "no account" from "wrong password".
        await dummy_verify_async(body.password)
        raise HTTPException(401, detail={"code": "invalid_credentials"})
    if not await verify_password_async(password_hash, body.password):
        raise HTTPException(401, detail={"code": "invalid_credentials"})
    if _require_verified() and unverified:
        raise HTTPException(403, detail={"code": "email_unverified"})
    # Only failures should add up: a member signing in on several devices
    # must not lock themselves out. The per-address count stays, so spraying
    # many accounts from one place is still capped.
    await rate_limit.clear(get_redis(), "login_email", email)
    return found


async def _resolve_oauth_user(
    session: AsyncSession, body: OAuthUpsertIn
) -> tuple[User, datetime | None]:
    email = body.email.strip().lower()
    user = await accounts_repo.get_user_by_account(
        session, body.provider, body.provider_account_id
    )
    if user is not None:
        # The linked identity wins even if Google now reports a different
        # email: email is the hax identity key and is never rewritten here.
        return user, None
    if not body.email_verified:
        # Fail closed against OAuth account takeover: an unverified provider
        # email proves nothing about who controls the mailbox, so it may
        # neither attach to an existing account nor reserve the address.
        raise HTTPException(403, detail={"code": "email_unverified"})
    user = await users_repo.get_by_email(session, email)
    cutoff = None
    if user is None:
        user = await users_repo.create_oauth_user(session, email, body.name)
    else:
        cutoff = await users_repo.claim_by_verified_email(user, body.name)
    await accounts_repo.link(session, user.id, body.provider, body.provider_account_id)
    return user, cutoff


@router.post(
    "/oauth-upsert",
    responses={403: {"description": "provider email unverified; nothing linked"}},
)
async def oauth_upsert(
    body: OAuthUpsertIn,
    session: AsyncSession = Depends(get_session),
) -> AuthUserOut:
    try:
        user, cutoff = await _resolve_oauth_user(session, body)
        await session.commit()
    except IntegrityError:
        # Lost a first-sign-in race: a concurrent request inserted the same
        # (provider, provider_account_id) or the same email between our lookup
        # and our INSERT. Postgres holds the colliding INSERT until the winner
        # commits, so once this fires the winner's rows are visible and one
        # re-run of the lookups resolves to them.
        await session.rollback()
        user, cutoff = await _resolve_oauth_user(session, body)
        await session.commit()
    if cutoff is not None:
        # Publish AFTER commit: the cache must never lead the DB, or a reader
        # could see "revoked" for a cutoff that a crash then rolled back.
        await publish_sva(get_redis(), user.id, cutoff)
    return AuthUserOut(id=user.id, email=users_repo.member_email(user), name=user.name)


def _anon_per_ip_per_day() -> int:
    return int(os.getenv("ANON_PER_IP_PER_DAY", "3"))


@router.post(
    "/anonymous",
    responses={429: {"description": "too many demo visitors from this address"}},
)
async def create_anonymous(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AnonymousOut:
    """A demo visitor: a user row with no email."""
    if not await rate_limit.hit(
        get_redis(),
        "anon_ip",
        _visitor_ip(request),
        limit=_anon_per_ip_per_day(),
        window_s=86400,
    ):
        raise HTTPException(429, detail={"code": "rate_limited"})
    user = await users_repo.create_anonymous(session)
    await session.commit()
    return AnonymousOut(id=user.id)
