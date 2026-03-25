"""Unit tests for integration service operations.

Covers:
- integration_service.py (get_user_available_tool_namespaces, build_creator_lookup_stages,
  format_community_integrations)
- integration_resolver.py (IntegrationResolver.resolve, get_mcp_config, get_server_url,
  is_mcp_integration, requires_authentication)
- integration_connection_service.py (build_integrations_config, connect_mcp_integration,
  connect_composio_integration, connect_self_integration, disconnect_integration,
  _invalidate_caches)
- user_integrations.py (get_user_integrations, get_user_connected_integrations,
  add_user_integration, remove_user_integration, check_user_has_integration,
  get_user_integration_capabilities)
- user_integration_status.py (update_user_integration_status)
- custom_crud.py (create_custom_integration, update_custom_integration,
  delete_custom_integration, create_and_connect_custom_integration)
"""

from datetime import UTC, datetime
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.integration_models import (
    CreateCustomIntegrationRequest,
    Integration,
    IntegrationResponse,
    IntegrationTool,
    UpdateCustomIntegrationRequest,
    UserIntegrationsListResponse,
)
from app.models.mcp_config import MCPConfig, SubAgentConfig
from app.models.oauth_models import OAuthIntegration
from app.schemas.integrations.responses import (
    CommunityIntegrationItem,
    IntegrationSuccessResponse,
)
from app.services.integrations.custom_crud import (
    create_and_connect_custom_integration,
    create_custom_integration,
    delete_custom_integration,
    update_custom_integration,
)
from app.services.integrations.integration_connection_service import (
    build_integrations_config,
    connect_composio_integration,
    connect_mcp_integration,
    connect_self_integration,
    disconnect_integration,
)
from app.services.integrations.integration_resolver import (
    IntegrationResolver,
    ResolvedIntegration,
)
from app.services.integrations.integration_service import (
    build_creator_lookup_stages,
    format_community_integrations,
    get_user_available_tool_namespaces,
)
from app.services.integrations.user_integration_status import (
    update_user_integration_status,
)
from app.services.integrations.user_integrations import (
    add_user_integration,
    check_user_has_integration,
    get_user_connected_integrations,
    get_user_integration_capabilities,
    get_user_integrations,
    remove_user_integration,
)


# ---------------------------------------------------------------------------
# Shared constants & helpers
# ---------------------------------------------------------------------------

USER_ID = "507f1f77bcf86cd799439011"
USER_ID_2 = "507f1f77bcf86cd799439022"
INTEGRATION_ID = "test-integration-123"
CUSTOM_INTEGRATION_ID = "custom-int-uuid-456"
SERVER_URL = "https://mcp.example.com/v1"


def _make_oauth_integration(
    *,
    id: str = "platform-int",
    name: str = "Platform Integration",
    description: str = "A platform integration",
    category: str = "productivity",
    provider: str = "google",
    managed_by: str = "self",
    available: bool = True,
    mcp_config: Optional[MCPConfig] = None,
    composio_config: Optional[Any] = None,
    subagent_config: Optional[SubAgentConfig] = None,
    is_featured: bool = False,
    display_priority: int = 0,
) -> OAuthIntegration:
    return OAuthIntegration(
        id=id,
        name=name,
        description=description,
        category=category,
        provider=provider,
        scopes=[],
        available=available,
        managed_by=managed_by,  # type: ignore[arg-type]
        mcp_config=mcp_config,
        composio_config=composio_config,
        subagent_config=subagent_config,
        is_featured=is_featured,
        display_priority=display_priority,
    )


def _make_custom_doc(
    *,
    integration_id: str = CUSTOM_INTEGRATION_ID,
    name: str = "Custom MCP",
    created_by: str = USER_ID,
    server_url: str = SERVER_URL,
    requires_auth: bool = False,
    auth_type: str = "none",
    is_public: bool = False,
) -> Dict[str, Any]:
    return {
        "integration_id": integration_id,
        "name": name,
        "description": "A custom integration",
        "category": "custom",
        "managed_by": "mcp",
        "source": "custom",
        "is_public": is_public,
        "created_by": created_by,
        "requires_auth": requires_auth,
        "auth_type": auth_type,
        "mcp_config": {
            "server_url": server_url,
            "requires_auth": requires_auth,
            "auth_type": auth_type,
        },
        "tools": [],
        "icon_url": None,
        "display_priority": 0,
        "is_featured": False,
        "created_at": datetime.now(UTC),
        "clone_count": 0,
    }


# ---------------------------------------------------------------------------
# IntegrationResolver tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIntegrationResolverResolve:
    """Tests for IntegrationResolver.resolve()."""

    @patch("app.services.integrations.integration_resolver.integrations_collection")
    @patch("app.services.integrations.integration_resolver.get_integration_by_id")
    async def test_resolve_platform_integration_with_mcp_config(
        self, mock_get_by_id, mock_collection
    ):
        mcp_cfg = MCPConfig(
            server_url=SERVER_URL, requires_auth=True, auth_type="oauth"
        )
        oauth_int = _make_oauth_integration(
            id="github", managed_by="mcp", mcp_config=mcp_cfg
        )
        mock_get_by_id.return_value = oauth_int

        result = await IntegrationResolver.resolve("github")

        assert result is not None
        assert result.source == "platform"
        assert result.integration_id == "github"
        assert result.requires_auth is True
        assert result.auth_type == "oauth"
        assert result.mcp_config == mcp_cfg
        assert result.platform_integration == oauth_int
        assert result.custom_doc is None
        mock_collection.find_one.assert_not_called()

    @patch("app.services.integrations.integration_resolver.integrations_collection")
    @patch("app.services.integrations.integration_resolver.get_integration_by_id")
    async def test_resolve_platform_with_composio_config(
        self, mock_get_by_id, mock_collection
    ):
        from app.models.mcp_config import ComposioConfig

        composio_cfg = ComposioConfig(
            auth_config_id="auth_123", toolkit="slack_toolkit"
        )
        oauth_int = _make_oauth_integration(
            id="slack", managed_by="composio", composio_config=composio_cfg
        )
        mock_get_by_id.return_value = oauth_int

        result = await IntegrationResolver.resolve("slack")

        assert result is not None
        assert result.requires_auth is True
        assert result.auth_type == "oauth"
        assert result.source == "platform"

    @patch("app.services.integrations.integration_resolver.integrations_collection")
    @patch("app.services.integrations.integration_resolver.get_integration_by_id")
    async def test_resolve_platform_self_managed(self, mock_get_by_id, mock_collection):
        oauth_int = _make_oauth_integration(
            id="gcal", managed_by="self", provider="google"
        )
        mock_get_by_id.return_value = oauth_int

        result = await IntegrationResolver.resolve("gcal")

        assert result is not None
        assert result.requires_auth is True
        assert result.auth_type == "oauth"
        assert result.managed_by == "self"

    @patch("app.services.integrations.integration_resolver.integrations_collection")
    @patch("app.services.integrations.integration_resolver.get_integration_by_id")
    async def test_resolve_platform_no_auth(self, mock_get_by_id, mock_collection):
        """Platform integration with no mcp, composio, or self — requires no auth."""
        mcp_cfg = MCPConfig(server_url=SERVER_URL, requires_auth=False)
        oauth_int = _make_oauth_integration(
            id="public-tool", managed_by="mcp", mcp_config=mcp_cfg
        )
        mock_get_by_id.return_value = oauth_int

        result = await IntegrationResolver.resolve("public-tool")

        assert result is not None
        assert result.requires_auth is False
        assert result.auth_type == "none"

    @patch("app.services.integrations.integration_resolver.integrations_collection")
    @patch("app.services.integrations.integration_resolver.get_integration_by_id")
    async def test_resolve_custom_integration_from_mongodb(
        self, mock_get_by_id, mock_collection
    ):
        mock_get_by_id.return_value = None
        custom_doc = _make_custom_doc()
        mock_collection.find_one = AsyncMock(return_value=custom_doc)

        result = await IntegrationResolver.resolve(CUSTOM_INTEGRATION_ID)

        assert result is not None
        assert result.source == "custom"
        assert result.name == "Custom MCP"
        assert result.managed_by == "mcp"
        assert result.platform_integration is None
        assert result.custom_doc == custom_doc
        assert isinstance(result.mcp_config, MCPConfig)
        assert result.mcp_config.server_url == SERVER_URL

    @patch("app.services.integrations.integration_resolver.integrations_collection")
    @patch("app.services.integrations.integration_resolver.get_integration_by_id")
    async def test_resolve_custom_integration_no_mcp_config(
        self, mock_get_by_id, mock_collection
    ):
        mock_get_by_id.return_value = None
        doc = _make_custom_doc()
        doc.pop("mcp_config")
        mock_collection.find_one = AsyncMock(return_value=doc)

        result = await IntegrationResolver.resolve(CUSTOM_INTEGRATION_ID)

        assert result is not None
        assert result.mcp_config is None
        assert result.requires_auth is False
        assert result.auth_type == "none"

    @patch("app.services.integrations.integration_resolver.integrations_collection")
    @patch("app.services.integrations.integration_resolver.get_integration_by_id")
    async def test_resolve_custom_with_auth_mismatch_syncs(
        self, mock_get_by_id, mock_collection
    ):
        """When mcp_config.requires_auth differs from doc-level, mcp_config wins and syncs."""
        mock_get_by_id.return_value = None
        doc = _make_custom_doc(requires_auth=False, auth_type="none")
        doc["mcp_config"]["requires_auth"] = True
        doc["mcp_config"]["auth_type"] = "oauth"
        mock_collection.find_one = AsyncMock(return_value=doc)
        mock_collection.update_one = AsyncMock()

        result = await IntegrationResolver.resolve(CUSTOM_INTEGRATION_ID)

        assert result is not None
        assert result.requires_auth is True
        assert result.auth_type == "oauth"
        mock_collection.update_one.assert_awaited_once()

    @patch("app.services.integrations.integration_resolver.integrations_collection")
    @patch("app.services.integrations.integration_resolver.get_integration_by_id")
    async def test_resolve_custom_sync_failure_is_non_fatal(
        self, mock_get_by_id, mock_collection
    ):
        """If syncing auth mismatch fails, resolve still returns correct data."""
        mock_get_by_id.return_value = None
        doc = _make_custom_doc(requires_auth=False)
        doc["mcp_config"]["requires_auth"] = True
        mock_collection.find_one = AsyncMock(return_value=doc)
        mock_collection.update_one = AsyncMock(side_effect=Exception("DB write failed"))

        result = await IntegrationResolver.resolve(CUSTOM_INTEGRATION_ID)

        assert result is not None
        assert result.requires_auth is True

    @patch("app.services.integrations.integration_resolver.integrations_collection")
    @patch("app.services.integrations.integration_resolver.get_integration_by_id")
    async def test_resolve_not_found_returns_none(
        self, mock_get_by_id, mock_collection
    ):
        mock_get_by_id.return_value = None
        mock_collection.find_one = AsyncMock(return_value=None)

        result = await IntegrationResolver.resolve("nonexistent")

        assert result is None


