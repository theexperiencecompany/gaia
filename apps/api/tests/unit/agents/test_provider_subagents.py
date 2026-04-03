"""Comprehensive unit tests for provider_subagents (app/agents/core/subagents/provider_subagents.py)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.mcp_config import MCPConfig, SubAgentConfig
from app.models.oauth_models import OAuthIntegration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop_create_task(coro, **kwargs):
    if asyncio.iscoroutine(coro):
        coro.close()
    return MagicMock()


def _make_subagent_config(**overrides) -> SubAgentConfig:
    defaults = {
        "has_subagent": True,
        "agent_name": "test_agent",
        "tool_space": "test_space",
        "handoff_tool_name": "handoff_test",
        "domain": "test",
        "capabilities": "test capabilities",
        "use_cases": "test use cases",
        "system_prompt": "You are a test agent.",
        "use_direct_tools": False,
        "disable_retrieve_tools": False,
    }
    defaults.update(overrides)
    return SubAgentConfig(**defaults)  # type: ignore[arg-type]


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

        composio_config = ComposioConfig(  # type: ignore[assignment]
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
        managed_by=managed_by,  # type: ignore[arg-type]
        mcp_config=mcp_config,
        subagent_config=subagent_config,
        composio_config=composio_config,
    )


# Shared mock patches
_BASE_PATCHES = {
    "app.agents.core.subagents.provider_subagents.init_llm": MagicMock(
        return_value=MagicMock()
    ),
}


# ---------------------------------------------------------------------------
# create_subagent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateSubagent:
    async def test_raises_when_integration_not_found(self):
        from app.agents.core.subagents.provider_subagents import create_subagent

        with patch(
            "app.agents.core.subagents.provider_subagents.get_integration_by_id",
            return_value=None,
        ):
            with pytest.raises(ValueError, match="not found"):
                await create_subagent("nonexistent")

    async def test_raises_when_no_subagent_config(self):
        from app.agents.core.subagents.provider_subagents import create_subagent

        # Build a mock integration that reports subagent_config as None
        mock_integration = MagicMock()
        mock_integration.subagent_config = None

        with patch(
            "app.agents.core.subagents.provider_subagents.get_integration_by_id",
            return_value=mock_integration,
        ):
            with pytest.raises(ValueError, match="not found"):
                await create_subagent("test_int")

    async def test_internal_integration(self):
        from app.agents.core.subagents.provider_subagents import create_subagent

        integration = _make_integration(managed_by="internal")
        mock_graph = MagicMock()
        mock_registry = AsyncMock()

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
            patch(
                "app.agents.core.subagents.provider_subagents.init_llm",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.SubAgentFactory.create_provider_subagent",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
        ):
            result = await create_subagent("test_int")

        assert result is mock_graph

    async def test_mcp_integration_no_auth(self):
        from app.agents.core.subagents.provider_subagents import create_subagent

        mcp_config = MCPConfig(server_url="https://example.com", requires_auth=False)
        integration = _make_integration(
            managed_by="mcp",
            mcp_config=mcp_config,
            composio_config=None,
        )
        mock_graph = MagicMock()
        mock_tools = [MagicMock()]

        mock_registry = AsyncMock()
        mock_registry._categories = {}
        mock_registry._add_category = MagicMock()
        mock_registry._index_category_tools = AsyncMock()

        mock_mcp_client = AsyncMock()
        mock_mcp_client.connect = AsyncMock(return_value=mock_tools)

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
            patch(
                "app.agents.core.subagents.provider_subagents.get_mcp_client",
                new_callable=AsyncMock,
                return_value=mock_mcp_client,
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.init_llm",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.SubAgentFactory.create_provider_subagent",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
        ):
            result = await create_subagent("test_int")

        assert result is mock_graph
        mock_mcp_client.connect.assert_called_once_with("test_int")
        mock_registry._add_category.assert_called_once()

    async def test_mcp_requires_auth_raises(self):
        from app.agents.core.subagents.provider_subagents import create_subagent

        mcp_config = MCPConfig(server_url="https://example.com", requires_auth=True)
        integration = _make_integration(
            managed_by="mcp",
            mcp_config=mcp_config,
            composio_config=None,
        )
        mock_registry = AsyncMock()
        mock_registry._categories = {}

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
            with pytest.raises(ValueError, match="requires authentication"):
                await create_subagent("test_int")

    async def test_mcp_category_already_registered(self):
        from app.agents.core.subagents.provider_subagents import create_subagent

        mcp_config = MCPConfig(server_url="https://example.com", requires_auth=False)
        integration = _make_integration(
            managed_by="mcp",
            mcp_config=mcp_config,
            composio_config=None,
        )
        mock_graph = MagicMock()
        mock_registry = AsyncMock()
        mock_registry._categories = {"test_int": MagicMock()}

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
            patch(
                "app.agents.core.subagents.provider_subagents.init_llm",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.SubAgentFactory.create_provider_subagent",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
        ):
            result = await create_subagent("test_int")

        assert result is mock_graph

    async def test_composio_integration(self):
        from app.agents.core.subagents.provider_subagents import create_subagent

        integration = _make_integration(managed_by="composio")
        mock_graph = MagicMock()
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
            patch(
                "app.agents.core.subagents.provider_subagents.init_llm",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.SubAgentFactory.create_provider_subagent",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
        ):
            result = await create_subagent("test_int")

        assert result is mock_graph
        mock_registry.register_provider_tools.assert_called_once()


# ---------------------------------------------------------------------------
# create_subagent_for_user
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateSubagentForUser:
    async def test_delegates_to_custom_when_integration_not_found(self):
        from app.agents.core.subagents.provider_subagents import (
            create_subagent_for_user,
        )

        mock_graph = MagicMock()

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.get_integration_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.provider_subagents._create_custom_mcp_subagent",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ) as mock_custom,
        ):
            result = await create_subagent_for_user("custom_abc", "user_123")

        mock_custom.assert_called_once_with("custom_abc", "user_123")
        assert result is mock_graph

    async def test_returns_none_when_no_subagent_config(self):
        from app.agents.core.subagents.provider_subagents import (
            create_subagent_for_user,
        )

        mock_integration = MagicMock()
        mock_integration.subagent_config = None

        with patch(
            "app.agents.core.subagents.provider_subagents.get_integration_by_id",
            return_value=mock_integration,
        ):
            result = await create_subagent_for_user("test_int", "user_123")

        assert result is None

    async def test_returns_none_when_not_mcp(self):
        from app.agents.core.subagents.provider_subagents import (
            create_subagent_for_user,
        )

        integration = _make_integration(managed_by="composio")
        with patch(
            "app.agents.core.subagents.provider_subagents.get_integration_by_id",
            return_value=integration,
        ):
            result = await create_subagent_for_user("test_int", "user_123")

        assert result is None

    async def test_mcp_with_cached_tools(self):
        from app.agents.core.subagents.provider_subagents import (
            create_subagent_for_user,
        )

        mcp_config = MCPConfig(server_url="https://example.com", requires_auth=True)
        integration = _make_integration(
            managed_by="mcp",
            mcp_config=mcp_config,
            composio_config=None,
        )
        mock_graph = MagicMock()
        mock_tools = [MagicMock()]

        mock_registry = AsyncMock()
        mock_registry._categories = {}
        mock_registry._add_category = MagicMock()
        mock_registry._index_category_tools = AsyncMock()

        mock_mcp_client = AsyncMock()
        mock_mcp_client._tools = {"test_int": mock_tools}
        mock_mcp_client.get_all_connected_tools = AsyncMock()

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
            patch(
                "app.agents.core.subagents.provider_subagents.get_mcp_client",
                new_callable=AsyncMock,
                return_value=mock_mcp_client,
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.init_llm",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.SubAgentFactory.create_provider_subagent",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch("asyncio.create_task", side_effect=_noop_create_task),
        ):
            result = await create_subagent_for_user("test_int", "user_123")

        assert result is mock_graph
        # Should use cached tools, not call connect
        mock_mcp_client.connect.assert_not_called()

    async def test_mcp_connect_failure_returns_none(self):
        from app.agents.core.subagents.provider_subagents import (
            create_subagent_for_user,
        )

        mcp_config = MCPConfig(server_url="https://example.com", requires_auth=True)
        integration = _make_integration(
            managed_by="mcp",
            mcp_config=mcp_config,
            composio_config=None,
        )

        mock_registry = AsyncMock()
        mock_registry._categories = {}

        mock_mcp_client = AsyncMock()
        mock_mcp_client._tools = {}
        mock_mcp_client.connect = AsyncMock(side_effect=Exception("connection fail"))

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
            patch(
                "app.agents.core.subagents.provider_subagents.get_mcp_client",
                new_callable=AsyncMock,
                return_value=mock_mcp_client,
            ),
        ):
            result = await create_subagent_for_user("test_int", "user_123")

        assert result is None

    async def test_mcp_no_tools_returns_none(self):
        from app.agents.core.subagents.provider_subagents import (
            create_subagent_for_user,
        )

        mcp_config = MCPConfig(server_url="https://example.com", requires_auth=True)
        integration = _make_integration(
            managed_by="mcp",
            mcp_config=mcp_config,
            composio_config=None,
        )

        mock_registry = AsyncMock()
        mock_registry._categories = {}

        mock_mcp_client = AsyncMock()
        mock_mcp_client._tools = {}
        mock_mcp_client.connect = AsyncMock(return_value=[])

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
            patch(
                "app.agents.core.subagents.provider_subagents.get_mcp_client",
                new_callable=AsyncMock,
                return_value=mock_mcp_client,
            ),
        ):
            result = await create_subagent_for_user("test_int", "user_123")

        assert result is None

    async def test_category_already_registered_skips_connect(self):
        from app.agents.core.subagents.provider_subagents import (
            create_subagent_for_user,
        )

        mcp_config = MCPConfig(server_url="https://example.com", requires_auth=True)
        integration = _make_integration(
            managed_by="mcp",
            mcp_config=mcp_config,
            composio_config=None,
        )
        mock_graph = MagicMock()

        mock_registry = AsyncMock()
        mock_registry._categories = {"mcp_test_int_user_123": MagicMock()}

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
            patch(
                "app.agents.core.subagents.provider_subagents.init_llm",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.SubAgentFactory.create_provider_subagent",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
        ):
            result = await create_subagent_for_user("test_int", "user_123")

        assert result is mock_graph


# ---------------------------------------------------------------------------
# _create_custom_mcp_subagent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateCustomMcpSubagent:
    async def test_returns_none_when_not_found_in_mongo(self):
        from app.agents.core.subagents.provider_subagents import (
            _create_custom_mcp_subagent,
        )

        with patch(
            "app.agents.core.subagents.provider_subagents.integrations_collection"
        ) as mock_col:
            mock_col.find_one = AsyncMock(return_value=None)
            result = await _create_custom_mcp_subagent("custom_abc", "user_123")

        assert result is None

    async def test_creates_graph_for_custom_mcp(self):
        from app.agents.core.subagents.provider_subagents import (
            _create_custom_mcp_subagent,
        )

        custom_doc = {
            "integration_id": "custom_abc",
            "mcp_config": {"server_url": "https://custom.example.com"},
        }
        mock_graph = MagicMock()
        mock_tools = [MagicMock() for _ in range(5)]

        mock_registry = AsyncMock()
        mock_registry._categories = {}
        mock_registry._add_category = MagicMock()
        mock_registry._index_category_tools = AsyncMock()

        mock_mcp_client = AsyncMock()
        mock_mcp_client._tools = {}
        mock_mcp_client.connect = AsyncMock(return_value=mock_tools)
        mock_mcp_client.get_all_connected_tools = AsyncMock()

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.integrations_collection"
            ) as mock_col,
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
            patch(
                "app.agents.core.subagents.provider_subagents.init_llm",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.SubAgentFactory.create_provider_subagent",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.derive_integration_namespace",
                return_value="custom.example.com",
            ),
            patch("asyncio.create_task", side_effect=_noop_create_task),
        ):
            mock_col.find_one = AsyncMock(return_value=custom_doc)
            result = await _create_custom_mcp_subagent("custom_abc", "user_123")

        assert result is mock_graph

    async def test_uses_direct_tools_for_small_toolset(self):
        from app.agents.core.subagents.provider_subagents import (
            _create_custom_mcp_subagent,
        )

        custom_doc = {
            "integration_id": "custom_abc",
            "mcp_config": {"server_url": "https://custom.example.com"},
        }
        mock_graph = MagicMock()
        mock_tools = [MagicMock() for _ in range(3)]  # Small = direct tools

        mock_registry = AsyncMock()
        mock_registry._categories = {}
        mock_registry._add_category = MagicMock()
        mock_registry._index_category_tools = AsyncMock()

        mock_mcp_client = AsyncMock()
        mock_mcp_client._tools = {}
        mock_mcp_client.connect = AsyncMock(return_value=mock_tools)
        mock_mcp_client.get_all_connected_tools = AsyncMock()

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.integrations_collection"
            ) as mock_col,
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
            patch(
                "app.agents.core.subagents.provider_subagents.init_llm",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.SubAgentFactory.create_provider_subagent",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ) as mock_factory,
            patch(
                "app.agents.core.subagents.provider_subagents.derive_integration_namespace",
                return_value="custom.example.com",
            ),
            patch("asyncio.create_task", side_effect=_noop_create_task),
        ):
            mock_col.find_one = AsyncMock(return_value=custom_doc)
            await _create_custom_mcp_subagent("custom_abc", "user_123")

        call_kwargs = mock_factory.call_args.kwargs
        assert call_kwargs["use_direct_tools"] is True
        assert call_kwargs["disable_retrieve_tools"] is True

    async def test_uses_retrieve_tools_for_large_toolset(self):
        from app.agents.core.subagents.provider_subagents import (
            _create_custom_mcp_subagent,
        )

        custom_doc = {
            "integration_id": "custom_abc",
            "mcp_config": {"server_url": "https://custom.example.com"},
        }
        mock_graph = MagicMock()
        mock_tools = [MagicMock() for _ in range(15)]  # Large = retrieve tools

        mock_registry = AsyncMock()
        mock_registry._categories = {}
        mock_registry._add_category = MagicMock()
        mock_registry._index_category_tools = AsyncMock()

        mock_mcp_client = AsyncMock()
        mock_mcp_client._tools = {}
        mock_mcp_client.connect = AsyncMock(return_value=mock_tools)
        mock_mcp_client.get_all_connected_tools = AsyncMock()

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.integrations_collection"
            ) as mock_col,
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
            patch(
                "app.agents.core.subagents.provider_subagents.init_llm",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.SubAgentFactory.create_provider_subagent",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ) as mock_factory,
            patch(
                "app.agents.core.subagents.provider_subagents.derive_integration_namespace",
                return_value="custom.example.com",
            ),
            patch("asyncio.create_task", side_effect=_noop_create_task),
        ):
            mock_col.find_one = AsyncMock(return_value=custom_doc)
            await _create_custom_mcp_subagent("custom_abc", "user_123")

        call_kwargs = mock_factory.call_args.kwargs
        assert call_kwargs["use_direct_tools"] is False
        assert call_kwargs["disable_retrieve_tools"] is False

    async def test_connect_failure_returns_none(self):
        from app.agents.core.subagents.provider_subagents import (
            _create_custom_mcp_subagent,
        )

        custom_doc = {
            "integration_id": "custom_abc",
            "mcp_config": {"server_url": "https://custom.example.com"},
        }

        mock_registry = AsyncMock()
        mock_registry._categories = {}

        mock_mcp_client = AsyncMock()
        mock_mcp_client._tools = {}
        mock_mcp_client.connect = AsyncMock(side_effect=Exception("conn fail"))

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.integrations_collection"
            ) as mock_col,
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
            patch(
                "app.agents.core.subagents.provider_subagents.derive_integration_namespace",
                return_value="custom.example.com",
            ),
        ):
            mock_col.find_one = AsyncMock(return_value=custom_doc)
            result = await _create_custom_mcp_subagent("custom_abc", "user_123")

        assert result is None

    async def test_no_tools_returns_none(self):
        from app.agents.core.subagents.provider_subagents import (
            _create_custom_mcp_subagent,
        )

        custom_doc = {
            "integration_id": "custom_abc",
            "mcp_config": {"server_url": "https://custom.example.com"},
        }

        mock_registry = AsyncMock()
        mock_registry._categories = {}

        mock_mcp_client = AsyncMock()
        mock_mcp_client._tools = {}
        mock_mcp_client.connect = AsyncMock(return_value=[])

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.integrations_collection"
            ) as mock_col,
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
            patch(
                "app.agents.core.subagents.provider_subagents.derive_integration_namespace",
                return_value="custom.example.com",
            ),
        ):
            mock_col.find_one = AsyncMock(return_value=custom_doc)
            result = await _create_custom_mcp_subagent("custom_abc", "user_123")

        assert result is None

    async def test_category_already_cached(self):
        from app.agents.core.subagents.provider_subagents import (
            _create_custom_mcp_subagent,
        )

        custom_doc = {
            "integration_id": "custom_abc",
            "mcp_config": {"server_url": "https://custom.example.com"},
        }
        mock_graph = MagicMock()
        cached_cat = MagicMock()
        cached_cat.tools = [MagicMock()]
        cached_cat.space = "cached_space"

        mock_registry = AsyncMock()
        mock_registry._categories = {"mcp_custom_abc_user_123": MagicMock()}
        mock_registry.get_category = MagicMock(return_value=cached_cat)

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.integrations_collection"
            ) as mock_col,
            patch(
                "app.agents.core.subagents.provider_subagents.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.init_llm",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.SubAgentFactory.create_provider_subagent",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.derive_integration_namespace",
                return_value="custom.example.com",
            ),
        ):
            mock_col.find_one = AsyncMock(return_value=custom_doc)
            result = await _create_custom_mcp_subagent("custom_abc", "user_123")

        assert result is mock_graph


# ---------------------------------------------------------------------------
# register_subagent_providers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterSubagentProviders:
    def test_registers_eligible_integrations(self):
        from app.agents.core.subagents.provider_subagents import (
            register_subagent_providers,
        )

        integration = _make_integration(
            managed_by="composio",
            subagent_config=_make_subagent_config(has_subagent=True),
        )

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.OAUTH_INTEGRATIONS",
                [integration],
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.providers"
            ) as mock_providers,
        ):
            count = register_subagent_providers()

        assert count == 1
        mock_providers.register.assert_called_once()

    def test_skips_no_subagent_config(self):
        from app.agents.core.subagents.provider_subagents import (
            register_subagent_providers,
        )

        integration = MagicMock(spec=OAuthIntegration)
        integration.subagent_config = None

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.OAUTH_INTEGRATIONS",
                [integration],
            ),
            patch(
                "app.agents.core.subagents.provider_subagents.providers"
            ) as mock_providers,
        ):
            count = register_subagent_providers()

        assert count == 0
        mock_providers.register.assert_not_called()

    def test_skips_has_subagent_false(self):
        from app.agents.core.subagents.provider_subagents import (
            register_subagent_providers,
        )

        integration = _make_integration(
            subagent_config=_make_subagent_config(has_subagent=False),
        )

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.OAUTH_INTEGRATIONS",
                [integration],
            ),
            patch("app.agents.core.subagents.provider_subagents.providers"),
        ):
            count = register_subagent_providers()

        assert count == 0

    def test_skips_auth_required_mcp(self):
        from app.agents.core.subagents.provider_subagents import (
            register_subagent_providers,
        )

        mcp_config = MCPConfig(server_url="https://example.com", requires_auth=True)
        integration = _make_integration(
            managed_by="mcp",
            mcp_config=mcp_config,
            composio_config=None,
            subagent_config=_make_subagent_config(has_subagent=True),
        )

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.OAUTH_INTEGRATIONS",
                [integration],
            ),
            patch("app.agents.core.subagents.provider_subagents.providers"),
        ):
            count = register_subagent_providers()

        assert count == 0

    def test_filters_by_integration_ids(self):
        from app.agents.core.subagents.provider_subagents import (
            register_subagent_providers,
        )

        int1 = _make_integration(
            integration_id="int1",
            subagent_config=_make_subagent_config(
                has_subagent=True, agent_name="agent_1"
            ),
        )
        int2 = _make_integration(
            integration_id="int2",
            subagent_config=_make_subagent_config(
                has_subagent=True, agent_name="agent_2"
            ),
        )

        with (
            patch(
                "app.agents.core.subagents.provider_subagents.OAUTH_INTEGRATIONS",
                [int1, int2],
            ),
            patch("app.agents.core.subagents.provider_subagents.providers"),
        ):
            count = register_subagent_providers(integration_ids=["int1"])

        assert count == 1
