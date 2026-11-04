"""email_tokens rows. Not user-scoped (these flows run pre-login); the table
is outside RLS (ADR 0012). Routes own the commit. Rows are deleted once dead
by the daily sweep (apps/worker/tasks.py::sweep_email_tokens)."""

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import EmailToken


async def create(
    session: AsyncSession,
    user_id: uuid.UUID,
    purpose: str,
    token_hash: str,
    expires_at: datetime,
) -> EmailToken:
    token = EmailToken(
        user_id=user_id, purpose=purpose, token_hash=token_hash, expires_at=expires_at
    )
    session.add(token)
    return token


async def void_unused(
    session: AsyncSession, user_id: uuid.UUID, purpose: str
) -> set[uuid.UUID]:
    """Void every live token of `purpose` for `user_id` in ONE statement and
    return the ids it voided. Issuing paths call it before creating a new
    token (one live link per purpose); consume() reuses it so spending a
    token and sweeping its siblings share one statement and one lock order."""
    result = await session.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user_id,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
        )
        .values(used_at=datetime.now(UTC))
        .returning(EmailToken.id)
    )
    return {row[0] for row in result}


async def get_valid(
    session: AsyncSession, token_hash: str, purpose: str
) -> EmailToken | None:
    result = await session.scalars(
        select(EmailToken).where(
            EmailToken.token_hash == token_hash,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
            EmailToken.expires_at > func.now(),
        )
    )
    return result.first()


async def consume(session: AsyncSession, token: EmailToken) -> bool:
    """Spend `token`: True iff this call voided it (a concurrent confirm with
    the same or a sibling link loses — the DB arbitrates, not a check-then-set)."""
    return token.id in await void_unused(session, token.user_id, token.purpose)


async def delete_dead(session: AsyncSession, *, limit: int) -> int:
    """Delete up to `limit` rows get_valid() can no longer return; returns how
    many went. The predicate is get_valid's exact complement on the same
    database clock, so a worker clock ahead of the database can never delete a
    live link. SKIP LOCKED: a row a request holds (void_unused also locks
    expired unused rows) is left for the next run, so the sweep never waits on
    a request, never hits lock_timeout, and cannot join a deadlock. The caller
    owns the commit."""
    dead = (
        select(EmailToken.id)
        .where(
            or_(EmailToken.used_at.is_not(None), EmailToken.expires_at <= func.now())
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    # A DELETE always executes to a CursorResult; the session's signature
    # only promises the Result base, which has no rowcount.
    result = cast(
        CursorResult[Any],
        await session.execute(
            delete(EmailToken)
            .where(EmailToken.id.in_(dead))
            .execution_options(synchronize_session=False)
        ),
    )
    return result.rowcount
