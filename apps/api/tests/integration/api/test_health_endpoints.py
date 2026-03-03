"""Integration tests for health check endpoints.

Tests the health/ping/root endpoints return correct status and payload
structure through the full FastAPI request lifecycle.
"""

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
