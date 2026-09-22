import os
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_session
from apps.api.enqueue import fire_and_forget
from apps.api.redis_client import get_redis
from apps.worker.tasks import send_email
from packages.core.auth import rate_limit
from packages.core.auth.email_tokens import (
    RESET_PASSWORD_TTL,
    VERIFY_EMAIL_TTL,
    expiry,
    generate,
    hash_token,
)
from packages.core.auth.passwords import hash_password_async
from packages.core.auth.revocation import publish_sva
from packages.core.schemas.auth import (
    AcceptedOut,
    EmailIn,
    EmailOut,
    ResetPasswordIn,
    SignupIn,
    TokenIn,
    TokenStatusOut,
)
from packages.db.models import User
from packages.db.repos import email_tokens as tokens_repo
from packages.db.repos import users as users_repo

router = APIRouter(prefix="/auth", tags=["auth"])


def client_ip(request: Request) -> str:
    # Direct-connect dev value. M3 note (spec): behind the proxy this must come
    # from X-Forwarded-For or every visitor shares one bucket.
    return request.client.host if request.client else "unknown"


def app_base_url() -> str:
    return os.getenv("APP_BASE_URL", "http://localhost:3000").rstrip("/")


# purpose -> (token lifetime, web path the emailed link opens)
_LINKS: dict[str, tuple[timedelta, str]] = {
    "verify_email": (VERIFY_EMAIL_TTL, "/verify-email"),
    "reset_password": (RESET_PASSWORD_TTL, "/reset-password"),
}


async def _issue_link(session: AsyncSession, user: User, purpose: str) -> str:
    ttl, path = _LINKS[purpose]
    raw, token_hash = generate()
    await tokens_repo.create(session, user.id, purpose, token_hash, expiry(ttl))
    return f"{app_base_url()}{path}?token={raw}"


async def _spend_token(session: AsyncSession, raw: str, purpose: str) -> User:
    """Token -> its user, spending the token. ONE uniform 400 for every
    failure — used / expired / wrong-purpose / unknown, a vanished user, or
    losing the race to a concurrent confirm — indistinguishable to the caller
    by design. consume() spends `raw`'s token and voids the user's other live
    tokens of the purpose in one statement (one lock order, no deadlock)."""
    token = await tokens_repo.get_valid(session, hash_token(raw), purpose)
    user = await users_repo.get_by_id(session, token.user_id) if token else None
    if token is None or user is None or not await tokens_repo.consume(session, token):
        raise HTTPException(400, detail={"code": "invalid_token"})
    return user


def _mail(to: str, template: str, params: dict[str, str]) -> None:
    """Queue one outgoing email. Every caller MUST be past the commit — the
    link it carries is only real once its token row is committed.

    The routes here are uniform-202 anti-enumeration surfaces, so the publish
    can neither raise nor be waited on. The template, never the address, is
    what the publisher may log.
    """
    fire_and_forget(send_email, to, template, params, log_ref=template)


def _account_exists_outgoing(email: str) -> tuple[str, str, dict[str, str]]:
    return (
        email,
        "account_exists",
        {
            "login_url": f"{app_base_url()}/login",
            "reset_url": f"{app_base_url()}/forgot-password",
        },
    )


async def _limit(
    request: Request,
    name: str,
    *,
    per_ip: int,
    window_s: int,
    email: str | None = None,
    per_email: int | None = None,
) -> None:
    # IP checked first and short-circuits: a flooding IP must not also burn a
    # victim's per-email budget by touching that bucket on its way to 429.
    if not await rate_limit.hit(
        get_redis(), f"{name}_ip", client_ip(request), limit=per_ip, window_s=window_s
    ):
        raise HTTPException(429, detail="too many requests; try again later")
    if email is not None:
        if per_email is None:
            raise ValueError("per_email is required when email is given")
        if not await rate_limit.hit(
            get_redis(), f"{name}_email", email, limit=per_email, window_s=window_s
        ):
            raise HTTPException(429, detail="too many requests; try again later")


