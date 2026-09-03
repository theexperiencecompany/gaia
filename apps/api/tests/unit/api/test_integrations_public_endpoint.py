"""Tests for app/api/v1/endpoints/integrations/public.py"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from httpx import AsyncClient
import pytest

from app.api.v1.endpoints.integrations import public as public_endpoint
from app.models.integration_models import (
    Integration,
    IntegrationWithCreator,
    UserIntegrationDocument,
)
from app.schemas.integrations.requests import ConnectIntegrationRequest
from app.schemas.integrations.responses import ConnectIntegrationResponse
from app.services.analytics_service import AnalyticsEvents
from app.services.integrations.integration_connection_service import McpConnectRequest
from tests.helpers import captured_wide_event

# Base URL for integration public endpoints
# routes.py: prefix="/integrations", public.py router has no extra prefix
# public.py: @router.get("/public/{identifier}"), @router.post("/public/{integration_id}/add"), @router.get("/search")
BASE = "/api/v1/integrations"

_PUBLIC = "app.api.v1.endpoints.integrations.public"


def _integration(integration_id: str, name: str, **overrides: object) -> Integration:
    data: dict[str, object] = {
        "integration_id": integration_id,
        "name": name,
        "description": "",
        "category": "custom",
        "managed_by": "mcp",
        "source": "custom",
        "is_public": True,
    }
    data.update(overrides)
    return Integration.model_validate(data)


def _with_creator(integration_id: str, name: str, **overrides: object) -> IntegrationWithCreator:
    data: dict[str, object] = {
        "integration_id": integration_id,
        "name": name,
        "description": "",
        "category": "custom",
        "managed_by": "mcp",
        "source": "custom",
        "is_public": True,
    }
    data.update(overrides)
    return IntegrationWithCreator.model_validate(data)


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

        with (
            patch(
                "app.api.v1.endpoints.integrations.public.OAUTH_INTEGRATIONS",
                [fake_native],
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.get_integration_tools",
                new_callable=AsyncMock,
                return_value=[{"name": "create_event", "description": "Create event"}],
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

        with (
            patch(
                "app.api.v1.endpoints.integrations.public.OAUTH_INTEGRATIONS",
                [fake_native],
            ),
            patch(
                "app.api.v1.endpoints.integrations.public.get_integration_tools",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            resp = await client.get(f"{BASE}/public/mcp_tool")

        assert resp.status_code == 200
        assert resp.json()["authType"] == "bearer"

    @pytest.mark.asyncio
    async def test_native_internal_integration_skipped(self, client: AsyncClient) -> None:
        """Internal integrations are not returned as native matches."""
        fake_native = MagicMock()
        fake_native.id = "internal_tool"
        fake_native.managed_by = "internal"

        with (
            patch(f"{_PUBLIC}.OAUTH_INTEGRATIONS", [fake_native]),
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.parse_integration_slug", return_value={}),
        ):
            mock_repo.get_public_by_slug = AsyncMock(return_value=None)
            resp = await client.get(f"{BASE}/public/internal_tool")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_slug_lookup_found(self, client: AsyncClient) -> None:
        """Return integration found via slug lookup."""
        integration = _with_creator(
            "abc123", "My Tool", slug="my-tool", description="A tool", clone_count=5
        )

        with (
            patch(f"{_PUBLIC}.OAUTH_INTEGRATIONS", []),
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
        ):
            mock_repo.get_public_by_slug = AsyncMock(return_value=integration)
            resp = await client.get(f"{BASE}/public/my-tool")

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "My Tool"
        assert body["slug"] == "my-tool"
        assert body["cloneCount"] == 5

    @pytest.mark.asyncio
    async def test_legacy_hash_fallback(self, client: AsyncClient) -> None:
        """Falls back to legacy hash-based lookup when slug lookup returns nothing."""
        integration = _with_creator("abc123", "Legacy Tool")

        with (
            patch(f"{_PUBLIC}.OAUTH_INTEGRATIONS", []),
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.parse_integration_slug", return_value={"shortid": "abc123"}),
        ):
            mock_repo.get_public_by_slug = AsyncMock(return_value=None)
            mock_repo.get_public_by_id_prefix = AsyncMock(return_value=integration)
            resp = await client.get(f"{BASE}/public/legacy-abc123")

        assert resp.status_code == 200
        assert resp.json()["name"] == "Legacy Tool"

    @pytest.mark.asyncio
    async def test_not_found(self, client: AsyncClient) -> None:
        """Return 404 when no integration matches."""
        with (
            patch(f"{_PUBLIC}.OAUTH_INTEGRATIONS", []),
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.parse_integration_slug", return_value={}),
        ):
            mock_repo.get_public_by_slug = AsyncMock(return_value=None)
            resp = await client.get(f"{BASE}/public/nonexistent")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(self, client: AsyncClient) -> None:
        """Unexpected exception maps to 500."""
        with (
            patch(f"{_PUBLIC}.OAUTH_INTEGRATIONS", new=[]),
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
        ):
            mock_repo.get_public_by_slug = AsyncMock(side_effect=TypeError("boom"))
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
        with patch("app.api.v1.endpoints.integrations.public.integration_repository") as mock_repo:
            mock_repo.get_public = AsyncMock(return_value=None)
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
            "mcp_config": None,
        }
        existing = UserIntegrationDocument(
            user_id="u1", integration_id="integ1", status="connected"
        )

        with (
            patch("app.api.v1.endpoints.integrations.public.integration_repository") as mock_repo,
            patch(
                "app.api.v1.endpoints.integrations.public.user_integration_repository"
            ) as mock_user_coll,
        ):
            mock_repo.get_public = AsyncMock(
                return_value=Integration.model_validate(
                    {
                        **original_doc,
                        "managed_by": "mcp",
                        "description": "",
                        "category": "custom",
                        "source": "custom",
                    }
                )
            )
            mock_user_coll.get_for_user = AsyncMock(return_value=existing)

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
            patch("app.api.v1.endpoints.integrations.public.integration_repository") as mock_repo,
            patch(
                "app.api.v1.endpoints.integrations.public.user_integration_repository"
            ) as mock_user_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.add_user_integration",
                new_callable=AsyncMock,
            ),
        ):
            mock_repo.get_public = AsyncMock(
                return_value=Integration.model_validate(
                    {
                        **original_doc,
                        "managed_by": "mcp",
                        "description": "",
                        "category": "custom",
                        "source": "custom",
                    }
                )
            )
            mock_repo.increment_clone_count = AsyncMock()
            mock_user_coll.get_for_user = AsyncMock(return_value=None)

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
        connect_result.error = None

        with (
            patch("app.api.v1.endpoints.integrations.public.integration_repository") as mock_repo,
            patch(
                "app.api.v1.endpoints.integrations.public.user_integration_repository"
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
            patch("app.api.v1.endpoints.integrations.public.capture_context_event") as mock_capture,
        ):
            mock_repo.get_public = AsyncMock(
                return_value=Integration.model_validate(
                    {
                        **original_doc,
                        "managed_by": "mcp",
                        "description": "",
                        "category": "custom",
                        "source": "custom",
                    }
                )
            )
            mock_repo.increment_clone_count = AsyncMock()
            mock_user_coll.get_for_user = AsyncMock(return_value=None)

            resp = await client.post(
                f"{BASE}/public/integ3/add",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "connected"
        assert body["toolsCount"] == 5
        mock_capture.assert_called_once_with(
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": "integ3", "source": "marketplace"},
        )

    @pytest.mark.asyncio
    async def test_re_attempt_connection(self, client: AsyncClient) -> None:
        """Existing non-connected integration re-attempts connection."""
        original_doc = {
            "integration_id": "integ4",
            "name": "Retry Integ",
            "is_public": True,
            "mcp_config": {"server_url": "https://mcp.example.com"},
        }
        existing = UserIntegrationDocument(user_id="u1", integration_id="integ4", status="created")

        connect_result = MagicMock()
        connect_result.status = "connected"
        connect_result.redirect_url = None
        connect_result.tools_count = 3
        connect_result.message = None
        connect_result.error = None

        with (
            patch("app.api.v1.endpoints.integrations.public.integration_repository") as mock_repo,
            patch(
                "app.api.v1.endpoints.integrations.public.user_integration_repository"
            ) as mock_user_coll,
            patch(
                "app.api.v1.endpoints.integrations.public.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=connect_result,
            ),
        ):
            mock_repo.get_public = AsyncMock(
                return_value=Integration.model_validate(
                    {
                        **original_doc,
                        "managed_by": "mcp",
                        "description": "",
                        "category": "custom",
                        "source": "custom",
                    }
                )
            )
            mock_user_coll.get_for_user = AsyncMock(return_value=existing)

            resp = await client.post(
                f"{BASE}/public/integ4/add",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "connected"
        assert resp.json()["message"] == "Integration added successfully"

    @pytest.mark.asyncio
    async def test_add_user_integration_value_error_suppressed(self, client: AsyncClient) -> None:
        """ValueError from add_user_integration is suppressed (duplicate)."""
        original_doc = {
            "integration_id": "integ5",
            "name": "Dup Integ",
            "is_public": True,
            "mcp_config": None,
        }

        connect_result = MagicMock()
        connect_result.status = "connected"
        connect_result.redirect_url = None
        connect_result.tools_count = 0
        connect_result.message = "ok"
        connect_result.error = None

        with (
            patch("app.api.v1.endpoints.integrations.public.integration_repository") as mock_repo,
            patch(
                "app.api.v1.endpoints.integrations.public.user_integration_repository"
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
            mock_repo.get_public = AsyncMock(
                return_value=Integration.model_validate(
                    {
                        **original_doc,
                        "managed_by": "mcp",
                        "description": "",
                        "category": "custom",
                        "source": "custom",
                    }
                )
            )
            mock_repo.increment_clone_count = AsyncMock()
            mock_user_coll.get_for_user = AsyncMock(return_value=None)

            resp = await client.post(
                f"{BASE}/public/integ5/add",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(self, client: AsyncClient) -> None:
        with patch("app.api.v1.endpoints.integrations.public.integration_repository") as mock_repo:
            mock_repo.get_public = AsyncMock(side_effect=RuntimeError("boom"))
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
        doc1 = _integration(
            "id1",
            "Tool A",
            description="Desc A",
            category="ai",
            clone_count=10,
            tools=[{"name": "t1"}, {"name": "t2"}],
            icon_url="https://icon.png",
        )
        doc2 = _integration("id2", "Tool B", description="Desc B", clone_count=0)

        with (
            patch(
                f"{_PUBLIC}.search_public_integrations",
                new_callable=AsyncMock,
                return_value=search_results,
            ),
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(
                f"{_PUBLIC}.generate_integration_slug",
                side_effect=lambda name, category: f"slug-{name}-{category}",
            ),
        ):
            mock_repo.find_public_by_ids = AsyncMock(return_value=[doc1, doc2])
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

        with (
            patch(
                f"{_PUBLIC}.search_public_integrations",
                new_callable=AsyncMock,
                return_value=search_results,
            ),
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
        ):
            mock_repo.find_public_by_ids = AsyncMock(return_value=[])
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


class TestAddPublicIntegrationHandler:
    """The add handler called directly, without the router in the way.

    The HTTP tests above cover the wire contract. These cover what the handler
    itself decides before any of that is visible: which catalog row it reads,
    and what it writes to the wide event — the only record of who added what
    when a marketplace add goes wrong.
    """

    USER = "507f1f77bcf86cd799439011"

    async def _call(self, integration_id: str = "integ1") -> object:
        return await public_endpoint.add_public_integration(
            integration_id=integration_id,
            request=ConnectIntegrationRequest(redirect_path="/integrations"),
            user_id=self.USER,
        )

    async def test_the_requested_integration_is_the_one_looked_up(self):
        # The id in the path is the row that gets cloned into the user's
        # workspace; looking up anything else would add the wrong integration
        # under the right name.
        existing = UserIntegrationDocument(
            user_id="u1", integration_id="integ1", status="connected"
        )
        with (
            patch(f"{_PUBLIC}.integration_repository") as repo,
            patch(f"{_PUBLIC}.user_integration_repository") as user_repo,
        ):
            repo.get_public = AsyncMock(
                side_effect=lambda iid: _integration("integ1", "Integ") if iid == "integ1" else None
            )
            user_repo.get_for_user = AsyncMock(return_value=existing)

            result = await self._call("integ1")

        repo.get_public.assert_awaited_once_with("integ1")
        assert result.status == "connected"

    async def test_an_integration_that_is_not_public_is_a_404(self):
        # get_public returns None for a private or missing row. Adding it
        # anyway would publish someone else's private integration by id.
        with patch(f"{_PUBLIC}.integration_repository") as repo:
            repo.get_public = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc_info:
                await self._call("not-public")

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Integration not found"

    async def test_the_wide_event_names_the_operation_the_user_and_the_integration(self):
        existing = UserIntegrationDocument(
            user_id="u1", integration_id="integ1", status="connected"
        )
        with (
            patch(f"{_PUBLIC}.integration_repository") as repo,
            patch(f"{_PUBLIC}.user_integration_repository") as user_repo,
        ):
            repo.get_public = AsyncMock(return_value=_integration("integ1", "Integ"))
            user_repo.get_for_user = AsyncMock(return_value=existing)

            async with captured_wide_event() as event:
                await self._call("integ1")
                operation = event["operation"]

        assert operation == "add_public_integration"
        assert event["integration_id"] == "integ1"
        assert event["user"] == {"id": self.USER}
        assert event["integration"] == {"id": "integ1"}

    async def test_the_marketplace_add_connects_the_community_server_as_non_platform(self):
        """Everything the MCP connect branches on comes from the catalog row.

        ``is_platform`` is the one that matters most: a platform integration may
        use GAIA's own credentials, and a community integration anyone can
        publish must never be treated as one. The rest are asserted with it
        because a dropped field is as wrong as a flipped one — the request is
        built once and nothing downstream can recover a missing server URL or
        the token the user pasted.
        """
        original = _integration(
            "integ1",
            "Community MCP",
            mcp_config={
                "server_url": "https://mcp.community.test",
                "requires_auth": True,
                "auth_type": "bearer",
            },
        )
        with (
            patch(f"{_PUBLIC}.integration_repository") as repo,
            patch(f"{_PUBLIC}.user_integration_repository") as user_repo,
            patch(f"{_PUBLIC}.add_user_integration", new_callable=AsyncMock),
            patch(
                f"{_PUBLIC}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=ConnectIntegrationResponse(
                    status="connected", integration_id="integ1", name="Community MCP"
                ),
            ) as connect,
        ):
            repo.get_public = AsyncMock(return_value=original)
            repo.increment_clone_count = AsyncMock()
            user_repo.get_for_user = AsyncMock(return_value=None)

            await public_endpoint.add_public_integration(
                integration_id="integ1",
                request=ConnectIntegrationRequest(redirect_path="/chat/7", bearer_token="paste-me"),
                user_id=self.USER,
            )

        assert connect.await_args.args[0] == McpConnectRequest(
            user_id=self.USER,
            integration_id="integ1",
            integration_name="Community MCP",
            requires_auth=True,
            redirect_path="/chat/7",
            server_url="https://mcp.community.test",
            is_platform=False,
            bearer_token="paste-me",
        )
