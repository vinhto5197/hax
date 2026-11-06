"""POST /internal/auth/verify-credentials: the per-address limit keys on the
browser address the web server forwards in X-Visitor-IP, falling back to the
connection's own address when the header is absent or empty; the per-email
limit ignores the address."""

import os

from sqlalchemy import text

from packages.core.auth.passwords import hash_password
from tests.api.factories import make_user

INTERNAL = {"X-Internal-Secret": os.environ["INTERNAL_API_SECRET"]}
IP_LIMIT = 30
EMAIL_LIMIT = 5
RATE_LIMITED = {"code": "rate_limited"}
INVALID = {"code": "invalid_credentials"}


async def _attempt(client, email, password="wrong-password", ip=None):
    headers = dict(INTERNAL)
    if ip is not None:
        headers["X-Visitor-IP"] = ip
    return await client.post(
        "/internal/auth/verify-credentials",
        json={"email": email, "password": password},
        headers=headers,
    )


async def _exhaust(client, ip, prefix="x"):
    """IP_LIMIT wrong-password attempts from `ip`, each for a distinct email."""
    for i in range(IP_LIMIT):
        r = await _attempt(client, f"{prefix}{i}@example.com", ip=ip)
        assert r.status_code == 401, (i, r.status_code, r.text)
        assert r.json()["detail"] == INVALID


async def _verified_user(admin_engine, email, password):
    u = await make_user(admin_engine, email)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE users SET password_hash = :h, email_verified_at = now()"
                " WHERE id = :id"
            ),
            {"h": hash_password(password), "id": u.id},
        )
    return u


async def test_30_attempts_from_one_visitor_address_answered_31st_rate_limited(
    client,
):
    await _exhaust(client, "198.51.100.4")
    r = await _attempt(client, "next@example.com", ip="198.51.100.4")
    assert r.status_code == 429
    assert r.json()["detail"] == RATE_LIMITED


async def test_another_visitor_address_is_not_limited_when_one_is_exhausted(
    client, admin_engine
):
    await _verified_user(admin_engine, "member@example.com", "correct-horse")
    await _exhaust(client, "198.51.100.4")
    assert (
        await _attempt(client, "next@example.com", ip="198.51.100.4")
    ).status_code == 429

    wrong = await _attempt(client, "member@example.com", ip="203.0.113.9")
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == INVALID

    right = await _attempt(
        client, "member@example.com", password="correct-horse", ip="203.0.113.9"
    )
    assert right.status_code == 200


async def test_attempts_without_a_visitor_address_key_on_the_connection_address(
    client,
):
    # Half header-less, half with an empty header: both fall back to the same
    # bucket, the connection's own address.
    for i in range(IP_LIMIT):
        ip = None if i % 2 == 0 else ""
        r = await _attempt(client, f"conn{i}@example.com", ip=ip)
        assert r.status_code == 401, (i, r.status_code, r.text)

    r = await _attempt(client, "conn-next@example.com")
    assert r.status_code == 429
    assert r.json()["detail"] == RATE_LIMITED

    forwarded = await _attempt(client, "fwd@example.com", ip="198.51.100.77")
    assert forwarded.status_code == 401
    assert forwarded.json()["detail"] == INVALID


async def test_an_empty_visitor_address_is_limited_like_a_missing_one(client):
    await _exhaust_with_empty_header(client)
    r = await _attempt(client, "empty-next@example.com", ip="")
    assert r.status_code == 429
    assert r.json()["detail"] == RATE_LIMITED
    r = await _attempt(client, "none-next@example.com")
    assert r.status_code == 429


async def _exhaust_with_empty_header(client):
    for i in range(IP_LIMIT):
        r = await _attempt(client, f"empty{i}@example.com", ip="")
        assert r.status_code == 401, (i, r.status_code, r.text)


async def test_the_per_email_limit_holds_across_visitor_addresses(client):
    for i in range(EMAIL_LIMIT):
        r = await _attempt(client, "target@example.com", ip=f"198.51.100.{i + 10}")
        assert r.status_code == 401, (i, r.status_code, r.text)
    r = await _attempt(client, "target@example.com", ip="198.51.100.99")
    assert r.status_code == 429
    assert r.json()["detail"] == RATE_LIMITED
