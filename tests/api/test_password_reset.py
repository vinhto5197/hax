"""Reset = inbox proof → new password → every prior session dies (DB + Redis
write-through). Also the only way a Google-born account gains a password."""

import asyncio
import os
import time
from types import SimpleNamespace

import jwt
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import apps.api.routers.auth as auth_router
from packages.core.auth.email_tokens import hash_token
from packages.core.auth.passwords import hash_password, verify_password
from packages.db.repos import email_tokens as tokens_repo
from tests.api.conftest import _make_user
from tests.api.factories import make_email_token

BODY = {"status": "check_inbox"}
INTERNAL = {"X-Internal-Secret": os.environ["INTERNAL_API_SECRET"]}


@pytest.fixture
def outbox(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        auth_router, "send_email", SimpleNamespace(delay=lambda *a: calls.append(a))
    )
    return calls


def _old_bearer(user, age_s=120) -> dict[str, str]:
    # A session minted `age_s` ago — bearer() mints "now", which can't
    # discriminate a same-second cutoff bump.
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": str(user.id),
            "email": user.email,
            "iss": "hax",
            "aud": "hax-api",
            "iat": now - age_s,
            "exp": now + 600,
            "jti": "old",
            "auth_time": now - age_s,
        },
        os.environ["AUTH_SECRET"],
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


async def _row(admin_engine, user_id):
    async with admin_engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT password_hash, email_verified_at, sessions_valid_after"
                    " FROM users WHERE id = :id"
                ),
                {"id": user_id},
            )
        ).one()


async def test_request_is_uniform_and_only_emails_real_accounts(
    client, admin_engine, user_a, outbox
):
    # user_a is a@test.local (raw SQL) — use an example.com user for the API.
    u = await _make_user(admin_engine, "r@example.com")
    await make_email_token(admin_engine, u.id, "reset_password", hash_token("h0"))
    unknown = await client.post(
        "/api/auth/request-password-reset", json={"email": "nobody@example.com"}
    )
    known = await client.post(
        "/api/auth/request-password-reset", json={"email": "r@example.com"}
    )
    assert (
        unknown.status_code == known.status_code == 202
        and unknown.json() == known.json() == BODY
    )
    assert [(c[0], c[1]) for c in outbox] == [("r@example.com", "reset_password")]
    assert outbox[0][2]["link"].startswith(
        "http://localhost:3000/reset-password?token="
    )
    async with admin_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT purpose, expires_at - now() AS ttl, token_hash"
                    " FROM email_tokens WHERE user_id = :id AND used_at IS NULL"
                ),
                {"id": u.id},
            )
        ).all()
    # The seeded "h0" link is voided by the request; exactly the new one
    # (same one-live-link invariant as resend-verification) remains.
    assert len(rows) == 1
    row = rows[0]
    assert row.purpose == "reset_password" and 3500 < row.ttl.total_seconds() <= 3600
    assert row.token_hash != hash_token("h0")


async def test_confirm_sets_password_verifies_and_revokes_sessions(
    client, admin_engine, fake_redis
):
    u = await _make_user(admin_engine, "r@example.com")
    async with admin_engine.begin() as conn:
        # sessions_valid_after defaults to creation time (~now); backdate it
        # so the "old" bearer (auth_time = now-120s) is valid pre-reset, the
        # same way a real account's cutoff predates any of its live sessions.
        await conn.execute(
            text(
                "UPDATE users SET password_hash = :h,"
                " sessions_valid_after = now() - interval '1 day' WHERE id = :id"
            ),
            {"h": hash_password("old-one-1"), "id": u.id},
        )
    old = _old_bearer(u)
    assert (await client.get("/api/conversations", headers=old)).status_code == 200
    await make_email_token(admin_engine, u.id, "reset_password", hash_token("raw1"))
    await make_email_token(admin_engine, u.id, "reset_password", hash_token("raw2"))

    res = await client.post(
        "/api/auth/reset-password", json={"token": "raw1", "password": "brand-new-9"}
    )
    assert res.status_code == 200 and res.json() == {"email": "r@example.com"}

    row = await _row(admin_engine, u.id)
    assert verify_password(row.password_hash, "brand-new-9")
    assert row.email_verified_at is not None
    assert await fake_redis.get(f"sva:{u.id}") == str(
        int(row.sessions_valid_after.timestamp())
    )
    assert (await client.get("/api/conversations", headers=old)).status_code == 401
    async with admin_engine.connect() as conn:
        used = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM email_tokens"
                    " WHERE user_id = :id AND used_at IS NULL"
                ),
                {"id": u.id},
            )
        ).scalar_one()
    assert used == 0  # raw2 voided too


