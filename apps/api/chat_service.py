import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from uuid import UUID

import anyio
from anthropic.types import MessageParam
from fastapi import HTTPException

from apps.worker.tasks import generate_title
from packages.db import AsyncSessionLocal
from packages.db.repos import conversations as conversations_repo

logger = logging.getLogger(__name__)

# no-cache: SSE must not be cached/buffered by intermediaries.
SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive"}


# --- Title enqueue ---------------------------------------------------------
# Publishing a Celery task is a BLOCKING network call to the broker: about a
# millisecond when it is healthy, seconds when it is unreachable. This module
# runs on the event loop, on every chat turn, so the publish is handed off
# twice before it touches the network:
#   1. _enqueue_title -> an asyncio task, so the request never waits for it;
#   2. that task -> a _publisher thread, so the event loop never blocks on it.
# The thread pushes the message to the broker; the worker process picks it up
# from there. Nothing here generates a title.

# A pool of its own: the default executor also runs password hashing and
# storage I/O, and stuck publishes must never be able to starve those. The
# threads wait on the network, not the CPU, so the size does not track core
# count — it bounds how many publishes can be stuck at once in this process.
_publisher = ThreadPoolExecutor(
    max_workers=int(os.getenv("ENQUEUE_THREADS", "2")),
    thread_name_prefix="title-publish",
)
# Beyond this many waiting publishes the broker is down, not slow: drop instead
# of queueing without bound. The next persisted assistant turn re-enqueues.
MAX_PENDING_ENQUEUES = int(os.getenv("ENQUEUE_MAX_PENDING", "100"))
# In-flight publishes only: each task removes itself when it finishes. The set
# exists because the loop holds only weak references to tasks, so one that
# nothing else references can be collected mid-flight. Process-wide and touched
# only from the event-loop thread.
_pending_enqueues: set[asyncio.Task[None]] = set()


async def _publish_title_task(conversation_id: UUID, user_id: UUID) -> None:
    publish = partial(
        generate_title.apply_async,
        args=(str(conversation_id), str(user_id)),
        retry=False,  # the re-enqueue on a later turn is the retry
    )
    try:
        await asyncio.get_running_loop().run_in_executor(_publisher, publish)
    except Exception as exc:
        logger.warning(
            "title enqueue failed for %s: %s", conversation_id, type(exc).__name__
        )


def _enqueue_title(conversation_id: UUID, user_id: UUID) -> None:
    """Hand titling to the worker without making the request wait for it.
    Callers MUST be past the commit: the task reads the first user message
    from Postgres, and the worker can see only committed rows.

    Fire-and-forget: neither the first token nor the end of a stream may wait
    on the broker. Never fatal: a lost or dropped enqueue only costs a title
    until the next persisted assistant turn, which re-enqueues while the title
    is still NULL. Logs the exception TYPE only — the payload and the
    surrounding turn carry user content.
    """
    if len(_pending_enqueues) >= MAX_PENDING_ENQUEUES:
        logger.warning("title enqueue dropped for %s: backlog full", conversation_id)
        return
    task = asyncio.create_task(_publish_title_task(conversation_id, user_id))
    _pending_enqueues.add(task)
    task.add_done_callback(_pending_enqueues.discard)


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
