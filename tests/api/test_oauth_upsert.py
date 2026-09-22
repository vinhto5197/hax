"""Linking rules for /internal/auth/oauth-upsert.

Every request here carries NO session and announces NO identity — the caller
is mid-sign-in. That the writes succeed as hax_app is itself an assertion:
users/accounts are deliberately outside RLS (ADR 0012). Seeding and
cross-checks go through the admin engine with raw SQL so the repo under test
can never seed its own passing data.
"""

import os

import pytest
from sqlalchemy import text

import apps.api.routers.internal_auth as internal_auth
from tests.api.conftest import _make_user
from tests.api.factories import make_account

INTERNAL = {"X-Internal-Secret": os.environ["INTERNAL_API_SECRET"]}


def google(sub="g-111", email="g@example.com", verified=True, name="G Person"):
    return {
        "provider": "google",
        "provider_account_id": sub,
        "email": email,
        "email_verified": verified,
        "name": name,
    }


@pytest.fixture
async def pw_user(admin_engine):
    # Password-style account (unverified, no name, no Google link yet).
    # Crosses pydantic's EmailStr (unlike the raw-SQL-only user_a/user_b
    # fixtures), which rejects the special-use .local domain.
    user = await _make_user(admin_engine, "pw@example.com")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET password_hash = 'not-a-real-hash' WHERE id = :id"),
            {"id": user.id},
        )
    return user


async def _users(admin_engine):
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, email, name, password_hash, email_verified_at,"
                " sessions_valid_after FROM users ORDER BY created_at"
            )
        )
        return rows.all()


async def _accounts(admin_engine):
    async with admin_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT user_id, provider, provider_account_id FROM accounts")
        )
        return rows.all()


async def test_new_google_identity_creates_verified_passwordless_user(
    client, admin_engine
):
    res = await client.post(
        "/internal/auth/oauth-upsert", json=google(), headers=INTERNAL
    )
    assert res.status_code == 200, res.text
    body = res.json()
    users = await _users(admin_engine)
    assert len(users) == 1
    row = users[0]
    assert str(row.id) == body["id"]
    assert row.email == "g@example.com" and row.name == "G Person"
    assert row.password_hash is None
    assert row.email_verified_at is not None
    assert await _accounts(admin_engine) == [(row.id, "google", "g-111")]


async def test_repeat_sign_in_is_idempotent(client, admin_engine):
    first = await client.post(
        "/internal/auth/oauth-upsert", json=google(), headers=INTERNAL
    )
    second = await client.post(
        "/internal/auth/oauth-upsert", json=google(), headers=INTERNAL
    )
    assert first.json()["id"] == second.json()["id"]
    assert len(await _users(admin_engine)) == 1
    assert len(await _accounts(admin_engine)) == 1


async def test_provider_account_match_wins_over_changed_email(client, admin_engine):
    # Same Google account, email changed on Google's side: still the same user,
    # and the stored email is NOT rewritten (email is the hax identity key).
    first = await client.post(
        "/internal/auth/oauth-upsert", json=google(), headers=INTERNAL
    )
    second = await client.post(
        "/internal/auth/oauth-upsert",
        json=google(email="renamed@example.com"),
        headers=INTERNAL,
    )
    assert second.json()["id"] == first.json()["id"]
    users = await _users(admin_engine)
    assert len(users) == 1 and users[0].email == "g@example.com"


async def test_verified_email_links_to_existing_user(client, admin_engine, pw_user):
    # pw_user: password-style account (no Google yet), unverified, no name.
    res = await client.post(
        "/internal/auth/oauth-upsert",
        json=google(email=pw_user.email),
        headers=INTERNAL,
    )
    assert res.status_code == 200, res.text
    assert res.json()["id"] == str(pw_user.id)
    users = await _users(admin_engine)
    assert len(users) == 1
    assert users[0].email_verified_at is not None  # inbox proven by Google
    assert users[0].name == "G Person"  # filled because it was NULL
    assert await _accounts(admin_engine) == [(pw_user.id, "google", "g-111")]


async def test_link_never_overwrites_existing_name(client, admin_engine, pw_user):
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET name = 'Chosen' WHERE id = :id"), {"id": pw_user.id}
        )
    res = await client.post(
        "/internal/auth/oauth-upsert",
        json=google(email=pw_user.email),
        headers=INTERNAL,
    )
    assert res.status_code == 200, res.text
    assert (await _users(admin_engine))[0].name == "Chosen"