@router.post("/signup", status_code=202)
async def signup(
    body: SignupIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AcceptedOut:
    email = body.email.strip().lower()
    # Per-email cap (3/h) bounds outgoing mail for one address; every branch
    # below sends exactly one email.
    await _limit(request, "signup", per_ip=10, window_s=3600, email=email, per_email=3)
    # Decide the email BEFORE commit, send it AFTER: a failed commit must never
    # mail a link whose token doesn't exist. Response is identical in all cases.
    outgoing: tuple[str, str, dict[str, str]]
    cutoff = None
    # Hash on EVERY branch (timing): an existing address must cost the same
    # argon2 work as a new one, or response time says which it is.
    password_hash = await hash_password_async(body.password)
    user = await users_repo.get_by_email(session, email)
    if user is None:
        user = await users_repo.create_password_user(
            session, email, password_hash, body.name
        )
        outgoing = (
            email,
            "verify_email",
            {"link": await _issue_link(session, user, "verify_email")},
        )
    elif user.email_verified_at is not None:
        outgoing = _account_exists_outgoing(email)
    else:
        # Unverified placeholder (fresh or stale): the last submitter owns the
        # pending password — verification is by link alone, so keeping an
        # earlier, unproven password would let this signup verify it.
        # Tokens before users: every writer takes locks in the same order as
        # consume() → no deadlock between a re-signup and a Confirm.
        await tokens_repo.void_unused(session, user.id, "verify_email")
        cutoff = await users_repo.replace_pending_password(
            session, user, password_hash, body.name
        )
        if cutoff is None:
            # A concurrent verify won the race: the row is now an existing,
            # verified account, so this submission is treated the same as
            # the verified branch — no new link for an account that's no
            # longer pending.
            outgoing = _account_exists_outgoing(email)
        else:
            outgoing = (
                email,
                "verify_email",
                {"link": await _issue_link(session, user, "verify_email")},
            )
    await session.commit()
    if cutoff is not None:
        await publish_sva(get_redis(), user.id, cutoff)
    _mail(*outgoing)
    return AcceptedOut()


@router.post("/resend-verification", status_code=202)
async def resend_verification(
    body: EmailIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AcceptedOut:
    # Resend re-sends whatever signup would have sent for this address;
    # existence never leaks (uniform 202), the inbox owner just gets a
    # useful email.
    email = body.email.strip().lower()
    await _limit(request, "resend", per_ip=10, window_s=3600, email=email, per_email=3)
    user = await users_repo.get_by_email(session, email)
    if user is None or (user.email_verified_at is None and user.password_hash is None):
        # Unknown address, or an unverified bootstrap placeholder with no
        # password yet: nothing to resend.
        return AcceptedOut()
    if user.email_verified_at is not None:
        _mail(*_account_exists_outgoing(email))
        return AcceptedOut()
    # Same invariant as signup: void earlier links first so the new one is
    # the only live verify link for this user.
    await tokens_repo.void_unused(session, user.id, "verify_email")
    link = await _issue_link(session, user, "verify_email")
    await session.commit()
    _mail(email, "verify_email", {"link": link})
    return AcceptedOut()


@router.post("/verify-email", responses={400: {"description": "invalid_token"}})
async def verify_email(
    body: TokenIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> EmailOut:
    # Token alone identifies the account, so this is IP-only (no email to
    # bucket on before the token is looked up).
    await _limit(request, "verify", per_ip=10, window_s=900)
    user = await _spend_token(session, body.token, "verify_email")
    await users_repo.mark_email_verified(session, user)
    await session.commit()
    return EmailOut(email=user.email)


@router.post("/request-password-reset", status_code=202)
async def request_password_reset(
    body: EmailIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AcceptedOut:
    email = body.email.strip().lower()
    await _limit(
        request, "reset_request", per_ip=10, window_s=3600, email=email, per_email=3
    )
    user = await users_repo.get_by_email(session, email)
    if user is None:
        return AcceptedOut()
    # Same invariant as signup/resend: void earlier links first so the new
    # one is the only live reset link for this user.
    await tokens_repo.void_unused(session, user.id, "reset_password")
    # Google-born accounts (no password) get the link too: this IS how they
    # add a password.
    link = await _issue_link(session, user, "reset_password")
    await session.commit()
    _mail(email, "reset_password", {"link": link})
    return AcceptedOut()


@router.post("/reset-password/check", responses={400: {"description": "invalid_token"}})
async def check_reset_password(
    body: TokenIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TokenStatusOut:
    # Read-only precheck so a page can show "invalid or expired" on load;
    # consumption happens only on the user's click (mail scanners pre-fetch
    # links).
    await _limit(request, "token_check", per_ip=30, window_s=900)
    token = await tokens_repo.get_valid(
        session, hash_token(body.token), "reset_password"
    )
    if token is None:
        raise HTTPException(400, detail={"code": "invalid_token"})
    return TokenStatusOut()


@router.post("/reset-password", responses={400: {"description": "invalid_token"}})
async def reset_password(
    body: ResetPasswordIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> EmailOut:
    await _limit(request, "reset_confirm", per_ip=10, window_s=900)
    user = await _spend_token(session, body.token, "reset_password")
    cutoff = await users_repo.reset_password(
        session, user, await hash_password_async(body.password)
    )
    await session.commit()
    await publish_sva(get_redis(), user.id, cutoff)
    # Inbox proof: the owner just set this password, so the guessing limiter
    # must not block the login that follows.
    await rate_limit.clear(get_redis(), "login_email", user.email)
    return EmailOut(email=user.email)
