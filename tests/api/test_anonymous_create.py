"""POST /internal/auth/anonymous: a user with no email, limited per visitor
address, reachable only with the internal secret."""

import os

from sqlalchemy import text

from tests.api.conftest import bearer

INTERNAL = {"X-Internal-Secret": os.environ["INTERNAL_API_SECRET"]}


async def _create(client, ip="203.0.113.7"):
    return await client.post(
        "/internal/auth/anonymous", headers={**INTERNAL, "X-Visitor-IP": ip}
    )


async def test_creates_a_user_with_no_email(client, admin_engine):
    r = await _create(client)
    assert r.status_code == 200
    uid = r.json()["id"]
    async with admin_engine.connect() as conn:
        email = (
            await conn.execute(
                text("SELECT email FROM users WHERE id = :i"), {"i": uid}
            )
        ).scalar_one()
    assert email is None


async def test_the_new_visitor_can_use_the_api(client):
    uid = (await _create(client)).json()["id"]

    class Visitor:
        id = uid
        email = None

    r = await client.get("/api/conversations", headers=bearer(Visitor, anonymous=True))
    assert r.status_code == 200 and r.json() == []


async def test_limited_per_visitor_address(client, monkeypatch):
    monkeypatch.setenv("ANON_PER_IP_PER_DAY", "2")
    assert (await _create(client, "198.51.100.1")).status_code == 200
    assert (await _create(client, "198.51.100.1")).status_code == 200
    third = await _create(client, "198.51.100.1")
    assert third.status_code == 429
    assert third.json()["detail"] == {"code": "rate_limited"}
    # Another address is a different bucket.
    assert (await _create(client, "198.51.100.2")).status_code == 200


async def test_requires_the_internal_secret(client):
    assert (await client.post("/internal/auth/anonymous")).status_code == 404
