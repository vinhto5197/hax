import json
from collections.abc import AsyncIterator, Callable
from uuid import UUID

import anyio
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
            # flush, not commit: emit the INSERT so the DB fills the
            # server-default id (via RETURNING), keeping conversation + message in
            # ONE atomic transaction (the commit below covers both). Committing
            # here would also expire id under the default expire_on_commit=True,
            # and the un-awaited lazy reload on the next read would MissingGreenlet.
            await session.flush()
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


async def event_stream(
    stream_fn: Callable[[list[MessageParam]], AsyncIterator[str | dict]],
    messages: list[MessageParam],
    conversation_id: UUID,
) -> AsyncIterator[str]:
    """Wrap an LLM stream as SSE, persisting the assistant turn at the end.

    `stream_fn` may yield either plain text tokens or the agentic harness's
    structured events ({"content": …} text deltas and {"status": …} tool-activity
    notes) — a bare text token is normalized to a content event, so one wrapper
    serves any stream shape. Today's sole consumer is /api/chat (the agentic
    harness); the tolerance for plain-text streams is kept so a future non-agentic
    stream_fn plugs in unchanged. Emits a conversation-id prelude, forwards each event,
    then [DONE]. Only content is accumulated and persisted as the assistant turn;
    status events are forwarded to the client but NOT persisted (transient UI
    activity, not conversation text). The agentic harness's per-turn tool_use /
    tool_result blocks are never persisted either — Postgres stays the canonical,
    replayable *text* history.
    """
    # Prelude: tell the client which conversation this is — essential on the
    # first turn, where the client started without an id.
    yield sse_event({"conversation_id": str(conversation_id)})

    buffer: list[str] = []
    try:
        async for item in stream_fn(messages):
            event = {"content": item} if isinstance(item, str) else item
            if "content" in event:
                buffer.append(event["content"])
            yield sse_event(event)
        # Terminator the frontend looks for to know the stream is over.
        yield "data: [DONE]\n\n"
    finally:
        # Persist whatever was streamed, even on client disconnect. On disconnect
        # Starlette cancels the anyio scope wrapping this stream; that cancellation
        # is level-triggered, so the FIRST await inside persist_assistant_turn
        # (acquiring a pooled connection / committing) would re-raise CancelledError
        # and drop the write — silently defeating this exact guarantee. A shielded
        # scope lets the DB write run to completion before the cancellation
        # propagates out.
        with anyio.CancelScope(shield=True):
            await persist_assistant_turn(conversation_id, "".join(buffer))
