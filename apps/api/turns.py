"""A chat reply as a server task that outlives the request that started it.

Contract with the route and its listener (chat_service.event_stream): the
route claims the turn and calls start_turn before it returns the response; the
task alone owns the turn's end — saving the reply and releasing the claim —
and the request only listens. A listener that goes away (disconnect,
cancellation) detaches; the task carries on and the reply is still saved.

A stored reply is always complete: a model failure, the turn deadline, or a
cancellation (drain_turns at shutdown) stores nothing and releases the claim.

The registry is the only strong reference to a running task (the event loop
holds tasks weakly), so a turn whose request is gone is not collected
mid-reply. Turns live in the process that started them; a returning client
learns the outcome from Postgres (`replying` on the conversation), so any
process can answer it.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Literal, TypeVar
from uuid import UUID

from anthropic.types import MessageParam

from apps.api import chat_service
from packages.db import AsyncSessionLocal
from packages.db.repos import conversations as conversations_repo

logger = logging.getLogger(__name__)

# Well inside conversations_repo.TURN_WINDOW, so a live turn's claim never
# reads as stale, while a dead process's claim still lapses within the window.
HEARTBEAT_SECONDS = 30
# The SDK client allows a 600 s timeout and 2 retries per call, over several
# calls a turn; without a deadline the heartbeat would hold a stalled turn's
# claim (every send a 409) for up to an hour.
TURN_DEADLINE_SECONDS = 600

Terminal = Literal["done", "failed"]
T = TypeVar("T")

_turns: set[asyncio.Task[None]] = set()


async def _shielded(aw: Awaitable[T]) -> T:
    """Run `aw` to completion even if the caller is cancelled meanwhile, then
    re-raise the cancellation. Unlike a bare asyncio.shield, the caller does
    not return until `aw` is done, so drain_turns's wait for a cancelled turn
    covers its cleanup."""
    inner = asyncio.ensure_future(aw)
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(inner)
            break
        except asyncio.CancelledError:
            if inner.cancelled():
                raise
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    return result


class Turn:
    def __init__(
        self, conversation_id: UUID, user_id: UUID, claimed_at: datetime
    ) -> None:
        self.conversation_id = conversation_id
        self.user_id = user_id
        # The claim's current value: refresh_turn moves it, and the release
        # MUST use the latest one or it clears nothing.
        self._token = claimed_at
        # Unbounded: the task never waits on its listener, and a detached
        # listener's backlog is one reply's events.
        self._queue: asyncio.Queue[dict | Terminal] = asyncio.Queue()

    async def listen(self) -> AsyncIterator[dict | Terminal]:
        """Every event of the turn, then exactly one terminal marker. One
        listener per turn."""
        while True:
            item = await self._queue.get()
            yield item
            if item == "done" or item == "failed":
                return

    async def _run(
        self,
        stream_fn: Callable[[list[MessageParam]], AsyncIterator[str | dict]],
        messages: list[MessageParam],
    ) -> None:
        buffer: list[str] = []
        # Insertion-ordered dedup by (document_id, chunk_idx), first hit
        # wins, across every search of the turn; forwarded events unchanged.
        sources: dict[tuple[str, int], dict] = {}
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(stop))
        completed = False
        outcome: Terminal = "failed"
        try:
            try:
                async with asyncio.timeout(TURN_DEADLINE_SECONDS):
                    async for item in stream_fn(messages):
                        event = {"content": item} if isinstance(item, str) else item
                        if "content" in event:
                            buffer.append(event["content"])
                        for s in event.get("sources", ()):
                            sources.setdefault((s["document_id"], s["chunk_idx"]), s)
                        self._queue.put_nowait(event)
                completed = True
            except Exception as exc:
                # Model failure or the deadline (TimeoutError). Type name only:
                # provider errors can echo prompt content.
                logger.warning(
                    "reply failed for conversation %s: %s",
                    self.conversation_id,
                    type(exc).__name__,
                )
        finally:
            # Every exit, cancellation included. The heartbeat is stopped and
            # awaited before the release, so the release uses the latest token.
            finish = asyncio.ensure_future(
                self._finish(stop, heartbeat, completed, buffer, sources)
            )
            try:
                await _shielded(finish)
            except Exception as exc:
                logger.warning(
                    "reply could not be saved for conversation %s: %s",
                    self.conversation_id,
                    type(exc).__name__,
                )
            finally:
                # Read from the finished save, not from _shielded's return: a
                # cancel that lands during a save that commits re-raises after
                # it, and the marker must still say the reply was stored.
                if (
                    finish.done()
                    and not finish.cancelled()
                    and finish.exception() is None
                    and finish.result()
                ):
                    outcome = "done"
                self._queue.put_nowait(outcome)

    async def _finish(
        self,
        stop: asyncio.Event,
        heartbeat: asyncio.Task[None],
        completed: bool,
        buffer: list[str],
        sources: dict[tuple[str, int], dict],
    ) -> bool:
        stop.set()
        await heartbeat
        if not completed:
            # A partial reply is never stored: history would replay it as whole.
            await chat_service.release_claim(self.conversation_id, self._token)
            return False
        # Saved and released before the terminal marker: a client that sees
        # [DONE] may send at once and must find the conversation free.
        try:
            await chat_service.persist_assistant_turn(
                self.conversation_id,
                self.user_id,
                "".join(buffer),
                list(sources.values()),
                claimed_at=self._token,
            )
        except Exception:
            # The save's release rolled back with it: free the conversation
            # now, best effort, rather than when TURN_WINDOW lapses.
            try:
                await chat_service.release_claim(self.conversation_id, self._token)
            except Exception as exc:
                logger.warning(
                    "claim release failed for conversation %s: %s",
                    self.conversation_id,
                    type(exc).__name__,
                )
            raise
        return True

    async def _heartbeat(self, stop: asyncio.Event) -> None:
        # Stopped by the event, never cancelled: a cancel could land between a
        # committed refresh and the token update and strand the claim.
        while True:
            try:
                await asyncio.wait_for(stop.wait(), HEARTBEAT_SECONDS)
                return
            except TimeoutError:
                pass
            try:
                if not await _shielded(self._refresh()):
                    # The claim lapsed and another turn took it: stop; this
                    # turn's release then clears nothing.
                    return
            except Exception as exc:
                logger.warning(
                    "claim refresh failed for conversation %s: %s",
                    self.conversation_id,
                    type(exc).__name__,
                )

    async def _refresh(self) -> bool:
        async with AsyncSessionLocal() as session:
            token = await conversations_repo.refresh_turn(
                session, self.conversation_id, self._token
            )
            await session.commit()
        if token is None:
            return False
        self._token = token
        return True


def start_turn(
    stream_fn: Callable[[list[MessageParam]], AsyncIterator[str | dict]],
    messages: list[MessageParam],
    conversation_id: UUID,
    user_id: UUID,
    claimed_at: datetime,
) -> Turn:
    """Start the reply as a task and return the handle its listener reads.
    The caller hands over the claim: from here the task alone releases it."""
    turn = Turn(conversation_id, user_id, claimed_at)
    task = asyncio.create_task(turn._run(stream_fn, messages))
    _turns.add(task)
    task.add_done_callback(_turns.discard)
    return turn


async def drain_turns(timeout: float) -> None:
    """Wait up to `timeout` seconds for in-flight turns, then cancel the rest
    and wait for their cleanup (each stores nothing and releases its claim)."""
    tasks = set(_turns)
    if not tasks:
        return
    _, pending = await asyncio.wait(tasks, timeout=timeout)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.wait(pending)
