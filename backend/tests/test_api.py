import pytest

@pytest.mark.asyncio
async def test_root_endpoint(async_client):
    response = await async_client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_digital_twin_state_unauthorized(async_client):
    response = await async_client.get("/api/v1/digital-twin/state")
    assert response.status_code in (401, 403)

@pytest.mark.asyncio
async def test_digital_twin_state_authorized(async_client, auth_headers):
    response = await async_client.get("/api/v1/digital-twin/state", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "cpu" in data
    assert "ram" in data
    assert "disk" in data

@pytest.mark.asyncio
async def test_digital_twin_update_authorized(async_client, auth_headers):
    response = await async_client.post("/api/v1/digital-twin/update", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "cpu" in data
