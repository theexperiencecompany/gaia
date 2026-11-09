"""
Tests for health check endpoints.

These are smoke tests — if the app boots and responds on these routes, the
deployment is healthy.
"""

from httpx import AsyncClient
import pytest

from app.models.health_models import DependencyStatus, ReadinessResponse
from tests.helpers import captured_wide_event


class TestHealthEndpoints:
    """Verify all health/ping routes return expected shape."""

    @pytest.mark.parametrize(
        "path",
        ["/", "/ping", "/health", "/api/v1/", "/api/v1/ping"],
    )
    async def test_health_returns_online(self, client: AsyncClient, path: str):
        resp = await client.get(path)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "online"
        assert "version" in body
        assert "name" in body

    async def test_health_includes_environment(self, client: AsyncClient):
        resp = await client.get("/health")
        body = resp.json()
        assert "environment" in body

    async def test_health_does_not_require_auth(self, unauthed_client: AsyncClient):
        """Health endpoints must be accessible without authentication."""
        resp = await unauthed_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "online"


class TestReadinessEndpoint:
    """GET /health/ready: 200 when every dependency answers, 503 naming the ones that do not."""

    @staticmethod
    def _report(*, mongodb_ok: bool) -> ReadinessResponse:
        return ReadinessResponse(
            status="ready" if mongodb_ok else "not_ready",
            dependencies=[
                DependencyStatus(name="postgres", ok=True, latency_ms=1.0),
                DependencyStatus(
                    name="mongodb",
                    ok=mongodb_ok,
                    latency_ms=2000.0,
                    error_type=None if mongodb_ok else "TimeoutError",
                ),
            ],
        )

    async def test_ready_is_200(
        self, unauthed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def ready() -> ReadinessResponse:
            return self._report(mongodb_ok=True)

        monkeypatch.setattr("app.api.v1.endpoints.readiness.check_readiness", ready)

        resp = await unauthed_client.get("/health/ready")

        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"

    async def test_a_failed_dependency_is_503_and_named(
        self, unauthed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def not_ready() -> ReadinessResponse:
            return self._report(mongodb_ok=False)

        monkeypatch.setattr("app.api.v1.endpoints.readiness.check_readiness", not_ready)

        async with captured_wide_event() as event:
            resp = await unauthed_client.get("/health/ready")

        assert resp.status_code == 503
        failed = [d["name"] for d in resp.json()["dependencies"] if not d["ok"]]
        assert failed == ["mongodb"]
        assert event["readiness"] == {"status": "not_ready", "failed": ["mongodb"]}
