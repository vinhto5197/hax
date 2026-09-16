"""Inbox-ownership tokens (verification + password reset).

Cross-module contract with packages/db/repos/email_tokens.py: the raw token
lives only in the emailed link; the DB stores sha256(raw). Validity (unused,
unexpired, purpose-matched) is decided by the repo, not here."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

VERIFY_EMAIL_TTL = timedelta(hours=24)
RESET_PASSWORD_TTL = timedelta(hours=1)


def generate() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)  # 256 bits
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def expiry(ttl: timedelta) -> datetime:
    return datetime.now(UTC) + ttl
