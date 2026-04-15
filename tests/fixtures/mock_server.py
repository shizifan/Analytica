import pytest_asyncio
import httpx
from mock_server.main import app


@pytest_asyncio.fixture(scope="session")
async def mock_client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": "Bearer TEST_TOKEN_2024"},
        timeout=10.0,
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def mock_client_no_auth():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        timeout=10.0,
    ) as client:
        yield client
