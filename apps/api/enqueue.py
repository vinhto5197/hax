"""The API's one way to put a Celery task on the broker.

Publishing is a BLOCKING network call: about a millisecond against a healthy
broker, about 6 s against a sick one whether the port refuses or the host is
unroutable (bounded by the broker's `socket_connect_timeout`, set in
`apps/worker/celery_app.py`; without `ignore_result` on the task, the
result-backend subscription pushes a refusing broker past 15 s). Every producer
in this app sits on a request path — chat turns, the public auth routes,
uploads — so a publish made inline on the event loop freezes the whole
process for every user for that long. Nothing here runs a task; it only hands
the message off:

  1. to a `_publisher` thread, so the event loop never blocks on the network;
  2. for `fire_and_forget`, to an asyncio task first, so the request does not
     wait for the publish at all.

A pool of its own: the default executor also runs password hashing and
storage I/O, and stuck publishes must never be able to starve those. The
threads wait on the network, not the CPU, so the size does not track core
count — it bounds how many publishes can be in flight at once; the pool's
queue behind them is unbounded for `publish` (each waiting caller holds its
own request and is dequeued if that request is cancelled) and capped by
MAX_PENDING for `fire_and_forget`. Stalled uploads therefore delay the
title/email publishes queued behind them — acceptable, everything is
degraded while the broker is.

Everything here runs on the event-loop thread (`_pending` is not locked);
`fire_and_forget` must not be called from a worker thread.

Caller contract: publish only AFTER the DB commit. Tasks are handed ids, and
the worker can see only committed rows. Tasks published from here should also
be declared `ignore_result=True` — a result-backend subscription is what
makes a publish hang for many seconds when Redis is unreachable.
"""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

from celery import Task

logger = logging.getLogger(__name__)

_publisher = ThreadPoolExecutor(
    max_workers=int(os.getenv("ENQUEUE_THREADS", "2")),
    thread_name_prefix="enqueue",
)
# Beyond this many waiting publishes the broker is down, not slow: drop
# instead of queueing without bound.
MAX_PENDING = int(os.getenv("ENQUEUE_MAX_PENDING", "100"))
# In-flight fire-and-forget publishes only: each task removes itself when it
# finishes. The set exists because the loop holds only weak references to
# tasks, so one that nothing else references can be collected mid-flight.
# Process-wide and touched only from the event-loop thread.
_pending: set[asyncio.Task[None]] = set()


async def publish(task: Task, *args: Any) -> None:
    """Publish `task` off the event loop and await the broker's answer.

    Raises whatever the publish raised — for callers that must know, e.g. an
    upload marking its document 'failed' rather than leaving it 'pending'
    with no task behind it. `args` must be JSON-serializable (the broker
    carries JSON, so ids travel as str).

    retry=False: an in-process retry only holds the caller longer against a
    broker that is already refusing; recovery belongs to the caller.
    """
    send = partial(task.apply_async, args=args, retry=False)
    await asyncio.get_running_loop().run_in_executor(_publisher, send)


def fire_and_forget(task: Task, *args: Any, log_ref: str) -> None:
    """Publish `task` without making the request wait for it. Never raises
    into the request (a publish failure is logged, not propagated).

    For work whose loss is recoverable elsewhere (an untitled conversation is
    re-enqueued on its next turn; every emailed link has a resend path), so a
    dropped or failed publish costs a retry, not the response — and a broker
    outage cannot change a route's status code or its timing.

    `log_ref` is what may appear in this module's log lines, chosen by the
    caller because the payload cannot be trusted to be loggable: arg 0 is an
    id for some tasks but a recipient address — user data — for `send_email`.
    Failures log the exception TYPE only for the same reason.
    """
    if len(_pending) >= MAX_PENDING:
        logger.warning("%s publish dropped for %s: backlog full", task.name, log_ref)
        return
    pending = asyncio.create_task(_publish_or_log(task, args, log_ref))
    _pending.add(pending)
    pending.add_done_callback(_pending.discard)


async def _publish_or_log(task: Task, args: tuple[Any, ...], log_ref: str) -> None:
    try:
        await publish(task, *args)
    except Exception as exc:
        logger.warning(
            "%s publish failed for %s: %s", task.name, log_ref, type(exc).__name__
        )
