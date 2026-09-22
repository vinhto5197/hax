"""Signup is an anti-enumeration surface: one 202 for every input; only the
email differs. All asserts go through the admin engine; the publish is
recorded, never executed."""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.orm.attributes import set_committed_value

import apps.api.routers.auth as auth_router
from apps.api import enqueue
from packages.core.auth.email_tokens import hash_token
from tests.api.conftest import _make_user
from tests.api.factories import make_email_token

BODY = {"status": "check_inbox"}


@pytest.fixture
def outbox(monkeypatch):
    calls: list[tuple] = []

    def record(task, *args, log_ref):
        # The loggable ref is the template, never arg 0 — that's the address.
        assert task is auth_router.send_email and log_ref == args[1]
        calls.append(args)

    monkeypatch.setattr(auth_router, "fire_and_forget", record)
    return calls


@pytest.fixture
async def pw_user(admin_engine):
    u = await _make_user(admin_engine, "pw@example.com")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET password_hash = 'old-hash' WHERE id = :id"),
            {"id": u.id},
        )
    return u


async def _user_row(admin_engine, email):
    async with admin_engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT id, password_hash, email_verified_at, sessions_valid_after"
                    " FROM users WHERE email = :e"
                ),
                {"e": email},
            )
        ).one_or_none()


async def _tokens(admin_engine, user_id):
    async with admin_engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT purpose, used_at, expires_at > now() AS live"
                    " FROM email_tokens WHERE user_id = :u ORDER BY created_at"
                ),
                {"u": user_id},
            )
        ).all()


def _token_from(call):
    to, template, params = call
    return params["link"].split("token=")[1]


async def test_new_signup_creates_unverified_user_and_emails_link(
    client, admin_engine, outbox
):
    res = await client.post(
        "/api/auth/signup", json={"email": "new@example.com", "password": "password1"}
    )
    assert res.status_code == 202 and res.json() == BODY
    row = await _user_row(admin_engine, "new@example.com")
    assert row.password_hash and row.email_verified_at is None
    assert len(outbox) == 1
    to, template, params = outbox[0]
    assert (to, template) == ("new@example.com", "verify_email")
    assert params["link"].startswith("http://localhost:3000/verify-email?token=")
    tokens = await _tokens(admin_engine, row.id)
    assert [(t.purpose, t.used_at, t.live) for t in tokens] == [
        ("verify_email", None, True)
    ]
    # The link carries the raw token; the DB holds only its hash.
    async with admin_engine.connect() as conn:
        stored = (
            await conn.execute(text("SELECT token_hash FROM email_tokens"))
        ).scalar_one()
    assert stored == hash_token(_token_from(outbox[0]))
    assert _token_from(outbox[0]) != stored


async def test_existing_verified_user_gets_account_exists_email(
    client, admin_engine, pw_user, outbox
):
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET email_verified_at = now() WHERE id = :id"),
            {"id": pw_user.id},
        )
    res = await client.post(
        "/api/auth/signup", json={"email": pw_user.email, "password": "password1"}
    )
    assert res.status_code == 202 and res.json() == BODY
    assert [(c[0], c[1]) for c in outbox] == [(pw_user.email, "account_exists")]
    assert (await _user_row(admin_engine, pw_user.email)).password_hash == "old-hash"
    assert await _tokens(admin_engine, pw_user.id) == []


async def test_resignup_on_unverified_placeholder_replaces_pending_password(
    client, admin_engine, pw_user, outbox, fake_redis
):
    # Pre-hijack defense with link-only verification: whoever signs up LAST
    # owns the pending password, so a victim's own signup can never verify a
    # stranger's password. Earlier links are voided; one live link remains.
    await make_email_token(
        admin_engine, pw_user.id, "verify_email", "h1", expires_in_s=3600
    )
    before = (await _user_row(admin_engine, pw_user.email)).sessions_valid_after
    res = await client.post(
        "/api/auth/signup", json={"email": pw_user.email, "password": "different1"}
    )
    assert res.status_code == 202 and res.json() == BODY
    assert [c[1] for c in outbox] == ["verify_email"]
    row = await _user_row(admin_engine, pw_user.email)
    assert row.password_hash != "old-hash" and row.email_verified_at is None
    assert row.sessions_valid_after > before
    assert await fake_redis.get(f"sva:{pw_user.id}") == str(
        int(row.sessions_valid_after.timestamp())
    )
    live = [
        t
        for t in await _tokens(admin_engine, pw_user.id)
        if t.live and t.used_at is None
    ]
    assert len(live) == 1  # h1 voided


