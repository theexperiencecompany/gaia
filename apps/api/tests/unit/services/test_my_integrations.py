"""Unit tests for my_integrations (the user's personalized integration catalog).

The merge of platform config + connection status + custom integrations is
the unit under test; `get_integration_tools` authorization is tested too.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.integration_models import (
    IntegrationResponse,
    IntegrationTool,
    UserIntegrationResponse,
    UserIntegrationsListResponse,
)
from app.schemas.integrations.responses import (
    IntegrationConfigItem,
    IntegrationsConfigResponse,
    MyIntegrationsResponse,
)
from app.services.integrations.my_integrations import get_integration_tools, get_my_integrations
from app.utils.errors import AppError

_MOD = "app.services.integrations.my_integrations"
USER_ID = "507f1f77bcf86cd799439011"


def _config_item(**overrides: object) -> IntegrationConfigItem:
    data: dict[str, object] = {
        "id": "github",
        "name": "GitHub",
        "description": "Code hosting",
        "category": "developer",
        "provider": "composio",
        "available": True,
        "is_special": False,
        "display_priority": 1,
        "included_integrations": [],
        "is_featured": True,
        "managed_by": "composio",
        "auth_type": "oauth",
        "requires_auth": True,
        "source": "platform",
        "slug": "github",
    }
    data.update(overrides)
    return IntegrationConfigItem(**data)


def _integration_response(**overrides: object) -> IntegrationResponse:
    data: dict[str, object] = {
        "integration_id": "custom-tool",
        "name": "Custom Tool",
        "description": "My MCP server",
        "category": "custom",
        "managed_by": "mcp",
        "source": "custom",
        "is_featured": False,
        "display_priority": 0,
        "tools": [IntegrationTool(name="do")],
        "is_public": True,
        "created_by": USER_ID,
    }
    data.update(overrides)
    return IntegrationResponse(**data)


def _user_integration(**overrides: object) -> UserIntegrationResponse:
    data: dict[str, object] = {
        "integration_id": "custom-tool",
        "status": "connected",
        "created_at": datetime.now(UTC),
        "integration": _integration_response(),
    }
    data.update(overrides)
    return UserIntegrationResponse(**data)


@pytest.fixture
def mock_redis_cache():
    """Bypass the @Cacheable layer so the wrapped function body runs."""
    with (
        patch("app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=None),
        patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
    ):
        yield


@pytest.fixture
def mock_deps():
    with (
        patch(f"{_MOD}.build_integrations_config") as m_config,
        patch(f"{_MOD}.get_all_integrations_status", new_callable=AsyncMock) as m_status,
        patch(f"{_MOD}.get_user_integrations", new_callable=AsyncMock) as m_user,
        patch(f"{_MOD}.get_tool_categories", new_callable=AsyncMock) as m_categories,
        patch(f"{_MOD}.IntegrationResolver.resolve", new_callable=AsyncMock) as m_resolve,
        patch(f"{_MOD}.check_user_has_integration", new_callable=AsyncMock) as m_has,
        patch(f"{_MOD}.get_integration_tool_list", new_callable=AsyncMock) as m_tools,
    ):
        m_config.return_value = IntegrationsConfigResponse(integrations=[_config_item()])
        m_status.return_value = {}
        m_user.return_value = UserIntegrationsListResponse(integrations=[])
        m_categories.return_value = {"Developer": 4}
        m_tools.return_value = []
        yield SimpleNamespace(
            config=m_config,
            status=m_status,
            user=m_user,
            categories=m_categories,
            resolve=m_resolve,
            has=m_has,
            tools=m_tools,
        )


class TestGetMyIntegrations:
    async def test_platform_integration_with_registry_tool_count(self, mock_deps, mock_redis_cache):
        """The registry tool-count fallback keys on the lowercased integration
        id — a matching registry entry is used when the user has no record."""
        mock_deps.categories.return_value = {"Github": 4}

        result = await get_my_integrations(USER_ID)

        assert isinstance(result, MyIntegrationsResponse)
        assert result.total == 1
        item = result.integrations[0]
        assert item.id == "github"
        assert item.source == "platform"
        assert item.status == "not_connected"
        assert item.tool_count == 4

    async def test_platform_integration_without_registry_match_has_zero_tools(
        self, mock_deps, mock_redis_cache
    ):
        mock_deps.categories.return_value = {"Developer": 4}

        result = await get_my_integrations(USER_ID)

        assert result.integrations[0].tool_count == 0

    async def test_platform_status_from_connection_map(self, mock_deps, mock_redis_cache):
        mock_deps.status.return_value = {"github": True}

        result = await get_my_integrations(USER_ID)

        assert result.integrations[0].status == "connected"

    async def test_user_integration_status_and_tool_count_win(self, mock_deps, mock_redis_cache):
        mock_deps.user.return_value = UserIntegrationsListResponse(
            integrations=[
                _user_integration(
                    integration_id="github",
                    status="created",
                    integration=_integration_response(
                        integration_id="github",
                        name="GitHub",
                        source="platform",
                        tools=[IntegrationTool(name="a"), IntegrationTool(name="b")],
                    ),
                )
            ]
        )

        result = await get_my_integrations(USER_ID)

        item = result.integrations[0]
        assert item.status == "created"
        assert item.tool_count == 2

    async def test_expired_platform_integration_carries_expired_at(
        self, mock_deps, mock_redis_cache
    ):
        """The UI renders "Disconnected <n> ago" from this — dropping it collapses
        a connection that broke into one that was never set up."""
        died = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
        mock_deps.user.return_value = UserIntegrationsListResponse(
            integrations=[
                _user_integration(
                    integration_id="github",
                    status="expired",
                    expired_at=died,
                    integration=_integration_response(
                        integration_id="github", name="GitHub", source="platform"
                    ),
                )
            ]
        )

        result = await get_my_integrations(USER_ID)

        item = result.integrations[0]
        assert item.status == "expired"
        assert item.expired_at == died

    async def test_platform_integration_without_user_record_has_no_expired_at(
        self, mock_deps, mock_redis_cache
    ):
        result = await get_my_integrations(USER_ID)

        assert result.integrations[0].expired_at is None

    async def test_expired_custom_integration_carries_expired_at(self, mock_deps, mock_redis_cache):
        died = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
        mock_deps.user.return_value = UserIntegrationsListResponse(
            integrations=[_user_integration(status="expired", expired_at=died)]
        )

        result = await get_my_integrations(USER_ID)

        custom = next(i for i in result.integrations if i.id == "custom-tool")
        assert custom.expired_at == died

    async def test_custom_integration_appended(self, mock_deps, mock_redis_cache):
        mock_deps.user.return_value = UserIntegrationsListResponse(
            integrations=[_user_integration()]
        )

        result = await get_my_integrations(USER_ID)

        assert result.total == 2
        custom = next(i for i in result.integrations if i.id == "custom-tool")
        assert custom.source == "custom"
        assert custom.status == "connected"
        assert custom.tool_count == 1
        assert custom.is_public is True
        assert custom.created_by == USER_ID

    async def test_platform_integration_not_duplicated_as_custom(self, mock_deps, mock_redis_cache):
        mock_deps.user.return_value = UserIntegrationsListResponse(
            integrations=[
                _user_integration(
                    integration_id="GITHUB",
                    integration=_integration_response(integration_id="GITHUB", source="platform"),
                )
            ]
        )

        result = await get_my_integrations(USER_ID)

        assert result.total == 1
        assert all(i.id == "github" for i in result.integrations)

    async def test_empty_catalog_still_lists_user_integrations(self, mock_deps, mock_redis_cache):
        mock_deps.config.return_value = IntegrationsConfigResponse(integrations=[])
        mock_deps.user.return_value = UserIntegrationsListResponse(
            integrations=[_user_integration()]
        )

        result = await get_my_integrations(USER_ID)

        assert result.total == 1
        assert result.integrations[0].source == "custom"


class TestGetIntegrationTools:
    async def test_platform_integration_always_readable(self, mock_deps):
        mock_deps.resolve.return_value = SimpleNamespace(source="platform", custom_doc=None)
        mock_deps.tools.return_value = [{"name": "a"}, {"name": "b"}]

        response = await get_integration_tools("github", USER_ID)

        assert response.integration_id == "github"
        assert response.count == 2
        assert [t.name for t in response.tools] == ["a", "b"]

    async def test_public_custom_integration_readable(self, mock_deps):
        mock_deps.resolve.return_value = SimpleNamespace(
            source="custom", custom_doc={"is_public": True, "created_by": "other"}
        )

        await get_integration_tools("custom-tool", USER_ID)

        assert mock_deps.tools.await_args.args[0] == "custom-tool"
        mock_deps.has.assert_not_awaited()

    async def test_own_custom_integration_readable(self, mock_deps):
        mock_deps.resolve.return_value = SimpleNamespace(
            source="custom", custom_doc={"is_public": False, "created_by": USER_ID}
        )

        await get_integration_tools("custom-tool", USER_ID)

        mock_deps.has.assert_not_awaited()

    async def test_private_custom_in_workspace_readable(self, mock_deps):
        mock_deps.resolve.return_value = SimpleNamespace(
            source="custom", custom_doc={"is_public": False, "created_by": "other"}
        )
        mock_deps.has.return_value = True

        await get_integration_tools("custom-tool", USER_ID)

        mock_deps.has.assert_awaited_once_with(USER_ID, "custom-tool")

    async def test_private_custom_forbidden(self, mock_deps):
        mock_deps.resolve.return_value = SimpleNamespace(
            source="custom", custom_doc={"is_public": False, "created_by": "other"}
        )
        mock_deps.has.return_value = False

        with pytest.raises(AppError) as exc_info:
            await get_integration_tools("custom-tool", USER_ID)

        assert exc_info.value.status_code == 403
        mock_deps.tools.assert_not_awaited()

    async def test_unresolved_returns_empty_response(self, mock_deps):
        mock_deps.resolve.return_value = None

        response = await get_integration_tools("ghost", USER_ID)

        assert response.integration_id == "ghost"
        assert response.tools == []
        assert response.count == 0
