"""User queries.

Repo-layer contract: this is the only place the app reads or writes user rows;
emails are normalized to lowercase HERE so every caller gets case-insensitive
semantics without remembering to.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
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


async def mark_email_verified(session: AsyncSession, user: User) -> None:
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)


async def replace_pending_password(
    session: AsyncSession, user: User, password_hash: str, name: str | None
) -> datetime | None:
    """A signup on a never-verified row takes it over: the earlier password
    was never proven (verification is by link alone, so the LAST submitter
    must own the pending password or a victim's own signup could verify a
    stranger's), so it's replaced and its sessions revoked. Conditional on
    the row STILL being unverified at write time — a concurrent verify wins
    and this returns None (caller treats the row as an existing account).
    Returns the new cutoff otherwise; caller publishes it after commit."""
    cutoff = datetime.now(UTC)
    values = {"password_hash": password_hash, "sessions_valid_after": cutoff}
    if name:
        values["name"] = name
    result = await session.execute(
        update(User)
        .where(User.id == user.id, User.email_verified_at.is_(None))
        .values(**values)
        .returning(User.id)
        .execution_options(synchronize_session=False)
    )
    if result.first() is None:
        return None
    # Expire rather than assign: `user` was loaded before this UPDATE ran, so
    # setting attributes here would mark it dirty against that stale snapshot
    # and cost a redundant second UPDATE at flush/commit. Expiring instead
    # means a later access re-reads what we just wrote, with no extra write
    # and no extra query unless something actually touches the object again.
    session.expire(user, list(values.keys()))
    return cutoff


async def reset_password(
    session: AsyncSession, user: User, password_hash: str
) -> datetime:
    """Inbox-proven password set. Stamps verified if NULL (the link proved
    the inbox) and revokes every prior session — a stolen token must not
    outlive a reset. Returns the cutoff; caller publishes it after commit."""
    cutoff = datetime.now(UTC)
    user.password_hash = password_hash
    user.sessions_valid_after = cutoff
    if user.email_verified_at is None:
        user.email_verified_at = cutoff
    return cutoff
