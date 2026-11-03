"""Argon2 runs with no transaction open: a login or a reset holds no pooled
connection (and no row lock) for the tens of milliseconds a hash takes."""

import os

import pytest
from sqlalchemy import text

import apps.api.routers.auth as auth_routes
import apps.api.routers.internal_auth as internal_routes
from packages.core.auth.email_tokens import hash_token
from packages.core.auth.passwords import hash_password
from tests.api.factories import make_email_token, make_user

INTERNAL = {"X-Internal-Secret": os.environ["INTERNAL_API_SECRET"]}


@pytest.fixture
def open_transactions(admin_engine, monkeypatch):
    """Wraps every Argon2 entry point the routes use; each call records how
    many app-role transactions were open at that moment."""
    seen: list[int] = []

    async def count() -> int:
        async with admin_engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE usename = 'hax_app' AND state = 'idle in transaction'"
                )
            )
            return result.scalar_one()

    def wrap(module, name):
        original = getattr(module, name)

        async def wrapped(*args):
            seen.append(await count())
            return await original(*args)

        monkeypatch.setattr(module, name, wrapped)

    wrap(internal_routes, "verify_password_async")
    wrap(internal_routes, "dummy_verify_async")
    wrap(auth_routes, "hash_password_async")
    return seen


async def _password_user(admin_engine, email):
    user = await make_user(admin_engine, email)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE users SET password_hash = :h, email_verified_at = now()"
                " WHERE id = :id"
            ),
            {"h": hash_password("correct-horse"), "id": user.id},
        )
    return user


async def test_login_verifies_the_password_with_no_transaction_open(
    client, admin_engine, open_transactions
):
    await _password_user(admin_engine, "l@example.com")
    res = await client.post(
        "/internal/auth/verify-credentials",
        json={"email": "l@example.com", "password": "correct-horse"},
        headers=INTERNAL,
    )
    assert res.status_code == 200
    assert open_transactions == [0]


async def test_wrong_password_is_still_refused(client, admin_engine, open_transactions):
    await _password_user(admin_engine, "w@example.com")
    res = await client.post(
        "/internal/auth/verify-credentials",
        json={"email": "w@example.com", "password": "wrong-horse"},
        headers=INTERNAL,
    )
    assert res.status_code == 401
    assert open_transactions == [0]


async def test_unknown_email_burns_the_dummy_hash_with_no_transaction_open(
    client, open_transactions
):
    res = await client.post(
        "/internal/auth/verify-credentials",
        json={"email": "nobody@example.com", "password": "correct-horse"},
        headers=INTERNAL,
    )
    assert res.status_code == 401
    assert open_transactions == [0]


async def test_reset_hashes_the_new_password_with_no_transaction_open(
    client, admin_engine, open_transactions
):
    user = await _password_user(admin_engine, "r@example.com")
    await make_email_token(admin_engine, user.id, "reset_password", hash_token("raw1"))
    res = await client.post(
        "/api/auth/reset-password", json={"token": "raw1", "password": "brand-new-9"}
    )
    assert res.status_code == 200
    assert open_transactions == [0]
