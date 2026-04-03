"""Tests for app.agents.core.subagents.handoff_tools."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.subagents.handoff_tools import (
    _get_subagent_by_id,
    _resolve_subagent,
    check_integration_connection,
    index_custom_mcp_as_subagent,
)


# ---------------------------------------------------------------------------
# check_integration_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckIntegrationConnection:
    async def test_returns_none_when_integration_not_found(self):
        with patch(
            "app.agents.core.subagents.handoff_tools.get_integration_by_id",
            return_value=None,
        ):
            result = await check_integration_connection("bogus", "user1")
        assert result is None

    async def test_returns_none_when_connected(self):
        integ = SimpleNamespace(name="Gmail", id="gmail")
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_integration_by_id",
                return_value=integ,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_status",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await check_integration_connection("gmail", "user1")
        assert result is None

    async def test_returns_error_when_not_connected(self):
        integ = SimpleNamespace(name="Gmail", id="gmail")
        mock_writer = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_integration_by_id",
                return_value=integ,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_status",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=mock_writer,
            ),
        ):
            result = await check_integration_connection("gmail", "user1")

        assert result is not None
        assert "not connected" in result
        assert mock_writer.call_count == 2  # progress + connection_required

    async def test_returns_none_on_exception(self):
        with patch(
            "app.agents.core.subagents.handoff_tools.get_integration_by_id",
            side_effect=RuntimeError("boom"),
        ):
            result = await check_integration_connection("bad", "user1")
        assert result is None


# ---------------------------------------------------------------------------
# _get_subagent_by_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetSubagentById:
    async def test_finds_platform_integration_by_id(self):
        cfg = SimpleNamespace(has_subagent=True)
        integ = SimpleNamespace(
            id="gmail",
            short_name="gmail",
            subagent_config=cfg,
        )
        with patch(
            "app.agents.core.subagents.handoff_tools.OAUTH_INTEGRATIONS",
            [integ],
        ):
            result = await _get_subagent_by_id("gmail")
        assert result is integ

    async def test_finds_platform_integration_by_short_name(self):
        cfg = SimpleNamespace(has_subagent=True)
        integ = SimpleNamespace(
            id="google_calendar",
            short_name="gcal",
            subagent_config=cfg,
        )
        with patch(
            "app.agents.core.subagents.handoff_tools.OAUTH_INTEGRATIONS",
            [integ],
        ):
            result = await _get_subagent_by_id("gcal")
        assert result is integ

    async def test_skips_platform_without_subagent_config(self):
        integ = SimpleNamespace(
            id="slack",
            short_name="slack",
            subagent_config=None,
        )
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.OAUTH_INTEGRATIONS",
                [integ],
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.integrations_collection"
            ) as mock_col,
            patch(
                "app.agents.core.subagents.handoff_tools.IntegrationResolver"
            ) as mock_resolver,
            patch(
                "app.agents.core.subagents.handoff_tools.set_cache",
                new_callable=AsyncMock,
            ),
        ):
            mock_col.find_one = AsyncMock(return_value=None)
            mock_resolver.resolve = AsyncMock(return_value=None)
            result = await _get_subagent_by_id("slack")
        assert result is None

    async def test_returns_cached_custom_integration(self):
        cached = {"id": "abc123", "name": "Custom MCP"}
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.OAUTH_INTEGRATIONS",
                [],
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value=cached,
            ),
        ):
            result = await _get_subagent_by_id("abc123")
        assert result == cached

    async def test_returns_none_for_negative_cache(self):
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.OAUTH_INTEGRATIONS",
                [],
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            result = await _get_subagent_by_id("missing")
        assert result is None

    async def test_finds_custom_from_mongodb(self):
        custom_doc = {
            "integration_id": "abc",
            "name": "My MCP",
            "source": "custom",
            "managed_by": "mcp",
            "mcp_config": {"url": "https://example.com"},
            "icon_url": "https://example.com/icon.png",
        }
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.OAUTH_INTEGRATIONS",
                [],
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.integrations_collection"
            ) as mock_col,
            patch(
                "app.agents.core.subagents.handoff_tools.set_cache",
                new_callable=AsyncMock,
            ),
        ):
            mock_col.find_one = AsyncMock(return_value=custom_doc)
            result = await _get_subagent_by_id("abc")

        assert result["id"] == "abc"
        assert result["name"] == "My MCP"

    async def test_fallback_to_integration_resolver(self):
        resolved_doc = {
            "integration_id": "res_id",
            "name": "Resolved",
            "mcp_config": {},
            "icon_url": None,
        }
        resolved = SimpleNamespace(custom_doc=resolved_doc, source="user_integrations")
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.OAUTH_INTEGRATIONS",
                [],
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.integrations_collection"
            ) as mock_col,
            patch(
                "app.agents.core.subagents.handoff_tools.IntegrationResolver"
            ) as mock_resolver,
            patch(
                "app.agents.core.subagents.handoff_tools.set_cache",
                new_callable=AsyncMock,
            ),
        ):
            mock_col.find_one = AsyncMock(return_value=None)
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            result = await _get_subagent_by_id("res_id")

        assert result["id"] == "res_id"
        assert result["source"] == "user_integrations"


# ---------------------------------------------------------------------------
# index_custom_mcp_as_subagent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIndexCustomMcpAsSubagent:
    async def test_indexes_mcp(self):
        mock_store = AsyncMock()
        with patch(
            "app.agents.core.subagents.handoff_tools.derive_integration_namespace",
            return_value="example.com",
        ):
            await index_custom_mcp_as_subagent(
                store=mock_store,
                integration_id="abc123",
                name="My Tool",
                description="Does stuff",
                server_url="https://example.com/mcp",
            )
        mock_store.abatch.assert_awaited_once()
        put_op = mock_store.abatch.call_args[0][0][0]
        assert put_op.key == "abc123"
        assert put_op.value["name"] == "My Tool"
        assert put_op.value["tool_namespace"] == "example.com"


# ---------------------------------------------------------------------------
# _resolve_subagent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResolveSubagent:
    async def test_returns_error_when_not_found(self):
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_integrations",
                return_value=[SimpleNamespace(id="gmail"), SimpleNamespace(id="slack")],
            ),
        ):
            graph, name, error, is_custom = await _resolve_subagent("unknown", "user1")
        assert graph is None
        assert "not found" in error

    async def test_resolves_custom_mcp(self):
        custom_dict = {"id": "abc", "name": "Custom"}
        mock_graph = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=custom_dict,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
        ):
            graph, name, int_id, is_custom = await _resolve_subagent("abc", "user1")
        assert graph is mock_graph
        assert is_custom is True
        assert int_id == "abc"

    async def test_custom_mcp_no_user_id(self):
        custom_dict = {"id": "abc", "name": "Custom"}
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=custom_dict,
        ):
            graph, name, error, is_custom = await _resolve_subagent("abc", None)
        assert graph is None
        assert "authentication" in error.lower()

    async def test_custom_mcp_no_id_field(self):
        custom_dict = {"id": "", "name": "Broken"}
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=custom_dict,
        ):
            graph, name, error, is_custom = await _resolve_subagent("broken", "user1")
        assert graph is None
        assert "no ID" in error

    async def test_custom_mcp_graph_creation_fails(self):
        custom_dict = {"id": "abc", "name": "Custom"}
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=custom_dict,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            graph, name, error, is_custom = await _resolve_subagent("abc", "user1")
        assert graph is None
        assert "Failed to create" in error

    async def test_platform_integration_no_subagent_config(self):
        integ = SimpleNamespace(subagent_config=None)
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=integ,
        ):
            graph, name, error, is_custom = await _resolve_subagent("integ", "user1")
        assert graph is None
        assert "not configured" in error

    async def test_platform_mcp_requires_auth_connected(self):
        cfg = SimpleNamespace(agent_name="gmail_agent", has_subagent=True)
        mcp_cfg = SimpleNamespace(requires_auth=True)
        integ = SimpleNamespace(
            id="gmail",
            name="Gmail",
            subagent_config=cfg,
            managed_by="mcp",
            mcp_config=mcp_cfg,
        )
        mock_graph = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=integ,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.MCPTokenStore"
            ) as mock_ts_cls,
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
        ):
            mock_ts = AsyncMock()
            mock_ts.is_connected.return_value = True
            mock_ts_cls.return_value = mock_ts
            graph, name, int_id, is_custom = await _resolve_subagent(
                "subagent:gmail", "user1"
            )
        assert graph is mock_graph
        assert is_custom is False

    async def test_platform_mcp_requires_auth_not_connected(self):
        cfg = SimpleNamespace(agent_name="gmail_agent", has_subagent=True)
        mcp_cfg = SimpleNamespace(requires_auth=True)
        integ = SimpleNamespace(
            id="gmail",
            name="Gmail",
            subagent_config=cfg,
            managed_by="mcp",
            mcp_config=mcp_cfg,
        )
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=integ,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.MCPTokenStore"
            ) as mock_ts_cls,
        ):
            mock_ts = AsyncMock()
            mock_ts.is_connected.return_value = False
            mock_ts_cls.return_value = mock_ts
            graph, name, error, is_custom = await _resolve_subagent("gmail", "user1")
        assert graph is None
        assert "OAuth" in error

    async def test_platform_mcp_requires_auth_no_user(self):
        cfg = SimpleNamespace(agent_name="gmail_agent", has_subagent=True)
        mcp_cfg = SimpleNamespace(requires_auth=True)
        integ = SimpleNamespace(
            id="gmail",
            name="Gmail",
            subagent_config=cfg,
            managed_by="mcp",
            mcp_config=mcp_cfg,
        )
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=integ,
        ):
            graph, name, error, is_custom = await _resolve_subagent("gmail", None)
        assert graph is None
        assert "authentication" in error.lower()

    async def test_platform_non_mcp_uses_provider(self):
        cfg = SimpleNamespace(agent_name="calendar_agent", has_subagent=True)
        integ = SimpleNamespace(
            id="gcal",
            name="Google Calendar",
            subagent_config=cfg,
            managed_by="internal",
            mcp_config=None,
        )
        mock_graph = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=integ,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.providers"
            ) as mock_providers,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_graph)
            graph, name, int_id, is_custom = await _resolve_subagent("gcal", "user1")
        assert graph is mock_graph
        assert name == "calendar_agent"

    async def test_platform_composio_checks_connection(self):
        cfg = SimpleNamespace(agent_name="composio_agent", has_subagent=True)
        integ = SimpleNamespace(
            id="composio",
            name="Composio",
            subagent_config=cfg,
            managed_by="composio",
            mcp_config=None,
        )
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=integ,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_connection",
                new_callable=AsyncMock,
                return_value="Not connected",
            ),
        ):
            graph, name, error, is_custom = await _resolve_subagent("composio", "user1")
        assert graph is None
        assert error == "Not connected"

    async def test_platform_provider_not_available(self):
        cfg = SimpleNamespace(agent_name="missing_agent", has_subagent=True)
        integ = SimpleNamespace(
            id="x",
            name="X",
            subagent_config=cfg,
            managed_by="internal",
            mcp_config=None,
        )
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=integ,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.providers"
            ) as mock_providers,
        ):
            mock_providers.aget = AsyncMock(return_value=None)
            graph, name, error, is_custom = await _resolve_subagent("x", "user1")
        assert graph is None
        assert "not available" in error

    async def test_platform_mcp_graph_creation_fails(self):
        cfg = SimpleNamespace(agent_name="mcp_agent", has_subagent=True)
        mcp_cfg = SimpleNamespace(requires_auth=True)
        integ = SimpleNamespace(
            id="mcp_int",
            name="MCP Int",
            subagent_config=cfg,
            managed_by="mcp",
            mcp_config=mcp_cfg,
        )
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=integ,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.MCPTokenStore"
            ) as mock_ts_cls,
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            mock_ts = AsyncMock()
            mock_ts.is_connected.return_value = True
            mock_ts_cls.return_value = mock_ts
            graph, name, error, is_custom = await _resolve_subagent("mcp_int", "user1")
        assert graph is None
        assert "Failed to create" in error
