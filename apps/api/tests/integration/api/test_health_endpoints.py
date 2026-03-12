"""Integration tests for health check endpoints.

Tests the health/ping/root endpoints return correct status and payload
structure through the full FastAPI request lifecycle.
"""

from unittest.mock import patch

import pytest


@pytest.mark.integration
class TestHealthEndpoints:
    """Test health check endpoints return expected responses."""

    async def test_health_endpoint_returns_200(self, test_client):
        """GET /health should return 200 with status 'online'."""
        response = await test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "online"
        assert "message" in data

    async def test_ping_endpoint_returns_200(self, test_client):
        """GET /ping should return 200 with same payload as /health."""
        response = await test_client.get("/ping")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "online"

    async def test_root_endpoint_returns_200(self, test_client):
        """GET / should return 200 (root health check)."""
        response = await test_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "online"

    async def test_api_v1_ping_returns_200(self, test_client):
        """GET /api/v1/ping should return 200."""
        response = await test_client.get("/api/v1/ping")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "online"

    async def test_health_response_contains_project_info(self, test_client):
        """Health response should include name, version, and environment fields."""
        response = await test_client.get("/health")
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "environment" in data

    async def test_health_response_includes_all_required_fields(self, test_client):
        """Health response must include status, message, name, version, and environment."""
        response = await test_client.get("/health")
        assert response.status_code == 200
        data = response.json()

        required_fields = {"status", "message", "name", "version", "environment"}
        missing = required_fields - set(data.keys())
        assert not missing, f"Health response missing fields: {missing}"

    async def test_health_response_status_is_online_string(self, test_client):
        """Health status field must be the exact string 'online', not a boolean or other value."""
        response = await test_client.get("/health")
        data = response.json()
        assert data["status"] == "online"
        assert isinstance(data["status"], str)

    async def test_health_when_project_info_unavailable_still_returns_200(
        self, test_client
    ):
        """GET /health should still return 200 when pyproject.toml cannot be read.

        The get_project_info utility falls back to default values on failure,
        so the endpoint must remain available even if file I/O fails.
        """
        with patch(
            "app.api.v1.endpoints.health.get_project_info",
            return_value={
                "name": "GAIA API",
                "version": "dev",
                "description": "Backend for GAIA",
            },
        ):
            response = await test_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "online"
        assert data["name"] == "GAIA API"
        assert data["version"] == "dev"

    async def test_health_when_get_project_info_raises_returns_500(self, test_client):
        """GET /health returns 500 when get_project_info raises unexpectedly.

        get_project_info() normally catches all exceptions internally and
        returns defaults, but if it propagates an exception the endpoint has
        no try/except and FastAPI must return 500 rather than 200.

        This guards against a hypothetical regression where the internal
        fallback is removed and the exception escapes.
        """
        with patch(
            "app.api.v1.endpoints.health.get_project_info",
            side_effect=RuntimeError("Unexpected I/O error reading pyproject.toml"),
        ):
            response = await test_client.get("/health")

        assert response.status_code == 500

    async def test_ping_and_health_return_identical_status(self, test_client):
        """Both /ping and /health must return the same 'status' value."""
        health_response = await test_client.get("/health")
        ping_response = await test_client.get("/ping")

        assert health_response.json()["status"] == ping_response.json()["status"]
