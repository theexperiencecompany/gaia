"""Tests for app/api/v1/endpoints/integrations/community.py"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.schemas.integrations.responses import (
    CommunityIntegrationItem,
    CommunityListResponse,
)

# __init__.py: prefix="/integrations", community.py router mounted at /community
BASE = "/api/v1/integrations/community"

_COMMUNITY = "app.api.v1.endpoints.integrations.community"


def _community_response() -> CommunityListResponse:
    return CommunityListResponse(
        integrations=[
            CommunityIntegrationItem.model_validate(
                {
                    "integration_id": "i1",
                    "slug": "my-tool",
                    "name": "My Tool",
                    "description": "A community tool",
                    "category": "custom",
                    "clone_count": 5,
                    "tool_count": 2,
                    "tools": [{"name": "tool_a", "description": "does A"}],
                }
            )
        ],
        total=1,
        has_more=False,
    )


class TestListCommunityIntegrations:
    """Tests for GET /api/v1/integrations/community."""

    @pytest.mark.asyncio
    async def test_happy_path_default_params(self, client: AsyncClient) -> None:
        with patch(f"{_COMMUNITY}.list_community", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = _community_response()
            resp = await client.get(BASE)

        assert resp.status_code == 200
        assert mock_list.await_args.args == ("popular", "all", 20, 0, None)

        body = resp.json()
        assert body["total"] == 1
        assert body["has_more"] is False
        item = body["integrations"][0]
        assert item["integrationId"] == "i1"
        assert item["slug"] == "my-tool"
        assert item["name"] == "My Tool"
        assert item["description"] == "A community tool"
        assert item["category"] == "custom"
        assert item["cloneCount"] == 5
        assert item["toolCount"] == 2
        assert item["iconUrl"] is None
        assert item["publishedAt"] is None
        assert item["creator"] is None
        assert item["tools"] == [{"name": "tool_a", "description": "does A", "destructive": False}]

    @pytest.mark.asyncio
    async def test_query_params_passed_through(self, client: AsyncClient) -> None:
        with patch(f"{_COMMUNITY}.list_community", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = _community_response()
            resp = await client.get(
                BASE,
                params={
                    "sort": "newest",
                    "category": "productivity",
                    "limit": 10,
                    "offset": 5,
                    "search": "calendar",
                },
            )

        assert resp.status_code == 200
        assert mock_list.await_args.args == ("newest", "productivity", 10, 5, "calendar")

    @pytest.mark.asyncio
    async def test_empty_list(self, client: AsyncClient) -> None:
        with patch(f"{_COMMUNITY}.list_community", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = CommunityListResponse()
            resp = await client.get(BASE)

        assert resp.status_code == 200
        assert resp.json() == {"integrations": [], "total": 0, "has_more": False}

    @pytest.mark.asyncio
    async def test_invalid_limit_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(BASE, params={"limit": "abc"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_service_error_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{_COMMUNITY}.list_community",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db down"),
        ):
            resp = await client.get(BASE)

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to fetch community integrations"
