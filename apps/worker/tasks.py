"""Celery tasks for hax background jobs (slice 2a: document ingestion)."""

import asyncio
import logging
from uuid import UUID

from apps.worker.celery_app import celery_app
from packages.core.rag.ingest import ingest_document_async
from packages.db import engine

logger = logging.getLogger(__name__)


@celery_app.task(name="ingest_document")
def ingest_document(document_id: str) -> None:
    """Sync Celery entrypoint for ingestion: bridge to the async pipeline.

    Celery prefork workers are synchronous, so we run the async ingest in a
    short-lived event loop (one per task) via ``asyncio.run``. The id arrives as a
    str (the JSON broker can't carry a UUID) and is parsed back here. Slice 2a
    step 3b adds transient-vs-permanent retry/backoff around this call.
    """
    logger.info("ingesting document %s", document_id)
    # _run_ingest(...) does NOT run here: calling an async function returns a lazy
    # coroutine object (its body hasn't executed). asyncio.run is what drives that
    # coroutine to completion on a fresh event loop. (Python coroutines are lazy —
    # unlike JS, where calling an async function starts running it eagerly.)
    asyncio.run(_run_ingest(UUID(document_id)))


async def _run_ingest(document_id: UUID) -> None:
    """Run the ingest, then dispose the async engine's connection pool.

    ``asyncio.run`` creates a NEW event loop per task, but the shared async engine
    caches asyncpg connections bound to whichever loop first used them. Without
    disposing, the 2nd task's loop would inherit connections bound to the 1st
    task's now-closed loop and fail with "attached to a different loop". Disposing
    in ``finally`` makes each task start with a clean pool — a cheap reconnect,
    negligible for infrequent ingestion.
    """
    try:
        await ingest_document_async(document_id)
    finally:
        await engine.dispose()
