"""Celery application for hax background jobs.

Broker + result backend are both Redis (``REDIS_URL``). The worker runs as a
**separate process** from the FastAPI app (see ADR 0010) — start it with
``make worker``. Tasks live in ``apps.worker.tasks`` (registered via ``include``).
"""

import asyncio
import logging
import os

from celery import Celery
from celery.signals import worker_process_init

from packages.db import engine
from packages.db.session import assert_rls_bound_role

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "hax",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["apps.worker.tasks"],
)

celery_app.conf.update(
    # JSON (not pickle) on the wire — safe, language-agnostic. Task args must be
    # JSON-serializable, so ids travel as str, never as UUID.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Ack the message only AFTER the task finishes, so a worker crash mid-task
    # redelivers it instead of dropping the work. This is *why* the task must be
    # idempotent — ingestion is, via delete-then-insert (see ingest_document_async).
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Ingestion is long-ish: don't let one worker hoard queued messages, and hard-
    # cap a single task so a hung embed call can't pin a slot forever.
    worker_prefetch_multiplier=1,
    task_time_limit=300,
    task_track_started=True,
    # Producers (the API) must fail fast when the broker is unreachable: with
    # no connect timeout a publish hangs on the OS TCP timeout, pinning a
    # thread per enqueue. Connect only — established-connection reads (the
    # worker's blocking pop) are untouched.
    broker_transport_options={"socket_connect_timeout": 2},
)


@worker_process_init.connect
def _check_rls_bound_role(**kwargs) -> None:
    # Fail closed before the worker pulls any task rather than run every
    # ingestion as a role that silently bypasses RLS. Fresh loop per process
    # init, same dispose pattern as tasks.py::_run_async (the pooled asyncpg
    # connections here are otherwise loop-bound).
    #
    # Celery's Signal.send wraps every receiver in try/except Exception (logs
    # and continues) so a plain `raise` here would be swallowed and the
    # prefork child would start pulling tasks anyway. SystemExit is a
    # BaseException, not an Exception, so it passes through that guard and
    # actually aborts the child — that's the only reason this handler works.
    async def _runner() -> None:
        try:
            await assert_rls_bound_role()
        finally:
            await engine.dispose()

    try:
        asyncio.run(_runner())
    except RuntimeError as exc:
        logger.critical(
            "worker process init: %s — refusing to start; connect as the "
            "app role (hax_app), not a superuser/BYPASSRLS role",
            exc,
        )
        raise SystemExit(1) from exc
    except Exception as exc:
        # A guard that cannot run must fail closed too: an unreachable database
        # at process init (cold stack, security group not yet open) is not
        # permission to consume tasks with the role unverified.
        logger.critical(
            "worker process init: could not verify the database role (%s) — "
            "refusing to start",
            type(exc).__name__,
        )
        raise SystemExit(1) from exc
