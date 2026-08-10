"""Tests for app/api/v1/endpoints/integrations/public.py"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from httpx import AsyncClient
import pytest

from app.models.integration_models import (
    Integration,
    IntegrationWithCreator,
    UserIntegrationDocument,
)
from app.models.workflow_models import PublicWorkflowRow

# Base URL for integration public endpoints
# routes.py: prefix="/integrations", public.py router has no extra prefix
# public.py: @router.get("/public/{identifier}"), @router.post("/public/{integration_id}/add"), @router.get("/search")
BASE = "/api/v1/integrations"

_PUBLIC = "app.api.v1.endpoints.integrations.public"

# FAKE_USER.user_id from tests/conftest.py — the get_user_id dependency resolves
# to it through the app's dependency override.
FAKE_USER_ID = "507f1f77bcf86cd799439011"


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


def _public_workflow(wf_id: str, title: str, **overrides: object) -> PublicWorkflowRow:
    data: dict[str, object] = {
        "id": wf_id,
        "user_id": "u-1",
        "title": title,
        "description": "Workflow description",
        "prompt": "Run the steps",
        "steps": [{"title": "step 1", "description": "Step description"}],
        "trigger_config": {"type": "manual"},
        "slug": f"slug-{wf_id}",
        "created_by": "system",
        "total_executions": 3,
        "created_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    }
    data.update(overrides)
    return PublicWorkflowRow.model_validate(data)


# ---------------------------------------------------------------------------
# GET /integrations/public/{identifier}
# ---------------------------------------------------------------------------


class TestGetPublicIntegration:
    """Tests for GET /integrations/public/{identifier}."""

    @pytest.mark.asyncio
    async def test_native_integration_found(self, client: AsyncClient) -> None:
        """Native platform integration returns the full platform-shaped body."""
        fake_native = MagicMock()
        fake_native.id = "googlecalendar"
        fake_native.name = "Google Calendar"
        fake_native.description = "Calendar integration"
        fake_native.category = "productivity"
        fake_native.managed_by = "self"
        fake_native.mcp_config = None
        fake_native.content = None

        with (
            patch(f"{_PUBLIC}.OAUTH_INTEGRATIONS", [fake_native]),
            patch(
                f"{_PUBLIC}.get_integration_tools",
                new_callable=AsyncMock,
                return_value=[{"name": "create_event", "description": "Create event"}],
            ) as mock_tools,
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
        ):
            mock_repo.get_public_by_slug = AsyncMock()
            resp = await client.get(f"{BASE}/public/googlecalendar")

        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "integrationId": "googlecalendar",
            "slug": "googlecalendar",
            "name": "Google Calendar",
            "description": "Calendar integration",
            "category": "productivity",
            "iconUrl": None,
            "creator": None,
            "mcpConfig": None,
            "tools": [{"name": "create_event", "description": "Create event", "destructive": False}],
            "cloneCount": 0,
            "toolCount": 1,
            "publishedAt": None,
            "source": "platform",
            "authType": "oauth",
            "content": None,
        }
        mock_tools.assert_awaited_once_with("googlecalendar")
        mock_repo.get_public_by_slug.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_native_managed_by_composio_implies_oauth(self, client: AsyncClient) -> None:
        """Native integration managed by composio (no mcp_config) implies oauth."""
        fake_native = MagicMock()
        fake_native.id = "github"
        fake_native.name = "GitHub"
        fake_native.description = "GitHub integration"
        fake_native.category = "developer"
        fake_native.managed_by = "composio"
        fake_native.mcp_config = None
        fake_native.content = None

        with (
            patch(f"{_PUBLIC}.OAUTH_INTEGRATIONS", [fake_native]),
            patch(
                f"{_PUBLIC}.get_integration_tools",
                new_callable=AsyncMock,
                return_value=[{"name": "open_issue"}],
            ) as mock_tools,
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
        ):
            mock_repo.get_public_by_slug = AsyncMock()
            resp = await client.get(f"{BASE}/public/github")

        assert resp.status_code == 200
        body = resp.json()
        assert body["authType"] == "oauth"
        assert body["source"] == "platform"
        assert body["tools"] == [{"name": "open_issue", "description": None, "destructive": False}]
        mock_tools.assert_awaited_once_with("github")

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
            patch(f"{_PUBLIC}.OAUTH_INTEGRATIONS", [fake_native]),
            patch(
                f"{_PUBLIC}.get_integration_tools",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_tools,
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
        ):
            mock_repo.get_public_by_slug = AsyncMock()
            resp = await client.get(f"{BASE}/public/mcp_tool")

        assert resp.status_code == 200
        body = resp.json()
        assert body["authType"] == "bearer"
        assert body["toolCount"] == 0
        assert body["tools"] == []
        mock_tools.assert_awaited_once_with("mcp_tool")

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
        assert resp.json()["detail"] == "Integration not found"
        mock_repo.get_public_by_slug.assert_awaited_once_with("internal_tool")

    @pytest.mark.asyncio
    async def test_slug_lookup_found(self, client: AsyncClient) -> None:
        """Custom integration found via slug returns the full custom-shaped body."""
        integration = _with_creator(
            "abc123",
            "My Tool",
            slug="my-tool",
            description="A tool",
            category="developer",
            clone_count=5,
            icon_url="https://icon.example/tool.png",
            creator={"name": "Ada", "picture": "https://icon.example/ada.png"},
            mcp_config={
                "server_url": "https://mcp.example.com",
                "requires_auth": True,
                "auth_type": "bearer",
            },
            tools=[{"name": "run", "description": "Run it"}],
            published_at=datetime(2026, 5, 1, tzinfo=UTC),
        )

        with (
            patch(f"{_PUBLIC}.OAUTH_INTEGRATIONS", []),
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.parse_integration_slug") as mock_parse,
        ):
            mock_repo.get_public_by_slug = AsyncMock(return_value=integration)
            resp = await client.get(f"{BASE}/public/my-tool")

        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "integrationId": "abc123",
            "slug": "my-tool",
            "name": "My Tool",
            "description": "A tool",
            "category": "developer",
            "iconUrl": "https://icon.example/tool.png",
            "creator": {"name": "Ada", "picture": "https://icon.example/ada.png"},
            "mcpConfig": {
                "serverUrl": "https://mcp.example.com",
                "requiresAuth": True,
                "authType": "bearer",
            },
            "tools": [{"name": "run", "description": "Run it", "destructive": False}],
            "cloneCount": 5,
            "toolCount": 1,
            "publishedAt": "2026-05-01T00:00:00Z",
            "source": "custom",
            "authType": None,
            "content": None,
        }
        mock_repo.get_public_by_slug.assert_awaited_once_with("my-tool")
        mock_parse.assert_not_called()

    @pytest.mark.asyncio
    async def test_slug_lookup_computes_missing_slug(self, client: AsyncClient) -> None:
        """Custom integration without a stored slug gets one generated."""
        integration = _with_creator("abc123", "My Tool", slug=None)

        with (
            patch(f"{_PUBLIC}.OAUTH_INTEGRATIONS", []),
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
        ):
            mock_repo.get_public_by_slug = AsyncMock(return_value=integration)
            resp = await client.get(f"{BASE}/public/my-tool")

        assert resp.status_code == 200
        assert resp.json()["slug"] == "my-tool-mcp-custom"

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
        mock_repo.get_public_by_slug.assert_awaited_once_with("legacy-abc123")
        mock_repo.get_public_by_id_prefix.assert_awaited_once_with("abc123")

    @pytest.mark.asyncio
    async def test_legacy_hash_fallback_no_shortid(self, client: AsyncClient) -> None:
        """When the slug parse yields no shortid, the id-prefix lookup is skipped."""
        with (
            patch(f"{_PUBLIC}.OAUTH_INTEGRATIONS", []),
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.parse_integration_slug", return_value={}),
        ):
            mock_repo.get_public_by_slug = AsyncMock(return_value=None)
            mock_repo.get_public_by_id_prefix = AsyncMock(return_value=None)
            resp = await client.get(f"{BASE}/public/no-hash")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Integration not found"
        mock_repo.get_public_by_id_prefix.assert_not_awaited()

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
        assert resp.json()["detail"] == "Integration not found"

    @pytest.mark.asyncio
    async def test_http_exception_is_re_raised(self, client: AsyncClient) -> None:
        """An HTTPException from the repository is not wrapped into a 500."""
        with (
            patch(f"{_PUBLIC}.OAUTH_INTEGRATIONS", []),
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
        ):
            mock_repo.get_public_by_slug = AsyncMock(
                side_effect=HTTPException(status_code=403, detail="forbidden")
            )
            resp = await client.get(f"{BASE}/public/blocked")

        assert resp.status_code == 403
        assert resp.json()["detail"] == "forbidden"

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
        assert resp.json()["detail"] == "Failed to fetch integration"


# ---------------------------------------------------------------------------
# POST /integrations/public/{integration_id}/add
# ---------------------------------------------------------------------------


class TestAddPublicIntegration:
    """Tests for POST /integrations/public/{integration_id}/add."""

    @pytest.mark.asyncio
    async def test_integration_not_found(self, client: AsyncClient) -> None:
        with (
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.user_integration_repository") as mock_user_repo,
            patch(f"{_PUBLIC}.connect_mcp_integration", new_callable=AsyncMock) as mock_connect,
        ):
            mock_repo.get_public = AsyncMock(return_value=None)
            mock_user_repo.get_for_user = AsyncMock()
            resp = await client.post(
                f"{BASE}/public/unknown/add",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Integration not found"
        mock_repo.get_public.assert_awaited_once_with("unknown")
        mock_user_repo.get_for_user.assert_not_awaited()
        mock_connect.assert_not_awaited()

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
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.user_integration_repository") as mock_user_coll,
            patch(f"{_PUBLIC}.add_user_integration", new_callable=AsyncMock) as mock_add,
            patch(f"{_PUBLIC}.connect_mcp_integration", new_callable=AsyncMock) as mock_connect,
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
        assert resp.json() == {
            "integrationId": "integ1",
            "name": "Integ",
            "status": "connected",
            "message": "Integration already connected",
            "redirectUrl": None,
            "toolsCount": None,
            "error": None,
        }
        mock_user_coll.get_for_user.assert_awaited_once_with(FAKE_USER_ID, "integ1")
        mock_add.assert_not_awaited()
        mock_connect.assert_not_awaited()

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
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.user_integration_repository") as mock_user_coll,
            patch(f"{_PUBLIC}.add_user_integration", new_callable=AsyncMock) as mock_add,
            patch(f"{_PUBLIC}.connect_mcp_integration", new_callable=AsyncMock) as mock_connect,
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
        assert resp.json() == {
            "integrationId": "integ2",
            "name": "Bearer Integ",
            "status": "error",
            "message": "Bearer token required for this integration",
            "redirectUrl": None,
            "toolsCount": None,
            "error": "bearer_required",
        }
        mock_add.assert_awaited_once_with(
            user_id=FAKE_USER_ID,
            integration_id="integ2",
            initial_status="created",
        )
        mock_repo.increment_clone_count.assert_awaited_once_with("integ2")
        mock_connect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bearer_flow_connects_with_token(self, client: AsyncClient) -> None:
        """A bearer_token in the request flows through to connect_mcp_integration."""
        original_doc = {
            "integration_id": "integ-bearer",
            "name": "Token Integ",
            "is_public": True,
            "mcp_config": {
                "server_url": "https://example.com",
                "requires_auth": True,
                "auth_type": "bearer",
            },
        }

        connect_result = MagicMock()
        connect_result.status = "redirect"
        connect_result.redirect_url = "https://oauth.example.com/return"
        connect_result.tools_count = None
        connect_result.message = "OAuth needed"
        connect_result.error = None

        with (
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.user_integration_repository") as mock_user_coll,
            patch(f"{_PUBLIC}.add_user_integration", new_callable=AsyncMock),
            patch(
                f"{_PUBLIC}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=connect_result,
            ) as mock_connect,
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
                f"{BASE}/public/integ-bearer/add",
                json={"redirect_path": "/custom/path", "bearer_token": "tok123"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "redirect"
        assert resp.json()["redirectUrl"] == "https://oauth.example.com/return"
        assert resp.json()["message"] == "OAuth needed"
        mock_connect.assert_awaited_once_with(
            user_id=FAKE_USER_ID,
            integration_id="integ-bearer",
            integration_name="Token Integ",
            requires_auth=True,
            redirect_path="/custom/path",
            server_url="https://example.com",
            is_platform=False,
            bearer_token="tok123",
        )

    @pytest.mark.asyncio
    async def test_bearer_auth_without_requires_auth_connects(self, client: AsyncClient) -> None:
        """bearer auth_type without requires_auth does not short-circuit to error."""
        original_doc = {
            "integration_id": "integ-soft",
            "name": "Soft Bearer",
            "is_public": True,
            "mcp_config": {
                "server_url": "https://example.com",
                "requires_auth": False,
                "auth_type": "bearer",
            },
        }

        connect_result = MagicMock()
        connect_result.status = "connected"
        connect_result.redirect_url = None
        connect_result.tools_count = 1
        connect_result.message = "ok"
        connect_result.error = None

        with (
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.user_integration_repository") as mock_user_coll,
            patch(f"{_PUBLIC}.add_user_integration", new_callable=AsyncMock),
            patch(
                f"{_PUBLIC}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=connect_result,
            ) as mock_connect,
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
                f"{BASE}/public/integ-soft/add",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "connected"
        assert resp.json()["error"] is None
        mock_connect.assert_awaited_once_with(
            user_id=FAKE_USER_ID,
            integration_id="integ-soft",
            integration_name="Soft Bearer",
            requires_auth=False,
            redirect_path="/integrations",
            server_url="https://example.com",
            is_platform=False,
            bearer_token=None,
        )

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
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.user_integration_repository") as mock_user_coll,
            patch(f"{_PUBLIC}.add_user_integration", new_callable=AsyncMock) as mock_add,
            patch(
                f"{_PUBLIC}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=connect_result,
            ) as mock_connect,
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
        assert body == {
            "integrationId": "integ3",
            "name": "New Integ",
            "status": "connected",
            "message": "Done",
            "redirectUrl": None,
            "toolsCount": 5,
            "error": None,
        }
        mock_add.assert_awaited_once_with(
            user_id=FAKE_USER_ID,
            integration_id="integ3",
            initial_status="created",
        )
        mock_repo.increment_clone_count.assert_awaited_once_with("integ3")
        mock_connect.assert_awaited_once_with(
            user_id=FAKE_USER_ID,
            integration_id="integ3",
            integration_name="New Integ",
            requires_auth=False,
            redirect_path="/integrations",
            server_url="https://mcp.example.com",
            is_platform=False,
            bearer_token=None,
        )

    @pytest.mark.asyncio
    async def test_successful_add_without_mcp_config(self, client: AsyncClient) -> None:
        """An integration without mcp_config connects with None server_url."""
        original_doc = {
            "integration_id": "integ6",
            "name": "No Config",
            "is_public": True,
            "mcp_config": None,
        }

        connect_result = MagicMock()
        connect_result.status = "connected"
        connect_result.redirect_url = None
        connect_result.tools_count = 0
        connect_result.message = None
        connect_result.error = None

        with (
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.user_integration_repository") as mock_user_coll,
            patch(f"{_PUBLIC}.add_user_integration", new_callable=AsyncMock),
            patch(
                f"{_PUBLIC}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=connect_result,
            ) as mock_connect,
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
                f"{BASE}/public/integ6/add",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 200
        mock_connect.assert_awaited_once_with(
            user_id=FAKE_USER_ID,
            integration_id="integ6",
            integration_name="No Config",
            requires_auth=False,
            redirect_path="/integrations",
            server_url=None,
            is_platform=False,
            bearer_token=None,
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
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.user_integration_repository") as mock_user_coll,
            patch(f"{_PUBLIC}.add_user_integration", new_callable=AsyncMock) as mock_add,
            patch(
                f"{_PUBLIC}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=connect_result,
            ) as mock_connect,
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
            mock_user_coll.get_for_user = AsyncMock(return_value=existing)

            resp = await client.post(
                f"{BASE}/public/integ4/add",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "connected"
        assert resp.json()["message"] == "Integration added successfully"
        mock_user_coll.get_for_user.assert_awaited_once_with(FAKE_USER_ID, "integ4")
        mock_add.assert_not_awaited()
        mock_repo.increment_clone_count.assert_not_awaited()
        mock_connect.assert_awaited_once()

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
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.user_integration_repository") as mock_user_coll,
            patch(
                f"{_PUBLIC}.add_user_integration",
                new_callable=AsyncMock,
                side_effect=ValueError("duplicate"),
            ) as mock_add,
            patch(
                f"{_PUBLIC}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=connect_result,
            ) as mock_connect,
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
        assert resp.json()["status"] == "connected"
        mock_add.assert_awaited_once()
        mock_repo.increment_clone_count.assert_awaited_once_with("integ5")
        mock_connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_user_integration_runtime_error_not_suppressed(self, client: AsyncClient) -> None:
        """Only ValueError is suppressed — other errors still 500."""
        original_doc = {
            "integration_id": "integ7",
            "name": "Crash Integ",
            "is_public": True,
            "mcp_config": None,
        }

        with (
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.user_integration_repository") as mock_user_coll,
            patch(
                f"{_PUBLIC}.add_user_integration",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db down"),
            ),
            patch(f"{_PUBLIC}.connect_mcp_integration", new_callable=AsyncMock) as mock_connect,
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
                f"{BASE}/public/integ7/add",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to add integration"
        mock_connect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_http_exception_is_re_raised(self, client: AsyncClient) -> None:
        """An HTTPException from the connection service is not wrapped into a 500."""
        original_doc = {
            "integration_id": "integ8",
            "name": "Conflict Integ",
            "is_public": True,
            "mcp_config": None,
        }

        with (
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
            patch(f"{_PUBLIC}.user_integration_repository") as mock_user_coll,
            patch(f"{_PUBLIC}.add_user_integration", new_callable=AsyncMock),
            patch(
                f"{_PUBLIC}.connect_mcp_integration",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=409, detail="conflict"),
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
                f"{BASE}/public/integ8/add",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 409
        assert resp.json()["detail"] == "conflict"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{_PUBLIC}.integration_repository") as mock_repo:
            mock_repo.get_public = AsyncMock(side_effect=RuntimeError("boom"))
            resp = await client.post(
                f"{BASE}/public/bad/add",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to add integration"


# ---------------------------------------------------------------------------
# GET /integrations/search
# ---------------------------------------------------------------------------


class TestSearchIntegrations:
    """Tests for GET /integrations/search."""

    @pytest.mark.asyncio
    async def test_empty_query(self, client: AsyncClient) -> None:
        with patch(
            f"{_PUBLIC}.search_public_integrations",
            new_callable=AsyncMock,
        ) as mock_search:
            resp = await client.get(f"{BASE}/search", params={"q": ""})

        assert resp.status_code == 200
        assert resp.json() == {"integrations": [], "query": ""}
        mock_search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_whitespace_only_query(self, client: AsyncClient) -> None:
        with patch(
            f"{_PUBLIC}.search_public_integrations",
            new_callable=AsyncMock,
        ) as mock_search:
            resp = await client.get(f"{BASE}/search", params={"q": "   "})

        assert resp.status_code == 200
        assert resp.json() == {"integrations": [], "query": "   "}
        mock_search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_search_results(self, client: AsyncClient) -> None:
        with patch(
            f"{_PUBLIC}.search_public_integrations",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_search:
            resp = await client.get(f"{BASE}/search", params={"q": "nonexistent"})

        assert resp.status_code == 200
        assert resp.json() == {"integrations": [], "query": "nonexistent"}
        mock_search.assert_awaited_once_with(query="nonexistent", limit=20)

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
            ) as mock_search,
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
        ):
            mock_repo.find_public_by_ids = AsyncMock(return_value=[doc1, doc2])
            resp = await client.get(f"{BASE}/search", params={"q": "tool"})

        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "integrations": [
                {
                    "integrationId": "id1",
                    "slug": "tool-a-mcp-ai",
                    "name": "Tool A",
                    "description": "Desc A",
                    "category": "ai",
                    "relevanceScore": 0.95,
                    "cloneCount": 10,
                    "toolCount": 2,
                    "iconUrl": "https://icon.png",
                },
                {
                    "integrationId": "id2",
                    "slug": "tool-b-mcp-custom",
                    "name": "Tool B",
                    "description": "Desc B",
                    "category": "custom",
                    "relevanceScore": 0.8,
                    "cloneCount": 0,
                    "toolCount": 0,
                    "iconUrl": None,
                },
            ],
            "query": "tool",
        }
        mock_search.assert_awaited_once_with(query="tool", limit=20)
        mock_repo.find_public_by_ids.assert_awaited_once_with(["id1", "id2"])

    @pytest.mark.asyncio
    async def test_search_strips_whitespace_before_querying(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{_PUBLIC}.search_public_integrations",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_search,
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
        ):
            mock_repo.find_public_by_ids = AsyncMock(return_value=[])
            resp = await client.get(f"{BASE}/search", params={"q": "  tool  "})

        assert resp.status_code == 200
        assert resp.json() == {"integrations": [], "query": "  tool  "}
        mock_search.assert_awaited_once_with(query="tool", limit=20)

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
        assert resp.json() == {"integrations": [], "query": "missing"}

    @pytest.mark.asyncio
    async def test_search_partial_docs_keeps_search_order(self, client: AsyncClient) -> None:
        """Found docs are emitted in search-result order, missing ones skipped."""
        search_results = [
            {"integration_id": "id_missing", "relevance_score": 0.9},
            {"integration_id": "id2", "relevance_score": 0.5},
        ]
        doc2 = _integration("id2", "Tool B", description="Desc B")

        with (
            patch(
                f"{_PUBLIC}.search_public_integrations",
                new_callable=AsyncMock,
                return_value=search_results,
            ),
            patch(f"{_PUBLIC}.integration_repository") as mock_repo,
        ):
            mock_repo.find_public_by_ids = AsyncMock(return_value=[doc2])
            resp = await client.get(f"{BASE}/search", params={"q": "partial"})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["integrations"]) == 1
        assert body["integrations"][0]["integrationId"] == "id2"
        assert body["integrations"][0]["relevanceScore"] == 0.5

    @pytest.mark.asyncio
    async def test_search_unexpected_error(self, client: AsyncClient) -> None:
        with patch(
            f"{_PUBLIC}.search_public_integrations",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db down"),
        ):
            resp = await client.get(f"{BASE}/search", params={"q": "test"})

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to search integrations"


# ---------------------------------------------------------------------------
# GET /integrations/public/{identifier}/workflows
# ---------------------------------------------------------------------------


class TestGetRelatedWorkflows:
    """Tests for GET /integrations/public/{identifier}/workflows."""

    @pytest.mark.asyncio
    async def test_returns_formatted_workflows(self, client: AsyncClient) -> None:
        row = _public_workflow(
            "wf-1",
            "First Workflow",
            total_executions=7,
            creator_info=[{"name": "Ada", "picture": "https://img/pic.png"}],
            created_by="user-1",
        )

        with patch(f"{_PUBLIC}.workflow_repository") as mock_repo:
            mock_repo.find_public_by_step_category = AsyncMock(return_value=[row])
            mock_repo.count_public_by_step_category = AsyncMock(return_value=12)
            resp = await client.get(f"{BASE}/public/slack/workflows")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 12
        assert body["workflows"] == [
            {
                "id": "wf-1",
                "title": "First Workflow",
                "description": "Workflow description",
                "slug": "slug-wf-1",
                "prompt": "Run the steps",
                "steps": [
                    {
                        "id": "",
                        "title": "step 1",
                        "description": "Step description",
                        "category": "general",
                    }
                ],
                "total_executions": 7,
                "created_at": "2026-01-02T03:04:05Z",
                "creator": {"id": "user-1", "name": "Ada", "avatar": "https://img/pic.png"},
            }
        ]
        mock_repo.find_public_by_step_category.assert_awaited_once_with(
            "slack", limit=10, offset=0
        )
        mock_repo.count_public_by_step_category.assert_awaited_once_with("slack")

    @pytest.mark.asyncio
    async def test_system_creator_falls_back_to_gaia_team(self, client: AsyncClient) -> None:
        row = _public_workflow("wf-1", "System Workflow", created_by="system")

        with patch(f"{_PUBLIC}.workflow_repository") as mock_repo:
            mock_repo.find_public_by_step_category = AsyncMock(return_value=[row])
            mock_repo.count_public_by_step_category = AsyncMock(return_value=1)
            resp = await client.get(f"{BASE}/public/slack/workflows")

        assert resp.status_code == 200
        creator = resp.json()["workflows"][0]["creator"]
        assert creator == {"id": "system", "name": "GAIA Team", "avatar": None}

    @pytest.mark.asyncio
    async def test_unknown_creator_falls_back_to_unknown(self, client: AsyncClient) -> None:
        row = _public_workflow("wf-1", "Orphan Workflow", created_by="deleted-user")

        with patch(f"{_PUBLIC}.workflow_repository") as mock_repo:
            mock_repo.find_public_by_step_category = AsyncMock(return_value=[row])
            mock_repo.count_public_by_step_category = AsyncMock(return_value=1)
            resp = await client.get(f"{BASE}/public/slack/workflows")

        assert resp.status_code == 200
        creator = resp.json()["workflows"][0]["creator"]
        assert creator == {"id": "deleted-user", "name": "Unknown", "avatar": None}

    @pytest.mark.asyncio
    async def test_step_category_kept_when_set(self, client: AsyncClient) -> None:
        row = _public_workflow(
            "wf-1",
            "Categorized",
            steps=[
                {
                    "id": "s-9",
                    "title": "step 1",
                    "description": "Step description",
                    "category": "gmail",
                }
            ],
        )

        with patch(f"{_PUBLIC}.workflow_repository") as mock_repo:
            mock_repo.find_public_by_step_category = AsyncMock(return_value=[row])
            mock_repo.count_public_by_step_category = AsyncMock(return_value=1)
            resp = await client.get(f"{BASE}/public/slack/workflows")

        assert resp.status_code == 200
        assert resp.json()["workflows"][0]["steps"] == [
            {"id": "s-9", "title": "step 1", "description": "Step description", "category": "gmail"}
        ]

    @pytest.mark.asyncio
    async def test_limit_offset_are_clamped(self, client: AsyncClient) -> None:
        with patch(f"{_PUBLIC}.workflow_repository") as mock_repo:
            mock_repo.find_public_by_step_category = AsyncMock(return_value=[])
            mock_repo.count_public_by_step_category = AsyncMock(return_value=0)
            resp = await client.get(
                f"{BASE}/public/slack/workflows", params={"limit": 999, "offset": -5}
            )

        assert resp.status_code == 200
        mock_repo.find_public_by_step_category.assert_awaited_once_with(
            "slack", limit=50, offset=0
        )

    @pytest.mark.asyncio
    async def test_limit_floor_is_one(self, client: AsyncClient) -> None:
        with patch(f"{_PUBLIC}.workflow_repository") as mock_repo:
            mock_repo.find_public_by_step_category = AsyncMock(return_value=[])
            mock_repo.count_public_by_step_category = AsyncMock(return_value=0)
            resp = await client.get(f"{BASE}/public/slack/workflows", params={"limit": 0})

        assert resp.status_code == 200
        mock_repo.find_public_by_step_category.assert_awaited_once_with("slack", limit=1, offset=0)

    @pytest.mark.asyncio
    async def test_empty_result(self, client: AsyncClient) -> None:
        with patch(f"{_PUBLIC}.workflow_repository") as mock_repo:
            mock_repo.find_public_by_step_category = AsyncMock(return_value=[])
            mock_repo.count_public_by_step_category = AsyncMock(return_value=0)
            resp = await client.get(f"{BASE}/public/slack/workflows")

        assert resp.status_code == 200
        assert resp.json() == {"workflows": [], "total": 0}

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(self, client: AsyncClient) -> None:
        with patch(f"{_PUBLIC}.workflow_repository") as mock_repo:
            mock_repo.find_public_by_step_category = AsyncMock(side_effect=RuntimeError("boom"))
            resp = await client.get(f"{BASE}/public/slack/workflows")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to fetch related workflows"
