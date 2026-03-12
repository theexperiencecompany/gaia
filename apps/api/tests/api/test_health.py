"""
Tests for health check endpoints.

These are smoke tests — if the app boots and responds on these routes, the
deployment is healthy.
"""

import pytest
from httpx import AsyncClient


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
