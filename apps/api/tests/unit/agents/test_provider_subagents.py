"""Comprehensive unit tests for provider_subagents (app/agents/core/subagents/provider_subagents.py)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.core.registry import integration_destructive_tools
from app.models.integration_models import Integration
from app.models.mcp_config import MCPConfig, SubAgentConfig
from app.models.oauth_models import OAuthIntegration
from app.models.subagent_models import Subagent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _integration_doc(integration_id: str, server_url: str) -> Integration:
    return Integration.model_validate(
        {
            "integration_id": integration_id,
            "name": "Custom MCP",
            "description": "",
            "category": "custom",
            "managed_by": "mcp",
            "source": "custom",
            "mcp_config": MCPConfig(server_url=server_url),
        }
    )


def _noop_create_task(coro, **kwargs):
    if asyncio.iscoroutine(coro):
        coro.close()
    return MagicMock()


def _make_subagent_config(**overrides) -> SubAgentConfig:
    defaults = {
        "has_subagent": True,
        "agent_name": "test_agent",
        "tool_space": "test_space",
        "domain": "test",
        "capabilities": "test capabilities",
        "use_cases": "test use cases",
        "system_prompt": "You are a test agent.",
        "use_direct_tools": False,
        "disable_retrieve_tools": False,
    }
    defaults.update(overrides)
    return SubAgentConfig(**defaults)  # type: ignore[arg-type]  # fixture spreads an untyped defaults dict into the model


def _make_integration(
    integration_id: str = "test_int",
    managed_by: str = "composio",
    mcp_config: MCPConfig | None = None,
    subagent_config: SubAgentConfig | None = None,
    composio_config: MagicMock | None = None,
    provider: str = "test_provider",
) -> OAuthIntegration:
    if subagent_config is None:
        subagent_config = _make_subagent_config()
    if composio_config is None and managed_by == "composio":
        from app.models.mcp_config import ComposioConfig

        composio_config = ComposioConfig(  # type: ignore[assignment]  # real ComposioConfig replaces the mock in this test
            auth_config_id="test_auth",
            toolkit="test_toolkit",
        )

    return OAuthIntegration(
        id=integration_id,
        name="Test Integration",
        description="Test",
        category="test",
        provider=provider,
        scopes=[],
        managed_by=managed_by,  # type: ignore[arg-type]  # fixture uses a plain string for the managed_by Literal
        mcp_config=mcp_config,
        subagent_config=subagent_config,
        composio_config=composio_config,
    )


def _make_subagent(
    integration_id: str = "test_int",
    managed_by: str = "composio",
    mcp_config: MCPConfig | None = None,
    provider: str = "test_provider",
    subagent_config: SubAgentConfig | None = None,
    available: bool = True,
) -> Subagent:
    """Build a real Subagent, as register_integration_tools receives it."""
    if subagent_config is None:
        subagent_config = _make_subagent_config()
    return Subagent(
        id=integration_id,
        name="Test Integration",
        provider=provider,
        managed_by=managed_by,  # type: ignore[arg-type]  # fixture uses a plain string for the managed_by Literal
        config=subagent_config,
        mcp_config=mcp_config,
        available=available,
    )


# Shared mock patches
_BASE_PATCHES = {
    "app.agents.core.subagents.provider_subagents.init_llm": MagicMock(return_value=MagicMock()),
}


# ---------------------------------------------------------------------------
# register_integration_tools: what lands in the registry
# ---------------------------------------------------------------------------


class TestRegisterIntegrationToolsEffects:
    async def test_internal_integration_touches_no_provider_tools(self):
        # Internal integrations run on tools registered at startup: the branch must
        # neither register Composio provider tools nor open an MCP session.
        from app.agents.core.subagents.provider_subagents import register_integration_tools

        subagent = _make_subagent(managed_by="internal")
        mock_registry = AsyncMock()

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.get_mcp_client",
                new_callable=AsyncMock,
            ) as mock_get_mcp_client,
        ):
            await register_integration_tools(subagent)

        mock_registry.register_provider_tools.assert_not_called()
        mock_get_mcp_client.assert_not_called()

    async def test_mcp_integration_no_auth(self):
        from app.agents.core.subagents.provider_subagents import register_integration_tools

        mcp_config = MCPConfig(server_url="https://example.com", requires_auth=False)
        subagent = _make_subagent(
            managed_by="mcp",
            mcp_config=mcp_config,
        )
        mock_tools = [MagicMock()]

        mock_registry = AsyncMock()
        mock_registry._categories = {}
        mock_registry._add_category = MagicMock()
        mock_registry._index_category_tools = AsyncMock()

        mock_mcp_client = AsyncMock()
        mock_mcp_client.connect = AsyncMock(return_value=mock_tools)

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.get_mcp_client",
                new_callable=AsyncMock,
                return_value=mock_mcp_client,
            ),
        ):
            await register_integration_tools(subagent)

        mock_mcp_client.connect.assert_called_once_with("test_int")
        mock_registry._add_category.assert_called_once()

    async def test_mcp_category_carries_the_space_owner_and_risk_set(self):
        """Default space hides the toolkit; missing integration_name drops the filter; None risk set sends destructive tools to the HIL classifier."""
        from app.agents.core.subagents.provider_subagents import register_integration_tools

        subagent = _make_subagent(
            integration_id="gmail",
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=False),
            subagent_config=_make_subagent_config(tool_space="mail_space"),
        )
        mock_registry = AsyncMock()
        mock_registry._categories = {}
        mock_registry._add_category = MagicMock()
        mock_registry._index_category_tools = AsyncMock()

        mock_mcp_client = AsyncMock()
        mock_mcp_client.connect = AsyncMock(return_value=[MagicMock()])

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.get_mcp_client",
                new_callable=AsyncMock,
                return_value=mock_mcp_client,
            ),
        ):
            await register_integration_tools(subagent)

        kwargs = mock_registry._add_category.call_args.kwargs
        assert kwargs["options"].space == "mail_space"
        assert kwargs["options"].integration_name == "gmail"
        curated = integration_destructive_tools("gmail")
        assert curated, "the fixture integration must have a curated risk set to pin"
        assert kwargs["risk"].destructive_tools == curated

    async def test_composio_integration(self):
        from app.agents.core.subagents.provider_subagents import register_integration_tools

        # Composio branch still looks up the OAuthIntegration to read
        # composio_config — Subagent intentionally does not carry it.
        integration = _make_integration(managed_by="composio")
        subagent = _make_subagent(
            managed_by="composio",
            subagent_config=_make_subagent_config(
                specific_tools=["TEST_TOOL_INCLUDED"],
                exclude_tools=["TEST_TOOL_EXCLUDED"],
            ),
        )
        mock_registry = AsyncMock()
        mock_registry.register_provider_tools = AsyncMock()

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.get_integration_by_id",
                return_value=integration,
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
        ):
            await register_integration_tools(subagent)

        # toolkit_name comes from the OAuthIntegration's composio_config while the
        # space/tool filters come from the Subagent's own config — a swap between
        # the two sources is exactly what this asserts against.
        mock_registry.register_provider_tools.assert_called_once_with(
            toolkit_name="test_toolkit",
            space_name="test_space",
            specific_tools=["TEST_TOOL_INCLUDED"],
            exclude_tools=["TEST_TOOL_EXCLUDED"],
        )

    async def test_composio_without_oauth_integration_raises(self):
        # A builtin Subagent declaring managed_by="composio" but with no
        # matching OAuthIntegration must fail loudly instead of silently
        # producing a tool-less agent.
        from app.agents.core.subagents.provider_subagents import register_integration_tools

        subagent = _make_subagent(managed_by="composio")
        mock_registry = AsyncMock()

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.get_integration_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
        ):
            with pytest.raises(ValueError, match="no matching OAuth integration"):
                await register_integration_tools(subagent)


# ---------------------------------------------------------------------------
# register_integration_tools
# ---------------------------------------------------------------------------


class TestRegisterIntegrationTools:
    """The returned category is how activate_integration finds the tools it just loaded — a wrong or missing name leaves the executor believing an integration has no tools, so it is asserted here rather than inferred from a side effect."""

    async def test_composio_returns_the_toolkit_category(self):
        from app.agents.core.subagents.provider_subagents import register_integration_tools
        from app.models.mcp_config import ComposioConfig

        subagent = _make_subagent(integration_id="gmail", managed_by="composio")
        integration = _make_integration(
            "gmail",
            managed_by="composio",
            composio_config=ComposioConfig(auth_config_id="a", toolkit="GMAIL"),
        )

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.get_tool_registry",
                new_callable=AsyncMock,
                return_value=AsyncMock(),
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.get_integration_by_id",
                return_value=integration,
            ),
        ):
            assert await register_integration_tools(subagent) == "GMAIL"

    async def test_mcp_returns_the_integration_id_category(self):
        from app.agents.core.subagents.provider_subagents import register_integration_tools

        subagent = _make_subagent(
            integration_id="deepwiki",
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=False),
        )
        registry = AsyncMock()
        registry._categories = {"deepwiki": MagicMock()}

        with patch(
            "app.agents.core.subagents.provider_subagents.get_tool_registry",
            new_callable=AsyncMock,
            return_value=registry,
        ):
            assert await register_integration_tools(subagent) == "deepwiki"

    async def test_internal_has_no_category_of_its_own(self):
        from app.agents.core.subagents.provider_subagents import register_integration_tools

        subagent = _make_subagent(integration_id="todos", managed_by="internal")

        with patch(
            "app.agents.core.subagents.provider_subagents.get_tool_registry",
            new_callable=AsyncMock,
            return_value=AsyncMock(),
        ):
            assert await register_integration_tools(subagent) is None

    async def test_mcp_without_a_server_config_has_no_category(self):
        from app.agents.core.subagents.provider_subagents import register_integration_tools

        subagent = _make_subagent(integration_id="deepwiki", managed_by="mcp", mcp_config=None)

        with patch(
            "app.agents.core.subagents.provider_subagents.get_tool_registry",
            new_callable=AsyncMock,
            return_value=AsyncMock(),
        ):
            assert await register_integration_tools(subagent) is None

    async def test_auth_required_mcp_refuses_to_register(self):
        """Its tools are per-user and never enter the process-global registry; registering them there would expose one user's session to every other."""
        from app.agents.core.subagents.provider_subagents import register_integration_tools

        subagent = _make_subagent(
            integration_id="perplexity",
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=True),
        )

        with patch(
            "app.agents.core.subagents.provider_subagents.get_tool_registry",
            new_callable=AsyncMock,
            return_value=AsyncMock(),
        ):
            with pytest.raises(ValueError, match="requires authentication"):
                await register_integration_tools(subagent)
