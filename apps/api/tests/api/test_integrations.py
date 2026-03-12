"""Tests for public integration endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch


INTEGRATION_ID = "integ-001"
SLUG = "my-tool-mcp-custom-integ001"


def _make_integration_doc(
    integration_id: str = INTEGRATION_ID,
    name: str = "My Tool",
    is_public: bool = True,
) -> dict:
    return {
        "_id": "fake-oid",
        "integration_id": integration_id,
        "name": name,
        "description": "A test integration",
        "category": "custom",
        "is_public": is_public,
        "tools": [{"name": "tool_a", "description": "does A"}],
        "mcp_config": {
            "server_url": "https://mcp.example.com",
            "requires_auth": False,
            "auth_type": "none",
        },
        "clone_count": 5,
        "icon_url": None,
    }


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
        doc = _make_integration_doc()
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[doc])

        with (
            patch(
                "app.api.v1.endpoints.integrations.public.search_public_integrations",
                new_callable=AsyncMock,
                return_value=search_results,
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.integrations_collection"
            ) as mock_coll,
        ):
            mock_coll.find = MagicMock(return_value=cursor)

            resp = await client.get("/api/v1/integrations/search?q=tool")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["integrations"]) == 1
            assert data["integrations"][0]["integrationId"] == INTEGRATION_ID

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
        with patch(
            "app.api.v1.endpoints.integrations.public.parse_integration_slug",
            return_value={},
        ):
            resp = await client.get("/api/v1/integrations/public/bad-slug")
            assert resp.status_code == 404

    async def test_not_found(self, client):
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[])

        with (
            patch(
                "app.api.v1.endpoints.integrations.public.parse_integration_slug",
                return_value={"shortid": "abc123"},
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.integrations_collection"
            ) as mock_coll,
        ):
            mock_coll.aggregate = MagicMock(return_value=cursor)

            resp = await client.get("/api/v1/integrations/public/some-slug")
            assert resp.status_code == 404
