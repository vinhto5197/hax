"""email_tokens rows. Not user-scoped (these flows run pre-login); the table
is outside RLS (ADR 0012). Routes own the commit."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import update
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


async def void_unused(session: AsyncSession, user_id: uuid.UUID, purpose: str) -> None:
    await session.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user_id,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
        )
        .values(used_at=datetime.now(UTC))
    )