async def test_google_born_account_gains_a_password(client, admin_engine):
    u = await _make_user(admin_engine, "g@example.com")  # password_hash NULL
    await make_email_token(admin_engine, u.id, "reset_password", hash_token("raw1"))
    res = await client.post(
        "/api/auth/reset-password", json={"token": "raw1", "password": "brand-new-9"}
    )
    assert res.status_code == 200
    assert verify_password(
        (await _row(admin_engine, u.id)).password_hash, "brand-new-9"
    )


async def test_invalid_tokens_rejected_and_nothing_changes(client, admin_engine):
    u = await _make_user(admin_engine, "r@example.com")
    await make_email_token(
        admin_engine, u.id, "reset_password", hash_token("used"), used=True
    )
    await make_email_token(
        admin_engine, u.id, "reset_password", hash_token("old"), expires_in_s=-1
    )
    await make_email_token(admin_engine, u.id, "verify_email", hash_token("verify"))
    for raw in ("used", "old", "verify", "unknown"):
        res = await client.post(
            "/api/auth/reset-password", json={"token": raw, "password": "brand-new-9"}
        )
        assert res.status_code == 400 and res.json()["detail"] == {
            "code": "invalid_token"
        }, raw
    assert (await _row(admin_engine, u.id)).password_hash is None


async def test_reset_password_length_policy(client):
    res = await client.post(
        "/api/auth/reset-password", json={"token": "x", "password": "short"}
    )
    assert res.status_code == 422


async def test_request_per_email_rate_limit(client, admin_engine, outbox):
    await _make_user(admin_engine, "r@example.com")
    for _ in range(3):
        await client.post(
            "/api/auth/request-password-reset", json={"email": "r@example.com"}
        )
    assert (
        await client.post(
            "/api/auth/request-password-reset", json={"email": "r@example.com"}
        )
    ).status_code == 429
    assert len(outbox) == 3


async def test_confirm_ip_rate_limit(client):
    # Token alone identifies the account (no email to bucket on), same as
    # verify-email: IP-only limiting.
    for _ in range(10):
        res = await client.post(
            "/api/auth/reset-password", json={"token": "x", "password": "password1"}
        )
        assert res.status_code == 400
    eleventh = await client.post(
        "/api/auth/reset-password", json={"token": "x", "password": "password1"}
    )
    assert eleventh.status_code == 429


async def test_request_ip_rate_limit(client):
    for i in range(10):
        res = await client.post(
            "/api/auth/request-password-reset", json={"email": f"u{i}@example.com"}
        )
        assert res.status_code == 202
    eleventh = await client.post(
        "/api/auth/request-password-reset", json={"email": "u10@example.com"}
    )
    assert eleventh.status_code == 429


async def test_length_caps(client):
    long_token = "x" * 129
    long_password = "x" * 129
    res = await client.post(
        "/api/auth/reset-password", json={"token": long_token, "password": "password1"}
    )
    assert res.status_code == 422
    res = await client.post(
        "/api/auth/reset-password", json={"token": "x", "password": long_password}
    )
    assert res.status_code == 422


async def test_reset_check_reports_validity_without_consuming(client, admin_engine):
    u = await _make_user(admin_engine, "r@example.com")
    await make_email_token(admin_engine, u.id, "reset_password", hash_token("raw1"))
    first = await client.post("/api/auth/reset-password/check", json={"token": "raw1"})
    second = await client.post("/api/auth/reset-password/check", json={"token": "raw1"})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {"status": "valid"}
    # The precheck consumed nothing: the token is still live for the real,
    # consuming call.
    res = await client.post(
        "/api/auth/reset-password", json={"token": "raw1", "password": "brand-new-9"}
    )
    assert res.status_code == 200 and res.json() == {"email": "r@example.com"}


