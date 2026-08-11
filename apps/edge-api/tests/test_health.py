import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def get(path: str) -> Response:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


@pytest.mark.anyio
async def test_live_health_endpoint() -> None:
    response = await get("/api/v1/health/live")
    settings = get_settings()

    assert response.status_code == 200
    assert response.json() == {
        "status": "alive",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@pytest.mark.anyio
async def test_ready_health_endpoint() -> None:
    response = await get("/api/v1/health/ready")
    settings = get_settings()

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@pytest.mark.anyio
async def test_version_endpoint() -> None:
    response = await get("/api/v1/version")
    settings = get_settings()

    assert response.status_code == 200
    assert response.json() == {
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "country": settings.default_country,
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/version",
    ],
)
async def test_technical_responses_are_not_cached(path: str) -> None:
    response = await get(path)

    assert response.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_openapi_contains_only_technical_routes() -> None:
    response = await get("/openapi.json")
    document = response.json()

    assert set(document["paths"]) == {
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/version",
    }
    assert {
        operation["operationId"]
        for path in document["paths"].values()
        for operation in path.values()
    } == {"get_liveness", "get_readiness", "get_version"}
