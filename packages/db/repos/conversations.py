"""Conversation + message queries, scoped by owner.

Repo-layer contract: every user-facing query REQUIRES the caller's user_id;
an ownership miss returns None/False/[] and routes map it to 404 (never 403 —
don't confirm existence). add_message/touch take no user_id: messages are only
ever reached through a conversation the caller proved they own earlier in the
same request, and RLS re-checks at the DB.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from packages.db.models import Conversation, Message

# A claim older than this counts as free. A running turn refreshes its claim
# well inside the window (refresh_turn), so the window bounds only how long a
# conversation whose replying process died stays blocked.
TURN_WINDOW = timedelta(minutes=2)


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


async def get_owned_detail(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> tuple[Conversation, bool] | None:
    """The owned conversation with its messages, and whether a reply holds a
    live claim on it; None on an ownership miss.

    `replying` is read in the same SELECT as the conversation row, against
    the database's now() (claim_turn's clock), and the messages load in a
    later statement: a reply saved between the two reads shows up as
    "replying" plus the reply, never as "free with no reply".
    """
    replying = func.coalesce(
        Conversation.streaming_since > func.now() - TURN_WINDOW, False
    )
    result = await session.execute(
        select(Conversation, replying)
        .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .options(selectinload(Conversation.messages))
    )
    row = result.first()
    if row is None:
        return None
    return row[0], bool(row[1])


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
    session: AsyncSession,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    sources: list[dict] | None = None,
    id: uuid.UUID | None = None,
) -> None:
    """`id` None -> the database assigns one. A given id that already exists
    fails the flush with a unique violation."""
    session.add(
        Message(
            id=id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            sources=sources,
        )
    )


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


async def first_user_message(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> str | None:
    """The conversation's first user message — the title task's only input.
    Owner-scoped: a foreign or missing conversation is None."""
    return await session.scalar(
        select(Message.content)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Message.role == "user",
        )
        .order_by(Message.created_at, Message.id)
        .limit(1)
    )


async def set_title_if_unset(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID, title: str
) -> bool:
    """First writer wins: redelivered tasks and duplicate enqueues can't churn
    a title. updated_at is left alone — a title must not reorder the sidebar."""
    result = await session.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.title.is_(None),
        )
        .values(title=title, updated_at=Conversation.updated_at)
        .returning(Conversation.id)
        .execution_options(synchronize_session=False)
    )
    return result.first() is not None


async def claim_turn(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> datetime | None:
    """Mark a reply as in progress; the claimed timestamp, or None when the
    conversation is not the caller's or another reply holds a live claim.

    One conditional UPDATE, so two concurrent claims serialize on the row lock
    and the loser sees the winner's value. The window is compared against the
    database's now(), never the app clock. The caller owns the commit.

    updated_at is pinned in every claim/release statement: its onupdate also
    fires on Core UPDATEs, and it orders the sidebar (touch owns it).
    """
    result = await session.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            (Conversation.streaming_since.is_(None))
            | (Conversation.streaming_since < func.now() - TURN_WINDOW),
        )
        .values(streaming_since=func.now(), updated_at=Conversation.updated_at)
        .returning(Conversation.streaming_since)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none()


async def release_turn(
    session: AsyncSession, conversation_id: uuid.UUID, claimed_at: datetime
) -> None:
    """Clear the claim only if it is still `claimed_at`: a turn whose claim
    lapsed and was re-claimed must not free the newer turn. The caller owns
    the commit."""
    await session.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.streaming_since == claimed_at,
        )
        .values(streaming_since=None, updated_at=Conversation.updated_at)
        .execution_options(synchronize_session=False)
    )


async def refresh_turn(
    session: AsyncSession, conversation_id: uuid.UUID, claimed_at: datetime
) -> datetime | None:
    """Move the claim to the database's now() if it is still `claimed_at`;
    the new value, which the turn MUST keep as its token (release_turn and the
    next refresh compare against it), or None when the claim lapsed and is no
    longer this turn's. The caller owns the commit."""
    result = await session.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.streaming_since == claimed_at,
        )
        .values(streaming_since=func.now(), updated_at=Conversation.updated_at)
        .returning(Conversation.streaming_since)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none()
