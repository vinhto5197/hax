"""Verification is by link alone: the token proves the inbox. The pre-hijack
defense lives in signup (re-signup replaces the pending password), not here."""

from sqlalchemy import text

from packages.core.auth.email_tokens import hash_token
from tests.api.conftest import _make_user
from tests.api.factories import make_email_token


async def _seed(admin_engine, email="v@example.com"):
    return await _make_user(admin_engine, email)


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


async def test_verify_email_ip_rate_limit(client):
    for _ in range(10):
        res = await client.post("/api/auth/verify-email", json={"token": "x"})
        assert res.status_code == 400
    eleventh = await client.post("/api/auth/verify-email", json={"token": "x"})
    assert eleventh.status_code == 429
