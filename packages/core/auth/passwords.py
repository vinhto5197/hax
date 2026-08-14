"""Password hashing (argon2id) for the credentials login method.

Cross-module contract: hashes written by hash_password are verified only by
verify_password; dummy_verify exists so an unknown-email login burns the same
argon2 work as a real mismatch (timing-equalized checks — spec threat table).
Routers must use the *_async wrappers: argon2 never runs inline on the event
loop, and the semaphore caps concurrent hashing memory.
"""

import asyncio
import os

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# OWASP argon2id parameters sized for the 1GiB alpha box: 19 MiB per op is the
# per-op memory budget. Verify reads params embedded in each stored hash, so
# hashes minted under other settings (e.g. old 64MiB dev hashes) still verify.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)

# Precomputed at import so dummy_verify's cost matches a real verification.
_DUMMY_HASH = _hasher.hash("hax-dummy-password-for-timing-only")

# PER-PROCESS cap on concurrent argon2 ops: cap = machine argon2 memory budget
# / memory_cost / uvicorn worker count (v0 = 1 worker). Lazy like
# apps/api/redis_client.py — importing never reads env or allocates.
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(int(os.getenv("ARGON2_MAX_CONCURRENT", "4")))
    return _semaphore


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def dummy_verify(password: str) -> None:
    try:
        _hasher.verify(_DUMMY_HASH, password)
    except VerifyMismatchError:
        pass


async def hash_password_async(password: str) -> str:
    async with _get_semaphore():
        return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password_hash: str, password: str) -> bool:
    async with _get_semaphore():
        return await asyncio.to_thread(verify_password, password_hash, password)


async def dummy_verify_async(password: str) -> None:
    async with _get_semaphore():
        await asyncio.to_thread(dummy_verify, password)
