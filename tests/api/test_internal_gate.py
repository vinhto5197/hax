"""The internal routes answer 404 to a missing or wrong secret."""

import pytest

BODY = {"email": "a@example.com", "password": "password1"}


@pytest.mark.parametrize("headers", [{}, {"X-Internal-Secret": "wrong"}])
async def test_wrong_or_missing_secret_is_404(client, headers):
    r = await client.post(
        "/internal/auth/verify-credentials", json=BODY, headers=headers
    )
    assert r.status_code == 404
