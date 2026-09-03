"""Unit tests for my_integrations (the user's personalized integration catalog).

The merge of platform config + connection status + custom integrations is
the unit under test; `get_integration_tools` authorization is tested too.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.config.oauth_config import get_integration_by_id
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
from tests.helpers import captured_wide_event

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

    async def test_a_cli_integration_counts_the_capabilities_it_declares(
        self, mock_deps, mock_redis_cache
    ):
        """A CLI integration registers one tool that wraps the whole command, so
        the tool registry can only ever say 1 — and says 0 until the category is
        lazily registered. Neither answers "what can this do", which is what the
        card shows; the catalog's declared capabilities do."""
        catalog_entry = get_integration_by_id("stripe_link")
        assert catalog_entry is not None
        assert catalog_entry.cli_config is not None
        assert catalog_entry.cli_config.capabilities, "the fixture needs a CLI with capabilities"

        mock_deps.config.return_value = IntegrationsConfigResponse(
            integrations=[_config_item(id="stripe_link", name="Stripe Link", managed_by="cli")]
        )
        mock_deps.categories.return_value = {}

        result = await get_my_integrations(USER_ID)

        assert result.integrations[0].tool_count == len(catalog_entry.cli_config.capabilities)

    async def test_a_platform_integration_with_no_cli_config_stays_at_zero(
        self, mock_deps, mock_redis_cache
    ):
        """The capability fallback must not invent a count for the OAuth and
        Composio integrations, which are the overwhelming majority."""
        mock_deps.config.return_value = IntegrationsConfigResponse(
            integrations=[_config_item(id="not-in-the-catalog")]
        )
        mock_deps.categories.return_value = {}

        result = await get_my_integrations(USER_ID)

        assert result.integrations[0].tool_count == 0

    async def test_the_wide_event_attributes_the_catalog_to_its_owner(
        self, mock_deps, mock_redis_cache
    ):
        """This response is entirely per-user, so "the wrong integrations came
        back" is only diagnosable if the event says whose they were."""
        async with captured_wide_event() as event:
            await get_my_integrations(USER_ID)
            user = event["user"]

        assert user == {"id": USER_ID}

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

    async def test_an_empty_stored_tool_list_falls_back_to_the_registry_count(
        self, mock_deps, mock_redis_cache
    ):
        """A user record whose tool list was never populated must not blank the
        card. The registry keys its counts by (often capitalised) category name
        while the catalog keys by id, so the fallback has to match them
        case-insensitively or every such integration silently shows nothing."""
        mock_deps.user.return_value = UserIntegrationsListResponse(
            integrations=[
                _user_integration(
                    integration_id="github",
                    integration=_integration_response(
                        integration_id="github", name="GitHub", source="platform", tools=[]
                    ),
                )
            ]
        )
        mock_deps.categories.return_value = {"Github": 4}

        result = await get_my_integrations(USER_ID)

        assert result.integrations[0].tool_count == 4

    async def test_an_integration_nobody_can_count_reports_no_tools(
        self, mock_deps, mock_redis_cache
    ):
        """Neither the user record nor the registry knows anything. Zero is the
        honest answer; any invented number becomes "1 tool" on a card for an
        integration that exposes none."""
        mock_deps.user.return_value = UserIntegrationsListResponse(
            integrations=[
                _user_integration(
                    integration_id="github",
                    integration=_integration_response(
                        integration_id="github", name="GitHub", source="platform", tools=[]
                    ),
                )
            ]
        )
        mock_deps.categories.return_value = {}

        result = await get_my_integrations(USER_ID)

        assert result.integrations[0].tool_count == 0

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


class TestCliToolCountBeatsTheRegistry:
    """What a CLI integration can do is its capabilities, not its tool count.

    One tool wraps the whole command, so the registry's answer is 1 once the
    category is registered. A user reading "1 tool" on a card that can create
    payments, list balances and pay 402 endpoints has been told something false.
    """

    async def test_capabilities_win_even_when_the_registry_has_counted_the_tool(self):
        from unittest.mock import AsyncMock, patch

        from app.services.integrations import my_integrations as module

        integration = module.get_integration_by_id("stripe_link")
        assert integration is not None and integration.cli_config is not None
        expected = len(integration.cli_config.capabilities)
        assert expected > 1, "fixture needs a CLI integration with several capabilities"

        # build_integrations_config is lru_cached and shared process-wide, so a
        # test that ran earlier can leave a stale catalog behind. Rebuild it.
        module.build_integrations_config.cache_clear()

        with (
            patch.object(module, "get_all_integrations_status", AsyncMock(return_value={})),
            patch.object(
                module,
                "get_user_integrations",
                AsyncMock(return_value=SimpleNamespace(integrations=[])),
            ),
            # The registry has counted the single wrapper tool.
            patch.object(module, "get_tool_categories", AsyncMock(return_value={"stripe_link": 1})),
        ):
            result = await module.get_my_integrations.__wrapped__("user-1")

        items = {i.id: i for i in result.integrations}
        assert "stripe_link" in items, "the CLI integration is missing from the catalog"
        assert items["stripe_link"].tool_count == expected
