"""Verification is by link alone: the token proves the inbox. The pre-hijack
defense lives in signup (re-signup replaces the pending password), not here."""

import pytest
from sqlalchemy import text

import apps.api.routers.auth as auth_router
from packages.core.auth.email_tokens import hash_token
from tests.api.factories import make_email_token, make_user


@pytest.fixture
def outbox(monkeypatch):
    calls: list[tuple] = []

    def record(task, *args, log_ref):
        calls.append(args)

    monkeypatch.setattr(auth_router, "fire_and_forget", record)
    return calls


def _token_from(call) -> str:
    _to, _template, params = call
    return params["link"].split("token=")[1]


async def _seed(admin_engine, email="v@example.com"):
    return await make_user(admin_engine, email)


async def _user_id(admin_engine, email):
    async with admin_engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT id FROM users WHERE email = :e"), {"e": email}
            )
        ).scalar_one()


async def _credentials(admin_engine, user_id):
    async with admin_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT password_hash, sessions_valid_after"
                    " FROM users WHERE id = :id"
                ),
                {"id": user_id},
            )
        ).one()
    return tuple(row)


async def _state(admin_engine, user_id):
    async with admin_engine.connect() as conn:
        verified = (
            await conn.execute(
                text("SELECT email_verified_at FROM users WHERE id = :id"),
                {"id": user_id},
            )
        ).scalar_one()
        tokens = (
            await conn.execute(
                text(
                    "SELECT token_hash, used_at FROM email_tokens"
                    " WHERE user_id = :id ORDER BY created_at"
                ),
                {"id": user_id},
            )
        ).all()
    return verified, tokens


async def test_valid_token_verifies_and_consumes_all_verify_tokens(
    client, admin_engine
):
    u = await _seed(admin_engine)
    await make_email_token(admin_engine, u.id, "verify_email", hash_token("raw1"))
    await make_email_token(admin_engine, u.id, "verify_email", hash_token("raw2"))
    res = await client.post("/api/auth/verify-email", json={"token": "raw1"})
    assert res.status_code == 200 and res.json() == {"email": "v@example.com"}
    verified, tokens = await _state(admin_engine, u.id)
    assert verified is not None
    # the other verify token is voided too
    assert all(t.used_at is not None for t in tokens)


async def test_used_expired_or_wrong_purpose_token_rejected(client, admin_engine):
    u = await _seed(admin_engine)
    await make_email_token(
        admin_engine, u.id, "verify_email", hash_token("used"), used=True
    )
    await make_email_token(
        admin_engine, u.id, "verify_email", hash_token("old"), expires_in_s=-1
    )
    await make_email_token(admin_engine, u.id, "reset_password", hash_token("reset"))
    for raw in ("used", "old", "reset", "unknown"):
        res = await client.post("/api/auth/verify-email", json={"token": raw})
        assert res.status_code == 400, raw
        assert res.json()["detail"] == {"code": "invalid_token"}, raw
    assert (await _state(admin_engine, u.id))[0] is None


async def test_verify_is_idempotent_on_double_click(client, admin_engine):
    u = await _seed(admin_engine)
    await make_email_token(admin_engine, u.id, "verify_email", hash_token("raw1"))
    first = await client.post("/api/auth/verify-email", json={"token": "raw1"})
    second = await client.post("/api/auth/verify-email", json={"token": "raw1"})
    assert first.status_code == 200 and second.status_code == 400
    assert (await _state(admin_engine, u.id))[0] is not None


async def test_superseded_link_is_rejected_and_the_new_one_still_works(
    client, admin_engine, outbox
):
    """A link voided by a later resend is dead at POST time, not merely marked
    used in the table: it 400s, leaves the account unverified, and the link
    that replaced it still verifies."""
    await client.post(
        "/api/auth/signup", json={"email": "v@example.com", "password": "password1"}
    )
    await client.post("/api/auth/resend-verification", json={"email": "v@example.com"})
    old_raw, new_raw = _token_from(outbox[0]), _token_from(outbox[1])
    assert old_raw != new_raw
    user_id = await _user_id(admin_engine, "v@example.com")

    dead = await client.post("/api/auth/verify-email", json={"token": old_raw})
    assert dead.status_code == 400
    assert dead.json()["detail"] == {"code": "invalid_token"}
    assert (await _state(admin_engine, user_id))[0] is None

    live = await client.post("/api/auth/verify-email", json={"token": new_raw})
    assert live.status_code == 200 and live.json() == {"email": "v@example.com"}
    assert (await _state(admin_engine, user_id))[0] is not None


async def test_verify_leaves_password_and_session_cutoff_untouched(
    client, admin_engine
):
    """Verification proves the inbox and nothing else: it must not rotate the
    pending password nor bump the revocation cutoff (which would kill the
    sessions of a user who merely clicked their link)."""
    u = await _seed(admin_engine)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET password_hash = 'pending-hash' WHERE id = :id"),
            {"id": u.id},
        )
    before = await _credentials(admin_engine, u.id)
    await make_email_token(admin_engine, u.id, "verify_email", hash_token("raw1"))

    res = await client.post("/api/auth/verify-email", json={"token": "raw1"})
    assert res.status_code == 200

    assert (await _state(admin_engine, u.id))[0] is not None
    assert await _credentials(admin_engine, u.id) == before


async def test_verify_email_ip_rate_limit(client):
    for _ in range(10):
        res = await client.post("/api/auth/verify-email", json={"token": "x"})
        assert res.status_code == 400
    eleventh = await client.post("/api/auth/verify-email", json={"token": "x"})
    assert eleventh.status_code == 429
