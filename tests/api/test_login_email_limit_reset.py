"""POST /internal/auth/verify-credentials: only a login answered 200 resets
the per-email count; failures (wrong password, unverified email) still add up
to the limit, and no login ever resets the per-address count."""

import os

from sqlalchemy import text

from packages.core.auth.passwords import hash_password
from tests.api.factories import make_user

INTERNAL = {"X-Internal-Secret": os.environ["INTERNAL_API_SECRET"]}
IP_LIMIT = 30
EMAIL_LIMIT = 5
RATE_LIMITED = {"code": "rate_limited"}
INVALID = {"code": "invalid_credentials"}
UNVERIFIED = {"code": "email_unverified"}
PASSWORD = "correct-horse"


async def _attempt(client, email, password="wrong-password", ip=None):
    headers = dict(INTERNAL)
    if ip is not None:
        headers["X-Visitor-IP"] = ip
    return await client.post(
        "/internal/auth/verify-credentials",
        json={"email": email, "password": password},
        headers=headers,
    )


async def _member(admin_engine, email, verified=True):
    u = await make_user(admin_engine, email)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE users SET password_hash = :h,"
                " email_verified_at = CASE WHEN :v THEN now() END"
                " WHERE id = :id"
            ),
            {"h": hash_password(PASSWORD), "v": verified, "id": u.id},
        )
    return u


async def _wrong(client, email, n, ip_base):
    for i in range(n):
        r = await _attempt(client, email, ip=f"198.51.100.{ip_base + i}")
        assert r.status_code == 401, (i, r.status_code, r.text)
        assert r.json()["detail"] == INVALID


async def test_six_successful_logins_in_a_row_from_different_addresses_all_succeed(
    client, admin_engine
):
    await _member(admin_engine, "member@example.com")
    for i in range(EMAIL_LIMIT + 1):
        r = await _attempt(
            client, "member@example.com", password=PASSWORD, ip=f"203.0.113.{i + 1}"
        )
        assert r.status_code == 200, (i, r.status_code, r.text)


async def test_a_successful_login_resets_the_per_email_count(client, admin_engine):
    await _member(admin_engine, "member@example.com")
    await _wrong(client, "member@example.com", EMAIL_LIMIT - 1, ip_base=10)

    ok = await _attempt(
        client, "member@example.com", password=PASSWORD, ip="198.51.100.20"
    )
    assert ok.status_code == 200, ok.text

    await _wrong(client, "member@example.com", EMAIL_LIMIT, ip_base=30)
    r = await _attempt(
        client, "member@example.com", password=PASSWORD, ip="198.51.100.40"
    )
    assert r.status_code == 429
    assert r.json()["detail"] == RATE_LIMITED


async def test_five_wrong_passwords_refuse_the_sixth_even_with_the_right_password(
    client, admin_engine
):
    await _member(admin_engine, "member@example.com")
    await _wrong(client, "member@example.com", EMAIL_LIMIT, ip_base=10)
    r = await _attempt(
        client, "member@example.com", password=PASSWORD, ip="198.51.100.99"
    )
    assert r.status_code == 429
    assert r.json()["detail"] == RATE_LIMITED


async def test_a_successful_login_does_not_reset_the_per_address_count(
    client, admin_engine
):
    ip = "198.51.100.4"
    members = [f"m{i}@example.com" for i in range(3)]
    for email in members:
        await _member(admin_engine, email)

    # 30 attempts from one address: each member logs in successfully once,
    # the rest are wrong passwords for distinct emails.
    for i in range(IP_LIMIT):
        if i % 10 == 9:
            email = members[i // 10]
            r = await _attempt(client, email, password=PASSWORD, ip=ip)
            assert r.status_code == 200, (i, r.status_code, r.text)
        else:
            r = await _attempt(client, f"x{i}@example.com", ip=ip)
            assert r.status_code == 401, (i, r.status_code, r.text)

    r = await _attempt(client, members[0], password=PASSWORD, ip=ip)
    assert r.status_code == 429
    assert r.json()["detail"] == RATE_LIMITED


async def test_an_unverified_correct_password_after_five_failures_is_rate_limited(
    client, admin_engine
):
    await _member(admin_engine, "pending@example.com", verified=False)
    await _wrong(client, "pending@example.com", EMAIL_LIMIT, ip_base=10)
    r = await _attempt(
        client, "pending@example.com", password=PASSWORD, ip="198.51.100.99"
    )
    assert r.status_code == 429
    assert r.json()["detail"] == RATE_LIMITED


async def test_an_unverified_correct_password_does_not_reset_the_per_email_count(
    client, admin_engine
):
    await _member(admin_engine, "pending@example.com", verified=False)
    await _wrong(client, "pending@example.com", EMAIL_LIMIT - 1, ip_base=10)

    r = await _attempt(
        client, "pending@example.com", password=PASSWORD, ip="198.51.100.20"
    )
    assert r.status_code == 403
    assert r.json()["detail"] == UNVERIFIED

    r = await _attempt(
        client, "pending@example.com", password=PASSWORD, ip="198.51.100.21"
    )
    assert r.status_code == 429
    assert r.json()["detail"] == RATE_LIMITED


async def test_an_email_with_no_account_is_rate_limited_after_five_wrong_attempts(
    client,
):
    await _wrong(client, "nobody@example.com", EMAIL_LIMIT, ip_base=10)
    r = await _attempt(client, "nobody@example.com", ip="198.51.100.99")
    assert r.status_code == 429
    assert r.json()["detail"] == RATE_LIMITED


async def test_a_mixed_case_successful_login_resets_the_lowercase_per_email_count(
    client, admin_engine
):
    await _member(admin_engine, "member@example.com")
    await _wrong(client, "member@example.com", EMAIL_LIMIT - 1, ip_base=10)

    ok = await _attempt(
        client, "Member@Example.com", password=PASSWORD, ip="198.51.100.20"
    )
    assert ok.status_code == 200, ok.text

    # All five must be 401: the fifth would be 429 had the success not
    # cleared the lowercase bucket.
    await _wrong(client, "member@example.com", EMAIL_LIMIT, ip_base=30)
