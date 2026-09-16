"""email_tokens rows. Not user-scoped (these flows run pre-login); the table
is outside RLS (ADR 0012). Routes own the commit."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
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