@pytest.mark.unit
class TestIntegrationResolverHelpers:
    """Tests for IntegrationResolver helper methods."""

    @patch.object(IntegrationResolver, "resolve", new_callable=AsyncMock)
    async def test_get_mcp_config_found(self, mock_resolve):
        mcp_cfg = MCPConfig(server_url=SERVER_URL)
        mock_resolve.return_value = ResolvedIntegration(
            integration_id="x",
            name="X",
            description="",
            category="c",
            managed_by="mcp",
            source="custom",
            requires_auth=False,
            auth_type=None,
            mcp_config=mcp_cfg,
            platform_integration=None,
            custom_doc=None,
        )

        result = await IntegrationResolver.get_mcp_config("x")
        assert result == mcp_cfg

    @patch.object(IntegrationResolver, "resolve", new_callable=AsyncMock)
    async def test_get_mcp_config_not_found(self, mock_resolve):
        mock_resolve.return_value = None

        result = await IntegrationResolver.get_mcp_config("missing")
        assert result is None

    @patch.object(IntegrationResolver, "get_mcp_config", new_callable=AsyncMock)
    async def test_get_server_url_found(self, mock_get_cfg):
        mock_get_cfg.return_value = MCPConfig(server_url=SERVER_URL)

        result = await IntegrationResolver.get_server_url("x")
        assert result == SERVER_URL

    @patch.object(IntegrationResolver, "get_mcp_config", new_callable=AsyncMock)
    async def test_get_server_url_no_config(self, mock_get_cfg):
        mock_get_cfg.return_value = None

        result = await IntegrationResolver.get_server_url("x")
        assert result is None

    @patch.object(IntegrationResolver, "resolve", new_callable=AsyncMock)
    async def test_is_mcp_integration_true(self, mock_resolve):
        mock_resolve.return_value = ResolvedIntegration(
            integration_id="x",
            name="X",
            description="",
            category="c",
            managed_by="mcp",
            source="custom",
            requires_auth=False,
            auth_type=None,
            mcp_config=None,
            platform_integration=None,
            custom_doc=None,
        )

        assert await IntegrationResolver.is_mcp_integration("x") is True

    @patch.object(IntegrationResolver, "resolve", new_callable=AsyncMock)
    async def test_is_mcp_integration_false_composio(self, mock_resolve):
        mock_resolve.return_value = ResolvedIntegration(
            integration_id="x",
            name="X",
            description="",
            category="c",
            managed_by="composio",
            source="platform",
            requires_auth=True,
            auth_type="oauth",
            mcp_config=None,
            platform_integration=None,
            custom_doc=None,
        )

        assert await IntegrationResolver.is_mcp_integration("x") is False

    @patch.object(IntegrationResolver, "resolve", new_callable=AsyncMock)
    async def test_is_mcp_integration_not_found(self, mock_resolve):
        mock_resolve.return_value = None
        assert await IntegrationResolver.is_mcp_integration("x") is False

    @patch.object(IntegrationResolver, "resolve", new_callable=AsyncMock)
    async def test_requires_authentication_true(self, mock_resolve):
        mock_resolve.return_value = ResolvedIntegration(
            integration_id="x",
            name="X",
            description="",
            category="c",
            managed_by="mcp",
            source="custom",
            requires_auth=True,
            auth_type="oauth",
            mcp_config=None,
            platform_integration=None,
            custom_doc=None,
        )

        assert await IntegrationResolver.requires_authentication("x") is True

    @patch.object(IntegrationResolver, "resolve", new_callable=AsyncMock)
    async def test_requires_authentication_not_found(self, mock_resolve):
        mock_resolve.return_value = None
        assert await IntegrationResolver.requires_authentication("x") is False


