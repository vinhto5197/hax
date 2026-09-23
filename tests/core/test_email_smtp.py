import email.utils
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


def test_display_name_from_keeps_the_name_but_addresses_stay_bare(monkeypatch):
    """A friendly SMTP_FROM ("hax <no-reply@hax.example>") survives verbatim in
    the From header, while the address-only uses — the Message-ID domain, and
    the envelope sender smtplib parses back out of that header — take the bare
    address, with the multipart body otherwise unchanged."""
    monkeypatch.setenv("SMTP_FROM", "hax <no-reply@hax.example>")
    monkeypatch.delenv("SMTP_USER", raising=False)
    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setattr(smtp.smtplib, "SMTP", MagicMock(return_value=client))

    smtp.send("to@example.com", _rendered())

    (msg,), _ = client.send_message.call_args
    assert msg["From"] == "hax <no-reply@hax.example>"
    # send_message derives the envelope sender this way when from_addr is
    # omitted, so the relay sees the address without the display name.
    assert email.utils.parseaddr(msg["From"])[1] == "no-reply@hax.example"
    assert msg["Message-ID"].endswith("@hax.example>")
    assert msg.get_body(preferencelist=("plain",)).get_content().strip() == "plain"
    assert "<p>plain</p>" in msg.get_body(preferencelist=("html",)).get_content()


def test_header_injection_in_recipient_is_rejected(monkeypatch):
    # Defense in depth: routes only pass EmailStr values, but the transport
    # itself must refuse a CR/LF in a header rather than emit a forged header.
    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setattr(smtp.smtplib, "SMTP", MagicMock(return_value=client))
    with pytest.raises(ValueError):
        smtp.send("victim@example.com\r\nBcc: other@example.com", _rendered())
    client.send_message.assert_not_called()
