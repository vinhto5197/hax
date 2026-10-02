"""A transient failure's retry is logged by Celery itself, rendering the
exception it was handed; that exception must carry the type name only. Runs
the real tasks eagerly (apply) so Celery's own trace logger speaks."""

import logging
import smtplib

import apps.worker.tasks as tasks


def test_email_retry_log_carries_no_address_or_relay_reply(monkeypatch, caplog):
    def refuse(to, rendered):
        raise smtplib.SMTPRecipientsRefused(
            {"jane@example.com": (550, b"no such user")}
        )

    monkeypatch.setattr(tasks.smtp, "send", refuse)
    monkeypatch.setattr(tasks.templates, "render", lambda template, params: "body")
    caplog.set_level(logging.INFO)

    # Eager apply runs every retry at once; the task then gives up quietly.
    tasks.send_email.apply(args=("jane@example.com", "verify_email", {}))

    assert caplog.text.count("Retry in") == 3
    assert "SMTPRecipientsRefused" in caplog.text
    assert "jane@example.com" not in caplog.text
    assert "no such user" not in caplog.text


def test_ingest_retry_log_carries_no_exception_text(monkeypatch, caplog):
    async def boom(doc_id):
        raise OSError("connection reset while sending chunk: SECRET CONTENT")

    monkeypatch.setattr(tasks, "ingest_document_async", boom)
    caplog.set_level(logging.INFO)

    doc = "00000000-0000-0000-0000-000000000001"
    owner = "00000000-0000-0000-0000-000000000002"
    # Eager apply runs every retry at once; the exhausted branch then raises.
    tasks.ingest_document.apply(args=(doc, owner))

    assert caplog.text.count("Retry in") == 3
    assert "OSError" in caplog.text
    assert "SECRET CONTENT" not in caplog.text
