import smtplib
from unittest.mock import MagicMock

import pytest
from celery.exceptions import Retry

import apps.worker.tasks as tasks


def test_send_email_renders_and_sends(monkeypatch):
    sent = MagicMock()
    monkeypatch.setattr(tasks.smtp, "send", sent)
    tasks.send_email.apply(
        args=("to@example.com", "verify_email", {"link": "http://x/?token=t"})
    ).get()
    (to, rendered), _ = sent.call_args
    assert to == "to@example.com" and "http://x/?token=t" in rendered.text


def test_transient_smtp_failure_retries_with_backoff(monkeypatch):
    monkeypatch.setattr(
        tasks.smtp, "send", MagicMock(side_effect=smtplib.SMTPConnectError(421, b"x"))
    )
    retry = MagicMock(side_effect=Retry())
    monkeypatch.setattr(tasks.send_email, "retry", retry)
    with pytest.raises(Retry):
        tasks.send_email.apply(
            args=("to@example.com", "verify_email", {"link": "l"}), throw=True
        ).get()
    assert retry.call_args.kwargs["countdown"] == 5  # base * 2**0


def test_bad_template_is_permanent_no_retry(monkeypatch, caplog):
    retry = MagicMock()
    monkeypatch.setattr(tasks.send_email, "retry", retry)
    result = tasks.send_email.apply(args=("to@example.com", "nope", {}))
    assert result.failed()
    retry.assert_not_called()


def test_gives_up_after_max_retries_without_raising(monkeypatch, caplog):
    monkeypatch.setattr(
        tasks.smtp, "send", MagicMock(side_effect=smtplib.SMTPConnectError(421, b"x"))
    )
    retry = MagicMock()
    monkeypatch.setattr(tasks.send_email, "retry", retry)
    result = tasks.send_email.apply(
        args=("to@example.com", "verify_email", {"link": "l"}),
        retries=tasks.EMAIL_MAX_RETRIES,
    )
    assert result.successful()
    retry.assert_not_called()
    assert "giving up" in caplog.text and "421" not in caplog.text
