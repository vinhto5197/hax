from tests.api.conftest import bearer


async def test_unauthenticated_request_401(client):
    r = await client.get("/api/conversations")
    assert r.status_code == 401


async def test_bearer_path_authenticates(client, user_a):
    r = await client.get("/api/conversations", headers=bearer(user_a))
    assert r.status_code == 200
    assert r.json() == []
