"""The queue contract: every registered task is routed by name, ingestion goes
to `ingest` and everything else to the default queue `celery`, so the ingest
worker and the fast worker (compose.prod.yml) are strict lanes.

Resolved through Celery's router, not by reading task_routes back: this is
what a publish — a first send, a retry, a beat tick — would actually do."""

import pytest

from apps.worker.celery_app import celery_app

FAST_TASKS = ("send_email", "generate_title", "sweep_anonymous_users")


def _registered_tasks() -> set[str]:
    return {name for name in celery_app.tasks if not name.startswith("celery.")}


def _queue_for(name: str) -> str:
    return celery_app.amqp.router.route({}, name)["queue"].name


def test_every_registered_task_has_an_explicit_route():
    # A new task lands in a lane by a conscious choice, never by default.
    assert _registered_tasks() == set(celery_app.conf.task_routes)


def test_ingest_document_publishes_to_the_ingest_queue():
    assert _queue_for("ingest_document") == "ingest"


@pytest.mark.parametrize("name", FAST_TASKS)
def test_fast_tasks_publish_to_the_default_queue(name):
    assert _queue_for(name) == "celery"


def test_the_default_queue_keeps_its_name():
    # A producer still on an older route table during a roll publishes to the
    # default queue; renaming it would orphan those messages.
    assert celery_app.conf.task_default_queue == "celery"
