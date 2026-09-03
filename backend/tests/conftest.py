import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.auth.jwt import create_access_token

@pytest.fixture
def auth_headers():
    token = create_access_token({"sub": "test_user_id"})
    return {"Authorization": f"Bearer {token}"}

@pytest_asyncio.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
