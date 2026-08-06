"""Tests for public integration endpoints."""

from unittest.mock import AsyncMock, patch

from app.models.integration_models import Integration

INTEGRATION_ID = "integ-001"


def _make_integration(
    integration_id: str = INTEGRATION_ID,
    name: str = "My Tool",
) -> Integration:
    return Integration.model_validate(
        {
            "integration_id": integration_id,
            "name": name,
            "description": "A test integration",
            "category": "custom",
            "managed_by": "mcp",
            "source": "custom",
            "is_public": True,
            "tools": [{"name": "tool_a", "description": "does A"}],
            "mcp_config": {
                "server_url": "https://mcp.example.com",
                "requires_auth": False,
                "auth_type": "none",
            },
            "clone_count": 5,
            "icon_url": None,
        }
    )


class TestSearchIntegrations:
    async def test_empty_query_returns_empty(self, client):
        resp = await client.get("/api/v1/integrations/search?q=")
        assert resp.status_code == 200
        data = resp.json()
        assert data["integrations"] == []

    async def test_search_with_results(self, client):
        search_results = [
            {
                "integration_id": INTEGRATION_ID,
                "relevance_score": 0.95,
            }
        ]

        with (
            patch(
                "app.api.v1.endpoints.integrations.public.search_public_integrations",
                new_callable=AsyncMock,
                return_value=search_results,
            ),
            patch("app.api.v1.endpoints.integrations.public.integration_repository") as mock_repo,
        ):
            mock_repo.find_public_by_ids = AsyncMock(return_value=[_make_integration()])

            resp = await client.get("/api/v1/integrations/search?q=tool")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["integrations"]) == 1
            assert data["integrations"][0]["integrationId"] == INTEGRATION_ID
            mock_repo.find_public_by_ids.assert_awaited_once_with([INTEGRATION_ID])

    async def test_search_no_matches(self, client):
        with patch(
            "app.api.v1.endpoints.integrations.public.search_public_integrations",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await client.get("/api/v1/integrations/search?q=nonexistent")
            assert resp.status_code == 200
            assert resp.json()["integrations"] == []


class TestGetPublicIntegration:
    async def test_invalid_slug(self, client):
        """A slug that parses to nothing never reaches the legacy prefix lookup."""
        with (
            patch("app.api.v1.endpoints.integrations.public.integration_repository") as mock_repo,
            patch(
                "app.api.v1.endpoints.integrations.public.parse_integration_slug",
                return_value={},
            ),
        ):
            mock_repo.get_public_by_slug = AsyncMock(return_value=None)
            mock_repo.get_public_by_id_prefix = AsyncMock(return_value=None)

            resp = await client.get("/api/v1/integrations/public/bad-slug")
            assert resp.status_code == 404
            mock_repo.get_public_by_id_prefix.assert_not_awaited()

    async def test_not_found(self, client):
        """A parseable legacy slug falls back to the id-prefix lookup, then 404s."""
        with (
            patch(
                "app.api.v1.endpoints.integrations.public.parse_integration_slug",
                return_value={"shortid": "abc123"},
            ),
            patch("app.api.v1.endpoints.integrations.public.integration_repository") as mock_repo,
        ):
            mock_repo.get_public_by_slug = AsyncMock(return_value=None)
            mock_repo.get_public_by_id_prefix = AsyncMock(return_value=None)

            resp = await client.get("/api/v1/integrations/public/some-slug")
            assert resp.status_code == 404
            mock_repo.get_public_by_id_prefix.assert_awaited_once_with("abc123")
