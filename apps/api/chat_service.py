import json
from collections.abc import AsyncIterator, Callable
from uuid import UUID

from anthropic.types import MessageParam
from fastapi import HTTPException
from sqlalchemy import func, select, update

from packages.db import AsyncSessionLocal
from packages.db.models import Conversation, Message

# SSE response headers: no-cache so proxies/browsers don't buffer a half-stream;
# keep-alive to hold the connection open for the whole stream.
SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive"}


def sse_event(data: dict) -> str:
    r"""Serialize a dict as one SSE 'data:' line.

    JSON-encoded because content can contain newlines, which would otherwise
    break the SSE event delimiter (\n\n).
    """
    return f"data: {json.dumps(data)}\n\n"


async def persist_user_turn(prompt: str, conversation_id: UUID | None) -> UUID:
    """Resolve or lazily create the conversation, persist the user message,
    and return the conversation id.

    Runs before the LLM call so the user turn survives a model error. Raises
    404 if a conversation_id is supplied but doesn't exist.
    """
    async with AsyncSessionLocal() as session:
        if conversation_id is None:
            conversation = Conversation()
            session.add(conversation)
            await session.flush()  # populate the server-default id via RETURNING
            conversation_id = conversation.id
        elif await session.get(Conversation, conversation_id) is None:
            raise HTTPException(status_code=404, detail="conversation not found")

        session.add(
            Message(conversation_id=conversation_id, role="user", content=prompt)
        )
        await session.commit()

    return conversation_id


async def load_history(conversation_id: UUID) -> list[MessageParam]:
    """Replay the conversation's persisted turns as Anthropic `messages`.

    Called after persist_user_turn, so the just-sent user message is already
    in the table and lands at the end of the list — the array is ready to
    send as-is, no separate append of the current prompt.

    Roles map 1:1 (the DB check constraint allows exactly 'user'/'assistant').
    Consecutive same-role turns are possible (e.g. the LLM errored before
    streaming, so no assistant turn was saved) — the API merges them, so no
    special handling. No windowing yet: the full history is sent every turn
    (bounded-context strategies are an M2 slice 2 concern).
    """
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(Message.role, Message.content)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        return [{"role": role, "content": content} for role, content in rows]


async def persist_assistant_turn(conversation_id: UUID, content: str) -> None:
    """Persist the assistant message and bump the conversation's updated_at.

    Called from the stream's finally block, so it runs on normal completion
    AND on client disconnect — whatever was streamed gets saved. No-ops if
    nothing was streamed (e.g. the LLM errored before producing output).
    """
    if not content:
        return
    async with AsyncSessionLocal() as session:
        session.add(
            Message(conversation_id=conversation_id, role="assistant", content=content)
        )
        # Bump updated_at (drives sidebar ordering). A child-message insert
        # doesn't touch the parent row, so update it explicitly rather than via
        # the relationship; func.now() keeps it on the DB clock like the column
        # default.
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=func.now())
        )
        await session.commit()


async def chat_event_stream(
    stream_fn: Callable[[list[MessageParam]], AsyncIterator[str]],
    messages: list[MessageParam],
    conversation_id: UUID,
) -> AsyncIterator[str]:
    """Wrap an LLM token stream as SSE, persisting the assistant turn at the end.

    Shared by both chat routes — they differ only in `stream_fn` (anthropic SDK
    vs Agent SDK). Emits a conversation-id prelude, one event per token, then
    [DONE], and persists whatever was streamed in a finally (so a client
    disconnect still saves the partial turn).
    """
    # Prelude: tell the client which conversation this is — essential on the
    # first turn, where the client started without an id.
    yield sse_event({"conversation_id": str(conversation_id)})

    buffer: list[str] = []
    try:
        async for chunk in stream_fn(messages):
            buffer.append(chunk)
            yield sse_event({"content": chunk})
        # Terminator the frontend looks for to know the stream is over.
        yield "data: [DONE]\n\n"
    finally:
        # Persist whatever was streamed, even on client disconnect.
        await persist_assistant_turn(conversation_id, "".join(buffer))
