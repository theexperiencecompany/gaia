"""Tests for app/api/v1/endpoints/integrations/public.py"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# Base URL for integration public endpoints
# routes.py: prefix="/integrations", public.py router has no extra prefix
# public.py: @router.get("/public/{identifier}"), @router.post("/public/{integration_id}/add"), @router.get("/search")
BASE = "/api/v1/integrations"


# ---------------------------------------------------------------------------
# GET /integrations/public/{identifier}
# ---------------------------------------------------------------------------


class TestGetPublicIntegration:
    """Tests for GET /integrations/public/{identifier}."""

    @pytest.mark.asyncio
    async def test_native_integration_found(self, client: AsyncClient) -> None:
        """Return native platform integration with tools."""
        fake_native = MagicMock()
        fake_native.id = "googlecalendar"
        fake_native.name = "Google Calendar"
        fake_native.description = "Calendar integration"
        fake_native.category = "productivity"
        fake_native.managed_by = "self"
        fake_native.mcp_config = None
        fake_native.content = None

        mock_tools_store = MagicMock()
        mock_tools_store.get_tools = AsyncMock(
            return_value=[{"name": "create_event", "description": "Create event"}]
        )

        with (
            patch(
                "app.api.v1.endpoints.integrations.public.OAUTH_INTEGRATIONS",
                [fake_native],
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.get_mcp_tools_store",
                return_value=mock_tools_store,
            ),
        ):
            resp = await client.get(f"{BASE}/public/googlecalendar")

        assert resp.status_code == 200
        body = resp.json()
        assert body["integrationId"] == "googlecalendar"
        assert body["name"] == "Google Calendar"
        assert body["source"] == "platform"
        assert body["toolCount"] == 1
        assert body["authType"] == "oauth"

    @pytest.mark.asyncio
    async def test_native_integration_with_mcp_auth(self, client: AsyncClient) -> None:
        """Native integration with mcp_config returns its auth_type."""
        fake_native = MagicMock()
        fake_native.id = "mcp_tool"
        fake_native.name = "MCP Tool"
        fake_native.description = "An MCP tool"
        fake_native.category = "custom"
        fake_native.managed_by = "mcp"
        fake_native.mcp_config = MagicMock()
        fake_native.mcp_config.auth_type = "bearer"
        fake_native.content = None

        mock_tools_store = MagicMock()
        mock_tools_store.get_tools = AsyncMock(return_value=[])

        with (
            patch(
                "app.api.v1.endpoints.integrations.public.OAUTH_INTEGRATIONS",
                [fake_native],
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.get_mcp_tools_store",
                return_value=mock_tools_store,
            ),
        ):
            resp = await client.get(f"{BASE}/public/mcp_tool")

        assert resp.status_code == 200
        assert resp.json()["authType"] == "bearer"

    @pytest.mark.asyncio
    async def test_native_internal_integration_skipped(
        self, client: AsyncClient
    ) -> None:
        """Internal integrations are not returned as native matches."""
        fake_native = MagicMock()
        fake_native.id = "internal_tool"
        fake_native.managed_by = "internal"

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with (
            patch(
                "app.api.v1.endpoints.integrations.public.OAUTH_INTEGRATIONS",
                [fake_native],
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.integrations_collection"
            ) as mock_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.build_slug_lookup_pipeline",
                return_value=[],
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.parse_integration_slug",
                return_value={},
            ),
        ):
            mock_coll.aggregate = MagicMock(return_value=mock_cursor)
            resp = await client.get(f"{BASE}/public/internal_tool")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_slug_lookup_found(self, client: AsyncClient) -> None:
        """Return integration found via slug lookup pipeline."""
        doc = {
            "integration_id": "abc123",
            "slug": "my-tool",
            "name": "My Tool",
            "description": "A tool",
            "category": "custom",
        }
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[doc])

        with (
            patch("app.api.v1.endpoints.integrations.public.OAUTH_INTEGRATIONS", []),
            patch(
                "app.api.v1.endpoints.integrations.public.integrations_collection"
            ) as mock_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.build_slug_lookup_pipeline",
                return_value=[],
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.format_public_integration_response",
                return_value={
                    "integration_id": "abc123",
                    "slug": "my-tool",
                    "name": "My Tool",
                    "description": "A tool",
                    "category": "custom",
                    "source": "custom",
                    "clone_count": 5,
                    "tool_count": 2,
                },
            ),
        ):
            mock_coll.aggregate = MagicMock(return_value=mock_cursor)
            resp = await client.get(f"{BASE}/public/my-tool")

        assert resp.status_code == 200
        assert resp.json()["name"] == "My Tool"

    @pytest.mark.asyncio
    async def test_legacy_hash_fallback(self, client: AsyncClient) -> None:
        """Falls back to legacy hash-based lookup when slug lookup returns nothing."""
        empty_cursor = AsyncMock()
        empty_cursor.to_list = AsyncMock(return_value=[])

        doc = {"integration_id": "abc123", "name": "Legacy Tool"}
        hash_cursor = AsyncMock()
        hash_cursor.to_list = AsyncMock(return_value=[doc])

        call_count = 0

        def make_cursor(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return empty_cursor if call_count == 1 else hash_cursor

        with (
            patch("app.api.v1.endpoints.integrations.public.OAUTH_INTEGRATIONS", []),
            patch(
                "app.api.v1.endpoints.integrations.public.integrations_collection"
            ) as mock_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.build_slug_lookup_pipeline",
                return_value=[],
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.parse_integration_slug",
                return_value={"shortid": "abc123"},
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.build_public_integration_pipeline",
                return_value=[],
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.format_public_integration_response",
                return_value={
                    "integration_id": "abc123",
                    "slug": "legacy",
                    "name": "Legacy Tool",
                    "description": "d",
                    "category": "custom",
                    "source": "custom",
                    "clone_count": 0,
                    "tool_count": 0,
                },
            ),
        ):
            mock_coll.aggregate = MagicMock(side_effect=make_cursor)
            resp = await client.get(f"{BASE}/public/legacy-abc123")

        assert resp.status_code == 200
        assert resp.json()["name"] == "Legacy Tool"

    @pytest.mark.asyncio
    async def test_not_found(self, client: AsyncClient) -> None:
        """Return 404 when no integration matches."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with (
            patch("app.api.v1.endpoints.integrations.public.OAUTH_INTEGRATIONS", []),
            patch(
                "app.api.v1.endpoints.integrations.public.integrations_collection"
            ) as mock_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.build_slug_lookup_pipeline",
                return_value=[],
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.parse_integration_slug",
                return_value={},
            ),
        ):
            mock_coll.aggregate = MagicMock(return_value=mock_cursor)
            resp = await client.get(f"{BASE}/public/nonexistent")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(self, client: AsyncClient) -> None:
        """Unexpected exception maps to 500."""
        with (
            patch(
                "app.api.v1.endpoints.integrations.public.OAUTH_INTEGRATIONS",
                new=[],
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.build_slug_lookup_pipeline",
                side_effect=TypeError("boom"),
            ),
        ):
            resp = await client.get(f"{BASE}/public/bad")

        assert resp.status_code == 500
        assert "Failed to fetch integration" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /integrations/public/{integration_id}/add
