import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TYPE_CHECKING, TypeVar
from uuid import UUID

from anthropic.types import MessageParam
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from apps.api.enqueue import fire_and_forget
from apps.worker.tasks import generate_title
from packages.db import AsyncSessionLocal
from packages.db.repos import conversations as conversations_repo

if TYPE_CHECKING:
    from apps.api.turns import Turn

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Under the client's 45-second silence limit (apps/web/lib/chatApi.ts), after
# which it treats the connection as lost.
KEEPALIVE_SECONDS = 15

# no-cache: SSE must not be cached/buffered by intermediaries.
SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive"}

# The 409 detail when a conversation already has a reply in progress.
TURN_IN_PROGRESS = "A reply is already in progress in this conversation."
# The 409 detail when the request's message id is already stored.
ALREADY_SENT = "This message was already sent."


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
    prompt: str,
    conversation_id: UUID | None,
    user_id: UUID,
    message_id: UUID | None = None,
) -> tuple[UUID, datetime]:
    """Resolve or lazily create the caller's conversation, claim its turn,
    persist the user message, and return (conversation id, claimed_at).

    Runs before the LLM call so the user turn survives a model error. 404 if
    conversation_id isn't owned by user_id — the write-path ownership gate
    (a foreign id and a nonexistent one are indistinguishable); 409 if another
    reply holds the conversation's claim, or if `message_id` is already
    stored (a duplicate send). Claim, ownership check and message commit or
    roll back together, so a refused turn leaves no trace. The
    caller MUST hand claimed_at to start_turn (whose task saves or releases)
    or release_claim; otherwise the claim holds until TURN_WINDOW lapses.

    A newly created conversation is queued for titling here, not after the
    reply: the title is generated from the first user message alone, so it can
    land while the reply still streams.
    """
    created = conversation_id is None
    async with AsyncSessionLocal() as session:
        if conversation_id is None:
            conversation = await conversations_repo.create(session, user_id)
            conversation_id = conversation.id
        claimed_at = await conversations_repo.claim_turn(
            session, user_id, conversation_id
        )
        if claimed_at is None:
            if (
                await conversations_repo.get_owned(session, user_id, conversation_id)
                is None
            ):
                raise HTTPException(status_code=404, detail="conversation not found")
            raise HTTPException(status_code=409, detail=TURN_IN_PROGRESS)

        await conversations_repo.add_message(
            session, conversation_id, "user", prompt, id=message_id
        )
        try:
            # Bumps the sidebar order now, not when the reply is saved. Inside
            # the try: the UPDATE autoflushes the message, so a duplicate id
            # can fail here as well as at the commit.
            await conversations_repo.touch(session, conversation_id)
            await session.commit()
        except IntegrityError:
            # The user message is the transaction's only insert that can
            # collide: its client-chosen id. The rollback drops the claim and
            # any conversation created above.
            if message_id is None:
                raise
            raise HTTPException(status_code=409, detail=ALREADY_SENT) from None

    if created:
        _enqueue_title(conversation_id, user_id)
    return conversation_id, claimed_at


async def load_history(conversation_id: UUID, user_id: UUID) -> list[MessageParam]:
    """Replay the conversation's persisted turns as Anthropic `messages`.

    Called after persist_user_turn (which owns the ownership check), so the
    just-sent user message lands last. Consecutive same-role turns (a failed
    reply stores no assistant turn, so a resend follows its own question) are
    merged here, joined by a blank line, so the history alternates for any
    provider. Full history every turn — no windowing in v0.
    """
    async with AsyncSessionLocal() as session:
        rows = await conversations_repo.load_history(session, user_id, conversation_id)
    history: list[MessageParam] = []
    for role, content in rows:
        if history and history[-1]["role"] == role:
            history[-1]["content"] = f"{history[-1]['content']}\n\n{content}"
        else:
            history.append({"role": role, "content": content})
    return history


async def persist_assistant_turn(
    conversation_id: UUID,
    user_id: UUID,
    content: str,
    sources: list[dict] | None = None,
    *,
    claimed_at: datetime,
) -> None:
    """Release the turn's claim and persist the assistant message (text +
    sources), bumping updated_at, in one transaction — "reply saved" and
    "conversation free" cannot disagree.

    Called only by the turn's task (apps/api/turns.py), on a clean finish:
    a stored reply is always complete. The claim is always released; the
    message is written only if something streamed — sources alone are not a
    turn. `claimed_at` is the claim's latest value, after any refresh.
    `sources` is the deduplicated provenance from the turn's searches; it is
    stored for the client and never replayed to the model.

    user_id is needed for the title task: the worker has no request to take an
    identity from, so the owner rides the Celery payload and the task announces
    it for RLS. A title that is still NULL here means the creation-time enqueue
    never produced one, so this turn queues it again.
    """
    untitled = False
    async with AsyncSessionLocal() as session:
        await conversations_repo.release_turn(session, conversation_id, claimed_at)
        if content:
            await conversations_repo.add_message(
                session, conversation_id, "assistant", content, sources=sources or None
            )
            await conversations_repo.touch(session, conversation_id)
            conversation = await conversations_repo.get_owned(
                session, user_id, conversation_id
            )
            untitled = conversation is not None and conversation.title is None
        await session.commit()

    if untitled:
        _enqueue_title(conversation_id, user_id)


async def release_claim(conversation_id: UUID, claimed_at: datetime) -> None:
    """Release a claim with nothing stored: the route's error path before
    start_turn, and a turn that failed, hit its deadline or was cancelled."""
    async with AsyncSessionLocal() as session:
        await conversations_repo.release_turn(session, conversation_id, claimed_at)
        await session.commit()


async def event_stream(turn: "Turn", conversation_id: UUID) -> AsyncIterator[str]:
    """Listen to a running turn as SSE: the conversation-id prelude, every
    event the turn yields, then [DONE] when the reply is saved and the claim
    released, or {"error": "reply_failed"} (a fixed code, never an exception's
    text) when it ended with nothing stored.

    Only listens: it never saves or releases. A disconnect or cancellation
    detaches it and the turn carries on. While the turn is silent (the model
    thinking, a slow tool) an SSE comment goes out every KEEPALIVE_SECONDS,
    so a live connection is never silent long enough for a client to take it
    for a lost one; clients ignore comment lines.
    """
    # Prelude: tells the client its conversation id (server-created on turn 1).
    yield sse_event({"conversation_id": str(conversation_id)})
    events = turn.listen()
    # One pending read carried across keepalives: a timeout must not cancel
    # the read itself, which would close the listen generator.
    pending: asyncio.Task | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(_next(events))
            done, _ = await asyncio.wait({pending}, timeout=KEEPALIVE_SECONDS)
            if not done:
                yield ": keepalive\n\n"
                continue
            item = pending.result()
            pending = None
            if item == "done":
                yield "data: [DONE]\n\n"
                return
            if item == "failed":
                yield sse_event({"error": "reply_failed"})
                return
            yield sse_event(item)
    finally:
        if pending is not None:
            pending.cancel()


async def _next(events: AsyncIterator[T]) -> T:
    return await anext(events)