# ---------------------------------------------------------------------------
# integration_service.py tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUserAvailableToolNamespaces:
    """Tests for get_user_available_tool_namespaces."""

    @patch(
        "app.services.integrations.integration_service.IntegrationResolver.get_server_url",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.integration_service.derive_integration_namespace")
    @patch("app.services.integrations.integration_service.get_integration_by_id")
    @patch(
        "app.services.integrations.integration_service.get_all_integrations_status",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.integration_service.OAUTH_INTEGRATIONS", [])
    async def test_returns_core_namespaces_when_no_integrations(
        self, mock_status, mock_get_by_id, mock_derive, mock_server_url
    ):
        mock_status.return_value = {}

        result = await get_user_available_tool_namespaces.__wrapped__(USER_ID)

        assert "general" in result
        assert "subagents" in result

    @patch(
        "app.services.integrations.integration_service.IntegrationResolver.get_server_url",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.integration_service.derive_integration_namespace")
    @patch("app.services.integrations.integration_service.get_integration_by_id")
    @patch(
        "app.services.integrations.integration_service.get_all_integrations_status",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_service.OAUTH_INTEGRATIONS",
        [
            _make_oauth_integration(id="todos", managed_by="internal", available=True),
            _make_oauth_integration(id="goals", managed_by="internal", available=True),
        ],
    )
    async def test_includes_internal_integrations(
        self, mock_status, mock_get_by_id, mock_derive, mock_server_url
    ):
        mock_status.return_value = {}

        result = await get_user_available_tool_namespaces.__wrapped__(USER_ID)

        assert "todos" in result
        assert "goals" in result

    @patch(
        "app.services.integrations.integration_service.IntegrationResolver.get_server_url",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.integration_service.derive_integration_namespace")
    @patch("app.services.integrations.integration_service.get_integration_by_id")
    @patch(
        "app.services.integrations.integration_service.get_all_integrations_status",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.integration_service.OAUTH_INTEGRATIONS", [])
    async def test_connected_platform_integration_uses_tool_space(
        self, mock_status, mock_get_by_id, mock_derive, mock_server_url
    ):
        mock_status.return_value = {"github": True}
        subagent = SubAgentConfig(
            agent_name="github_agent",
            tool_space="github",
            handoff_tool_name="call_github",
            domain="code",
            capabilities="Git operations",
            use_cases="Code management",
            system_prompt="You are a github agent.",
        )
        platform_int = _make_oauth_integration(
            id="github", managed_by="mcp", subagent_config=subagent
        )
        mock_get_by_id.return_value = platform_int

        result = await get_user_available_tool_namespaces.__wrapped__(USER_ID)

        assert "github" in result

    @patch(
        "app.services.integrations.integration_service.IntegrationResolver.get_server_url",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.integration_service.derive_integration_namespace")
    @patch("app.services.integrations.integration_service.get_integration_by_id")
    @patch(
        "app.services.integrations.integration_service.get_all_integrations_status",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.integration_service.OAUTH_INTEGRATIONS", [])
    async def test_connected_custom_integration_derives_namespace(
        self, mock_status, mock_get_by_id, mock_derive, mock_server_url
    ):
        mock_status.return_value = {CUSTOM_INTEGRATION_ID: True}
        mock_get_by_id.return_value = None  # Not a platform integration
        mock_server_url.return_value = SERVER_URL
        mock_derive.return_value = "mcp.example.com/v1"

        result = await get_user_available_tool_namespaces.__wrapped__(USER_ID)

        assert "mcp.example.com/v1" in result
        mock_derive.assert_called_once_with(
            CUSTOM_INTEGRATION_ID, SERVER_URL, is_custom=True
        )

    @patch(
        "app.services.integrations.integration_service.IntegrationResolver.get_server_url",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.integration_service.derive_integration_namespace")
    @patch("app.services.integrations.integration_service.get_integration_by_id")
    @patch(
        "app.services.integrations.integration_service.get_all_integrations_status",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.integration_service.OAUTH_INTEGRATIONS", [])
    async def test_disconnected_integrations_excluded(
        self, mock_status, mock_get_by_id, mock_derive, mock_server_url
    ):
        mock_status.return_value = {"github": False, "slack": False}

        result = await get_user_available_tool_namespaces.__wrapped__(USER_ID)

        # Only core namespaces should remain
        assert result == {"general", "subagents"}

    @patch(
        "app.services.integrations.integration_service.IntegrationResolver.get_server_url",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.integration_service.derive_integration_namespace")
    @patch("app.services.integrations.integration_service.get_integration_by_id")
    @patch(
        "app.services.integrations.integration_service.get_all_integrations_status",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_service.OAUTH_INTEGRATIONS",
        [
            _make_oauth_integration(
                id="reminders", managed_by="internal", available=False
            ),
        ],
    )
    async def test_unavailable_internal_integrations_excluded(
        self, mock_status, mock_get_by_id, mock_derive, mock_server_url
    ):
        mock_status.return_value = {}

        result = await get_user_available_tool_namespaces.__wrapped__(USER_ID)

        assert "reminders" not in result

    @patch(
        "app.services.integrations.integration_service.IntegrationResolver.get_server_url",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.integration_service.derive_integration_namespace")
    @patch("app.services.integrations.integration_service.get_integration_by_id")
    @patch(
        "app.services.integrations.integration_service.get_all_integrations_status",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.integration_service.OAUTH_INTEGRATIONS", [])
    async def test_platform_without_subagent_falls_to_custom_path(
        self, mock_status, mock_get_by_id, mock_derive, mock_server_url
    ):
        """Platform integration connected but no subagent_config, treated like custom."""
        mock_status.return_value = {"some-int": True}
        # get_integration_by_id returns an integration but without subagent_config
        platform_int = _make_oauth_integration(
            id="some-int", managed_by="mcp", subagent_config=None
        )
        mock_get_by_id.return_value = platform_int
        mock_server_url.return_value = "https://some-server.com"
        mock_derive.return_value = "some-server.com"

        result = await get_user_available_tool_namespaces.__wrapped__(USER_ID)

        assert "some-server.com" in result


@pytest.mark.unit
class TestBuildCreatorLookupStages:
    def test_returns_five_pipeline_stages(self):
        stages = build_creator_lookup_stages()
        assert len(stages) == 5

    def test_first_stage_is_addfields(self):
        stages = build_creator_lookup_stages()
        assert "$addFields" in stages[0]

    def test_lookup_stage_targets_users_collection(self):
        stages = build_creator_lookup_stages()
        lookup = stages[1]["$lookup"]
        assert lookup["from"] == "users"
        assert lookup["localField"] == "created_by_oid"
        assert lookup["foreignField"] == "_id"

    def test_final_stage_removes_temp_fields(self):
        stages = build_creator_lookup_stages()
        project = stages[4]["$project"]
        assert project.get("creator_info") == 0
        assert project.get("created_by_oid") == 0


@pytest.mark.unit
class TestFormatCommunityIntegrations:
    def test_format_empty_list(self):
        assert format_community_integrations([]) == []

    def test_format_basic_document(self):
        doc = {
            "integration_id": "abc",
            "name": "Test",
            "description": "desc",
            "category": "custom",
            "tools": [
                {"name": "tool1", "description": "d1"},
                {"name": "tool2"},
            ],
            "slug": "test-mcp-custom",
        }
        result = format_community_integrations([doc])

        assert len(result) == 1
        item = result[0]
        assert isinstance(item, CommunityIntegrationItem)
        assert item.integration_id == "abc"
        assert item.slug == "test-mcp-custom"
        assert item.tool_count == 2
        assert len(item.tools) == 2

    def test_tools_truncated_to_10(self):
        tools = [{"name": f"tool_{i}", "description": f"d{i}"} for i in range(15)]
        doc = {
            "integration_id": "x",
            "name": "X",
            "description": "",
            "category": "custom",
            "tools": tools,
        }
        result = format_community_integrations([doc])

        assert len(result[0].tools) == 10
        assert result[0].tool_count == 15

    def test_with_creator_data(self):
        doc = {
            "integration_id": "abc",
            "name": "Test",
            "description": "",
            "category": "custom",
            "tools": [],
            "creator": {"name": "Alice", "picture": "https://img.com/a.jpg"},
        }
        result = format_community_integrations([doc])

        assert result[0].creator is not None
        assert result[0].creator.name == "Alice"

    def test_without_creator_data(self):
        doc = {
            "integration_id": "abc",
            "name": "Test",
            "description": "",
            "category": "custom",
            "tools": [],
        }
        result = format_community_integrations([doc])
        assert result[0].creator is None

    def test_slug_falls_back_to_generated(self):
        doc = {
            "integration_id": "abc",
            "name": "My Tool",
            "description": "",
            "category": "developer",
            "tools": [],
        }
        result = format_community_integrations([doc])

        # Should generate a slug since "slug" key is not present
        assert result[0].slug is not None
        assert len(result[0].slug) > 0

    def test_clone_count_defaults_to_zero(self):
        doc = {
            "integration_id": "abc",
            "name": "Test",
            "description": "",
            "category": "custom",
            "tools": [],
        }
        result = format_community_integrations([doc])
        assert result[0].clone_count == 0


# ---------------------------------------------------------------------------
# user_integration_status.py tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateUserIntegrationStatus:
    @patch(
        "app.services.integrations.user_integration_status.user_integrations_collection"
    )
    async def test_update_status_connected_success(self, mock_collection):
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_result.upserted_id = None
        mock_result.matched_count = 0
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        result = await update_user_integration_status.__wrapped__(
            USER_ID, INTEGRATION_ID, "connected"
        )

        assert result is True
        call_args = mock_collection.update_one.call_args
        set_data = call_args[0][1]["$set"]
        assert set_data["status"] == "connected"
        assert "connected_at" in set_data

    @patch(
        "app.services.integrations.user_integration_status.user_integrations_collection"
    )
    async def test_update_status_created_no_connected_at(self, mock_collection):
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_result.upserted_id = None
        mock_result.matched_count = 0
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        result = await update_user_integration_status.__wrapped__(
            USER_ID, INTEGRATION_ID, "created"
        )

        assert result is True
        set_data = mock_collection.update_one.call_args[0][1]["$set"]
        assert "connected_at" not in set_data

    @patch(
        "app.services.integrations.user_integration_status.user_integrations_collection"
    )
    async def test_upsert_creates_new_record(self, mock_collection):
        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_result.upserted_id = "new_id"
        mock_result.matched_count = 0
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        result = await update_user_integration_status.__wrapped__(
            USER_ID, INTEGRATION_ID, "connected"
        )

        assert result is True
        # Verify upsert=True was passed
        assert mock_collection.update_one.call_args[1].get("upsert") is True

    @patch(
        "app.services.integrations.user_integration_status.user_integrations_collection"
    )
    async def test_matched_but_not_modified_is_success(self, mock_collection):
        """Matching an existing doc with same values is still success."""
        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_result.upserted_id = None
        mock_result.matched_count = 1
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        result = await update_user_integration_status.__wrapped__(
            USER_ID, INTEGRATION_ID, "connected"
        )

        assert result is True

    @patch(
        "app.services.integrations.user_integration_status.user_integrations_collection"
    )
    async def test_no_match_no_upsert_returns_false(self, mock_collection):
        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_result.upserted_id = None
        mock_result.matched_count = 0
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        result = await update_user_integration_status.__wrapped__(
            USER_ID, INTEGRATION_ID, "created"
        )

        assert result is False


# ---------------------------------------------------------------------------
# user_integrations.py tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUserIntegrations:
    @patch(
        "app.services.integrations.user_integrations.get_integration_details",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.user_integrations.user_integrations_collection")
    async def test_returns_hydrated_integrations(
        self, mock_collection, mock_get_details
    ):
        now = datetime.now(UTC)
        docs = [
            {
                "user_id": USER_ID,
                "integration_id": "github",
                "status": "connected",
                "created_at": now,
                "connected_at": now,
            },
        ]

        # Create async iterable mock for cursor
        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.__aiter__ = MagicMock(return_value=iter(docs).__iter__())

        async def aiter_docs(*args, **kwargs):
            for doc in docs:
                yield doc

        mock_cursor.__aiter__ = aiter_docs
        mock_collection.find = MagicMock(return_value=mock_cursor)

        mock_response = IntegrationResponse(
            integration_id="github",
            name="GitHub",
            description="GitHub integration",
            category="developer",
            managed_by="mcp",
            source="platform",
            is_featured=True,
            display_priority=10,
        )
        mock_get_details.return_value = mock_response

        result = await get_user_integrations(USER_ID)

        assert isinstance(result, UserIntegrationsListResponse)
        assert result.total == 1
        assert result.integrations[0].integration_id == "github"
        assert result.integrations[0].status == "connected"
        assert result.integrations[0].integration.name == "GitHub"

    @patch(
        "app.services.integrations.user_integrations.get_integration_details",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.user_integrations.user_integrations_collection")
    async def test_skips_integration_with_no_details(
        self, mock_collection, mock_get_details
    ):
        now = datetime.now(UTC)
        docs = [
            {
                "user_id": USER_ID,
                "integration_id": "deleted-int",
                "status": "connected",
                "created_at": now,
            },
        ]

        async def aiter_docs(*args, **kwargs):
            for doc in docs:
                yield doc

        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.__aiter__ = aiter_docs
        mock_collection.find = MagicMock(return_value=mock_cursor)
        mock_get_details.return_value = None

        result = await get_user_integrations(USER_ID)

        assert result.total == 0
        assert result.integrations == []

    @patch(
        "app.services.integrations.user_integrations.get_integration_details",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.user_integrations.user_integrations_collection")
    async def test_handles_parse_error_gracefully(
        self, mock_collection, mock_get_details
    ):
        """If UserIntegration(**doc) raises, that entry is skipped."""
        bad_doc = {"user_id": USER_ID}  # Missing required fields

        async def aiter_docs(*args, **kwargs):
            yield bad_doc

        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.__aiter__ = aiter_docs
        mock_collection.find = MagicMock(return_value=mock_cursor)

        result = await get_user_integrations(USER_ID)
        assert result.total == 0

    @patch(
        "app.services.integrations.user_integrations.get_integration_details",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.user_integrations.user_integrations_collection")
    async def test_empty_workspace(self, mock_collection, mock_get_details):
        async def aiter_empty(*args, **kwargs):
            return
            yield  # noqa

        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.__aiter__ = aiter_empty
        mock_collection.find = MagicMock(return_value=mock_cursor)

        result = await get_user_integrations(USER_ID)
        assert result.total == 0
        assert result.integrations == []


@pytest.mark.unit
class TestGetUserConnectedIntegrations:
    @patch("app.services.integrations.user_integrations.user_integrations_collection")
    async def test_returns_serialized_documents(self, mock_collection):
        docs = [
            {
                "_id": MagicMock(),
                "user_id": USER_ID,
                "integration_id": "github",
                "status": "connected",
            },
        ]
        # _id needs to be a valid ObjectId-like for serialize_document
        from bson import ObjectId

        docs[0]["_id"] = ObjectId()

        async def aiter_docs(*args, **kwargs):
            for doc in docs:
                yield doc

        mock_cursor = MagicMock()
        mock_cursor.__aiter__ = aiter_docs
        mock_collection.find = MagicMock(return_value=mock_cursor)

        result = await get_user_connected_integrations.__wrapped__(USER_ID)

        assert len(result) == 1
        assert result[0]["integration_id"] == "github"
        assert "id" in result[0]  # serialize_document converts _id to id

    @patch("app.services.integrations.user_integrations.user_integrations_collection")
    async def test_empty_list_when_no_integrations(self, mock_collection):
        async def aiter_empty(*args, **kwargs):
            return
            yield  # NOSONAR — intentionally unreachable: makes this an async generator

        mock_cursor = MagicMock()
        mock_cursor.__aiter__ = aiter_empty
        mock_collection.find = MagicMock(return_value=mock_cursor)

        result = await get_user_connected_integrations.__wrapped__(USER_ID)
        assert result == []


@pytest.mark.unit
class TestAddUserIntegration:
    @patch("app.services.integrations.user_integrations.user_integrations_collection")
    @patch(
        "app.services.integrations.user_integrations.get_integration_details",
        new_callable=AsyncMock,
    )
    async def test_add_success_no_auth_defaults_connected(
        self, mock_get_details, mock_collection
    ):
        mock_get_details.return_value = IntegrationResponse(
            integration_id="my-int",
            name="My Int",
            description="desc",
            category="custom",
            managed_by="mcp",
            source="custom",
            is_featured=False,
            display_priority=0,
            requires_auth=False,
        )
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()

        result = await add_user_integration.__wrapped__(USER_ID, "my-int")

        assert result.status == "connected"
        assert result.connected_at is not None
        mock_collection.insert_one.assert_awaited_once()

    @patch("app.services.integrations.user_integrations.user_integrations_collection")
    @patch(
        "app.services.integrations.user_integrations.get_integration_details",
        new_callable=AsyncMock,
    )
    async def test_add_with_auth_defaults_created(
        self, mock_get_details, mock_collection
    ):
        mock_get_details.return_value = IntegrationResponse(
            integration_id="oauth-int",
            name="OAuth Int",
            description="desc",
            category="custom",
            managed_by="mcp",
            source="custom",
            is_featured=False,
            display_priority=0,
            requires_auth=True,
        )
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()

        result = await add_user_integration.__wrapped__(USER_ID, "oauth-int")

        assert result.status == "created"
        assert result.connected_at is None

    @patch("app.services.integrations.user_integrations.user_integrations_collection")
    @patch(
        "app.services.integrations.user_integrations.get_integration_details",
        new_callable=AsyncMock,
    )
    async def test_add_with_explicit_initial_status(
        self, mock_get_details, mock_collection
    ):
        mock_get_details.return_value = IntegrationResponse(
            integration_id="x",
            name="X",
            description="",
            category="c",
            managed_by="mcp",
            source="custom",
            is_featured=False,
            display_priority=0,
            requires_auth=True,
        )
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()

        result = await add_user_integration.__wrapped__(
            USER_ID, "x", initial_status="connected"
        )

        assert result.status == "connected"

    @patch("app.services.integrations.user_integrations.user_integrations_collection")
    @patch(
        "app.services.integrations.user_integrations.get_integration_details",
        new_callable=AsyncMock,
    )
    async def test_add_raises_if_not_found(self, mock_get_details, mock_collection):
        mock_get_details.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await add_user_integration.__wrapped__(USER_ID, "nonexistent")

    @patch("app.services.integrations.user_integrations.user_integrations_collection")
    @patch(
        "app.services.integrations.user_integrations.get_integration_details",
        new_callable=AsyncMock,
    )
    async def test_add_raises_if_already_exists(
        self, mock_get_details, mock_collection
    ):
        mock_get_details.return_value = IntegrationResponse(
            integration_id="dup",
            name="Dup",
            description="",
            category="c",
            managed_by="mcp",
            source="custom",
            is_featured=False,
            display_priority=0,
        )
        mock_collection.find_one = AsyncMock(return_value={"integration_id": "dup"})

        with pytest.raises(ValueError, match="already added"):
            await add_user_integration.__wrapped__(USER_ID, "dup")


@pytest.mark.unit
class TestRemoveUserIntegration:
    @patch("app.services.integrations.user_integrations.user_integrations_collection")
    async def test_remove_success(self, mock_collection):
        mock_result = MagicMock()
        mock_result.deleted_count = 1
        mock_collection.delete_one = AsyncMock(return_value=mock_result)

        result = await remove_user_integration.__wrapped__(USER_ID, INTEGRATION_ID)

        assert result is True

    @patch("app.services.integrations.user_integrations.user_integrations_collection")
    async def test_remove_not_found(self, mock_collection):
        mock_result = MagicMock()
        mock_result.deleted_count = 0
        mock_collection.delete_one = AsyncMock(return_value=mock_result)

        result = await remove_user_integration.__wrapped__(USER_ID, "missing")

        assert result is False


@pytest.mark.unit
class TestCheckUserHasIntegration:
    @patch("app.services.integrations.user_integrations.user_integrations_collection")
    async def test_has_integration(self, mock_collection):
        mock_collection.find_one = AsyncMock(
            return_value={"user_id": USER_ID, "integration_id": INTEGRATION_ID}
        )

        result = await check_user_has_integration(USER_ID, INTEGRATION_ID)
        assert result is True

    @patch("app.services.integrations.user_integrations.user_integrations_collection")
    async def test_does_not_have_integration(self, mock_collection):
        mock_collection.find_one = AsyncMock(return_value=None)

        result = await check_user_has_integration(USER_ID, "missing")
        assert result is False


@pytest.mark.unit
class TestGetUserIntegrationCapabilities:
    @patch(
        "app.services.integrations.user_integrations.get_integration_details",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.user_integrations.get_user_connected_integrations",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.user_integrations.get_tool_registry",
        new_callable=AsyncMock,
    )
    async def test_includes_core_tools_and_integrations(
        self, mock_registry, mock_connected, mock_details
    ):
        # Mock the tool registry
        core_tool = MagicMock()
        core_tool.name = "web_search"
        core_category = MagicMock()
        core_category.tools = [core_tool]
        registry = MagicMock()
        registry.get_core_categories.return_value = [core_category]
        mock_registry.return_value = registry

        mock_connected.return_value = [
            {"integration_id": "github", "status": "connected"},
        ]

        int_tool = IntegrationTool(name="create_issue", description="Create an issue")
        mock_details.return_value = IntegrationResponse(
            integration_id="github",
            name="GitHub",
            description="",
            category="developer",
            managed_by="mcp",
            source="platform",
            is_featured=False,
            display_priority=0,
            tools=[int_tool],
        )

        result = await get_user_integration_capabilities.__wrapped__(USER_ID)

        assert "web_search" in result["tool_names"]
        assert "create_issue" in result["tool_names"]
        assert "GitHub" in result["integration_names"]
        assert "github" in result["capabilities"]

    @patch(
        "app.services.integrations.user_integrations.get_integration_details",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.user_integrations.get_user_connected_integrations",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.user_integrations.get_tool_registry",
        new_callable=AsyncMock,
    )
    async def test_skips_integrations_with_no_details(
        self, mock_registry, mock_connected, mock_details
    ):
        registry = MagicMock()
        registry.get_core_categories.return_value = []
        mock_registry.return_value = registry

        mock_connected.return_value = [
            {"integration_id": "deleted"},
        ]
        mock_details.return_value = None

        result = await get_user_integration_capabilities.__wrapped__(USER_ID)

        assert result["integration_names"] == []
        assert result["capabilities"] == {}

    @patch(
        "app.services.integrations.user_integrations.get_integration_details",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.user_integrations.get_user_connected_integrations",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.user_integrations.get_tool_registry",
        new_callable=AsyncMock,
    )
    async def test_skips_entries_without_integration_id(
        self, mock_registry, mock_connected, mock_details
    ):
        registry = MagicMock()
        registry.get_core_categories.return_value = []
        mock_registry.return_value = registry

        mock_connected.return_value = [
            {"status": "connected"},  # Missing integration_id
        ]

        result = await get_user_integration_capabilities.__wrapped__(USER_ID)
        assert result["integration_names"] == []

    @patch(
        "app.services.integrations.user_integrations.get_integration_details",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.user_integrations.get_user_connected_integrations",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.user_integrations.get_tool_registry",
        new_callable=AsyncMock,
    )
    async def test_no_connected_integrations(
        self, mock_registry, mock_connected, mock_details
    ):
        registry = MagicMock()
        registry.get_core_categories.return_value = []
        mock_registry.return_value = registry
        mock_connected.return_value = []

        result = await get_user_integration_capabilities.__wrapped__(USER_ID)

        assert result["integration_names"] == []
        assert result["tool_names"] == []
        assert result["capabilities"] == {}


# ---------------------------------------------------------------------------
# custom_crud.py tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateCustomIntegration:
    @patch(
        "app.services.integrations.custom_crud.add_user_integration",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_create_success(self, mock_int_collection, mock_add_user):
        mock_int_collection.insert_one = AsyncMock()
        mock_add_user.return_value = MagicMock()

        request = CreateCustomIntegrationRequest(
            name="My MCP",
            description="desc",
            server_url=SERVER_URL,
        )

        result = await create_custom_integration(USER_ID, request)

        assert isinstance(result, Integration)
        assert result.name == "My MCP"
        assert result.managed_by == "mcp"
        assert result.source == "custom"
        assert result.created_by == USER_ID
        assert result.mcp_config is not None
        assert result.mcp_config.server_url == SERVER_URL
        mock_int_collection.insert_one.assert_awaited_once()
        mock_add_user.assert_awaited_once()

    @patch(
        "app.services.integrations.custom_crud.add_user_integration",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_create_with_icon_url(self, mock_int_collection, mock_add_user):
        mock_int_collection.insert_one = AsyncMock()
        mock_add_user.return_value = MagicMock()

        request = CreateCustomIntegrationRequest(name="My MCP", server_url=SERVER_URL)

        result = await create_custom_integration(
            USER_ID, request, icon_url="https://example.com/icon.png"
        )

        assert result.icon_url == "https://example.com/icon.png"

    @patch(
        "app.services.integrations.custom_crud.add_user_integration",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_create_rolls_back_on_user_integration_failure(
        self, mock_int_collection, mock_add_user
    ):
        mock_int_collection.insert_one = AsyncMock()
        mock_int_collection.delete_one = AsyncMock()
        mock_add_user.side_effect = Exception("User integration failed")

        request = CreateCustomIntegrationRequest(name="Fail MCP", server_url=SERVER_URL)

        with pytest.raises(Exception, match="User integration failed"):
            await create_custom_integration(USER_ID, request)

        mock_int_collection.delete_one.assert_awaited_once()

    @patch(
        "app.services.integrations.custom_crud.add_user_integration",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_create_with_auth_requirements(
        self, mock_int_collection, mock_add_user
    ):
        mock_int_collection.insert_one = AsyncMock()
        mock_add_user.return_value = MagicMock()

        request = CreateCustomIntegrationRequest(
            name="Auth MCP",
            server_url=SERVER_URL,
            requires_auth=True,
            auth_type="oauth",
        )

        result = await create_custom_integration(USER_ID, request)

        assert result.mcp_config.requires_auth is True
        assert result.mcp_config.auth_type == "oauth"

    @patch(
        "app.services.integrations.custom_crud.add_user_integration",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_create_public_integration(self, mock_int_collection, mock_add_user):
        mock_int_collection.insert_one = AsyncMock()
        mock_add_user.return_value = MagicMock()

        request = CreateCustomIntegrationRequest(
            name="Public MCP",
            server_url=SERVER_URL,
            is_public=True,
        )

        result = await create_custom_integration(USER_ID, request)
        assert result.is_public is True


@pytest.mark.unit
class TestUpdateCustomIntegration:
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_update_name_success(self, mock_collection):
        doc = _make_custom_doc()
        updated_doc = {**doc, "name": "New Name"}
        mock_collection.find_one = AsyncMock(side_effect=[doc, updated_doc])
        mock_collection.update_one = AsyncMock()

        request = UpdateCustomIntegrationRequest(name="New Name")
        result = await update_custom_integration(
            USER_ID, CUSTOM_INTEGRATION_ID, request
        )

        assert result is not None
        assert result.name == "New Name"
        mock_collection.update_one.assert_awaited_once()

    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_update_not_found_returns_none(self, mock_collection):
        mock_collection.find_one = AsyncMock(return_value=None)

        request = UpdateCustomIntegrationRequest(name="New Name")
        result = await update_custom_integration(USER_ID, "missing", request)

        assert result is None

    @patch(
        "app.services.integrations.custom_crud.cleanup_integration_chroma_data",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_update_server_url_cleans_up_old_namespace(
        self, mock_collection, mock_chroma_cleanup
    ):
        import copy

        doc = _make_custom_doc(server_url="https://old-server.com")
        updated_doc = copy.deepcopy(doc)
        updated_doc["mcp_config"]["server_url"] = "https://new-server.com"
        mock_collection.find_one = AsyncMock(side_effect=[doc, updated_doc])
        mock_collection.update_one = AsyncMock()

        request = UpdateCustomIntegrationRequest(server_url="https://new-server.com")
        result = await update_custom_integration(
            USER_ID, CUSTOM_INTEGRATION_ID, request
        )

        assert result is not None
        mock_chroma_cleanup.assert_awaited_once_with(
            CUSTOM_INTEGRATION_ID, "https://old-server.com"
        )

    @patch(
        "app.services.integrations.custom_crud.cleanup_integration_chroma_data",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_update_server_url_same_url_no_cleanup(
        self, mock_collection, mock_chroma_cleanup
    ):
        doc = _make_custom_doc(server_url=SERVER_URL)
        mock_collection.find_one = AsyncMock(side_effect=[doc, doc])
        mock_collection.update_one = AsyncMock()

        request = UpdateCustomIntegrationRequest(server_url=SERVER_URL)
        await update_custom_integration(USER_ID, CUSTOM_INTEGRATION_ID, request)

        mock_chroma_cleanup.assert_not_awaited()

    @patch(
        "app.services.integrations.custom_crud.cleanup_integration_chroma_data",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_update_server_url_chroma_cleanup_failure_non_fatal(
        self, mock_collection, mock_chroma_cleanup
    ):
        doc = _make_custom_doc(server_url="https://old.com")
        updated_doc = {**doc}
        updated_doc["mcp_config"]["server_url"] = "https://new.com"
        mock_collection.find_one = AsyncMock(side_effect=[doc, updated_doc])
        mock_collection.update_one = AsyncMock()
        mock_chroma_cleanup.side_effect = Exception("Chroma error")

        request = UpdateCustomIntegrationRequest(server_url="https://new.com")
        # Should not raise
        result = await update_custom_integration(
            USER_ID, CUSTOM_INTEGRATION_ID, request
        )
        assert result is not None

    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_update_description_and_is_public(self, mock_collection):
        doc = _make_custom_doc()
        updated_doc = {**doc, "description": "new desc", "is_public": True}
        mock_collection.find_one = AsyncMock(side_effect=[doc, updated_doc])
        mock_collection.update_one = AsyncMock()

        request = UpdateCustomIntegrationRequest(description="new desc", is_public=True)
        result = await update_custom_integration(
            USER_ID, CUSTOM_INTEGRATION_ID, request
        )

        assert result is not None
        call_args = mock_collection.update_one.call_args[0][1]["$set"]
        assert call_args["description"] == "new desc"
        assert call_args["is_public"] is True

    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_update_requires_auth(self, mock_collection):
        doc = _make_custom_doc(requires_auth=False)
        updated_doc = {**doc}
        updated_doc["mcp_config"]["requires_auth"] = True
        mock_collection.find_one = AsyncMock(side_effect=[doc, updated_doc])
        mock_collection.update_one = AsyncMock()

        request = UpdateCustomIntegrationRequest(requires_auth=True)
        result = await update_custom_integration(
            USER_ID, CUSTOM_INTEGRATION_ID, request
        )

        assert result is not None
        call_args = mock_collection.update_one.call_args[0][1]["$set"]
        assert "mcp_config" in call_args
        assert call_args["mcp_config"]["requires_auth"] is True


@pytest.mark.unit
class TestDeleteCustomIntegration:
    @patch(
        "app.services.integrations.custom_crud.delete_cache_by_pattern",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.delete_cache", new_callable=AsyncMock)
    @patch(
        "app.services.integrations.custom_crud.cleanup_integration_chroma_data",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.get_db_session")
    @patch(
        "app.services.integrations.custom_crud.remove_public_integration",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.user_integrations_collection")
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_delete_as_creator_success(
        self,
        mock_int_collection,
        mock_user_int_collection,
        mock_remove_public,
        mock_get_db,
        mock_chroma_cleanup,
        mock_delete_cache,
        mock_delete_pattern,
    ):
        doc = _make_custom_doc(created_by=USER_ID, is_public=False)
        mock_int_collection.find_one = AsyncMock(return_value=doc)
        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_int_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        # Mock affected users cursor
        async def aiter_affected(*args, **kwargs):
            yield {"user_id": USER_ID}

        mock_affected_cursor = MagicMock()
        mock_affected_cursor.__aiter__ = aiter_affected
        mock_user_int_collection.find = MagicMock(return_value=mock_affected_cursor)
        mock_user_int_collection.delete_many = AsyncMock()

        # Mock PostgreSQL session
        mock_session = AsyncMock()
        mock_db_ctx = AsyncMock()
        mock_db_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_db.return_value = mock_db_ctx

        result = await delete_custom_integration(USER_ID, CUSTOM_INTEGRATION_ID)

        assert result is True
        mock_int_collection.delete_one.assert_awaited_once()
        mock_user_int_collection.delete_many.assert_awaited_once()
        mock_chroma_cleanup.assert_awaited_once()

    @patch(
        "app.services.integrations.custom_crud.delete_cache_by_pattern",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.delete_cache", new_callable=AsyncMock)
    @patch(
        "app.services.integrations.custom_crud.cleanup_integration_chroma_data",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.get_db_session")
    @patch(
        "app.services.integrations.custom_crud.remove_public_integration",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.user_integrations_collection")
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_delete_public_integration_removes_from_store(
        self,
        mock_int_collection,
        mock_user_int_collection,
        mock_remove_public,
        mock_get_db,
        mock_chroma_cleanup,
        mock_delete_cache,
        mock_delete_pattern,
    ):
        doc = _make_custom_doc(created_by=USER_ID, is_public=True)
        mock_int_collection.find_one = AsyncMock(return_value=doc)
        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_int_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        async def aiter_empty(*args, **kwargs):
            return
            yield  # NOSONAR — intentionally unreachable: makes this an async generator

        mock_cursor = MagicMock()
        mock_cursor.__aiter__ = aiter_empty
        mock_user_int_collection.find = MagicMock(return_value=mock_cursor)
        mock_user_int_collection.delete_many = AsyncMock()

        mock_session = AsyncMock()
        mock_db_ctx = AsyncMock()
        mock_db_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_db.return_value = mock_db_ctx

        result = await delete_custom_integration(USER_ID, CUSTOM_INTEGRATION_ID)

        assert result is True
        mock_remove_public.assert_awaited_once_with(CUSTOM_INTEGRATION_ID)

    @patch(
        "app.services.integrations.custom_crud.delete_cache_by_pattern",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.user_integrations_collection")
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_delete_not_found_checks_user_integrations(
        self, mock_int_collection, mock_user_int_collection, mock_delete_pattern
    ):
        """When integration doc not found, fall back to user_integrations cleanup."""
        mock_int_collection.find_one = AsyncMock(return_value=None)
        mock_user_int_collection.find_one = AsyncMock(
            return_value={"user_id": USER_ID, "integration_id": "orphan"}
        )
        mock_user_int_collection.delete_one = AsyncMock()

        result = await delete_custom_integration(USER_ID, "orphan")

        assert result is True
        mock_user_int_collection.delete_one.assert_awaited_once()
        mock_delete_pattern.assert_awaited_once()

    @patch("app.services.integrations.custom_crud.user_integrations_collection")
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_delete_not_found_no_user_integration_returns_false(
        self, mock_int_collection, mock_user_int_collection
    ):
        mock_int_collection.find_one = AsyncMock(return_value=None)
        mock_user_int_collection.find_one = AsyncMock(return_value=None)

        result = await delete_custom_integration(USER_ID, "nonexistent")

        assert result is False

    @patch(
        "app.services.integrations.custom_crud.delete_cache_by_pattern",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.get_db_session")
    @patch("app.services.integrations.custom_crud.user_integrations_collection")
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_delete_as_non_creator_removes_user_integration_only(
        self,
        mock_int_collection,
        mock_user_int_collection,
        mock_get_db,
        mock_delete_pattern,
    ):
        """Non-creator can only remove from their workspace, not delete the integration."""
        doc = _make_custom_doc(created_by="other-user-id")
        mock_int_collection.find_one = AsyncMock(return_value=doc)

        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 1
        mock_user_int_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        mock_session = AsyncMock()
        mock_db_ctx = AsyncMock()
        mock_db_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_db.return_value = mock_db_ctx

        result = await delete_custom_integration(USER_ID, CUSTOM_INTEGRATION_ID)

        assert result is True
        # Should NOT delete from integrations_collection
        mock_int_collection.delete_one.assert_not_called()
        # Should delete from user_integrations_collection
        mock_user_int_collection.delete_one.assert_awaited_once()
        mock_delete_pattern.assert_awaited_once()

    @patch(
        "app.services.integrations.custom_crud.delete_cache_by_pattern",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.delete_cache", new_callable=AsyncMock)
    @patch(
        "app.services.integrations.custom_crud.cleanup_integration_chroma_data",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.get_db_session")
    @patch(
        "app.services.integrations.custom_crud.remove_public_integration",
        new_callable=AsyncMock,
    )
    @patch("app.services.integrations.custom_crud.user_integrations_collection")
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_delete_creator_db_delete_zero_returns_false(
        self,
        mock_int_collection,
        mock_user_int_collection,
        mock_remove_public,
        mock_get_db,
        mock_chroma_cleanup,
        mock_delete_cache,
        mock_delete_pattern,
    ):
        doc = _make_custom_doc(created_by=USER_ID)
        mock_int_collection.find_one = AsyncMock(return_value=doc)
        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 0
        mock_int_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        result = await delete_custom_integration(USER_ID, CUSTOM_INTEGRATION_ID)

        assert result is False

    @patch("app.services.integrations.custom_crud.user_integrations_collection")
    @patch("app.services.integrations.custom_crud.integrations_collection")
    async def test_delete_as_non_creator_zero_deleted_returns_false(
        self, mock_int_collection, mock_user_int_collection
    ):
        doc = _make_custom_doc(created_by="other-user")
        mock_int_collection.find_one = AsyncMock(return_value=doc)
        mock_delete_result = MagicMock()
        mock_delete_result.deleted_count = 0
        mock_user_int_collection.delete_one = AsyncMock(return_value=mock_delete_result)

        result = await delete_custom_integration(USER_ID, CUSTOM_INTEGRATION_ID)

        assert result is False


@pytest.mark.unit
class TestCreateAndConnectCustomIntegration:
    @patch(
        "app.services.integrations.custom_crud.create_custom_integration",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.custom_crud.fetch_favicon_from_url",
        new_callable=AsyncMock,
    )
    async def test_bearer_token_flow(self, mock_favicon, mock_create):
        mock_favicon.return_value = None
        integration = Integration(
            integration_id="new-id",
            name="Bearer Int",
            description="",
            category="custom",
            managed_by="mcp",
            source="custom",
            mcp_config=MCPConfig(server_url=SERVER_URL),
        )
        mock_create.return_value = integration

        mock_mcp_client = AsyncMock()
        mock_mcp_client.connect.return_value = ["tool1", "tool2"]

        # Mock MCPTokenStore
        with (
            patch(
                "app.services.integrations.custom_crud.MCPTokenStore"
            ) as mock_token_store_cls,
            patch(
                "app.services.integrations.custom_crud.update_user_integration_status",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.integrations.custom_crud.integrations_collection"
            ) as mock_int_col,
        ):
            mock_store_instance = AsyncMock()
            mock_token_store_cls.return_value = mock_store_instance

            # _get_integration returns the Integration
            mock_int_col.find_one = AsyncMock(return_value=integration.model_dump())

            request = CreateCustomIntegrationRequest(
                name="Bearer Int",
                server_url=SERVER_URL,
                bearer_token="my-secret-token",
            )

            result_int, result_status = await create_and_connect_custom_integration(
                USER_ID, request, mock_mcp_client
            )

            assert result_status["status"] == "connected"
            assert result_status["tools_count"] == 2
            mock_store_instance.store_bearer_token.assert_awaited_once()

    @patch(
        "app.services.integrations.custom_crud.create_custom_integration",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.custom_crud.fetch_favicon_from_url",
        new_callable=AsyncMock,
    )
    async def test_probe_fails_returns_error(self, mock_favicon, mock_create):
        mock_favicon.return_value = None
        integration = Integration(
            integration_id="new-id",
            name="Probe Fail",
            description="",
            category="custom",
            managed_by="mcp",
            source="custom",
            mcp_config=MCPConfig(server_url=SERVER_URL),
        )
        mock_create.return_value = integration

        mock_mcp_client = AsyncMock()
        mock_mcp_client.probe_connection.side_effect = Exception("Connection refused")

        request = CreateCustomIntegrationRequest(
            name="Probe Fail",
            server_url=SERVER_URL,
        )

        result_int, result_status = await create_and_connect_custom_integration(
            USER_ID, request, mock_mcp_client
        )

        assert result_status["status"] == "failed"
        assert "Connection refused" in result_status["error"]

    @patch(
        "app.services.integrations.custom_crud.create_custom_integration",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.custom_crud.fetch_favicon_from_url",
        new_callable=AsyncMock,
    )
    async def test_probe_detects_auth_requirement(self, mock_favicon, mock_create):
        mock_favicon.return_value = None
        integration = Integration(
            integration_id="new-id",
            name="Auth Probe",
            description="",
            category="custom",
            managed_by="mcp",
            source="custom",
            mcp_config=MCPConfig(server_url=SERVER_URL),
        )
        mock_create.return_value = integration

        mock_mcp_client = AsyncMock()
        mock_mcp_client.probe_connection.return_value = {
            "requires_auth": True,
            "auth_type": "oauth",
        }
        mock_mcp_client.build_oauth_auth_url.return_value = "https://auth.example.com"

        request = CreateCustomIntegrationRequest(
            name="Auth Probe",
            server_url=SERVER_URL,
        )

        result_int, result_status = await create_and_connect_custom_integration(
            USER_ID, request, mock_mcp_client
        )

        assert result_status["status"] == "requires_oauth"
        assert result_status["oauth_url"] == "https://auth.example.com"

    @patch(
        "app.services.integrations.custom_crud.create_custom_integration",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.custom_crud.fetch_favicon_from_url",
        new_callable=AsyncMock,
    )
    async def test_connect_without_auth_success(self, mock_favicon, mock_create):
        mock_favicon.return_value = "https://example.com/fav.ico"
        integration = Integration(
            integration_id="new-id",
            name="No Auth",
            description="",
            category="custom",
            managed_by="mcp",
            source="custom",
            mcp_config=MCPConfig(server_url=SERVER_URL),
        )
        mock_create.return_value = integration

        mock_mcp_client = AsyncMock()
        mock_mcp_client.probe_connection.return_value = {}
        mock_mcp_client.connect.return_value = ["t1", "t2", "t3"]

        request = CreateCustomIntegrationRequest(
            name="No Auth",
            server_url=SERVER_URL,
        )

        result_int, result_status = await create_and_connect_custom_integration(
            USER_ID, request, mock_mcp_client
        )

        assert result_status["status"] == "connected"
        assert result_status["tools_count"] == 3

    @patch(
        "app.services.integrations.custom_crud.create_custom_integration",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.custom_crud.fetch_favicon_from_url",
        new_callable=AsyncMock,
    )
    async def test_connect_raises_oauth_error_triggers_auth_flow(
        self, mock_favicon, mock_create
    ):
        from mcp_use.client.exceptions import OAuthAuthenticationError

        mock_favicon.return_value = None
        integration = Integration(
            integration_id="new-id",
            name="OAuthErr",
            description="",
            category="custom",
            managed_by="mcp",
            source="custom",
            mcp_config=MCPConfig(server_url=SERVER_URL),
        )
        mock_create.return_value = integration

        mock_mcp_client = AsyncMock()
        mock_mcp_client.probe_connection.return_value = {}
        mock_mcp_client.connect.side_effect = OAuthAuthenticationError("Need auth")
        mock_mcp_client.build_oauth_auth_url.return_value = "https://oauth.example.com"

        request = CreateCustomIntegrationRequest(
            name="OAuthErr",
            server_url=SERVER_URL,
        )

        result_int, result_status = await create_and_connect_custom_integration(
            USER_ID, request, mock_mcp_client
        )

        assert result_status["status"] == "requires_oauth"

    @patch(
        "app.services.integrations.custom_crud.create_custom_integration",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.custom_crud.fetch_favicon_from_url",
        new_callable=AsyncMock,
    )
    async def test_connect_generic_error(self, mock_favicon, mock_create):
        mock_favicon.return_value = None
        integration = Integration(
            integration_id="new-id",
            name="Err",
            description="",
            category="custom",
            managed_by="mcp",
            source="custom",
            mcp_config=MCPConfig(server_url=SERVER_URL),
        )
        mock_create.return_value = integration

        mock_mcp_client = AsyncMock()
        mock_mcp_client.probe_connection.return_value = {}
        mock_mcp_client.connect.side_effect = RuntimeError("Server down")

        request = CreateCustomIntegrationRequest(
            name="Err",
            server_url=SERVER_URL,
        )

        result_int, result_status = await create_and_connect_custom_integration(
            USER_ID, request, mock_mcp_client
        )

        assert result_status["status"] == "failed"
        assert "Server down" in result_status["error"]


# ---------------------------------------------------------------------------
# integration_connection_service.py tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildIntegrationsConfig:
    @patch(
        "app.services.integrations.integration_connection_service.OAUTH_INTEGRATIONS",
        [
            _make_oauth_integration(
                id="github",
                managed_by="mcp",
                mcp_config=MCPConfig(server_url=SERVER_URL, requires_auth=True),
            ),
            _make_oauth_integration(id="todos", managed_by="internal"),
        ],
    )
    def test_excludes_internal_integrations(self):
        build_integrations_config.cache_clear()
        result = build_integrations_config()

        ids = [i.id for i in result.integrations]
        assert "github" in ids
        assert "todos" not in ids

    @patch(
        "app.services.integrations.integration_connection_service.OAUTH_INTEGRATIONS",
        [
            _make_oauth_integration(
                id="no-auth-mcp",
                managed_by="mcp",
                mcp_config=MCPConfig(server_url=SERVER_URL, requires_auth=False),
            ),
        ],
    )
    def test_auth_type_none_when_no_auth_required(self):
        build_integrations_config.cache_clear()
        result = build_integrations_config()

        assert result.integrations[0].auth_type == "none"

    @patch(
        "app.services.integrations.integration_connection_service.OAUTH_INTEGRATIONS",
        [
            _make_oauth_integration(
                id="oauth-mcp",
                managed_by="mcp",
                mcp_config=MCPConfig(server_url=SERVER_URL, requires_auth=True),
            ),
        ],
    )
    def test_auth_type_oauth_when_auth_required(self):
        build_integrations_config.cache_clear()
        result = build_integrations_config()

        assert result.integrations[0].auth_type == "oauth"

    @patch(
        "app.services.integrations.integration_connection_service.OAUTH_INTEGRATIONS",
        [
            _make_oauth_integration(id="no-mcp", managed_by="self"),
        ],
    )
    def test_auth_type_none_when_no_mcp_config(self):
        build_integrations_config.cache_clear()
        result = build_integrations_config()

        assert result.integrations[0].auth_type is None

    @patch(
        "app.services.integrations.integration_connection_service.OAUTH_INTEGRATIONS",
        [],
    )
    def test_empty_integrations(self):
        build_integrations_config.cache_clear()
        result = build_integrations_config()
        assert result.integrations == []


@pytest.mark.unit
class TestConnectMcpIntegration:
    @patch(
        "app.services.integrations.integration_connection_service.invalidate_mcp_status_cache",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_mcp_client",
        new_callable=AsyncMock,
    )
    async def test_connect_no_auth_success(self, mock_get_client, mock_invalidate):
        mock_client = AsyncMock()
        mock_client.connect.return_value = ["tool1", "tool2"]
        mock_get_client.return_value = mock_client

        result = await connect_mcp_integration(
            user_id=USER_ID,
            integration_id=INTEGRATION_ID,
            integration_name="Test",
            requires_auth=False,
            redirect_path="/integrations",
            server_url=SERVER_URL,
            probe_result={},
        )

        assert result.status == "connected"
        assert result.tools_count == 2
        mock_invalidate.assert_awaited_once()

    @patch(
        "app.services.integrations.integration_connection_service.update_user_integration_status",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_mcp_client",
        new_callable=AsyncMock,
    )
    async def test_connect_requires_auth_returns_redirect(
        self, mock_get_client, mock_update_status
    ):
        mock_client = AsyncMock()
        mock_client.build_oauth_auth_url.return_value = "https://auth.example.com"
        mock_get_client.return_value = mock_client

        result = await connect_mcp_integration(
            user_id=USER_ID,
            integration_id=INTEGRATION_ID,
            integration_name="Test",
            requires_auth=True,
            redirect_path="/integrations",
            is_platform=False,
        )

        assert result.status == "redirect"
        assert result.redirect_url == "https://auth.example.com"
        mock_update_status.assert_awaited_once_with(USER_ID, INTEGRATION_ID, "created")

    @patch(
        "app.services.integrations.integration_connection_service.update_user_integration_status",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_mcp_client",
        new_callable=AsyncMock,
    )
    async def test_connect_requires_auth_platform_skips_status_update(
        self, mock_get_client, mock_update_status
    ):
        mock_client = AsyncMock()
        mock_client.build_oauth_auth_url.return_value = "https://auth.example.com"
        mock_get_client.return_value = mock_client

        result = await connect_mcp_integration(
            user_id=USER_ID,
            integration_id=INTEGRATION_ID,
            integration_name="Test",
            requires_auth=True,
            redirect_path="/integrations",
            is_platform=True,
        )

        assert result.status == "redirect"
        mock_update_status.assert_not_awaited()

    @patch(
        "app.services.integrations.integration_connection_service.invalidate_mcp_status_cache",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.MCPTokenStore",
    )
    @patch(
        "app.services.integrations.integration_connection_service.update_user_integration_status",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_mcp_client",
        new_callable=AsyncMock,
    )
    async def test_connect_bearer_token_success(
        self,
        mock_get_client,
        mock_update_status,
        mock_token_store_cls,
        mock_invalidate,
    ):
        mock_client = AsyncMock()
        mock_client.connect.return_value = ["t1"]
        mock_get_client.return_value = mock_client

        mock_store = AsyncMock()
        mock_token_store_cls.return_value = mock_store

        result = await connect_mcp_integration(
            user_id=USER_ID,
            integration_id=INTEGRATION_ID,
            integration_name="Test",
            requires_auth=False,
            redirect_path="/integrations",
            bearer_token="my-token",
        )

        assert result.status == "connected"
        assert result.tools_count == 1
        mock_store.store_bearer_token.assert_awaited_once()

    @patch(
        "app.services.integrations.integration_connection_service.invalidate_mcp_status_cache",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.MCPTokenStore",
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_mcp_client",
        new_callable=AsyncMock,
    )
    async def test_connect_bearer_token_failure_rolls_back(
        self, mock_get_client, mock_token_store_cls, mock_invalidate
    ):
        mock_client = AsyncMock()
        mock_client.connect.side_effect = RuntimeError("Connection failed")
        mock_get_client.return_value = mock_client

        mock_store = AsyncMock()
        mock_token_store_cls.return_value = mock_store

        result = await connect_mcp_integration(
            user_id=USER_ID,
            integration_id=INTEGRATION_ID,
            integration_name="Test",
            requires_auth=False,
            redirect_path="/integrations",
            bearer_token="bad-token",
        )

        assert result.status == "error"
        assert result.error is not None
        mock_store.delete_credentials.assert_awaited_once()

    @patch(
        "app.services.integrations.integration_connection_service.get_mcp_client",
        new_callable=AsyncMock,
    )
    async def test_probe_detects_auth_requirement(self, mock_get_client):
        """When probe_result is None, probe is performed and discovers auth requirement."""
        mock_client = AsyncMock()
        mock_client.probe_connection.return_value = {
            "requires_auth": True,
            "auth_type": "oauth",
        }
        mock_client.build_oauth_auth_url.return_value = "https://auth.url"
        mock_get_client.return_value = mock_client

        with patch(
            "app.services.integrations.integration_connection_service.update_user_integration_status",
            new_callable=AsyncMock,
        ):
            result = await connect_mcp_integration(
                user_id=USER_ID,
                integration_id=INTEGRATION_ID,
                integration_name="Test",
                requires_auth=False,
                redirect_path="/integrations",
                server_url=SERVER_URL,
                probe_result=None,
            )

        assert result.status == "redirect"

    @patch(
        "app.services.integrations.integration_connection_service.update_user_integration_status",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_mcp_client",
        new_callable=AsyncMock,
    )
    async def test_connect_catches_oauth_authentication_error(
        self, mock_get_client, mock_update_status
    ):
        from mcp_use.exceptions import OAuthAuthenticationError

        mock_client = AsyncMock()
        mock_client.connect.side_effect = OAuthAuthenticationError("Need auth")
        mock_client.build_oauth_auth_url.return_value = "https://auth.url"
        mock_get_client.return_value = mock_client

        result = await connect_mcp_integration(
            user_id=USER_ID,
            integration_id=INTEGRATION_ID,
            integration_name="Test",
            requires_auth=False,
            redirect_path="/integrations",
            server_url=SERVER_URL,
            probe_result={},
        )

        assert result.status == "redirect"
        assert result.redirect_url == "https://auth.url"

    @patch(
        "app.services.integrations.integration_connection_service.invalidate_mcp_status_cache",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_mcp_client",
        new_callable=AsyncMock,
    )
    async def test_connect_none_tools_returns_zero_count(
        self, mock_get_client, mock_invalidate
    ):
        mock_client = AsyncMock()
        mock_client.connect.return_value = None
        mock_get_client.return_value = mock_client

        result = await connect_mcp_integration(
            user_id=USER_ID,
            integration_id=INTEGRATION_ID,
            integration_name="Test",
            requires_auth=False,
            redirect_path="/integrations",
            server_url=SERVER_URL,
            probe_result={},
        )

        assert result.status == "connected"
        assert result.tools_count == 0


@pytest.mark.unit
class TestConnectComposioIntegration:
    @patch(
        "app.services.integrations.integration_connection_service.update_user_integration_status",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.create_oauth_state",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_composio_service",
    )
    async def test_connect_success(
        self, mock_get_composio, mock_create_state, mock_update_status
    ):
        mock_service = AsyncMock()
        mock_service.connect_account.return_value = {
            "redirect_url": "https://composio.dev/auth"
        }
        mock_get_composio.return_value = mock_service
        mock_create_state.return_value = "state-token"

        result = await connect_composio_integration(
            user_id=USER_ID,
            integration_id="slack",
            integration_name="Slack",
            provider="slack",
            redirect_path="/integrations",
        )

        assert result.status == "redirect"
        assert result.redirect_url == "https://composio.dev/auth"
        mock_update_status.assert_awaited_once_with(USER_ID, "slack", "created")


@pytest.mark.unit
class TestConnectSelfIntegration:
    @patch(
        "app.services.integrations.integration_connection_service.build_google_oauth_url",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_integration_scopes",
    )
    @patch(
        "app.services.integrations.integration_connection_service.update_user_integration_status",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.create_oauth_state",
        new_callable=AsyncMock,
    )
    async def test_connect_google_success(
        self,
        mock_create_state,
        mock_update_status,
        mock_get_scopes,
        mock_build_url,
    ):
        mock_create_state.return_value = "state-token"
        mock_get_scopes.return_value = ["email", "calendar"]
        mock_build_url.return_value = "https://accounts.google.com/auth"

        result = await connect_self_integration(
            user_id=USER_ID,
            user_email="test@example.com",
            integration_id="gcal",
            integration_name="Google Calendar",
            provider="google",
            redirect_path="/integrations",
        )

        assert result.status == "redirect"
        assert result.redirect_url == "https://accounts.google.com/auth"

    async def test_connect_unsupported_provider_returns_error(self):
        result = await connect_self_integration(
            user_id=USER_ID,
            user_email="test@example.com",
            integration_id="microsoft",
            integration_name="Microsoft",
            provider="microsoft",
            redirect_path="/integrations",
        )

        assert result.status == "error"
        assert "not implemented" in result.error.lower()


@pytest.mark.unit
class TestDisconnectIntegration:
    @patch(
        "app.services.integrations.integration_connection_service._invalidate_caches",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.remove_user_integration",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.delete_custom_integration",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_mcp_client",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    async def test_disconnect_custom_integration_owned(
        self,
        mock_resolve,
        mock_get_client,
        mock_delete_custom,
        mock_remove_user,
        mock_invalidate,
    ):
        mock_resolve.return_value = ResolvedIntegration(
            integration_id=CUSTOM_INTEGRATION_ID,
            name="My MCP",
            description="",
            category="custom",
            managed_by="mcp",
            source="custom",
            requires_auth=False,
            auth_type=None,
            mcp_config=None,
            platform_integration=None,
            custom_doc={"created_by": USER_ID},
        )
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await disconnect_integration(USER_ID, CUSTOM_INTEGRATION_ID)

        assert isinstance(result, IntegrationSuccessResponse)
        mock_client.disconnect.assert_awaited_once()
        mock_remove_user.assert_awaited_once()
        mock_delete_custom.assert_awaited_once()

    @patch(
        "app.services.integrations.integration_connection_service._invalidate_caches",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.remove_user_integration",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_mcp_client",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    async def test_disconnect_custom_not_owned_skips_delete(
        self, mock_resolve, mock_get_client, mock_remove_user, mock_invalidate
    ):
        mock_resolve.return_value = ResolvedIntegration(
            integration_id=CUSTOM_INTEGRATION_ID,
            name="Not mine",
            description="",
            category="custom",
            managed_by="mcp",
            source="custom",
            requires_auth=False,
            auth_type=None,
            mcp_config=None,
            platform_integration=None,
            custom_doc={"created_by": "other-user"},
        )
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await disconnect_integration(USER_ID, CUSTOM_INTEGRATION_ID)

        assert isinstance(result, IntegrationSuccessResponse)
        mock_client.disconnect.assert_awaited_once()
        mock_remove_user.assert_awaited_once()

    @patch(
        "app.services.integrations.integration_connection_service.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    async def test_disconnect_not_found_raises(self, mock_resolve):
        mock_resolve.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await disconnect_integration(USER_ID, "nonexistent")

    @patch(
        "app.services.integrations.integration_connection_service._invalidate_caches",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_composio_service",
    )
    @patch(
        "app.services.integrations.integration_connection_service.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    async def test_disconnect_composio_integration(
        self, mock_resolve, mock_get_composio, mock_invalidate
    ):
        platform_int = _make_oauth_integration(
            id="slack", managed_by="composio", provider="slack"
        )
        mock_resolve.return_value = ResolvedIntegration(
            integration_id="slack",
            name="Slack",
            description="",
            category="communication",
            managed_by="composio",
            source="platform",
            requires_auth=True,
            auth_type="oauth",
            mcp_config=None,
            platform_integration=platform_int,
            custom_doc=None,
        )
        mock_service = AsyncMock()
        mock_get_composio.return_value = mock_service

        result = await disconnect_integration(USER_ID, "slack")

        assert isinstance(result, IntegrationSuccessResponse)
        mock_service.delete_connected_account.assert_awaited_once_with(
            user_id=USER_ID, provider="slack"
        )

    @patch(
        "app.services.integrations.integration_connection_service._invalidate_caches",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_composio_service",
    )
    @patch(
        "app.services.integrations.integration_connection_service.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    async def test_disconnect_composio_no_provider_raises(
        self, mock_resolve, mock_get_composio, mock_invalidate
    ):
        mock_get_composio.return_value = MagicMock()
        mock_resolve.return_value = ResolvedIntegration(
            integration_id="bad",
            name="Bad",
            description="",
            category="c",
            managed_by="composio",
            source="platform",
            requires_auth=True,
            auth_type="oauth",
            mcp_config=None,
            platform_integration=None,
            custom_doc=None,
        )

        with pytest.raises(ValueError, match="Provider not configured"):
            await disconnect_integration(USER_ID, "bad")

    @patch(
        "app.services.integrations.integration_connection_service._invalidate_caches",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.token_repository",
    )
    @patch(
        "app.services.integrations.integration_connection_service.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    async def test_disconnect_self_managed_integration(
        self, mock_resolve, mock_token_repo, mock_invalidate
    ):
        platform_int = _make_oauth_integration(
            id="gcal", managed_by="self", provider="google"
        )
        mock_resolve.return_value = ResolvedIntegration(
            integration_id="gcal",
            name="Google Calendar",
            description="",
            category="productivity",
            managed_by="self",
            source="platform",
            requires_auth=True,
            auth_type="oauth",
            mcp_config=None,
            platform_integration=platform_int,
            custom_doc=None,
        )
        mock_token_repo.revoke_token = AsyncMock()

        result = await disconnect_integration(USER_ID, "gcal")

        assert isinstance(result, IntegrationSuccessResponse)
        mock_token_repo.revoke_token.assert_awaited_once_with(
            user_id=USER_ID, provider="google"
        )

    @patch(
        "app.services.integrations.integration_connection_service._invalidate_caches",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    async def test_disconnect_self_no_provider_raises(
        self, mock_resolve, mock_invalidate
    ):
        mock_resolve.return_value = ResolvedIntegration(
            integration_id="x",
            name="X",
            description="",
            category="c",
            managed_by="self",
            source="platform",
            requires_auth=True,
            auth_type="oauth",
            mcp_config=None,
            platform_integration=None,
            custom_doc=None,
        )

        with pytest.raises(ValueError, match="Provider not configured"):
            await disconnect_integration(USER_ID, "x")

    @patch(
        "app.services.integrations.integration_connection_service._invalidate_caches",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.remove_user_integration",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_mcp_client",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    async def test_disconnect_platform_mcp_integration(
        self, mock_resolve, mock_get_client, mock_remove_user, mock_invalidate
    ):
        mock_resolve.return_value = ResolvedIntegration(
            integration_id="perplexity",
            name="Perplexity",
            description="",
            category="ai",
            managed_by="mcp",
            source="platform",
            requires_auth=True,
            auth_type="oauth",
            mcp_config=MCPConfig(server_url=SERVER_URL),
            platform_integration=_make_oauth_integration(
                id="perplexity", managed_by="mcp"
            ),
            custom_doc=None,
        )
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        result = await disconnect_integration(USER_ID, "perplexity")

        assert isinstance(result, IntegrationSuccessResponse)
        mock_client.disconnect.assert_awaited_once()
        mock_remove_user.assert_awaited_once()

    @patch(
        "app.services.integrations.integration_connection_service.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    async def test_disconnect_unsupported_managed_by_raises(self, mock_resolve):
        mock_resolve.return_value = ResolvedIntegration(
            integration_id="x",
            name="X",
            description="",
            category="c",
            managed_by="internal",
            source="platform",
            requires_auth=False,
            auth_type=None,
            mcp_config=None,
            platform_integration=None,
            custom_doc=None,
        )

        with pytest.raises(ValueError, match="disconnect not supported"):
            await disconnect_integration(USER_ID, "x")


@pytest.mark.unit
class TestInvalidateCaches:
    @patch(
        "app.services.integrations.integration_connection_service.update_user_integration_status",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.remove_user_integration",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_integration_by_id",
    )
    @patch(
        "app.services.integrations.integration_connection_service.delete_cache",
        new_callable=AsyncMock,
    )
    async def test_invalidate_mcp_skips_extra_work(
        self, mock_delete_cache, mock_get_by_id, mock_remove, mock_update_status
    ):
        from app.services.integrations.integration_connection_service import (
            _invalidate_caches,
        )

        await _invalidate_caches(USER_ID, INTEGRATION_ID, "mcp")

        mock_delete_cache.assert_awaited_once()
        mock_remove.assert_not_awaited()
        mock_update_status.assert_not_awaited()

    @patch(
        "app.services.integrations.integration_connection_service.update_user_integration_status",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.remove_user_integration",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_integration_by_id",
    )
    @patch(
        "app.services.integrations.integration_connection_service.delete_cache",
        new_callable=AsyncMock,
    )
    async def test_invalidate_platform_removes_user_record(
        self, mock_delete_cache, mock_get_by_id, mock_remove, mock_update_status
    ):
        from app.services.integrations.integration_connection_service import (
            _invalidate_caches,
        )

        mock_get_by_id.return_value = _make_oauth_integration(id="gcal")

        await _invalidate_caches(USER_ID, "gcal", "self")

        mock_remove.assert_awaited_once()
        mock_update_status.assert_not_awaited()

    @patch(
        "app.services.integrations.integration_connection_service.update_user_integration_status",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.remove_user_integration",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_integration_by_id",
    )
    @patch(
        "app.services.integrations.integration_connection_service.delete_cache",
        new_callable=AsyncMock,
    )
    async def test_invalidate_custom_non_mcp_sets_status_created(
        self, mock_delete_cache, mock_get_by_id, mock_remove, mock_update_status
    ):
        from app.services.integrations.integration_connection_service import (
            _invalidate_caches,
        )

        mock_get_by_id.return_value = None  # Not a platform integration

        await _invalidate_caches(USER_ID, CUSTOM_INTEGRATION_ID, "composio")

        mock_update_status.assert_awaited_once_with(
            USER_ID, CUSTOM_INTEGRATION_ID, "created"
        )
        mock_remove.assert_not_awaited()

    @patch(
        "app.services.integrations.integration_connection_service.update_user_integration_status",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.remove_user_integration",
        new_callable=AsyncMock,
    )
    @patch(
        "app.services.integrations.integration_connection_service.get_integration_by_id",
    )
    @patch(
        "app.services.integrations.integration_connection_service.delete_cache",
        new_callable=AsyncMock,
    )
    async def test_invalidate_redis_error_non_fatal(
        self, mock_delete_cache, mock_get_by_id, mock_remove, mock_update_status
    ):
        import redis

        from app.services.integrations.integration_connection_service import (
            _invalidate_caches,
        )

        mock_delete_cache.side_effect = redis.RedisError("Connection lost")

        # Should not raise
        await _invalidate_caches(USER_ID, INTEGRATION_ID, "mcp")
