import asyncio

from httpx import ASGITransport, AsyncClient, Response

from rift_api.config import Settings
from rift_api.main import create_app


async def request_health() -> Response:
    app = create_app(Settings(service_name="rift-api", environment="test"))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get("/health")


def test_health_endpoint() -> None:
    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "rift-api",
    }
