"""A write authenticated by the login cookie is refused unless the browser says
it came from hax's own pages (Sec-Fetch-Site same-origin or none, or an Origin
the API allows), and the 403 says why in its detail. The cookie's SameSite=Lax
already stops other sites' background requests; this second layer covers a
same-site page (another subdomain). Bearer-token clients, reads and the
internal routes are untouched."""

import os
import uuid

import pytest
from sqlalchemy import text

from packages.core.auth.passwords import hash_password
from tests.api.conftest import bearer
from tests.api.factories import make_user

COOKIE = "authjs.session-token"
GONE = f"/api/conversations/{uuid.uuid4()}"  # a write that reaches auth, then 404s
REFUSED = "cross-site request refused"
INTERNAL = {"X-Internal-Secret": os.environ["INTERNAL_API_SECRET"]}


def cookie_of(user) -> dict[str, str]:
    token = bearer(user)["Authorization"].removeprefix("Bearer ")
    return {"Cookie": f"{COOKIE}={token}"}


def assert_refused(r) -> None:
    assert r.status_code == 403
    assert r.json()["detail"] == REFUSED


async def test_a_cookie_write_from_another_site_is_refused(client, user_a):
    r = await client.delete(
        GONE,
        headers={
            **cookie_of(user_a),
            "Sec-Fetch-Site": "cross-site",
            "Origin": "https://evil.example",
        },
    )
    assert_refused(r)


async def test_a_cookie_write_from_a_sibling_subdomain_is_refused(client, user_a):
    r = await client.delete(
        GONE,
        headers={
            **cookie_of(user_a),
            "Sec-Fetch-Site": "same-site",
            "Origin": "https://evil.hax-ai.chat",
        },
    )
    assert_refused(r)


async def test_a_cookie_write_with_no_origin_signal_is_refused(client, user_a):
    r = await client.delete(GONE, headers=cookie_of(user_a))
    assert_refused(r)


async def test_a_cookie_write_from_the_same_origin_passes(client, user_a):
    r = await client.delete(
        GONE, headers={**cookie_of(user_a), "Sec-Fetch-Site": "same-origin"}
    )
    assert r.status_code == 404


async def test_a_cookie_write_from_an_allowed_origin_passes(
    client, user_a, monkeypatch
):
    # Dev and the journey stack serve the web and the API on different ports:
    # same site, another origin, listed in CORS_ALLOW_ORIGINS.
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3001")
    r = await client.delete(
        GONE,
        headers={
            **cookie_of(user_a),
            "Sec-Fetch-Site": "same-site",
            "Origin": "http://localhost:3001",
        },
    )
    assert r.status_code == 404


async def test_a_cookie_write_from_the_apps_own_base_url_passes(
    client, user_a, monkeypatch
):
    monkeypatch.setenv("APP_BASE_URL", "https://hax-ai.chat")
    r = await client.delete(
        GONE, headers={**cookie_of(user_a), "Origin": "https://hax-ai.chat"}
    )
    assert r.status_code == 404


async def test_a_bearer_write_is_untouched(client, user_a):
    r = await client.delete(
        GONE,
        headers={
            **bearer(user_a),
            "Sec-Fetch-Site": "cross-site",
            "Origin": "https://evil.example",
        },
    )
    assert r.status_code == 404


async def test_a_cookie_read_from_another_site_is_untouched(client, user_a):
    r = await client.get(
        "/api/conversations",
        headers={
            **cookie_of(user_a),
            "Sec-Fetch-Site": "cross-site",
            "Origin": "https://evil.example",
        },
    )
    assert r.status_code == 200


@pytest.mark.parametrize("path", ["/api/chat", "/api/documents"])
async def test_the_two_routes_the_review_named_refuse_a_cross_site_cookie_write(
    client, user_a, path
):
    r = await client.post(
        path,
        headers={
            **cookie_of(user_a),
            "Sec-Fetch-Site": "cross-site",
            "Origin": "https://evil.example",
        },
        content=b'{"prompt": "hi"}',
    )
    assert_refused(r)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PUT", "/api/me/profile", {"about": "I like tea."}),
        ("POST", f"/api/conversations/{uuid.uuid4()}/stop", None),
        ("DELETE", GONE, None),
    ],
    ids=["PUT", "POST", "DELETE"],
)
async def test_a_cookie_write_marked_cross_site_is_refused_even_with_no_origin(
    client, user_a, method, path, body
):
    r = await client.request(
        method,
        path,
        json=body,
        headers={**cookie_of(user_a), "Sec-Fetch-Site": "cross-site"},
    )
    assert_refused(r)


async def test_a_cookie_write_with_no_fetch_site_and_an_unlisted_origin_is_refused(
    client, user_a
):
    r = await client.delete(
        GONE, headers={**cookie_of(user_a), "Origin": "https://evil.example"}
    )
    assert_refused(r)


async def test_a_cookie_write_with_no_fetch_site_and_a_cors_listed_origin_passes(
    client, user_a, monkeypatch
):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3001")
    r = await client.delete(
        GONE, headers={**cookie_of(user_a), "Origin": "http://localhost:3001"}
    )
    assert r.status_code == 404


async def test_a_cookie_write_the_browser_marks_user_initiated_passes(client, user_a):
    r = await client.delete(
        GONE, headers={**cookie_of(user_a), "Sec-Fetch-Site": "none"}
    )
    assert r.status_code == 404


async def test_a_same_origin_cookie_write_completes(client, user_a):
    r = await client.put(
        "/api/me/profile",
        json={"about": "I like tea."},
        headers={**cookie_of(user_a), "Sec-Fetch-Site": "same-origin"},
    )
    assert 200 <= r.status_code < 300


async def test_an_internal_auth_route_ignores_a_cross_site_cookie(
    client, admin_engine, user_a
):
    u = await make_user(admin_engine, "x@example.com")
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE users SET password_hash = :h, email_verified_at = now()"
                " WHERE id = :id"
            ),
            {"h": hash_password("correct-horse"), "id": u.id},
        )
    r = await client.post(
        "/internal/auth/verify-credentials",
        json={"email": "x@example.com", "password": "correct-horse"},
        headers={**INTERNAL, **cookie_of(user_a), "Sec-Fetch-Site": "cross-site"},
    )
    assert r.status_code == 200