async def test_resignup_loses_to_a_concurrent_verify(
    client, admin_engine, pw_user, outbox, monkeypatch
):
    # Simulates a session that fetched `pw_user` while still unverified, then
    # lost a race: a concurrent verify-email commits before this request
    # writes. The conditional UPDATE in replace_pending_password must lose to
    # it, not overwrite the now-verified row's password.
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET email_verified_at = now() WHERE id = :id"),
            {"id": pw_user.id},
        )
    real_get_by_email = auth_router.users_repo.get_by_email

    async def stale_snapshot(session, email):
        # set_committed_value, not a plain assignment: assigning would mark
        # the ORM object dirty and autoflush would write NULL back to the
        # row on the very next session.execute() (void_unused), silently
        # curing the race this test exists to simulate. This sets the
        # in-memory value only, as if the row had been read before the
        # concurrent verify committed.
        user = await real_get_by_email(session, email)
        if user is not None:
            set_committed_value(user, "email_verified_at", None)
        return user

    monkeypatch.setattr(auth_router.users_repo, "get_by_email", stale_snapshot)
    res = await client.post(
        "/api/auth/signup", json={"email": pw_user.email, "password": "newpass99"}
    )
    assert res.status_code == 202 and res.json() == BODY
    assert (await _user_row(admin_engine, pw_user.email)).password_hash == "old-hash"
    assert outbox == [
        (
            pw_user.email,
            "account_exists",
            {
                "login_url": f"{auth_router.app_base_url()}/login",
                "reset_url": f"{auth_router.app_base_url()}/forgot-password",
            },
        )
    ]
    live = [
        t
        for t in await _tokens(admin_engine, pw_user.id)
        if t.live and t.used_at is None
    ]
    assert live == []


async def test_signup_burns_a_hash_on_every_branch(
    client, admin_engine, pw_user, outbox, monkeypatch
):
    # Timing side channel: every branch must cost the same argon2 work as
    # every other, or response time (or a skipped hash) says which one ran.
    # Checked per-request, not cumulatively, so one branch skipping its hash
    # can't hide behind another branch's call.
    calls = {"n": 0}
    real = auth_router.hash_password_async

    async def counting(pw):
        calls["n"] += 1
        return await real(pw)

    monkeypatch.setattr(auth_router, "hash_password_async", counting)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET email_verified_at = now() WHERE id = :id"),
            {"id": pw_user.id},
        )
    placeholder = await _make_user(admin_engine, "placeholder@example.com")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET password_hash = 'old-hash' WHERE id = :id"),
            {"id": placeholder.id},
        )

    calls["n"] = 0
    await client.post(
        "/api/auth/signup", json={"email": pw_user.email, "password": "password1"}
    )
    assert calls["n"] == 1  # (a) existing verified user

    calls["n"] = 0
    await client.post(
        "/api/auth/signup", json={"email": "new2@example.com", "password": "password1"}
    )
    assert calls["n"] == 1  # (b) new address

    calls["n"] = 0
    await client.post(
        "/api/auth/signup",
        json={"email": placeholder.email, "password": "password1"},
    )
    assert calls["n"] == 1  # (c) existing unverified placeholder


async def test_stale_unverified_placeholder_is_reclaimed(
    client, admin_engine, pw_user, outbox, fake_redis
):
    await make_email_token(
        admin_engine, pw_user.id, "verify_email", "h1", expires_in_s=-1
    )
    before = (await _user_row(admin_engine, pw_user.email)).sessions_valid_after
    res = await client.post(
        "/api/auth/signup", json={"email": pw_user.email, "password": "newpass99"}
    )
    assert res.status_code == 202 and res.json() == BODY
    row = await _user_row(admin_engine, pw_user.email)
    assert row.password_hash != "old-hash" and row.email_verified_at is None
    assert row.sessions_valid_after > before
    assert await fake_redis.get(f"sva:{pw_user.id}") == str(
        int(row.sessions_valid_after.timestamp())
    )
    assert [c[1] for c in outbox] == ["verify_email"]
    live = [
        t
        for t in await _tokens(admin_engine, pw_user.id)
        if t.live and t.used_at is None
    ]
    assert len(live) == 1


async def test_google_born_user_is_verified_so_signup_says_account_exists(
    client, admin_engine, outbox
):
    u = await _make_user(admin_engine, "g@example.com")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET email_verified_at = now() WHERE id = :id"),
            {"id": u.id},
        )
    res = await client.post(
        "/api/auth/signup", json={"email": "g@example.com", "password": "password1"}
    )
    assert res.status_code == 202
    assert [c[1] for c in outbox] == ["account_exists"]
    assert (await _user_row(admin_engine, "g@example.com")).password_hash is None