# ---------------------------------------------------------------------------


class TestAddPublicIntegration:
    """Tests for POST /integrations/public/{integration_id}/add."""

    @pytest.mark.asyncio
    async def test_integration_not_found(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.integrations.public.integrations_collection"
        ) as mock_coll:
            mock_coll.find_one = AsyncMock(return_value=None)
            resp = await client.post(
                f"{BASE}/public/unknown/add",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_already_connected(self, client: AsyncClient) -> None:
        original_doc = {
            "integration_id": "integ1",
            "name": "Integ",
            "is_public": True,
            "mcp_config": {},
        }
        existing = {"user_id": "u1", "integration_id": "integ1", "status": "connected"}

        with (
            patch(
                "app.api.v1.endpoints.integrations.public.integrations_collection"
            ) as mock_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.user_integrations_collection"
            ) as mock_user_coll,
        ):
            mock_coll.find_one = AsyncMock(return_value=original_doc)
            mock_user_coll.find_one = AsyncMock(return_value=existing)

            resp = await client.post(
                f"{BASE}/public/integ1/add",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "connected"
        assert "already connected" in resp.json()["message"]

    @pytest.mark.asyncio
    async def test_bearer_required(self, client: AsyncClient) -> None:
        """When auth_type is bearer but no token provided, return error status."""
        original_doc = {
            "integration_id": "integ2",
            "name": "Bearer Integ",
            "is_public": True,
            "mcp_config": {
                "server_url": "https://example.com",
                "requires_auth": True,
                "auth_type": "bearer",
            },
        }

        with (
            patch(
                "app.api.v1.endpoints.integrations.public.integrations_collection"
            ) as mock_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.user_integrations_collection"
            ) as mock_user_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.add_user_integration",
                new_callable=AsyncMock,
            ),
        ):
            mock_coll.find_one = AsyncMock(return_value=original_doc)
            mock_coll.update_one = AsyncMock()
            mock_user_coll.find_one = AsyncMock(return_value=None)

            resp = await client.post(
                f"{BASE}/public/integ2/add",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "error"
        assert resp.json()["error"] == "bearer_required"

    @pytest.mark.asyncio
    async def test_successful_add_new_integration(self, client: AsyncClient) -> None:
        """New integration is added, clone count incremented, and connected."""
        original_doc = {
            "integration_id": "integ3",
            "name": "New Integ",
            "is_public": True,
            "mcp_config": {"server_url": "https://mcp.example.com"},
        }

        connect_result = MagicMock()
        connect_result.status = "connected"
        connect_result.redirect_url = None
        connect_result.tools_count = 5
        connect_result.message = "Done"

        with (
            patch(
                "app.api.v1.endpoints.integrations.public.integrations_collection"
            ) as mock_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.user_integrations_collection"
            ) as mock_user_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.add_user_integration",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=connect_result,
            ),
        ):
            mock_coll.find_one = AsyncMock(return_value=original_doc)
            mock_coll.update_one = AsyncMock()
            mock_user_coll.find_one = AsyncMock(return_value=None)

            resp = await client.post(
                f"{BASE}/public/integ3/add",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "connected"
        assert body["toolsCount"] == 5

    @pytest.mark.asyncio
    async def test_re_attempt_connection(self, client: AsyncClient) -> None:
        """Existing non-connected integration re-attempts connection."""
        original_doc = {
            "integration_id": "integ4",
            "name": "Retry Integ",
            "is_public": True,
            "mcp_config": {"server_url": "https://mcp.example.com"},
        }
        existing = {"user_id": "u1", "integration_id": "integ4", "status": "error"}

        connect_result = MagicMock()
        connect_result.status = "connected"
        connect_result.redirect_url = None
        connect_result.tools_count = 3
        connect_result.message = None

        with (
            patch(
                "app.api.v1.endpoints.integrations.public.integrations_collection"
            ) as mock_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.user_integrations_collection"
            ) as mock_user_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=connect_result,
            ),
        ):
            mock_coll.find_one = AsyncMock(return_value=original_doc)
            mock_user_coll.find_one = AsyncMock(return_value=existing)

            resp = await client.post(
                f"{BASE}/public/integ4/add",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "connected"
        assert resp.json()["message"] == "Integration added successfully"

    @pytest.mark.asyncio
    async def test_add_user_integration_value_error_suppressed(
        self, client: AsyncClient
    ) -> None:
        """ValueError from add_user_integration is suppressed (duplicate)."""
        original_doc = {
            "integration_id": "integ5",
            "name": "Dup Integ",
            "is_public": True,
            "mcp_config": {},
        }

        connect_result = MagicMock()
        connect_result.status = "connected"
        connect_result.redirect_url = None
        connect_result.tools_count = 0
        connect_result.message = "ok"

        with (
            patch(
                "app.api.v1.endpoints.integrations.public.integrations_collection"
            ) as mock_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.user_integrations_collection"
            ) as mock_user_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.add_user_integration",
                new_callable=AsyncMock,
                side_effect=ValueError("duplicate"),
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=connect_result,
            ),
        ):
            mock_coll.find_one = AsyncMock(return_value=original_doc)
            mock_coll.update_one = AsyncMock()
            mock_user_coll.find_one = AsyncMock(return_value=None)

            resp = await client.post(
                f"{BASE}/public/integ5/add",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.integrations.public.integrations_collection"
        ) as mock_coll:
            mock_coll.find_one = AsyncMock(side_effect=RuntimeError("boom"))
            resp = await client.post(
                f"{BASE}/public/bad/add",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# GET /integrations/search
# ---------------------------------------------------------------------------


class TestSearchIntegrations:
    """Tests for GET /integrations/search."""

    @pytest.mark.asyncio
    async def test_empty_query(self, client: AsyncClient) -> None:
        resp = await client.get(f"{BASE}/search", params={"q": ""})
        assert resp.status_code == 200
        assert resp.json()["integrations"] == []

    @pytest.mark.asyncio
    async def test_whitespace_only_query(self, client: AsyncClient) -> None:
        resp = await client.get(f"{BASE}/search", params={"q": "   "})
        assert resp.status_code == 200
        assert resp.json()["integrations"] == []

    @pytest.mark.asyncio
    async def test_no_search_results(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.integrations.public.search_public_integrations",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await client.get(f"{BASE}/search", params={"q": "nonexistent"})

        assert resp.status_code == 200
        assert resp.json()["integrations"] == []

    @pytest.mark.asyncio
    async def test_search_with_results(self, client: AsyncClient) -> None:
        search_results = [
            {"integration_id": "id1", "relevance_score": 0.95},
            {"integration_id": "id2", "relevance_score": 0.80},
        ]
        doc1 = {
            "integration_id": "id1",
            "name": "Tool A",
            "description": "Desc A",
            "category": "ai",
            "clone_count": 10,
            "tools": [{"name": "t1"}, {"name": "t2"}],
            "icon_url": "https://icon.png",
            "is_public": True,
        }
        doc2 = {
            "integration_id": "id2",
            "name": "Tool B",
            "description": "Desc B",
            "category": "custom",
            "clone_count": 0,
            "tools": [],
            "is_public": True,
        }

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[doc1, doc2])

        with (
            patch(
                "app.api.v1.endpoints.integrations.public.search_public_integrations",
                new_callable=AsyncMock,
                return_value=search_results,
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.integrations_collection"
            ) as mock_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.generate_integration_slug",
                side_effect=lambda name, category, integration_id: (
                    f"slug-{integration_id}"
                ),
            ),
        ):
            mock_coll.find = MagicMock(return_value=mock_cursor)
            resp = await client.get(f"{BASE}/search", params={"q": "tool"})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["integrations"]) == 2
        assert body["integrations"][0]["name"] == "Tool A"
        assert body["integrations"][0]["toolCount"] == 2
        assert body["query"] == "tool"

    @pytest.mark.asyncio
    async def test_search_skips_missing_docs(self, client: AsyncClient) -> None:
        """When a search result has no matching doc, it's skipped."""
        search_results = [
            {"integration_id": "id_missing", "relevance_score": 0.9},
        ]

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

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
            mock_coll.find = MagicMock(return_value=mock_cursor)
            resp = await client.get(f"{BASE}/search", params={"q": "missing"})

        assert resp.status_code == 200
        assert resp.json()["integrations"] == []

    @pytest.mark.asyncio
    async def test_search_unexpected_error(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.integrations.public.search_public_integrations",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db down"),
        ):
            resp = await client.get(f"{BASE}/search", params={"q": "test"})

        assert resp.status_code == 500
        assert "Failed to search" in resp.json()["detail"]
