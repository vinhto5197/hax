"""current_user with an anonymous (no-email) bearer: accepted, email None."""

from starlette.requests import Request

from apps.api.auth import current_user
from tests.api.conftest import bearer


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "method": "GET", "path": "/"})


async def test_anonymous_bearer_has_no_email(user_a):
    me = await current_user(_request(bearer(user_a, anonymous=True)))
    assert me.id == user_a.id
    assert me.email is None


async def test_regular_bearer_carries_email(user_a):
    me = await current_user(_request(bearer(user_a)))
    assert me.email == user_a.email


async def test_anonymous_bearer_is_accepted_by_a_route(client, user_a):
    r = await client.get("/api/conversations", headers=bearer(user_a, anonymous=True))
    assert r.status_code == 200
    assert r.json() == []
