"""Celery tasks for hax background jobs (slice 2a: document ingestion)."""

import asyncio
import logging
import smtplib
from uuid import UUID

from apps.worker.celery_app import celery_app
from packages.core.email import smtp, templates
from packages.core.rag.ingest import (
    PermanentIngestError,
    ingest_document_async,
    mark_document_failed,
)
from packages.db import engine
from packages.db.user_context import current_user_id

logger = logging.getLogger(__name__)

# Transient failures retry with exponential backoff: base * 2**retries -> 5s, 10s,
# 20s, then the 4th failure records 'failed'. That's 3 retries after the initial
# attempt (matches the task's max_retries).
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 5  # seconds

# doc.error is user-visible (DocumentOut.error). Permanent errors carry
# messages we authored; anything else is raw SDK/driver text that can leak
# endpoints, keys, or paths — log the raw form, store the generic line.
GENERIC_INGEST_ERROR = (
    "ingestion failed after retries (temporary service error); re-upload to retry"
)


def _public_error(exc: BaseException) -> str:
    return str(exc) if isinstance(exc, PermanentIngestError) else GENERIC_INGEST_ERROR


def _run_async(coro) -> None:
    """Drive a coroutine in a fresh event loop, then dispose the async engine's pool.

    ``asyncio.run`` creates a NEW loop per call, but the shared async engine caches
    asyncpg connections bound to whichever loop first used them. Disposing after
    each call means the next one — a retry, or the failure-recording call below —
    starts with a clean pool instead of connections bound to a closed loop
    ("attached to a different loop"). A cheap reconnect, negligible for infrequent
    ingestion.
    """

    async def _runner() -> None:
        try:
            await coro
        finally:
            await engine.dispose()

    asyncio.run(_runner())


def _record_failed(doc_id: UUID, error: str) -> None:
    """Best-effort record of terminal 'failed', which NEVER raises.

    The task calls this right before re-raising the original ingest error, so if
    the DB write here failed and propagated, it would mask that original error (and
    Celery would log the wrong cause). Swallowing + logging keeps the original
    failure intact; the doc just stays at 'processing' in the rare double-failure.
    """
    try:
        _run_async(mark_document_failed(doc_id, error))
    except Exception:
        logger.exception("failed to record 'failed' status for document %s", doc_id)


@celery_app.task(bind=True, name="ingest_document", max_retries=MAX_RETRIES)
def ingest_document(self, document_id: str, user_id: str) -> None:
    """Sync Celery entrypoint: run the async pipeline and own retry + terminal status.

    ``ingest_document_async`` drives pending/processing -> ready and raises on
    failure without touching 'failed'; this task classifies that failure:

    - ``PermanentIngestError`` (missing doc/key, non-UTF-8, no chunks) -> record
      'failed' and stop; retrying can't help.
    - anything else (Voyage / S3 / DB I/O) -> transient: retry with exponential
      backoff, leaving status='processing' so the polling UI keeps waiting; on the
      final attempt, record 'failed'.

    The id arrives as a str (the JSON broker can't carry a UUID) and is parsed back
    here. user_id rides the payload — the enqueuing request knows the owner; the
    worker announces it for RLS.
    """
    doc_id = UUID(document_id)
    logger.info("ingesting document %s (attempt %d)", doc_id, self.request.retries + 1)
    # asyncio.run copies the current context, so the coroutine (and the
    # _record_failed calls below) see the announced identity.
    token = current_user_id.set(UUID(user_id))
    try:
        _run_async(ingest_document_async(doc_id))
    except PermanentIngestError as exc:
        logger.error("permanent ingest failure for %s: %s", doc_id, exc, exc_info=True)
        _record_failed(doc_id, _public_error(exc))
        raise
    except Exception as exc:
        if self.request.retries >= MAX_RETRIES:
            logger.error(
                "ingest exhausted retries for %s: %s", doc_id, exc, exc_info=True
            )
            _record_failed(doc_id, _public_error(exc))
            raise
        countdown = RETRY_BACKOFF_BASE * (2**self.request.retries)
        # Exception TYPE only, never str(exc): a DBAPI error's text can carry
        # bound parameters (chunk content) even with hide_parameters=True if
        # the exception was constructed outside the engine's own wrapping —
        # exc_info is also deliberately omitted here for the same reason.
        logger.warning(
            "transient ingest failure for %s; retry %d/%d in %ds: %s",
            doc_id,
            self.request.retries + 1,
            MAX_RETRIES,
            countdown,
            type(exc).__name__,
        )
        raise self.retry(exc=exc, countdown=countdown)
    finally:
        current_user_id.reset(token)


EMAIL_MAX_RETRIES = 3


@celery_app.task(bind=True, name="send_email", max_retries=EMAIL_MAX_RETRIES)
def send_email(self, to: str, template: str, params: dict[str, str]) -> None:
    # Sync on purpose: smtplib is blocking and the worker is a prefork process.
    # Rendering errors are ours (bad template/params) — no retry. Transport
    # errors retry 5/10/20 s, then give up: email loss is non-fatal, every
    # link has a resend path, and a poisoned message must not pin a slot.
    rendered = templates.render(template, params)
    try:
        smtp.send(to, rendered)
    except (smtplib.SMTPException, OSError) as exc:
        if self.request.retries >= EMAIL_MAX_RETRIES:
            logger.error(
                "send_email giving up: template=%s err=%s", template, type(exc).__name__
            )
            return
        countdown = RETRY_BACKOFF_BASE * 2**self.request.retries
        logger.warning(
            "send_email transient failure (attempt %d/%d): %s; retrying in %ds",
            self.request.retries + 1,
            EMAIL_MAX_RETRIES,
            type(exc).__name__,
            countdown,
        )
        raise self.retry(exc=exc, countdown=countdown)