async def test_reset_check_rejects_used_expired_wrong_purpose_unknown(
    client, admin_engine
):
    u = await _make_user(admin_engine, "r@example.com")
    await make_email_token(
        admin_engine, u.id, "reset_password", hash_token("used"), used=True
    )
    await make_email_token(
        admin_engine, u.id, "reset_password", hash_token("old"), expires_in_s=-1
    )
    await make_email_token(admin_engine, u.id, "verify_email", hash_token("verify"))
    for raw in ("used", "old", "verify", "unknown"):
        res = await client.post("/api/auth/reset-password/check", json={"token": raw})
        assert res.status_code == 400, raw
        assert res.json()["detail"] == {"code": "invalid_token"}, raw
    assert (await _row(admin_engine, u.id)).password_hash is None


async def test_double_consume_is_strictly_single_use(client, admin_engine):
    # Two concurrent confirms with the SAME token, different passwords:
    # consume()'s atomic conditional UPDATE must let exactly one through.
    u = await _make_user(admin_engine, "r@example.com")
    await make_email_token(admin_engine, u.id, "reset_password", hash_token("raw1"))

    results = await asyncio.gather(
        client.post(
            "/api/auth/reset-password",
            json={"token": "raw1", "password": "password-one"},
        ),
        client.post(
            "/api/auth/reset-password",
            json={"token": "raw1", "password": "password-two"},
        ),
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 400]

    winner_password = (
        "password-one" if results[0].status_code == 200 else "password-two"
    )
    row = await _row(admin_engine, u.id)
    assert verify_password(row.password_hash, winner_password)


async def test_double_consume_is_single_use_hermetic(client, admin_engine, monkeypatch):
    # Hermetic variant: force get_valid to keep returning the same live token
    # object on both calls (as it would mid-race) and run the confirms
    # sequentially. With atomic consume() the second call still loses.
    u = await _make_user(admin_engine, "r@example.com")
    await make_email_token(admin_engine, u.id, "reset_password", hash_token("raw1"))
    # Fetch the live token via a throwaway session (admin-bound; email_tokens
    # is outside RLS) so the monkeypatch below can hand back the SAME ORM
    # object on both calls, simulating what a race would see.
    async with AsyncSession(admin_engine) as seed_session:
        token = await tokens_repo.get_valid(
            seed_session, hash_token("raw1"), "reset_password"
        )

    async def stale_get_valid(session, token_hash, purpose):
        return token

    monkeypatch.setattr(tokens_repo, "get_valid", stale_get_valid)

    first = await client.post(
        "/api/auth/reset-password", json={"token": "raw1", "password": "password-one"}
    )
    second = await client.post(
        "/api/auth/reset-password", json={"token": "raw1", "password": "password-two"}
    )

    assert first.status_code == 200 and second.status_code == 400
    row = await _row(admin_engine, u.id)
    assert verify_password(row.password_hash, "password-one")


async def test_reset_clears_login_rate_limit(client, admin_engine):
    # Inbox proof: a reset must clear the login_email guessing bucket, or the
    # "failed a few logins -> forgot password -> reset" path 429s at the very
    # login the user just earned.
    u = await _make_user(admin_engine, "r@example.com")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET password_hash = :h WHERE id = :id"),
            {"h": hash_password("old-one-1"), "id": u.id},
        )
    for _ in range(5):
        await client.post(
            "/internal/auth/verify-credentials",
            json={"email": "r@example.com", "password": "wrong-password"},
            headers=INTERNAL,
        )
    # Bucket burned by the 5 wrong attempts; the 6th 429s even with the
    # correct (pre-reset) password.
    sixth = await client.post(
        "/internal/auth/verify-credentials",
        json={"email": "r@example.com", "password": "old-one-1"},
        headers=INTERNAL,
    )
    assert sixth.status_code == 429

    await make_email_token(admin_engine, u.id, "reset_password", hash_token("raw1"))
    res = await client.post(
        "/api/auth/reset-password", json={"token": "raw1", "password": "brand-new-9"}
    )
    assert res.status_code == 200

    after = await client.post(
        "/internal/auth/verify-credentials",
        json={"email": "r@example.com", "password": "brand-new-9"},
        headers=INTERNAL,
    )
    assert after.status_code == 200
