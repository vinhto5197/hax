"""Celery tasks for hax background jobs: document ingestion, transactional
email, conversation titles."""

import asyncio
import logging
import smtplib
from uuid import UUID

import anthropic
from sqlalchemy.exc import InterfaceError, OperationalError

from apps.worker.celery_app import celery_app
from packages.core import titles
from packages.core.email import smtp, templates
from packages.core.rag.ingest import (
    PermanentIngestError,
    ingest_document_async,
    mark_document_failed,
)
from packages.db import AsyncSessionLocal, engine
from packages.db.repos import conversations as conversations_repo
from packages.db.user_context import current_user_id

logger = logging.getLogger(__name__)

# Transient failures retry with exponential backoff: base * 2**retries -> 5s, 10s,
# 20s. That's 3 retries after the initial attempt (matches each task's
# max_retries); what the 4th failure does is the task's own decision.
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 5  # seconds


def _retry_transient(task, exc: BaseException, *, max_retries: int, label: str) -> None:
    """Backoff 5/10/20 s, then give up QUIETLY (return) — for work whose loss is
    recoverable elsewhere: email has a resend path, an untitled conversation is
    re-enqueued on its next turn. Logs the exception TYPE only; relay replies
    and SDK messages can carry addresses or message content.

    Caller contract: this either raises Retry (Celery re-queues) or returns,
    and the caller must then treat the task as done."""
    if task.request.retries >= max_retries:
        logger.error("%s giving up: %s", label, type(exc).__name__)
        return
    countdown = RETRY_BACKOFF_BASE * 2**task.request.retries
    logger.warning(
        "%s transient failure (attempt %d/%d): %s; retrying in %ds",
        label,
        task.request.retries + 1,
        max_retries,
        type(exc).__name__,
        countdown,
    )
    raise task.retry(exc=exc, countdown=countdown)


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


# ignore_result: the UI polls documents.status, nobody reads the task result,
# and the result-backend subscription is what makes a publish hang when Redis
# is unreachable (see apps/api/enqueue.py).
@celery_app.task(
    bind=True, name="ingest_document", max_retries=MAX_RETRIES, ignore_result=True
)
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


# ignore_result, as for generate_title below: nobody reads this task's result,
# and the result-backend subscription every publish would otherwise open is
# what makes an enqueue hang for many seconds when Redis is unreachable.
@celery_app.task(
    bind=True, name="send_email", max_retries=EMAIL_MAX_RETRIES, ignore_result=True
)
def send_email(self, to: str, template: str, params: dict[str, str]) -> None:
    # Sync on purpose: smtplib is blocking and the worker is a prefork process.
    # Rendering errors are ours (bad template/params) — no retry. Transport
    # errors retry 5/10/20 s, then give up: email loss is non-fatal, every
    # link has a resend path, and a poisoned message must not pin a slot.
    rendered = templates.render(template, params)
    try:
        smtp.send(to, rendered)
    except (smtplib.SMTPException, OSError) as exc:
        _retry_transient(
            self, exc, max_retries=EMAIL_MAX_RETRIES, label=f"send_email[{template}]"
        )


def _is_transient(exc: BaseException) -> bool:
    """Title-task classification only. A 4xx other than 429 is our bug (bad
    request/auth) and retrying it just burns attempts."""
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return isinstance(
        exc, (anthropic.APIConnectionError, OperationalError, InterfaceError, OSError)
    )


async def generate_title_async(conversation_id: UUID, user_id: UUID) -> None:
    # Two short sessions and no connection held across the model call: a slow
    # model must not pin a pooled connection.
    async with AsyncSessionLocal() as session:
        conversation = await conversations_repo.get_owned(
            session, user_id, conversation_id
        )
        if conversation is None or conversation.title is not None:
            return
        message = await conversations_repo.first_user_message(
            session, user_id, conversation_id
        )
    if message is None:
        return
    title = await titles.suggest_title(message)
    if title is None:
        return
    async with AsyncSessionLocal() as session:
        await conversations_repo.set_title_if_unset(
            session, user_id, conversation_id, title
        )
        await session.commit()


# ignore_result: nobody reads this task's result, and without it every publish
# also subscribes to the result backend — which is what makes an enqueue hang
# for many seconds when Redis is unreachable. Consequence: this task's state
# is never visible in the result backend.
@celery_app.task(
    bind=True, name="generate_title", max_retries=MAX_RETRIES, ignore_result=True
)
def generate_title(self, conversation_id: str, user_id: str) -> None:
    """Write a conversation's title from its first user message, once.

    Payload is two strings (the JSON broker can't carry UUIDs). user_id rides
    the payload — the enqueuing request knows the owner; the worker announces
    it for RLS and resets it in `finally` (prefork children are long-lived).

    Idempotent by construction (the write is conditional on title IS NULL), so
    at-least-once delivery and racing enqueues are harmless. No title from the
    model, or a permanent failure, leaves title NULL — the API re-enqueues on a
    later turn, so nothing here is worth failing loudly for.

    Never log the message or the generated title: exception type only, plus the
    HTTP status for a permanent API error.
    """
    conv_id, owner_id = UUID(conversation_id), UUID(user_id)
    logger.info(
        "titling conversation %s (attempt %d)", conv_id, self.request.retries + 1
    )
    token = current_user_id.set(owner_id)
    try:
        _run_async(generate_title_async(conv_id, owner_id))
    except Exception as exc:
        if _is_transient(exc):
            _retry_transient(self, exc, max_retries=MAX_RETRIES, label="generate_title")
            return
        logger.error(
            "generate_title permanent failure for %s: %s (status=%s)",
            conv_id,
            type(exc).__name__,
            getattr(exc, "status_code", None),
        )
    finally:
        current_user_id.reset(token)
