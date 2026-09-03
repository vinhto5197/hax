"""Conversation + message queries, scoped by owner (M2.5 slice 2).

Repo-layer contract (spec: Isolation): every user-facing query REQUIRES the
caller's user_id; an ownership miss returns None/False/[] and routes map it to
404 (never 403 — don't confirm existence). add_message/touch take no user_id:
messages are only ever reached through a conversation the caller proved they
own earlier in the same request; RLS re-checks at the DB from slice 2 on.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from packages.db.models import Conversation, Message


async def list_for_user(
    session: AsyncSession, user_id: uuid.UUID
) -> Sequence[Conversation]:
    result = await session.scalars(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
    )
    return result.all()


async def get_owned(
    session: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    with_messages: bool = False,
) -> Conversation | None:
    stmt = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id
    )
    if with_messages:
        # selectinload: second query, avoids a lazy load in async context.
        stmt = stmt.options(selectinload(Conversation.messages))
    result = await session.scalars(stmt)
    return result.first()


async def create(session: AsyncSession, user_id: uuid.UUID) -> Conversation:
    conversation = Conversation(user_id=user_id)
    session.add(conversation)
    # flush, not commit: fills the server-default id; the caller owns the
    # transaction boundary.
    await session.flush()
    return conversation


async def delete_owned(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> bool:
    conversation = await get_owned(session, user_id, conversation_id)
    if conversation is None:
        return False
    # Messages go via ON DELETE CASCADE (passive_deletes on the model).
    await session.delete(conversation)
    return True


async def add_message(
    session: AsyncSession, conversation_id: uuid.UUID, role: str, content: str
) -> None:
    session.add(Message(conversation_id=conversation_id, role=role, content=content))


async def touch(session: AsyncSession, conversation_id: uuid.UUID) -> None:
    """Bump updated_at (drives sidebar ordering) — a child insert doesn't
    touch the parent row."""
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=func.now())
    )


async def load_history(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> list[tuple[str, str]]:
    """(role, content) turns, oldest first. Owner-scoped via join even though
    callers verify ownership first — an unowned id yields []."""
    rows = await session.execute(
        select(Message.role, Message.content)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.conversation_id == conversation_id,
            Conversation.user_id == user_id,
        )
        .order_by(Message.created_at)
    )
    return [(role, content) for role, content in rows]
