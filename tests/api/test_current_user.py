"""current_user with an anonymous (no-email) bearer: accepted, email None."""

import os
import time

import jwt
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


async def test_a_token_with_no_email_key_at_all_is_also_anonymous(user_a):
    # auth.ts always emits the key; a token minted elsewhere may omit it. Both
    # read as a visitor.
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": str(user_a.id),
            "iss": "hax",
            "aud": "hax-api",
            "iat": now,
            "exp": now + 600,
            "jti": "t",
            "auth_time": now,
        },
        os.environ["AUTH_SECRET"],
        algorithm="HS256",
    )
    me = await current_user(_request({"Authorization": f"Bearer {token}"}))
    assert me.email is None
