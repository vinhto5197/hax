"""User queries — the first repo module (M2.5 slice 1).

Repo-layer contract (spec: Isolation): this is the only place the app reads or
writes user rows; emails are normalized to lowercase HERE so every caller gets
case-insensitive semantics without remembering to. Slices 2–3 extend the repo
pattern to conversations/documents/accounts.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import User


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.scalars(
        select(User).where(func.lower(User.email) == email.strip().lower())
    )
    return result.first()


async def get_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def create_password_user(
    session: AsyncSession, email: str, password_hash: str, name: str | None
) -> User:
    user = User(email=email.strip().lower(), password_hash=password_hash, name=name)
    session.add(user)
    # flush not commit: the route owns the transaction boundary.
    await session.flush()
    return user


async def get_sessions_valid_after(
    session: AsyncSession, user_id: uuid.UUID
) -> datetime | None:
    result = await session.execute(
        select(User.sessions_valid_after).where(User.id == user_id)
    )
    row = result.first()
    return row[0] if row else None


async def create_oauth_user(
    session: AsyncSession, email: str, name: str | None
) -> User:
    # Provider-verified email is the only way in here (the route refuses
    # unverified ones), so the account is born verified and passwordless;
    # the reset flow is what later attaches a password.
    user = User(
        email=email.strip().lower(),
        name=name,
        email_verified_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    return user


async def claim_by_verified_email(
    session: AsyncSession, user: User, name: str | None
) -> datetime | None:
    """A provider-verified sign-in claims an existing row for `user.email`.

    Returns the new sessions cutoff when the claim revoked sessions, else None.
    Invariant: a password on a never-verified row was set by an unproven
    party (anyone can sign up with someone else's address before the owner
    does), so the proven owner's claim clears it and revokes its sessions
    rather than inheriting it. Caller must publish the returned cutoff to the
    revocation cache after commit (write-through contract, core/auth/revocation).
    """
    cutoff: datetime | None = None
    if user.email_verified_at is None:
        if user.password_hash is not None:
            user.password_hash = None
            cutoff = datetime.now(UTC)
            user.sessions_valid_after = cutoff
        user.email_verified_at = datetime.now(UTC)
    if user.name is None and name:
        user.name = name
    return cutoff
