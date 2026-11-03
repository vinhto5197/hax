"""422s from request validation never echo the rejected body: each detail
item keeps loc, msg and type (what the web reads) and drops input and ctx,
so a rejected password never comes back in the response."""

import pytest

TOO_SHORT = "hunter7"
TOO_LONG = "S3cretPassw0rd!" * 10


@pytest.mark.parametrize("password", [TOO_SHORT, TOO_LONG], ids=["short", "long"])
async def test_signup_validation_error_does_not_echo_password(client, password):
    res = await client.post(
        "/api/auth/signup",
        json={"email": "echo@example.com", "password": password},
    )

    assert res.status_code == 422
    detail = res.json()["detail"]
    assert isinstance(detail, list) and detail
    for item in detail:
        assert set(item) == {"loc", "msg", "type"}
    assert any(item["loc"][-1] == "password" for item in detail)
    assert password not in res.text