async def test_link_to_unverified_password_user_clears_password_and_revokes_sessions(
    client, admin_engine, pw_user, fake_redis
):
    # Threat model: an attacker could sign up victim@example.com with a
    # password before the victim ever visits; the victim's later Google
    # sign-in must not inherit that password, and any session it created
    # must die.
    before = (await _users(admin_engine))[0].sessions_valid_after
    res = await client.post(
        "/internal/auth/oauth-upsert",
        json=google(email=pw_user.email),
        headers=INTERNAL,
    )
    assert res.status_code == 200, res.text
    assert res.json()["id"] == str(pw_user.id)
    row = (await _users(admin_engine))[0]
    assert row.password_hash is None
    assert row.email_verified_at is not None
    assert row.sessions_valid_after > before
    cached = await fake_redis.get(f"sva:{pw_user.id}")
    assert cached == str(int(row.sessions_valid_after.timestamp()))


async def test_link_to_already_verified_user_keeps_password(
    client, admin_engine, pw_user, fake_redis
):
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET email_verified_at = now() WHERE id = :id"),
            {"id": pw_user.id},
        )
    before = (await _users(admin_engine))[0].sessions_valid_after
    res = await client.post(
        "/internal/auth/oauth-upsert",
        json=google(email=pw_user.email),
        headers=INTERNAL,
    )
    assert res.status_code == 200, res.text
    row = (await _users(admin_engine))[0]
    assert row.password_hash == "not-a-real-hash"
    assert row.sessions_valid_after == before
    assert await fake_redis.get(f"sva:{pw_user.id}") is None


async def test_email_match_is_case_insensitive(client, admin_engine, pw_user):
    res = await client.post(
        "/internal/auth/oauth-upsert",
        json=google(email=pw_user.email.upper()),
        headers=INTERNAL,
    )
    assert res.json()["id"] == str(pw_user.id)
    assert len(await _users(admin_engine)) == 1


async def test_unverified_email_never_links_to_existing_user(
    client, admin_engine, pw_user
):
    res = await client.post(
        "/internal/auth/oauth-upsert",
        json=google(email=pw_user.email, verified=False),
        headers=INTERNAL,
    )
    assert res.status_code == 403
    assert res.json()["detail"] == {"code": "email_unverified"}
    assert await _accounts(admin_engine) == []
    assert (await _users(admin_engine))[0].email_verified_at is None


async def test_unverified_email_never_creates_a_user(client, admin_engine):
    res = await client.post(
        "/internal/auth/oauth-upsert", json=google(verified=False), headers=INTERNAL
    )
    assert res.status_code == 403
    assert await _users(admin_engine) == []


async def test_unknown_provider_is_rejected(client, admin_engine):
    res = await client.post(
        "/internal/auth/oauth-upsert",
        json={**google(), "provider": "github"},
        headers=INTERNAL,
    )
    assert res.status_code == 422
    assert await _users(admin_engine) == []


async def test_requires_internal_secret(client, admin_engine):
    res = await client.post("/internal/auth/oauth-upsert", json=google())
    assert res.status_code == 404
    assert await _users(admin_engine) == []


async def test_lost_first_sign_in_race_resolves_to_the_winner(
    client, admin_engine, pw_user, monkeypatch
):
    # Two first sign-ins for the same Google account race. Simulate the loser:
    # its account lookup ran before the winner committed (patched to miss
    # once), so it creates a fresh user, then its account INSERT collides
    # with the winner's unique (provider, provider_account_id) row. The route
    # must roll back and re-resolve to the winner — one user, one account.
    await make_account(admin_engine, pw_user.id, "google", "g-111")
    real = internal_auth.accounts_repo.get_user_by_account
    calls = {"n": 0}

    async def miss_once(session, provider, provider_account_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real(session, provider, provider_account_id)

    monkeypatch.setattr(internal_auth.accounts_repo, "get_user_by_account", miss_once)
    res = await client.post(
        "/internal/auth/oauth-upsert",
        json=google(email="loser@example.com"),
        headers=INTERNAL,
    )
    assert res.status_code == 200, res.text
    assert res.json()["id"] == str(pw_user.id)
    assert calls["n"] == 2
    assert len(await _users(admin_engine)) == 1  # the loser's user was rolled back
    assert len(await _accounts(admin_engine)) == 1


async def test_google_born_user_cannot_log_in_with_a_password(client):
    # Cross-endpoint contract: password_hash NULL means verify-credentials
    # takes the dummy-verify path and 401s (no oracle that the account exists).
    await client.post("/internal/auth/oauth-upsert", json=google(), headers=INTERNAL)
    res = await client.post(
        "/internal/auth/verify-credentials",
        json={"email": "g@example.com", "password": "whatever-8"},
        headers=INTERNAL,
    )
    assert res.status_code == 401
