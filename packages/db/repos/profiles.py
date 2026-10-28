"""A member's note about themselves, scoped by owner (required user_id; the
row's RLS policy binds it as well). The caller owns the transaction. The note
is user content: never log it."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import UserProfile


async def get_about(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    return await session.scalar(
        select(UserProfile.about).where(UserProfile.user_id == user_id)
    )


async def set_about(
    session: AsyncSession, user_id: uuid.UUID, about: str
) -> str | None:
    """Store `about` stripped, or delete the note when that leaves nothing;
    returns what is stored (None when deleted). Length and NUL are the
    schema's to refuse; the CHECK constraint backs the cap."""
    about = about.strip()
    if not about:
        await session.execute(delete(UserProfile).where(UserProfile.user_id == user_id))
        return None
    stmt = insert(UserProfile).values(user_id=user_id, about=about)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[UserProfile.user_id], set_={"about": stmt.excluded.about}
        )
    )
    return about
