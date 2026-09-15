import ssl
from unittest.mock import MagicMock

import pytest

from packages.core.email import smtp
from packages.core.email.templates import Rendered


def _rendered() -> Rendered:
    return Rendered(subject="Hi", text="plain", html="<p>plain</p>")


def test_send_builds_multipart_and_uses_env(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "mail.test")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.com")
    monkeypatch.delenv("SMTP_USER", raising=False)
    client = MagicMock()
    ctor = MagicMock(return_value=client)
    client.__enter__.return_value = client
    monkeypatch.setattr(smtp.smtplib, "SMTP", ctor)

    smtp.send("to@example.com", _rendered())

    ctor.assert_called_once_with("mail.test", 2525, timeout=smtp.TIMEOUT_S)
    client.starttls.assert_not_called()
    client.login.assert_not_called()
    (msg,), _ = client.send_message.call_args
    assert msg["To"] == "to@example.com"
    assert msg["From"] == "noreply@example.com"
    assert msg["Subject"] == "Hi"
    assert msg.get_body(preferencelist=("plain",)).get_content().strip() == "plain"
    assert "<p>plain</p>" in msg.get_body(preferencelist=("html",)).get_content()
    assert msg["Date"]
    assert msg["Message-ID"].endswith("@example.com>")


def test_send_uses_starttls_and_login_when_credentials_set(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "u")
    monkeypatch.setenv("SMTP_PASSWORD", "p")
    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setattr(smtp.smtplib, "SMTP", MagicMock(return_value=client))

    smtp.send("to@example.com", _rendered())

    client.starttls.assert_called_once()
    # The context is what makes the TLS verified; without it starttls() still
    # "works" against any certificate, and this is the line that sends creds.
    assert client.starttls.call_args.kwargs["context"].verify_mode == ssl.CERT_REQUIRED
    client.login.assert_called_once_with("u", "p")


def test_header_injection_in_recipient_is_rejected(monkeypatch):
    # Defense in depth: routes only pass EmailStr values, but the transport
    # itself must refuse a CR/LF in a header rather than emit a forged header.
    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setattr(smtp.smtplib, "SMTP", MagicMock(return_value=client))
    with pytest.raises(ValueError):
        smtp.send("victim@example.com\r\nBcc: other@example.com", _rendered())
    client.send_message.assert_not_called()
