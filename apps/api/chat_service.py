import json
import logging
from collections.abc import AsyncIterator, Callable
from uuid import UUID

import anyio
from anthropic.types import MessageParam
from fastapi import HTTPException

from apps.api.enqueue import fire_and_forget
from apps.worker.tasks import generate_title
from packages.db import AsyncSessionLocal
from packages.db.repos import conversations as conversations_repo

logger = logging.getLogger(__name__)

# no-cache: SSE must not be cached/buffered by intermediaries.
SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive"}


def _enqueue_title(conversation_id: UUID, user_id: UUID) -> None:
    """Hand titling to the worker without making the request wait for it.
    Callers MUST be past the commit: the task reads the first user message
    from Postgres, and the worker can see only committed rows.

    Neither the first token nor the end of a stream may wait on the broker,
    and a lost publish only costs a title until the next persisted assistant
    turn, which re-enqueues while the title is still NULL — so this is the
    fire-and-forget hand-off, never the awaited one.
    """
    cid = str(conversation_id)
    fire_and_forget(generate_title, cid, str(user_id), log_ref=cid)


def sse_event(data: dict) -> str:
    r"""One SSE 'data:' line. JSON-encoded — raw newlines would break the \n\n
    event delimiter."""
    return f"data: {json.dumps(data)}\n\n"


async def persist_user_turn(
    prompt: str, conversation_id: UUID | None, user_id: UUID
) -> UUID:
    """Resolve or lazily create the caller's conversation, persist the user
    message, and return the conversation id.

    Runs before the LLM call so the user turn survives a model error. 404 if
    conversation_id isn't owned by user_id — the write-path ownership gate
    (a foreign id and a nonexistent one are indistinguishable).

    A newly created conversation is queued for titling here, not after the
    reply: the title is generated from the first user message alone, so it can
    land while the reply still streams.
    """
    created = conversation_id is None
    async with AsyncSessionLocal() as session:
        if conversation_id is None:
            conversation = await conversations_repo.create(session, user_id)
            conversation_id = conversation.id
        elif (
            await conversations_repo.get_owned(session, user_id, conversation_id)
            is None
        ):
            raise HTTPException(status_code=404, detail="conversation not found")

        await conversations_repo.add_message(session, conversation_id, "user", prompt)
        await session.commit()

    if created:
        _enqueue_title(conversation_id, user_id)
    return conversation_id


async def load_history(conversation_id: UUID, user_id: UUID) -> list[MessageParam]:
    """Replay the conversation's persisted turns as Anthropic `messages`.

    Called after persist_user_turn (which owns the ownership check), so the
    just-sent user message lands last. Consecutive same-role turns can occur
    (an errored turn saves no assistant reply); the API merges them. Full
    history every turn — no windowing in v0.
    """
    async with AsyncSessionLocal() as session:
        rows = await conversations_repo.load_history(session, user_id, conversation_id)
    return [{"role": role, "content": content} for role, content in rows]


async def persist_assistant_turn(
    conversation_id: UUID, user_id: UUID, content: str
) -> None:
    """Persist the assistant message and bump the conversation's updated_at.

    Runs from the stream's finally, so completion AND disconnect both save
    whatever streamed. No-ops if nothing was streamed.

    user_id is needed for the title task: the worker has no request to take an
    identity from, so the owner rides the Celery payload and the task announces
    it for RLS. A title that is still NULL here means the creation-time enqueue
    never produced one, so this turn queues it again.
    """
    if not content:
        return
    async with AsyncSessionLocal() as session:
        await conversations_repo.add_message(
            session, conversation_id, "assistant", content
        )
        await conversations_repo.touch(session, conversation_id)
        conversation = await conversations_repo.get_owned(
            session, user_id, conversation_id
        )
        untitled = conversation is not None and conversation.title is None
        await session.commit()

    if untitled:
        _enqueue_title(conversation_id, user_id)


async def event_stream(
    stream_fn: Callable[[list[MessageParam]], AsyncIterator[str | dict]],
    messages: list[MessageParam],
    conversation_id: UUID,
    user_id: UUID,
) -> AsyncIterator[str]:
    """Wrap an LLM stream as SSE, persisting the assistant turn at the end.

    `stream_fn` may yield plain text tokens or structured events ({"content": …}
    deltas, {"status": …} tool-activity notes); bare tokens are normalized to
    content events. Emits a conversation-id prelude, forwards every event, then
    [DONE]. Only content is buffered and persisted as the assistant turn —
    status events (and the harness's tool_use/tool_result blocks) never reach
    Postgres, which stays the canonical replayable *text* history.
    """
    # Prelude: tells the client its conversation id (server-created on turn 1).
    yield sse_event({"conversation_id": str(conversation_id)})

    buffer: list[str] = []
    try:
        async for item in stream_fn(messages):
            event = {"content": item} if isinstance(item, str) else item
            if "content" in event:
                buffer.append(event["content"])
            yield sse_event(event)
        yield "data: [DONE]\n\n"
    finally:
        # Persist even on client disconnect. Disconnect cancels the surrounding
        # anyio scope, and that cancellation is level-triggered — the first await
        # inside an unshielded persist would re-raise CancelledError and drop the
        # write. The shield lets the DB write complete before cancellation
        # propagates.
        with anyio.CancelScope(shield=True):
            await persist_assistant_turn(conversation_id, user_id, "".join(buffer))
