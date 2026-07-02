"""Celery application for hax background jobs (slice 2a onward).

Broker + result backend are both Redis (``REDIS_URL``). The worker runs as a
**separate process** from the FastAPI app (see ADR 0010) — start it with
``make worker``. Tasks live in ``apps.worker.tasks`` (registered via ``include``).
"""

import os

from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "hax",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["apps.worker.tasks"],
)

celery_app.conf.update(
    # JSON (not pickle) on the wire — safe, language-agnostic. Task args must be
    # JSON-serializable, so we pass the document id as a str, not a UUID.
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
)
