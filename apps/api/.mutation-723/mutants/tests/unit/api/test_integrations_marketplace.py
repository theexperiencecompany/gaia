"""Tests for app/api/v1/endpoints/integrations/marketplace.py"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.models.integration_models import IntegrationResponse, MarketplaceResponse

# __init__.py: prefix="/integrations", marketplace.py router mounted at /marketplace
BASE = "/api/v1/integrations/marketplace"

_MARKETPLACE = "app.api.v1.endpoints.integrations.marketplace"


def _integration_response(
    integration_id: str, name: str, **overrides: object
) -> IntegrationResponse:
    data: dict[str, object] = {
        "integration_id": integration_id,
        "name": name,
        "description": "A test integration",
        "category": "custom",
        "managed_by": "mcp",
        "source": "custom",
        "is_featured": False,
        "display_priority": 0,
    }
    data.update(overrides)
    return IntegrationResponse.model_validate(data)


def _marketplace_response() -> MarketplaceResponse:
    featured = _integration_response("f1", "Featured Tool", is_featured=True, display_priority=10)
    regular = _integration_response("i1", "My Tool", clone_count=5)
    return MarketplaceResponse(featured=[featured], integrations=[regular], total=2)


class TestListMarketplaceIntegrations:
    """Tests for GET /api/v1/integrations/marketplace."""

    @pytest.mark.asyncio
    async def test_happy_path(self, client: AsyncClient) -> None:
        with patch(f"{_MARKETPLACE}.get_all_integrations", new_callable=AsyncMock) as mock_get_all:
            mock_get_all.return_value = _marketplace_response()
            resp = await client.get(BASE)

        assert resp.status_code == 200
        mock_get_all.assert_awaited_once_with(category=None)

        body = resp.json()
        assert body["total"] == 2
        assert body["featured"][0]["integrationId"] == "f1"
        assert body["featured"][0]["isFeatured"] is True
        assert body["featured"][0]["displayPriority"] == 10

        item = body["integrations"][0]
        assert item["integrationId"] == "i1"
        assert item["name"] == "My Tool"
        assert item["description"] == "A test integration"
        assert item["category"] == "custom"
        assert item["managedBy"] == "mcp"
        assert item["source"] == "custom"
        assert item["cloneCount"] == 5
        assert item["tools"] == []

    @pytest.mark.asyncio
    async def test_category_param_passed_through(self, client: AsyncClient) -> None:
        with patch(f"{_MARKETPLACE}.get_all_integrations", new_callable=AsyncMock) as mock_get_all:
            mock_get_all.return_value = _marketplace_response()
            resp = await client.get(BASE, params={"category": "ai"})

        assert resp.status_code == 200
        mock_get_all.assert_awaited_once_with(category="ai")

    @pytest.mark.asyncio
    async def test_empty_marketplace(self, client: AsyncClient) -> None:
        with patch(f"{_MARKETPLACE}.get_all_integrations", new_callable=AsyncMock) as mock_get_all:
            mock_get_all.return_value = MarketplaceResponse()
            resp = await client.get(BASE)

        assert resp.status_code == 200
        assert resp.json() == {"featured": [], "integrations": [], "total": 0}

    @pytest.mark.asyncio
    async def test_service_error_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{_MARKETPLACE}.get_all_integrations",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db down"),
        ):
            resp = await client.get(BASE)

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to fetch integrations"


class TestGetMarketplaceIntegration:
    """Tests for GET /api/v1/integrations/marketplace/{integration_id}."""

    @pytest.mark.asyncio
    async def test_happy_path(self, client: AsyncClient) -> None:
        with patch(
            f"{_MARKETPLACE}.get_integration_details", new_callable=AsyncMock
        ) as mock_details:
            mock_details.return_value = _integration_response(
                "i1", "My Tool", slug="my-tool", clone_count=5
            )
            resp = await client.get(f"{BASE}/i1")

        assert resp.status_code == 200
        mock_details.assert_awaited_once_with("i1")
        body = resp.json()
        assert body["integrationId"] == "i1"
        assert body["name"] == "My Tool"
        assert body["slug"] == "my-tool"
        assert body["cloneCount"] == 5

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, client: AsyncClient) -> None:
        with patch(
            f"{_MARKETPLACE}.get_integration_details", new_callable=AsyncMock
        ) as mock_details:
            mock_details.return_value = None
            resp = await client.get(f"{BASE}/missing")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Integration not found"

    @pytest.mark.asyncio
    async def test_service_error_returns_500(self, client: AsyncClient) -> None:
        """Route has no try/except, so the app-level handler maps it to 500."""
        with patch(
            f"{_MARKETPLACE}.get_integration_details",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db down"),
        ):
            resp = await client.get(f"{BASE}/i1")

        assert resp.status_code == 500
        assert resp.json() == {"error": "internal_server_error"}
