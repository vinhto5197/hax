"""AUTH_REQUIRE_EMAIL_VERIFICATION is ON by default (hard-set in
tests/conftest.py): unverified password users can't mint a session."""

import os

from sqlalchemy import text

from packages.core.auth.passwords import hash_password
from tests.api.factories import make_user

INTERNAL = {"X-Internal-Secret": os.environ["INTERNAL_API_SECRET"]}


async def _pw_user(admin_engine, verified):
    u = await make_user(admin_engine, "g@example.com")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE users SET password_hash = :h,"
                " email_verified_at = CASE WHEN :v THEN now() END"
                " WHERE id = :id"
            ),
            {"h": hash_password("correct-horse"), "v": verified, "id": u.id},
        )
    return u


async def test_unverified_user_gets_email_unverified(client, admin_engine):
    await _pw_user(admin_engine, verified=False)
    res = await client.post(
        "/internal/auth/verify-credentials",
        json={"email": "g@example.com", "password": "correct-horse"},
        headers=INTERNAL,
    )
    assert res.status_code == 403 and res.json()["detail"] == {
        "code": "email_unverified"
    }


async def test_verified_user_logs_in(client, admin_engine):
    await _pw_user(admin_engine, verified=True)
    res = await client.post(
        "/internal/auth/verify-credentials",
        json={"email": "g@example.com", "password": "correct-horse"},
        headers=INTERNAL,
    )
    assert res.status_code == 200


async def test_gate_can_be_switched_off(client, admin_engine, monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRE_EMAIL_VERIFICATION", "false")
    await _pw_user(admin_engine, verified=False)
    res = await client.post(
        "/internal/auth/verify-credentials",
        json={"email": "g@example.com", "password": "correct-horse"},
        headers=INTERNAL,
    )
    assert res.status_code == 200


async def test_unverified_user_with_wrong_password_gets_401_not_403(
    client, admin_engine
):
    # Pins the check order: the verification gate is consulted only AFTER the
    # password has already matched, so "unverified" is never an oracle an
    # attacker can read off without first proving the password.
    await _pw_user(admin_engine, verified=False)
    res = await client.post(
        "/internal/auth/verify-credentials",
        json={"email": "g@example.com", "password": "wrong-password"},
        headers=INTERNAL,
    )
    assert res.status_code == 401
    assert res.json()["detail"] == {"code": "invalid_credentials"}


async def test_gate_is_on_when_the_env_var_is_absent(client, admin_engine, monkeypatch):
    # The code default is the security-relevant half: any box whose env omits
    # the var must still gate. conftest's hard-set is removed for this test.
    monkeypatch.delenv("AUTH_REQUIRE_EMAIL_VERIFICATION", raising=False)
    await _pw_user(admin_engine, verified=False)
    res = await client.post(
        "/internal/auth/verify-credentials",
        json={"email": "g@example.com", "password": "correct-horse"},
        headers=INTERNAL,
    )
    assert res.status_code == 403
