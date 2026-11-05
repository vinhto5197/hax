"""Login's Argon2 runs with no app transaction open, so it holds no pooled
connection for the tens of milliseconds a hash takes; reset spends its token
first, so a bad token costs no hash. The probe counts only this test
database's hax_app backends and never its own, so a dev stack running beside
the suite cannot flip it."""

import os

import pytest
from sqlalchemy import text

import apps.api.routers.auth as auth_router
import apps.api.routers.internal_auth as internal_auth_router
from packages.core.auth.email_tokens import hash_token
from packages.core.auth.passwords import hash_password
from packages.db import engine as app_engine
from tests.api.factories import make_email_token, make_user

INTERNAL = {"X-Internal-Secret": os.environ["INTERNAL_API_SECRET"]}
EMAIL = "pw@example.com"
OLD_PW = "correct-horse"
NEW_PW = "brand-new-battery-9"


async def _pw_user(admin_engine):
    u = await make_user(admin_engine, EMAIL)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE users SET password_hash = :h, email_verified_at = now()"
                " WHERE id = :id"
            ),
            {"h": hash_password(OLD_PW), "id": u.id},
        )
    return u


async def _app_backends_in_transaction(admin_engine) -> list[str]:
    """States of every hax_app backend on hax_test that is inside a
    transaction (the probe's own admin connection excluded)."""
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT state FROM pg_stat_activity"
                " WHERE datname = current_database() AND usename = 'hax_app'"
                " AND pid <> pg_backend_pid()"
                " AND (state LIKE 'idle in transaction%' OR xact_start IS NOT NULL)"
            )
        )
        return [r[0] for r in rows]


async def _login(client, email, password):
    return await client.post(
        "/internal/auth/verify-credentials",
        json={"email": email, "password": password},
        headers=INTERNAL,
    )


@pytest.fixture
def observed_verify(monkeypatch, admin_engine):
    """Wraps both verify paths of the login route: each call records what
    hax_app transactions were open at that moment, then runs the real verify."""
    seen: dict[str, list[list[str]]] = {"verify": [], "dummy": []}
    real_verify = internal_auth_router.verify_password_async
    real_dummy = internal_auth_router.dummy_verify_async

    async def verify(password_hash, password):
        seen["verify"].append(await _app_backends_in_transaction(admin_engine))
        return await real_verify(password_hash, password)

    async def dummy(password):
        seen["dummy"].append(await _app_backends_in_transaction(admin_engine))
        return await real_dummy(password)

    monkeypatch.setattr(internal_auth_router, "verify_password_async", verify)
    monkeypatch.setattr(internal_auth_router, "dummy_verify_async", dummy)
    return seen


@pytest.fixture
def hash_calls(monkeypatch):
    calls: list[str] = []
    real = auth_router.hash_password_async

    async def recording(password):
        calls.append(password)
        return await real(password)

    monkeypatch.setattr(auth_router, "hash_password_async", recording)
    return calls


async def test_the_transaction_probe_sees_an_open_app_transaction(admin_engine):
    async with app_engine.connect() as conn:
        await conn.begin()
        await conn.execute(text("SELECT 1"))
        assert await _app_backends_in_transaction(admin_engine) != []
        await conn.rollback()


async def test_login_password_verify_runs_with_no_open_transaction(
    client, admin_engine, observed_verify
):
    u = await _pw_user(admin_engine)
    res = await _login(client, EMAIL, OLD_PW)
    assert res.status_code == 200
    assert str(u.id) in res.text
    assert observed_verify["verify"], "the login never verified the password"
    assert observed_verify["verify"] == [[]] * len(observed_verify["verify"])


async def test_wrong_password_verify_runs_with_no_open_transaction(
    client, admin_engine, observed_verify
):
    await _pw_user(admin_engine)
    res = await _login(client, EMAIL, "wrong-password")
    assert res.status_code == 401
    assert observed_verify["verify"], "the login never verified the password"
    assert observed_verify["verify"] == [[]] * len(observed_verify["verify"])


async def test_unknown_email_dummy_verify_runs_with_no_open_transaction(
    client, observed_verify
):
    res = await _login(client, "nobody@example.com", OLD_PW)
    assert res.status_code == 401
    assert observed_verify["dummy"], "an unknown email skipped the dummy verify"
    assert observed_verify["dummy"] == [[]] * len(observed_verify["dummy"])


async def _reset(client, token, password=NEW_PW):
    return await client.post(
        "/api/auth/reset-password", json={"token": token, "password": password}
    )


async def test_reset_with_an_unknown_token_is_400_and_never_hashes(
    client, admin_engine, hash_calls
):
    await _pw_user(admin_engine)
    res = await _reset(client, "never-issued")
    assert res.status_code == 400
    assert hash_calls == []


async def test_reset_with_a_used_token_is_400_and_never_hashes(
    client, admin_engine, hash_calls
):
    u = await _pw_user(admin_engine)
    await make_email_token(
        admin_engine, u.id, "reset_password", hash_token("spent"), used=True
    )
    res = await _reset(client, "spent")
    assert res.status_code == 400
    assert hash_calls == []


async def test_reset_with_an_expired_token_is_400_and_never_hashes(
    client, admin_engine, hash_calls
):
    u = await _pw_user(admin_engine)
    await make_email_token(
        admin_engine, u.id, "reset_password", hash_token("stale"), expires_in_s=-60
    )
    res = await _reset(client, "stale")
    assert res.status_code == 400
    assert hash_calls == []


async def test_refused_reset_leaves_the_old_password_working(client, admin_engine):
    u = await _pw_user(admin_engine)
    await make_email_token(
        admin_engine, u.id, "reset_password", hash_token("stale"), expires_in_s=-60
    )
    await _reset(client, "stale")
    assert (await _login(client, EMAIL, OLD_PW)).status_code == 200
    assert (await _login(client, EMAIL, NEW_PW)).status_code == 401


async def test_reset_with_a_valid_token_changes_the_password(
    client, admin_engine, hash_calls
):
    u = await _pw_user(admin_engine)
    await make_email_token(admin_engine, u.id, "reset_password", hash_token("fresh"))
    res = await _reset(client, "fresh")
    assert 200 <= res.status_code < 300
    assert hash_calls == [NEW_PW]
    assert (await _login(client, EMAIL, NEW_PW)).status_code == 200
    assert (await _login(client, EMAIL, OLD_PW)).status_code == 401
