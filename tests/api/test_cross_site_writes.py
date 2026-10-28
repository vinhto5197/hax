"""A write authenticated by the login cookie is refused unless the browser says
it came from hax's own pages (Sec-Fetch-Site same-origin, or an Origin the API
allows). The cookie's SameSite=Lax already stops other sites' background
requests; this second layer covers a same-site page (another subdomain).
Bearer-token clients, reads and the internal routes are untouched."""

import uuid

import pytest

from tests.api.conftest import bearer

COOKIE = "authjs.session-token"
GONE = f"/api/conversations/{uuid.uuid4()}"  # a write that reaches auth, then 404s


def cookie_of(user) -> dict[str, str]:
    token = bearer(user)["Authorization"].removeprefix("Bearer ")
    return {"Cookie": f"{COOKIE}={token}"}


async def test_a_cookie_write_from_another_site_is_refused(client, user_a):
    r = await client.delete(
        GONE,
        headers={
            **cookie_of(user_a),
            "Sec-Fetch-Site": "cross-site",
            "Origin": "https://evil.example",
        },
    )
    assert r.status_code == 403


async def test_a_cookie_write_from_a_sibling_subdomain_is_refused(client, user_a):
    r = await client.delete(
        GONE,
        headers={
            **cookie_of(user_a),
            "Sec-Fetch-Site": "same-site",
            "Origin": "https://evil.hax-ai.chat",
        },
    )
    assert r.status_code == 403


async def test_a_cookie_write_with_no_origin_signal_is_refused(client, user_a):
    r = await client.delete(GONE, headers=cookie_of(user_a))
    assert r.status_code == 403


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
    assert r.status_code == 403
