"""The public health route the uptime monitor and the compose healthcheck
both call: under /api, no auth, 200."""


async def test_health_is_public_and_under_api(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