async def test_no_email_sent_when_commit_fails(
    client, admin_engine, outbox, monkeypatch
):
    from sqlalchemy.ext.asyncio import AsyncSession

    async def boom(self):
        raise RuntimeError("db down")

    monkeypatch.setattr(AsyncSession, "commit", boom)
    with pytest.raises(RuntimeError):
        await client.post(
            "/api/auth/signup", json={"email": "x@example.com", "password": "password1"}
        )
    assert outbox == []


async def test_a_dead_broker_leaves_the_202_untouched(client, pw_user, monkeypatch):
    # Uniform 202 is the anti-enumeration contract; a broker outage must not
    # break it (nor make the caller wait for the publish). The real publisher
    # runs here — only the task is faked.
    def unreachable(args, retry):
        raise OSError("broker down")

    monkeypatch.setattr(
        auth_router,
        "send_email",
        SimpleNamespace(name="send_email", apply_async=unreachable),
    )
    signup = await client.post(
        "/api/auth/signup", json={"email": "dead@example.com", "password": "password1"}
    )
    resend = await client.post(
        "/api/auth/resend-verification", json={"email": pw_user.email}
    )
    await asyncio.gather(*enqueue._pending, return_exceptions=True)

    assert signup.status_code == resend.status_code == 202
    assert signup.json() == resend.json() == BODY


async def test_signup_per_email_cap_limits_outgoing_mail(client, admin_engine, outbox):
    # First POST creates the user; the next two hit the unverified-placeholder
    # branch (re-signup on the same, still-unverified address). All three
    # stay under the per-email cap (3/h); the 4th trips it. The IP cap is
    # 10/h so it won't interfere with only 4 requests from one IP.
    email = "capped@example.com"
    for _ in range(3):
        res = await client.post(
            "/api/auth/signup", json={"email": email, "password": "password1"}
        )
        assert res.status_code == 202
    fourth = await client.post(
        "/api/auth/signup", json={"email": email, "password": "password1"}
    )
    assert fourth.status_code == 429
    assert len(outbox) == 3


async def test_resend_verification_mirrors_signup(
    client, admin_engine, pw_user, outbox
):
    # A live link already exists (e.g. from signup); resend must void it so
    # exactly one verify link is ever live for a user.
    await make_email_token(
        admin_engine, pw_user.id, "verify_email", "h0", expires_in_s=3600
    )
    unknown = await client.post(
        "/api/auth/resend-verification", json={"email": "nobody@example.com"}
    )
    known = await client.post(
        "/api/auth/resend-verification", json={"email": pw_user.email}
    )
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json() == BODY
    assert [(c[0], c[1]) for c in outbox] == [(pw_user.email, "verify_email")]
    live = [
        t
        for t in await _tokens(admin_engine, pw_user.id)
        if t.live and t.used_at is None
    ]
    assert len(live) == 1
    async with admin_engine.connect() as conn:
        stored = (
            await conn.execute(
                text(
                    "SELECT token_hash FROM email_tokens"
                    " WHERE user_id = :u AND used_at IS NULL"
                ),
                {"u": pw_user.id},
            )
        ).scalar_one()
    assert stored != "h0"

    # Verified user (incl. Google-born): mirrors signup's account_exists
    # branch — no token work, existence still doesn't leak in the response.
    verified = await _make_user(admin_engine, "verified@example.com")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET email_verified_at = now() WHERE id = :id"),
            {"id": verified.id},
        )
    res = await client.post(
        "/api/auth/resend-verification", json={"email": verified.email}
    )
    assert res.status_code == 202 and res.json() == BODY
    assert outbox[-1] == (
        verified.email,
        "account_exists",
        {
            "login_url": f"{auth_router.app_base_url()}/login",
            "reset_url": f"{auth_router.app_base_url()}/forgot-password",
        },
    )
    assert await _tokens(admin_engine, verified.id) == []

    # Unverified, passwordless bootstrap placeholder: nothing to resend.
    placeholder = await _make_user(admin_engine, "placeholder2@example.com")
    before = len(outbox)
    res = await client.post(
        "/api/auth/resend-verification", json={"email": placeholder.email}
    )
    assert res.status_code == 202 and res.json() == BODY
    assert len(outbox) == before


async def test_resend_per_email_rate_limit(client, pw_user, outbox):
    for _ in range(3):
        await client.post(
            "/api/auth/resend-verification", json={"email": pw_user.email}
        )
    fourth = await client.post(
        "/api/auth/resend-verification", json={"email": pw_user.email}
    )
    assert fourth.status_code == 429
    assert len(outbox) == 3


async def test_signup_ip_rate_limit_unchanged(client, outbox):
    for i in range(10):
        await client.post(
            "/api/auth/signup",
            json={"email": f"u{i}@example.com", "password": "password1"},
        )
    res = await client.post(
        "/api/auth/signup", json={"email": "u10@example.com", "password": "password1"}
    )
    assert res.status_code == 429
