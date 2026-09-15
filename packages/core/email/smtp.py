"""SMTP transport (Mailpit in dev, SES-over-SMTP at M3 via the same env).

Header safety is the EmailMessage API's: it raises on CR/LF in header values,
so a forged header can never be emitted — callers must not pre-format
headers themselves."""

import email.utils
import os
import smtplib
import ssl
from email.message import EmailMessage

from packages.core.email.templates import Rendered

TIMEOUT_S = 10


def send(to: str, rendered: Rendered) -> None:
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM", "hax@localhost")
    msg["To"] = to
    msg["Subject"] = rendered.subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    # Explicit domain: make_msgid() would otherwise call getfqdn(), which can
    # block for tens of seconds in a DNS-restricted worker.
    domain = email.utils.parseaddr(msg["From"])[1].rpartition("@")[2] or "localhost"
    msg["Message-ID"] = email.utils.make_msgid(domain=domain)
    msg.set_content(rendered.text)
    msg.add_alternative(rendered.html, subtype="html")

    host = os.getenv("SMTP_HOST", "localhost")
    port = int(os.getenv("SMTP_PORT", "1025"))
    user = os.getenv("SMTP_USER")
    with smtplib.SMTP(host, port, timeout=TIMEOUT_S) as client:
        if user:
            # Verified TLS: the next line sends the relay credentials.
            client.starttls(context=ssl.create_default_context())
            client.login(user, os.environ["SMTP_PASSWORD"])
        client.send_message(msg)
