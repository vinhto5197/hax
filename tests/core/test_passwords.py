import asyncio
import time

from packages.core.auth import passwords
from packages.core.auth.passwords import (
    dummy_verify,
    dummy_verify_async,
    hash_password,
    hash_password_async,
    verify_password,
    verify_password_async,
)


def test_hash_is_not_plaintext_and_verifies():
    h = hash_password("correct horse battery staple")
    assert "correct horse" not in h
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse battery staple") is True


def test_wrong_password_fails():
    h = hash_password("right")
    assert verify_password(h, "wrong") is False


def test_garbage_hash_fails_not_raises():
    assert verify_password("not-a-hash", "anything") is False


def test_two_hashes_of_same_password_differ():
    # Per-hash random salt — equal hashes would mean a broken salt.
    assert hash_password("same") != hash_password("same")


def test_dummy_verify_swallows_result():
    assert dummy_verify("whatever") is None


async def test_async_wrappers_round_trip(monkeypatch):
    # Fresh semaphore per test: the module global would otherwise carry an
    # object bound to a previous test's event loop.
    monkeypatch.setattr(passwords, "_semaphore", None)
    h = await hash_password_async("correct horse battery staple")
    assert await verify_password_async(h, "correct horse battery staple") is True
    assert await verify_password_async(h, "wrong") is False


async def test_dummy_verify_async_returns_none(monkeypatch):
    monkeypatch.setattr(passwords, "_semaphore", None)
    assert await dummy_verify_async("whatever") is None


async def test_semaphore_caps_concurrency(monkeypatch):
    monkeypatch.setenv("ARGON2_MAX_CONCURRENT", "1")
    monkeypatch.setattr(passwords, "_semaphore", None)

    active = 0
    max_active = 0

    def counting_verify(password_hash: str, password: str) -> bool:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        # Long enough that overlapping ops would be observed as active == 2.
        time.sleep(0.05)
        active -= 1
        return True

    monkeypatch.setattr(passwords, "verify_password", counting_verify)
    results = await asyncio.gather(
        verify_password_async("h", "p"), verify_password_async("h", "p")
    )
    assert results == [True, True]
    assert max_active == 1  # cap=1 serialized the two ops
    assert passwords._semaphore is not None  # lazily created from env
