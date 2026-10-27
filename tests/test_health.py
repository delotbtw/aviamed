async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_protected_endpoint_requires_auth(client):
    resp = await client.get("/users/me")
    assert resp.status_code == 401
