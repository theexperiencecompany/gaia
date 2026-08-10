"""Tests for app.agents.core.subagents.handoff_tools."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from langchain_core.tools import Tool
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command
import pytest

from app.agents.core.subagents.handoff_tools import (
    SUBAGENTS_NAMESPACE,
    _build_integration_metadata,
    _extract_service_username,
    _get_subagent_by_id,
    _has_parked_subagent,
    _resolve_display_metadata,
    _resolve_subagent,
    _run_blocking_handoff,
    _sanitize_task_user_reference,
    _subagent_resume_status,
    check_integration_connection,
    handoff,
    index_custom_mcp_as_subagent,
    prepare_subagent_execution,
    resume_parked_subagent,
)
from app.agents.core.subagents.provider_subagents import SubagentUnavailableError
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    SubagentOutcome,
)
from app.constants.cache import SUBAGENT_CACHE_PREFIX, SUBAGENT_CACHE_TTL
from app.constants.hil import HIL_RESUME_CONFIG_KEY
from app.constants.log_tags import LogTag
from app.models.hil_models import HILApprovalStatus
from app.models.integration_models import Integration
from app.models.mcp_config import MCPConfig, SubAgentConfig
from app.models.subagent_models import Subagent
from app.utils.agent_utils import IntegrationMetadata


def _integration(integration_id: str, name: str, **overrides: object) -> Integration:
    data: dict[str, object] = {
        "integration_id": integration_id,
        "name": name,
        "description": "",
        "category": "custom",
        "managed_by": "mcp",
        "source": "custom",
    }
    data.update(overrides)
    return Integration.model_validate(data)


def _make_subagent_config(agent_name: str = "gmail_agent") -> SubAgentConfig:
    return SubAgentConfig(
        has_subagent=True,
        agent_name=agent_name,
        tool_space="gmail_space",
        handoff_tool_name="call_gmail",
        domain="gmail",
        capabilities="email",
        use_cases="emails",
        system_prompt="You are gmail.",
    )


def _make_subagent(
    subagent_id: str = "gmail",
    short_name: str | None = "gmail",
    name: str = "Gmail",
    managed_by: str = "internal",
    mcp_config: MCPConfig | None = None,
    agent_name: str = "gmail_agent",
) -> Subagent:
    """Real Subagent for tests of handoff_tools (post-refactor)."""
    return Subagent(
        id=subagent_id,
        name=name,
        provider=subagent_id,
        managed_by=managed_by,  # type: ignore[arg-type]
        config=_make_subagent_config(agent_name=agent_name),
        short_name=short_name,
        mcp_config=mcp_config,
    )


def _make_ctx(**configurable: object) -> SubagentExecutionContext:
    return SubagentExecutionContext(
        subagent_graph=MagicMock(),
        agent_name="gmail_agent",
        config={},
        configurable=configurable,
        integration_id="gmail",
        initial_state={},
    )


def _cache_key(search_id: str) -> str:
    return f"{SUBAGENT_CACHE_PREFIX}:{search_id}"


# ---------------------------------------------------------------------------
# check_integration_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckIntegrationConnection:
    async def test_returns_none_when_integration_not_found(self):
        with patch(
            "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
            return_value=None,
        ) as mock_lookup, patch(
            "app.agents.core.subagents.handoff_tools.check_integration_status",
            new_callable=AsyncMock,
        ) as mock_status:
            result = await check_integration_connection("bogus", "user1")
        assert result is None
        mock_lookup.assert_called_once_with("bogus")
        mock_status.assert_not_awaited()

    async def test_returns_none_when_connected(self):
        subagent = _make_subagent("gmail")
        mock_writer = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=subagent,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_status",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_status,
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=mock_writer,
            ),
        ):
            result = await check_integration_connection("gmail", "user1")
        assert result is None
        mock_status.assert_awaited_once_with("gmail", "user1")
        mock_writer.assert_not_called()

    async def test_returns_connection_message_when_not_connected(self):
        subagent = _make_subagent("gmail")
        mock_writer = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=subagent,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_status",
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_status,
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_connect_link_url",
                new_callable=AsyncMock,
                return_value="https://connect.example/link",
            ) as mock_link,
            patch(
                "app.agents.core.subagents.handoff_tools.build_integration_connection_message",
                return_value="CONNECTION REQUIRED",
            ) as mock_msg,
        ):
            result = await check_integration_connection("gmail", "user1")

        assert result == "CONNECTION REQUIRED"
        mock_status.assert_awaited_once_with("gmail", "user1")
        mock_link.assert_awaited_once_with("user1", "gmail")
        mock_msg.assert_called_once_with("Gmail", "https://connect.example/link")
        assert mock_writer.call_args_list == [
            call({"progress": "Checking Gmail connection..."}),
            call(
                {
                    "integration_connection_required": {
                        "integration_id": "gmail",
                        "message": (
                            "To use Gmail features, please connect your account first."
                        ),
                    }
                }
            ),
        ]

    async def test_returns_none_on_exception_and_logs_error(self):
        with patch(
            "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
            side_effect=RuntimeError("boom"),
        ), patch("app.agents.core.subagents.handoff_tools.log") as mock_log:
            result = await check_integration_connection("bad", "user1")
        assert result is None
        mock_log.error.assert_called_once_with(
            f"{LogTag.AGENT} Error checking integration status",
            integration_id="bad",
            error_type="RuntimeError",
            error="boom",
        )


# ---------------------------------------------------------------------------
# _get_subagent_by_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetSubagentById:
    async def test_finds_platform_integration_by_id(self):
        subagent = _make_subagent("gmail")
        with patch(
            "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
            return_value=subagent,
        ) as mock_lookup:
            result = await _get_subagent_by_id("gmail")
        assert result is subagent
        mock_lookup.assert_called_once_with("gmail")

    async def test_finds_platform_integration_by_short_name(self):
        subagent = _make_subagent("google_calendar", short_name="gcal")
        # Registry's get_subagent_by_id resolves the short_name lookup itself —
        # the mock returns the same subagent regardless of the input string.
        with patch(
            "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
            return_value=subagent,
        ) as mock_lookup:
            result = await _get_subagent_by_id("gcal")
        assert result is subagent
        mock_lookup.assert_called_once_with("gcal")

    async def test_normalizes_whitespace_and_case_before_lookup(self):
        subagent = _make_subagent("gmail")
        with patch(
            "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
            return_value=subagent,
        ) as mock_lookup:
            result = await _get_subagent_by_id("  GMAIL  ")
        assert result is subagent
        mock_lookup.assert_called_once_with("gmail")

    async def test_returns_cached_custom_integration(self):
        cached = {"id": "abc123", "name": "Custom MCP"}
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value=cached,
            ) as mock_cache,
            patch(
                "app.agents.core.subagents.handoff_tools.integration_repository",
                new=AsyncMock(),
            ) as mock_repo,
            patch(
                "app.agents.core.subagents.handoff_tools.set_cache",
                new_callable=AsyncMock,
            ) as mock_set,
        ):
            result = await _get_subagent_by_id("abc123")
        assert result == cached
        mock_cache.assert_awaited_once_with(_cache_key("abc123"))
        mock_repo.find_by_id_prefix_or_name.assert_not_awaited()
        mock_set.assert_not_awaited()

    async def test_returns_none_for_negative_cache(self):
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value={},
            ) as mock_cache,
            patch(
                "app.agents.core.subagents.handoff_tools.integration_repository",
                new=AsyncMock(),
            ) as mock_repo,
            patch(
                "app.agents.core.subagents.handoff_tools.set_cache",
                new_callable=AsyncMock,
            ) as mock_set,
        ):
            result = await _get_subagent_by_id("missing")
        assert result is None
        mock_cache.assert_awaited_once_with(_cache_key("missing"))
        mock_repo.find_by_id_prefix_or_name.assert_not_awaited()
        mock_set.assert_not_awaited()

    async def test_finds_custom_from_mongodb(self):
        custom = _integration(
            "abc",
            "My MCP",
            mcp_config=MCPConfig(server_url="https://example.com"),
            icon_url="https://example.com/icon.png",
        )
        expected = {
            "id": "abc",
            "name": "My MCP",
            "source": "custom",
            "managed_by": "mcp",
            "mcp_config": {
                "server_url": "https://example.com",
                "requires_auth": False,
                "auth_type": None,
                "transport": None,
                "client_id": None,
                "client_secret": None,
                "client_id_env": None,
                "client_secret_env": None,
                "oauth_scopes": None,
                "oauth_metadata": None,
            },
            "icon_url": "https://example.com/icon.png",
            "subagent_config": None,
        }
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.integration_repository",
                new=AsyncMock(),
            ) as mock_repo,
            patch(
                "app.agents.core.subagents.handoff_tools.IntegrationResolver",
                new=AsyncMock(),
            ) as mock_resolver,
            patch(
                "app.agents.core.subagents.handoff_tools.set_cache",
                new_callable=AsyncMock,
            ) as mock_set,
        ):
            mock_repo.find_by_id_prefix_or_name = AsyncMock(return_value=custom)
            result = await _get_subagent_by_id("abc")

        assert result == expected
        mock_repo.find_by_id_prefix_or_name.assert_awaited_once_with("abc")
        mock_resolver.resolve.assert_not_awaited()
        mock_set.assert_awaited_once_with(_cache_key("abc"), expected, ttl=SUBAGENT_CACHE_TTL)

    async def test_finds_custom_from_mongodb_without_mcp_config(self):
        custom = _integration("abc", "My MCP")
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.integration_repository",
                new=AsyncMock(),
            ) as mock_repo,
            patch(
                "app.agents.core.subagents.handoff_tools.set_cache",
                new_callable=AsyncMock,
            ),
        ):
            mock_repo.find_by_id_prefix_or_name = AsyncMock(return_value=custom)
            result = await _get_subagent_by_id("abc")

        assert result == {
            "id": "abc",
            "name": "My MCP",
            "source": "custom",
            "managed_by": "mcp",
            "mcp_config": None,
            "icon_url": None,
            "subagent_config": None,
        }

    async def test_fallback_to_integration_resolver(self):
        resolved_doc = {
            "integration_id": "res_id",
            "name": "Resolved",
            "mcp_config": {},
            "icon_url": "https://x/icon.png",
        }
        resolved = SimpleNamespace(custom_doc=resolved_doc, source="user_integrations")
        expected = {
            "id": "res_id",
            "name": "Resolved",
            "source": "user_integrations",
            "managed_by": "mcp",
            "mcp_config": {},
            "icon_url": "https://x/icon.png",
            "subagent_config": None,
        }
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.integration_repository",
                new=AsyncMock(),
            ) as mock_repo,
            patch(
                "app.agents.core.subagents.handoff_tools.IntegrationResolver",
                new=AsyncMock(),
            ) as mock_resolver,
            patch(
                "app.agents.core.subagents.handoff_tools.set_cache",
                new_callable=AsyncMock,
            ) as mock_set,
        ):
            mock_repo.find_by_id_prefix_or_name = AsyncMock(return_value=None)
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            result = await _get_subagent_by_id("res_id")

        assert result == expected
        mock_repo.find_by_id_prefix_or_name.assert_awaited_once_with("res_id")
        mock_resolver.resolve.assert_awaited_once_with("res_id")
        mock_set.assert_awaited_once_with(_cache_key("res_id"), expected, ttl=SUBAGENT_CACHE_TTL)

    async def test_resolver_without_custom_doc_caches_negative(self):
        resolved = SimpleNamespace(custom_doc=None, source="user_integrations")
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.integration_repository",
                new=AsyncMock(),
            ) as mock_repo,
            patch(
                "app.agents.core.subagents.handoff_tools.IntegrationResolver",
                new=AsyncMock(),
            ) as mock_resolver,
            patch(
                "app.agents.core.subagents.handoff_tools.set_cache",
                new_callable=AsyncMock,
            ) as mock_set,
        ):
            mock_repo.find_by_id_prefix_or_name = AsyncMock(return_value=None)
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            result = await _get_subagent_by_id("res_id")

        assert result is None
        mock_set.assert_awaited_once_with(
            _cache_key("res_id"), {}, ttl=SUBAGENT_CACHE_TTL
        )

    async def test_skips_platform_without_subagent_config(self):
        # Registry never returns subagents without a config; falls through to
        # cache/MongoDB. Slack is not a registered subagent, so the lookup
        # returns None and we exercise the custom-MCP fallback path.
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.integration_repository",
                new=AsyncMock(),
            ) as mock_repo,
            patch(
                "app.agents.core.subagents.handoff_tools.IntegrationResolver",
                new=AsyncMock(),
            ) as mock_resolver,
            patch(
                "app.agents.core.subagents.handoff_tools.set_cache",
                new_callable=AsyncMock,
            ) as mock_set,
        ):
            mock_repo.find_by_id_prefix_or_name = AsyncMock(return_value=None)
            mock_resolver.resolve = AsyncMock(return_value=None)
            result = await _get_subagent_by_id("slack")

        assert result is None
        mock_repo.find_by_id_prefix_or_name.assert_awaited_once_with("slack")
        mock_resolver.resolve.assert_awaited_once_with("slack")
        mock_set.assert_awaited_once_with(_cache_key("slack"), {}, ttl=SUBAGENT_CACHE_TTL)


# ---------------------------------------------------------------------------
# index_custom_mcp_as_subagent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIndexCustomMcpAsSubagent:
    async def test_indexes_mcp(self):
        mock_store = AsyncMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.derive_integration_namespace",
                return_value="example.com",
            ) as mock_derive,
            patch("app.agents.core.subagents.handoff_tools.log") as mock_log,
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
        assert put_op.namespace == SUBAGENTS_NAMESPACE
        assert put_op.index == ["description"]
        assert put_op.value == {
            "id": "abc123",
            "name": "My Tool",
            "description": "My Tool. Does stuff.",
            "source": "custom",
            "tool_namespace": "example.com",
        }
        mock_derive.assert_called_once_with(
            "abc123", "https://example.com/mcp", is_custom=True
        )
        mock_log.info.assert_called_once_with(
            f"{LogTag.AGENT} Indexed custom MCP as subagent",
            integration_name="My Tool",
            integration_id="abc123",
            tool_count=0,
        )

    async def test_indexes_mcp_without_description(self):
        mock_store = AsyncMock()
        with patch(
            "app.agents.core.subagents.handoff_tools.derive_integration_namespace",
            return_value="example.com",
        ):
            await index_custom_mcp_as_subagent(
                store=mock_store,
                integration_id="abc123",
                name="My Tool",
                description=None,
                server_url="https://example.com/mcp",
            )
        put_op = mock_store.abatch.call_args[0][0][0]
        assert put_op.value["description"] == "My Tool."

    async def test_indexes_mcp_with_tool_summaries(self):
        mock_store = AsyncMock()
        tools = [
            Tool(name="get_meetings", description="Fetch meetings", func=lambda: "x"),
            Tool(name="search", description="Search the web", func=lambda: "x"),
        ]
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.derive_integration_namespace",
                return_value="example.com",
            ),
            patch("app.agents.core.subagents.handoff_tools.log") as mock_log,
        ):
            await index_custom_mcp_as_subagent(
                store=mock_store,
                integration_id="abc123",
                name="My Tool",
                description="Does stuff",
                server_url="https://example.com/mcp",
                tools=tools,
            )
        put_op = mock_store.abatch.call_args[0][0][0]
        assert put_op.value["description"] == (
            "My Tool. Does stuff. Available tools: get_meetings: Fetch meetings; "
            "search: Search the web."
        )
        mock_log.info.assert_called_once_with(
            f"{LogTag.AGENT} Indexed custom MCP as subagent",
            integration_name="My Tool",
            integration_id="abc123",
            tool_count=2,
        )

    async def test_tool_without_description_uses_name_only(self):
        mock_store = AsyncMock()
        tools = [
            Tool(name="bare", description="", func=lambda: "x"),
            Tool(name="also_bare", description="", func=lambda: "x"),
            Tool(name="named", description="Has text", func=lambda: "x"),
        ]
        with patch(
            "app.agents.core.subagents.handoff_tools.derive_integration_namespace",
            return_value="example.com",
        ):
            await index_custom_mcp_as_subagent(
                store=mock_store,
                integration_id="abc123",
                name="My Tool",
                description="Does stuff",
                server_url=None,
                tools=tools,
            )
        put_op = mock_store.abatch.call_args[0][0][0]
        assert put_op.value["description"] == (
            "My Tool. Does stuff. Available tools: bare; also_bare; named: Has text."
        )

    async def test_tool_summary_takes_first_line_and_truncates(self):
        mock_store = AsyncMock()
        tools = [
            Tool(
                name="multi",
                description="First line only\nSecond line dropped",
                func=lambda: "x",
            ),
            Tool(name="long", description="x" * 200, func=lambda: "x"),
        ]
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
                tools=tools,
            )
        put_op = mock_store.abatch.call_args[0][0][0]
        assert put_op.value["description"] == (
            f"My Tool. Does stuff. Available tools: multi: First line only; "
            f"long: {'x' * 120}."
        )

    async def test_empty_tools_list_omits_tool_summaries(self):
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
                tools=[],
            )
        put_op = mock_store.abatch.call_args[0][0][0]
        assert put_op.value["description"] == "My Tool. Does stuff."

    async def test_server_url_none_derives_namespace_without_url(self):
        mock_store = AsyncMock()
        with patch(
            "app.agents.core.subagents.handoff_tools.derive_integration_namespace",
            return_value="example.com",
        ) as mock_derive:
            await index_custom_mcp_as_subagent(
                store=mock_store,
                integration_id="abc123",
                name="My Tool",
                description="Does stuff",
                server_url=None,
            )
        mock_derive.assert_called_once_with("abc123", None, is_custom=True)


# ---------------------------------------------------------------------------
# _resolve_subagent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResolveSubagent:
    async def test_returns_exact_error_when_not_found(self):
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.all_subagents",
                return_value=(
                    _make_subagent("gmail"),
                    _make_subagent("slack"),
                ),
            ),
        ):
            graph, name, error, is_custom = await _resolve_subagent("unknown", "user1")
        assert (graph, name, is_custom) == (None, None, False)
        assert error == (
            "Subagent 'unknown' not found. Use retrieve_tools to find available "
            "subagents. Examples: subagent:gmail, subagent:slack"
        )

    async def test_not_found_uses_raw_id_and_truncates_examples_to_five(self):
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.all_subagents",
                return_value=tuple(
                    _make_subagent(sid) for sid in ("gmail", "slack", "gcal", "todo", "x", "y")
                ),
            ),
        ):
            graph, name, error, is_custom = await _resolve_subagent("subagent:missing", "user1")
        assert (graph, name, is_custom) == (None, None, False)
        assert error == (
            "Subagent 'subagent:missing' not found. Use retrieve_tools to find available "
            "subagents. Examples: subagent:gmail, subagent:slack, subagent:gcal, "
            "subagent:todo, subagent:x..."
        )

    async def test_resolves_custom_mcp(self):
        custom_dict = {"id": "abc", "name": "Custom"}
        mock_graph = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=custom_dict,
            ) as mock_lookup,
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ) as mock_create,
        ):
            graph, name, int_id, is_custom = await _resolve_subagent("abc", "user1")
        assert graph is mock_graph
        assert is_custom is True
        assert int_id == "abc"
        assert name == "custom_mcp_abc"
        mock_lookup.assert_awaited_once_with("abc")
        mock_create.assert_awaited_once_with("abc", "user1")

    async def test_custom_mcp_no_user_id(self):
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
            ) as mock_create,
        ):
            graph, name, error, is_custom = await _resolve_subagent("abc", None)
        assert (graph, name, is_custom) == (None, None, False)
        assert error == "Error: Custom requires authentication. Please sign in first."
        mock_create.assert_not_awaited()

    async def test_custom_mcp_missing_name_falls_back_to_id(self):
        custom_dict = {"id": "abc"}
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=custom_dict,
        ):
            graph, name, error, is_custom = await _resolve_subagent("abc", None)
        assert (graph, name, is_custom) == (None, None, False)
        assert error == "Error: abc requires authentication. Please sign in first."

    async def test_custom_mcp_no_id_field(self):
        custom_dict = {"name": "Broken"}
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=custom_dict,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            graph, name, error, is_custom = await _resolve_subagent("broken", "user1")
        assert (graph, name, is_custom) == (None, None, False)
        assert error == "Error: Custom integration has no ID"
        mock_create.assert_not_awaited()

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
                side_effect=SubagentUnavailableError("connection failed"),
            ),
        ):
            graph, name, error, is_custom = await _resolve_subagent("abc", "user1")
        assert (graph, name, is_custom) == (None, None, False)
        assert error == "Error: Custom is unavailable — connection failed"

    async def test_platform_mcp_requires_auth_connected(self):
        mcp_cfg = MCPConfig(server_url="https://example.com", requires_auth=True)
        subagent = _make_subagent("gmail", "gmail", "Gmail", managed_by="mcp", mcp_config=mcp_cfg)
        mock_graph = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch("app.agents.core.subagents.handoff_tools.MCPTokenStore") as mock_ts_cls,
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ) as mock_create,
        ):
            mock_ts = AsyncMock()
            mock_ts.is_connected.return_value = True
            mock_ts_cls.return_value = mock_ts
            graph, name, int_id, is_custom = await _resolve_subagent("subagent:gmail", "user1")
        assert graph is mock_graph
        assert is_custom is False
        assert name == "gmail_agent"
        assert int_id == "gmail"
        mock_ts_cls.assert_called_once_with(user_id="user1")
        mock_ts.is_connected.assert_awaited_once_with("gmail")
        mock_create.assert_awaited_once_with("gmail", "user1")

    async def test_platform_mcp_requires_auth_not_connected(self):
        mcp_cfg = MCPConfig(server_url="https://example.com", requires_auth=True)
        subagent = _make_subagent("gmail", "gmail", "Gmail", managed_by="mcp", mcp_config=mcp_cfg)
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch("app.agents.core.subagents.handoff_tools.MCPTokenStore") as mock_ts_cls,
            patch(
                "app.agents.core.subagents.handoff_tools.build_connect_link_url",
                new_callable=AsyncMock,
                return_value="https://connect.example/gmail",
            ) as mock_link,
            patch(
                "app.agents.core.subagents.handoff_tools.build_integration_connection_message",
                return_value="NEEDS CONNECT",
            ) as mock_msg,
        ):
            mock_ts = AsyncMock()
            mock_ts.is_connected.return_value = False
            mock_ts_cls.return_value = mock_ts
            graph, name, error, is_custom = await _resolve_subagent("gmail", "user1")
        assert (graph, name, is_custom) == (None, None, False)
        assert error == "NEEDS CONNECT"
        mock_ts.is_connected.assert_awaited_once_with("gmail")
        mock_link.assert_awaited_once_with("user1", "gmail")
        mock_msg.assert_called_once_with("Gmail", "https://connect.example/gmail")

    async def test_platform_mcp_requires_auth_no_user(self):
        mcp_cfg = MCPConfig(server_url="https://example.com", requires_auth=True)
        subagent = _make_subagent("gmail", "gmail", "Gmail", managed_by="mcp", mcp_config=mcp_cfg)
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch("app.agents.core.subagents.handoff_tools.MCPTokenStore") as mock_ts_cls,
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            graph, name, error, is_custom = await _resolve_subagent("gmail", None)
        assert (graph, name, is_custom) == (None, None, False)
        assert error == "Error: gmail_agent requires authentication. Please sign in first."
        mock_ts_cls.assert_not_called()
        mock_create.assert_not_awaited()

    async def test_platform_mcp_without_config_uses_provider(self):
        subagent = _make_subagent("mcp_int", "mcp_int", "MCP Int", managed_by="mcp")
        mock_graph = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch("app.agents.core.subagents.handoff_tools.MCPTokenStore") as mock_ts_cls,
            patch(
                "app.agents.core.subagents.handoff_tools.providers",
                new=AsyncMock(),
            ) as mock_providers,
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_connection",
                new_callable=AsyncMock,
            ) as mock_check,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_graph)
            graph, name, int_id, is_custom = await _resolve_subagent("mcp_int", "user1")
        assert graph is mock_graph
        assert is_custom is False
        assert name == "gmail_agent"
        mock_ts_cls.assert_not_called()
        mock_check.assert_not_awaited()
        mock_providers.aget.assert_awaited_once_with("gmail_agent")

    async def test_platform_non_mcp_uses_provider(self):
        subagent = _make_subagent(
            "gcal",
            "gcal",
            "Google Calendar",
            managed_by="internal",
            agent_name="calendar_agent",
        )
        mock_graph = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.providers",
                new=AsyncMock(),
            ) as mock_providers,
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_connection",
                new_callable=AsyncMock,
            ) as mock_check,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_graph)
            graph, name, int_id, is_custom = await _resolve_subagent("gcal", "user1")
        assert graph is mock_graph
        assert name == "calendar_agent"
        assert int_id == "gcal"
        assert is_custom is False
        mock_providers.aget.assert_awaited_once_with("calendar_agent")
        mock_check.assert_not_awaited()

    async def test_platform_composio_checks_connection(self):
        subagent = _make_subagent(
            "composio",
            "composio",
            "Composio",
            managed_by="composio",
            agent_name="composio_agent",
        )
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_connection",
                new_callable=AsyncMock,
                return_value="Not connected",
            ) as mock_check,
            patch(
                "app.agents.core.subagents.handoff_tools.providers",
                new=AsyncMock(),
            ) as mock_providers,
        ):
            graph, name, error, is_custom = await _resolve_subagent("composio", "user1")
        assert (graph, name, is_custom) == (None, None, False)
        assert error == "Not connected"
        mock_check.assert_awaited_once_with("composio", "user1")
        mock_providers.aget.assert_not_awaited()

    async def test_platform_skips_connection_check_without_user(self):
        subagent = _make_subagent(
            "composio",
            "composio",
            "Composio",
            managed_by="composio",
            agent_name="composio_agent",
        )
        mock_graph = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_connection",
                new_callable=AsyncMock,
            ) as mock_check,
            patch(
                "app.agents.core.subagents.handoff_tools.providers",
                new=AsyncMock(),
            ) as mock_providers,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_graph)
            graph, name, int_id, is_custom = await _resolve_subagent("composio", None)
        assert graph is mock_graph
        assert is_custom is False
        mock_check.assert_not_awaited()
        mock_providers.aget.assert_awaited_once_with("composio_agent")

    async def test_platform_provider_not_available(self):
        subagent = _make_subagent("x", "x", "X", managed_by="internal", agent_name="missing_agent")
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.providers",
                new=AsyncMock(),
            ) as mock_providers,
        ):
            mock_providers.aget = AsyncMock(return_value=None)
            graph, name, error, is_custom = await _resolve_subagent("x", "user1")
        assert (graph, name, is_custom) == (None, None, False)
        assert error == "Error: missing_agent not available"

    async def test_platform_provider_key_error(self):
        subagent = _make_subagent("x", "x", "X", managed_by="internal", agent_name="missing_agent")
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.providers",
                new=AsyncMock(),
            ) as mock_providers,
        ):
            mock_providers.aget = AsyncMock(side_effect=KeyError("missing_agent"))
            graph, name, error, is_custom = await _resolve_subagent("x", "user1")
        assert (graph, name, is_custom) == (None, None, False)
        assert error == "Error: missing_agent not available"

    async def test_platform_mcp_graph_creation_fails(self):
        mcp_cfg = MCPConfig(server_url="https://example.com", requires_auth=True)
        subagent = _make_subagent(
            "mcp_int",
            "mcp_int",
            "MCP Int",
            managed_by="mcp",
            mcp_config=mcp_cfg,
            agent_name="mcp_agent",
        )
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch("app.agents.core.subagents.handoff_tools.MCPTokenStore") as mock_ts_cls,
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new_callable=AsyncMock,
                side_effect=SubagentUnavailableError("server error"),
            ),
        ):
            mock_ts = AsyncMock()
            mock_ts.is_connected.return_value = True
            mock_ts_cls.return_value = mock_ts
            graph, name, error, is_custom = await _resolve_subagent("mcp_int", "user1")
        assert (graph, name, is_custom) == (None, None, False)
        assert error == "Error: mcp_agent is unavailable — server error"


# ---------------------------------------------------------------------------
# _extract_service_username
# ---------------------------------------------------------------------------


class TestExtractServiceUsername:
    def test_none_metadata_returns_none(self):
        assert _extract_service_username(None) is None

    def test_empty_metadata_returns_none(self):
        assert _extract_service_username({}) is None

    def test_returns_username_key(self):
        assert _extract_service_username({"username": "jdoe"}) == "jdoe"

    def test_falls_back_to_login_key(self):
        assert _extract_service_username({"login": "jdoe"}) == "jdoe"

    def test_falls_back_to_handle_key(self):
        assert _extract_service_username({"handle": "jdoe"}) == "jdoe"

    def test_first_truthy_key_wins(self):
        assert _extract_service_username({"username": "u", "login": "l"}) == "u"

    def test_empty_username_skips_to_login(self):
        assert _extract_service_username({"username": "", "login": "l"}) == "l"

    def test_unknown_keys_return_none(self):
        assert _extract_service_username({"display_name": "jdoe"}) is None

    def test_non_string_value_is_stringified(self):
        assert _extract_service_username({"username": 42}) == "42"


# ---------------------------------------------------------------------------
# _sanitize_task_user_reference
# ---------------------------------------------------------------------------


class TestSanitizeTaskUserReference:
    def test_no_gaia_name_returns_task_unchanged(self):
        task = "user: Gaia User"
        assert _sanitize_task_user_reference(task, None, "gmail", "jdoe") == task

    def test_provider_hint_absent_returns_task_unchanged(self):
        task = "user: Gaia User"
        assert _sanitize_task_user_reference(task, "Gaia User", "gmail", "jdoe") == task

    def test_no_user_reference_returns_task_unchanged(self):
        task = "Check gmail for new mail"
        assert _sanitize_task_user_reference(task, "Gaia User", "gmail", "jdoe") == task

    def test_replaces_user_reference(self):
        assert (
            _sanitize_task_user_reference(
                "user: Gaia User on gmail", "Gaia User", "gmail", "jdoe"
            )
            == "user: jdoe on gmail"
        )

    def test_replaces_username_reference(self):
        assert (
            _sanitize_task_user_reference(
                "username = Gaia User on gmail", "Gaia User", "gmail", "jdoe"
            )
            == "username = jdoe on gmail"
        )

    def test_replaces_account_reference(self):
        assert (
            _sanitize_task_user_reference(
                "account: Gaia User on gmail", "Gaia User", "gmail", "jdoe"
            )
            == "account: jdoe on gmail"
        )

    def test_replaces_all_three_patterns_in_one_task(self):
        task = "user: Gaia User, username: Gaia User, account: Gaia User via gmail"
        assert (
            _sanitize_task_user_reference(task, "Gaia User", "gmail", "jdoe")
            == "user: jdoe, username: jdoe, account: jdoe via gmail"
        )

    def test_match_is_case_insensitive(self):
        assert (
            _sanitize_task_user_reference(
                "USER: GAIUS via GMAIL", "Gaius", "gmail", "jdoe"
            )
            == "USER: jdoe via GMAIL"
        )

    def test_falls_back_to_authenticated_user(self):
        assert (
            _sanitize_task_user_reference("user: Gaia User on gmail", "Gaia User", "gmail", None)
            == "user: authenticated user on gmail"
        )

    def test_gaia_name_with_regex_metacharacters_is_escaped(self):
        task = "user: A.B (C) on gmail"
        assert (
            _sanitize_task_user_reference(task, "A.B (C)", "gmail", "jdoe")
            == "user: jdoe on gmail"
        )


# ---------------------------------------------------------------------------
# _resolve_display_metadata
# ---------------------------------------------------------------------------


class TestResolveDisplayMetadata:
    def test_no_metadata_returns_fallbacks(self):
        assert _resolve_display_metadata(None, "gmail", "gmail") == ("gmail", None, "gmail")

    def test_empty_metadata_returns_fallbacks(self):
        assert _resolve_display_metadata({}, "gmail", "gmail") == ("gmail", None, "gmail")

    def test_full_metadata(self):
        metadata: IntegrationMetadata = {
            "name": "Gmail",
            "icon_url": "https://x/icon.png",
            "integration_id": "gmail",
        }
        assert _resolve_display_metadata(metadata, "fallback", "cat") == (
            "Gmail",
            "https://x/icon.png",
            "gmail",
        )

    def test_missing_name_falls_back_to_fallback_name(self):
        metadata: IntegrationMetadata = {"icon_url": "https://x/icon.png"}
        assert _resolve_display_metadata(metadata, "fallback", "cat") == (
            "fallback",
            "https://x/icon.png",
            "cat",
        )

    def test_missing_integration_id_falls_back_to_category(self):
        metadata: IntegrationMetadata = {"name": "Gmail", "icon_url": None}
        assert _resolve_display_metadata(metadata, "fallback", "cat") == (
            "Gmail",
            None,
            "cat",
        )


# ---------------------------------------------------------------------------
# _subagent_resume_status
# ---------------------------------------------------------------------------


class TestSubagentResumeStatus:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (HILApprovalStatus.APPROVED, HILApprovalStatus.APPROVED),
            (HILApprovalStatus.TIMEOUT, HILApprovalStatus.TIMEOUT),
            (HILApprovalStatus.DENIED, HILApprovalStatus.DENIED),
            (HILApprovalStatus.ABANDONED, HILApprovalStatus.DENIED),
            (HILApprovalStatus.AUTO_APPROVED, HILApprovalStatus.DENIED),
        ],
    )
    def test_maps_status(self, status: HILApprovalStatus, expected: HILApprovalStatus):
        assert _subagent_resume_status(status) == expected


# ---------------------------------------------------------------------------
# _build_integration_metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBuildIntegrationMetadata:
    async def test_custom_returns_metadata_from_dict(self):
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value={"icon_url": "https://x/icon.png", "name": "My MCP"},
        ) as mock_lookup:
            metadata = await _build_integration_metadata(True, "abc")
        assert metadata == {
            "icon_url": "https://x/icon.png",
            "integration_id": "abc",
            "name": "My MCP",
        }
        mock_lookup.assert_awaited_once_with("abc")

    async def test_custom_without_name_falls_back_to_id(self):
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value={"icon_url": None},
        ):
            metadata = await _build_integration_metadata(True, "abc")
        assert metadata == {
            "icon_url": None,
            "integration_id": "abc",
            "name": "abc",
        }

    async def test_custom_not_found_returns_none(self):
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            metadata = await _build_integration_metadata(True, "abc")
        assert metadata is None

    async def test_custom_non_dict_result_returns_none(self):
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=_make_subagent("abc"),
        ):
            metadata = await _build_integration_metadata(True, "abc")
        assert metadata is None

    async def test_platform_returns_metadata(self):
        subagent = _make_subagent("gmail")
        with patch(
            "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
            return_value=subagent,
        ) as mock_platform:
            metadata = await _build_integration_metadata(False, "gmail")
        assert metadata == {
            "icon_url": None,
            "integration_id": "gmail",
            "name": "Gmail",
        }
        mock_platform.assert_called_once_with("gmail")

    async def test_platform_with_icon_url(self):
        platform_integ = SimpleNamespace(icon_url="https://x/icon.png", name="Gmail")
        with patch(
            "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
            return_value=platform_integ,
        ):
            metadata = await _build_integration_metadata(False, "gmail")
        assert metadata == {
            "icon_url": "https://x/icon.png",
            "integration_id": "gmail",
            "name": "Gmail",
        }

    async def test_platform_not_found_returns_none(self):
        with patch(
            "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
            return_value=None,
        ):
            metadata = await _build_integration_metadata(False, "gmail")
        assert metadata is None


# ---------------------------------------------------------------------------
# _has_parked_subagent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHasParkedSubagent:
    async def test_false_without_conversation_id(self):
        with patch(
            "app.agents.core.subagents.handoff_tools.list_parked_subagents_for_conversation",
            new_callable=AsyncMock,
        ) as mock_list:
            result = await _has_parked_subagent(_make_ctx(thread_id="t1"))
        assert result is False
        mock_list.assert_not_awaited()

    async def test_false_without_thread_id(self):
        with patch(
            "app.agents.core.subagents.handoff_tools.list_parked_subagents_for_conversation",
            new_callable=AsyncMock,
        ) as mock_list:
            result = await _has_parked_subagent(_make_ctx(conversation_id="c1"))
        assert result is False
        mock_list.assert_not_awaited()

    async def test_true_when_a_record_owns_the_thread(self):
        records = [SimpleNamespace(subagent_thread_id="other"), SimpleNamespace(subagent_thread_id="t1")]
        with patch(
            "app.agents.core.subagents.handoff_tools.list_parked_subagents_for_conversation",
            new_callable=AsyncMock,
            return_value=records,
        ) as mock_list:
            result = await _has_parked_subagent(
                _make_ctx(conversation_id="c1", thread_id="t1")
            )
        assert result is True
        mock_list.assert_awaited_once_with("c1")

    async def test_false_when_no_record_owns_the_thread(self):
        records = [SimpleNamespace(subagent_thread_id="other")]
        with patch(
            "app.agents.core.subagents.handoff_tools.list_parked_subagents_for_conversation",
            new_callable=AsyncMock,
            return_value=records,
        ) as mock_list:
            result = await _has_parked_subagent(
                _make_ctx(conversation_id="c1", thread_id="t1")
            )
        assert result is False
        mock_list.assert_awaited_once_with("c1")


# ---------------------------------------------------------------------------
# prepare_subagent_execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPrepareSubagentExecution:
    async def test_builds_execution_context(self):
        mock_graph = MagicMock()
        subagent = _make_subagent(
            "gcal", "gcal", "Google Calendar", managed_by="internal", agent_name="calendar_agent"
        )
        task = "user: Gaia User on gcal"
        configurable = {
            "user_id": "user1",
            "thread_id": "t1",
            "email": "e@example.com",
            "user_name": "Gaia User",
        }
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(mock_graph, "calendar_agent", "gcal", False),
            ) as mock_resolve,
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
                return_value="SUBAGENT_CONFIG",
            ) as mock_build_config,
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={"new": "configurable"},
            ) as mock_agent_configurable,
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_system_message",
                new_callable=AsyncMock,
                return_value="SYS_MSG",
            ) as mock_system_message,
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=subagent,
            ) as mock_platform_lookup,
            patch(
                "app.agents.core.subagents.handoff_tools.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={"username": "svc"},
            ) as mock_provider_metadata,
            patch(
                "app.agents.core.subagents.handoff_tools.build_initial_messages",
                new_callable=AsyncMock,
                return_value=[{"role": "user", "content": "hi"}],
            ) as mock_build_messages,
            patch(
                "app.agents.core.subagents.handoff_tools._build_integration_metadata",
                new_callable=AsyncMock,
                return_value={"icon_url": None, "integration_id": "gcal", "name": "Gcal"},
            ) as mock_integration_metadata,
            patch("app.agents.core.subagents.handoff_tools.log") as mock_log,
        ):
            ctx, metadata, error = await prepare_subagent_execution(
                subagent_id="gcal",
                task=task,
                configurable=configurable,
                stream_id="s1",
            )

        assert error is None
        assert metadata == {"icon_url": None, "integration_id": "gcal", "name": "Gcal"}
        mock_resolve.assert_awaited_once_with("gcal", "user1")
        mock_log.set.assert_called_once_with(
            subagent={
                "name": "calendar_agent",
                "provider": "gcal",
                "is_custom": False,
                "task_length": 23,
            }
        )
        mock_build_config.assert_called_once_with(
            conversation_id="t1",
            user={"user_id": "user1", "email": "e@example.com", "name": "Gaia User"},
            thread_id="gcal_t1",
            base_configurable=configurable,
            agent_name="calendar_agent",
            subagent_id="calendar_agent",
        )
        mock_agent_configurable.assert_called_once_with("SUBAGENT_CONFIG")
        mock_system_message.assert_awaited_once_with(integration_id="gcal")
        mock_platform_lookup.assert_called_once_with("gcal")
        mock_provider_metadata.assert_awaited_once_with("user1", "gcal")
        mock_build_messages.assert_awaited_once_with(
            system_message="SYS_MSG",
            agent_name="calendar_agent",
            configurable={"new": "configurable"},
            task="user: svc on gcal",
            user_id="user1",
            subagent_id="calendar_agent",
            integration_id="gcal",
            provider_metadata={"username": "svc"},
        )
        mock_integration_metadata.assert_awaited_once_with(False, "gcal")

        assert ctx.agent_name == "calendar_agent"
        assert ctx.integration_id == "gcal"
        assert ctx.subagent_graph is mock_graph
        assert ctx.config == "SUBAGENT_CONFIG"
        assert ctx.configurable == {"new": "configurable"}
        assert ctx.user_id == "user1"
        assert ctx.stream_id == "s1"
        assert ctx.initial_state == {
            "messages": [{"role": "user", "content": "hi"}],
            "todos": [],
            "intent": "user: svc on gcal",
            "integration_usernames": {"gcal": "svc"},
        }

    async def test_no_provider_metadata_passes_none(self):
        mock_graph = MagicMock()
        task = "user: Gaia User on gcal"
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(mock_graph, "gmail_agent", "gcal", False),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
                return_value={},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_system_message",
                new_callable=AsyncMock,
                return_value="SYS_MSG",
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=SimpleNamespace(provider=None),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_provider_metadata",
                new_callable=AsyncMock,
            ) as mock_provider_metadata,
            patch(
                "app.agents.core.subagents.handoff_tools.build_initial_messages",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_build_messages,
            patch(
                "app.agents.core.subagents.handoff_tools._build_integration_metadata",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            ctx, metadata, error = await prepare_subagent_execution(
                subagent_id="gcal",
                task=task,
                configurable={"user_id": "user1", "thread_id": "t1", "user_name": "Gaia User"},
                stream_id=None,
            )

        assert error is None
        assert metadata is None
        assert ctx.stream_id is None
        mock_provider_metadata.assert_not_awaited()
        mock_build_messages.assert_awaited_once()
        provider_kwarg = mock_build_messages.call_args.kwargs
        assert provider_kwarg["provider_metadata"] is None
        assert provider_kwarg["task"] == "user: authenticated user on gcal"
        assert ctx.initial_state["integration_usernames"] == {}
        assert ctx.initial_state["intent"] == "user: authenticated user on gcal"

    async def test_provider_without_service_username_leaves_usernames_empty(self):
        mock_graph = MagicMock()
        subagent = _make_subagent("gcal", "gcal", "Google Calendar", managed_by="internal")
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(mock_graph, "gmail_agent", "gcal", False),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
                return_value={},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_system_message",
                new_callable=AsyncMock,
                return_value="SYS_MSG",
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=subagent,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={"other_key": "x"},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_initial_messages",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_build_messages,
            patch(
                "app.agents.core.subagents.handoff_tools._build_integration_metadata",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            ctx, metadata, error = await prepare_subagent_execution(
                subagent_id="gcal",
                task="do it",
                configurable={"user_id": "user1", "thread_id": "t1"},
                stream_id=None,
            )

        assert error is None
        assert metadata is None
        provider_kwarg = mock_build_messages.call_args.kwargs
        assert provider_kwarg["provider_metadata"] == {"other_key": "x"}
        assert ctx.initial_state["integration_usernames"] == {}

    async def test_missing_thread_id_uses_empty_string(self):
        mock_graph = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(mock_graph, "gmail_agent", "gcal", False),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
                return_value={},
            ) as mock_build_config,
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_system_message",
                new_callable=AsyncMock,
                return_value="SYS_MSG",
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_initial_messages",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._build_integration_metadata",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            ctx, metadata, error = await prepare_subagent_execution(
                subagent_id="gcal",
                task="do it",
                configurable={"user_id": "user1"},
                stream_id=None,
            )

        assert error is None
        assert metadata is None
        mock_build_config.assert_called_once()
        kwargs = mock_build_config.call_args.kwargs
        assert kwargs["conversation_id"] == ""
        assert kwargs["thread_id"] == "gcal_"

    async def test_returns_error_from_resolve(self):
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(None, None, "Boom", False),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
            ) as mock_build_config,
            patch("app.agents.core.subagents.handoff_tools.log") as mock_log,
        ):
            ctx, metadata, error = await prepare_subagent_execution(
                subagent_id="missing",
                task="do it",
                configurable={"user_id": "user1"},
            )
        assert (ctx, metadata) == (None, None)
        assert error == "Boom"
        mock_build_config.assert_not_called()
        mock_log.set.assert_not_called()

    async def test_unknown_error_fallback_when_resolve_returns_no_error(self):
        mock_graph = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(mock_graph, "gmail_agent", None, False),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
            ) as mock_build_config,
            patch("app.agents.core.subagents.handoff_tools.log") as mock_log,
        ):
            ctx, metadata, error = await prepare_subagent_execution(
                subagent_id="missing",
                task="do it",
                configurable={"user_id": "user1"},
            )
        assert (ctx, metadata) == (None, None)
        assert error == "Unknown error resolving subagent"
        mock_build_config.assert_not_called()
        mock_log.set.assert_not_called()

    async def test_error_uses_resolve_error_when_only_graph_missing(self):
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(None, "some_agent", "some_id", False),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
            ) as mock_build_config,
            patch("app.agents.core.subagents.handoff_tools.log") as mock_log,
        ):
            ctx, metadata, error = await prepare_subagent_execution(
                subagent_id="missing",
                task="do it",
                configurable={"user_id": "user1"},
            )
        assert (ctx, metadata) == (None, None)
        assert error == "some_id"
        mock_build_config.assert_not_called()
        mock_log.set.assert_not_called()


# ---------------------------------------------------------------------------
# _run_blocking_handoff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRunBlockingHandoff:
    async def test_fresh_run_executes_and_emits_start_end_events(self):
        ctx = _make_ctx(conversation_id="c1")
        ctx.config = {"configurable": {}}
        mock_writer = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.subagent_row_id",
                return_value="sa-123",
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_display_metadata",
                return_value=("Gmail", "https://x/icon.png", "gmail"),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.format_subagent_start_event",
                return_value={"type": "start"},
            ) as mock_start,
            patch(
                "app.agents.core.subagents.handoff_tools.format_subagent_end_event",
                return_value={"type": "end", "duration_ms": 42},
            ) as mock_end,
            patch(
                "app.agents.core.subagents.handoff_tools.recover_from_checkpoint",
                new_callable=AsyncMock,
            ) as mock_recover,
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="done"),
            ) as mock_execute,
        ):
            result = await _run_blocking_handoff(
                ctx,
                {"integration_id": "gmail"},
                "gmail_agent",
                "gmail",
                "tc-1",
            )

        assert result == "done"
        # Fresh runs skip the checkpoint probe entirely.
        mock_recover.assert_not_awaited()
        mock_execute.assert_awaited_once_with(
            ctx=ctx,
            stream_writer=mock_writer,
            integration_metadata={"integration_id": "gmail"},
            subagent_id="sa-123",
        )
        mock_start.assert_called_once_with(
            subagent_name="Gmail",
            agent_type="handoff",
            subagent_id="sa-123",
            icon_url="https://x/icon.png",
            tool_category="gmail",
        )
        mock_end.assert_called_once_with(subagent_id="sa-123", duration_ms=42)
        assert mock_writer.call_args_list == [
            call({"subagent_start": {"type": "start"}}),
            call({"subagent_end": {"type": "end", "duration_ms": 42}}),
        ]
        # Stable subagent row id is propagated into both config layers.
        assert ctx.configurable["subagent_id"] == "sa-123"
        assert ctx.config["configurable"]["subagent_id"] == "sa-123"

    async def test_probe_parked_with_recovered_checkpoint_skips_execution(self):
        ctx = _make_ctx()
        mock_writer = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.subagent_row_id",
                return_value="sa-123",
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_display_metadata",
                return_value=("Gmail", None, "gmail"),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.format_subagent_start_event",
                return_value={},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.format_subagent_end_event",
                return_value={},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.recover_from_checkpoint",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="recovered"),
            ) as mock_recover,
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new_callable=AsyncMock,
            ) as mock_execute,
        ):
            result = await _run_blocking_handoff(
                ctx, None, "gmail_agent", "gmail", "tc-1", probe_parked=True
            )

        assert result == "recovered"
        mock_recover.assert_awaited_once_with(ctx)
        mock_execute.assert_not_awaited()

    async def test_probe_parked_without_checkpoint_falls_back_to_execution(self):
        ctx = _make_ctx()
        mock_writer = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.subagent_row_id",
                return_value="sa-123",
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_display_metadata",
                return_value=("Gmail", None, "gmail"),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.format_subagent_start_event",
                return_value={},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.format_subagent_end_event",
                return_value={},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.recover_from_checkpoint",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_recover,
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="done"),
            ) as mock_execute,
        ):
            result = await _run_blocking_handoff(
                ctx, None, "gmail_agent", "gmail", "tc-1", probe_parked=True
            )

        assert result == "done"
        mock_recover.assert_awaited_once_with(ctx)
        mock_execute.assert_awaited_once_with(
            ctx=ctx,
            stream_writer=mock_writer,
            integration_metadata=None,
            subagent_id="sa-123",
        )

    async def test_paused_outcome_loops_with_resume_decision(self):
        ctx = _make_ctx()
        mock_writer = MagicMock()
        paused = SubagentOutcome(text="", interrupt={"approval_id": "a1"})
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=mock_writer,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.subagent_row_id",
                return_value="sa-123",
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_display_metadata",
                return_value=("Gmail", None, "gmail"),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.format_subagent_start_event",
                return_value={},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.format_subagent_end_event",
                return_value={},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.recover_from_checkpoint",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.resume_for_gate",
                return_value="DECISION",
            ) as mock_gate,
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new_callable=AsyncMock,
                side_effect=[paused, SubagentOutcome(text="final")],
            ) as mock_execute,
        ):
            result = await _run_blocking_handoff(ctx, None, "gmail_agent", "gmail", "tc-1")

        assert result == "final"
        mock_gate.assert_called_once_with({"approval_id": "a1"})
        calls = mock_execute.await_args_list
        assert len(calls) == 2
        # First pass runs without a resume; the resume pass carries the decision.
        assert "resume" not in calls[0].kwargs
        resume_cmd = calls[1].kwargs["resume"]
        assert isinstance(resume_cmd, Command)
        assert resume_cmd.resume == "DECISION"


# ---------------------------------------------------------------------------
# resume_parked_subagent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResumeParkedSubagent:
    def _record(self, **overrides: object) -> SimpleNamespace:
        data: dict[str, object] = {
            "subagent_agent_name": "gmail",
            "user_id": "user1",
            "conversation_id": "c1",
            "subagent_thread_id": "gmail_t1",
            "status": HILApprovalStatus.APPROVED,
            "feedback": "ok",
            "scope": "once",
        }
        data.update(overrides)
        return SimpleNamespace(**data)

    async def test_resolve_failure_returns_error_text(self):
        with patch(
            "app.agents.core.subagents.handoff_tools._resolve_subagent",
            new_callable=AsyncMock,
            return_value=(None, None, "Boom", False),
        ):
            outcome = await resume_parked_subagent(self._record(), {}, MagicMock())
        assert outcome == SubagentOutcome(text="Error resuming gmail: Boom")

    async def test_resolve_failure_without_error_message(self):
        with patch(
            "app.agents.core.subagents.handoff_tools._resolve_subagent",
            new_callable=AsyncMock,
            return_value=(None, None, None, False),
        ):
            outcome = await resume_parked_subagent(self._record(), {}, MagicMock())
        assert outcome == SubagentOutcome(text="Error resuming gmail: subagent not resolvable")

    async def test_missing_checkpoint_returns_error(self):
        mock_graph = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(mock_graph, "gmail_agent", "gmail", False),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
                return_value="SUBAGENT_CONFIG",
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={"configurable": "parsed"},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.recover_from_checkpoint",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new_callable=AsyncMock,
            ) as mock_execute,
        ):
            outcome = await resume_parked_subagent(self._record(), {}, MagicMock())

        assert outcome == SubagentOutcome(
            text="Error resuming gmail_agent: its checkpoint is missing."
        )
        mock_execute.assert_not_awaited()

    async def test_unpaused_outcome_returned_as_is(self):
        mock_graph = MagicMock()
        recovered = SubagentOutcome(text="final answer")
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(mock_graph, "gmail_agent", "gmail", False),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
                return_value="SUBAGENT_CONFIG",
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.recover_from_checkpoint",
                new_callable=AsyncMock,
                return_value=recovered,
            ) as mock_recover,
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new_callable=AsyncMock,
            ) as mock_execute,
        ):
            outcome = await resume_parked_subagent(self._record(), {}, MagicMock())

        assert outcome is recovered
        mock_recover.assert_awaited_once()
        mock_execute.assert_not_awaited()

    async def test_paused_outcome_resumes_with_mapped_decision(self):
        mock_graph = MagicMock()
        record = self._record(
            status=HILApprovalStatus.ABANDONED, feedback="no", scope="once"
        )
        mock_writer = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_subagent",
                new_callable=AsyncMock,
                return_value=(mock_graph, "gmail_agent", "gmail", False),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.build_agent_config",
                return_value="SUBAGENT_CONFIG",
            ) as mock_build_config,
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={"configurable": "parsed"},
            ) as mock_agent_configurable,
            patch(
                "app.agents.core.subagents.handoff_tools.recover_from_checkpoint",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="", interrupt={"approval_id": "a1"}),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="done"),
            ) as mock_execute,
        ):
            outcome = await resume_parked_subagent(
                record, {"stream_id": "s1", "email": "e@x.com"}, mock_writer
            )

        assert outcome == SubagentOutcome(text="done")
        # Everything is reconstructed from the record + configurable.
        mock_build_config.assert_called_once_with(
            conversation_id="c1",
            user={"user_id": "user1", "email": "e@x.com", "name": None},
            thread_id="gmail_t1",
            base_configurable={"stream_id": "s1", "email": "e@x.com"},
            agent_name="gmail_agent",
            subagent_id="gmail_agent",
        )
        mock_agent_configurable.assert_called_once_with("SUBAGENT_CONFIG")
        assert mock_execute.await_count == 1
        resume_cmd = mock_execute.await_args.kwargs["resume"]
        assert isinstance(resume_cmd, Command)
        # ABANDONED maps to a denial so the gate accepts it.
        assert resume_cmd.resume == {
            "status": HILApprovalStatus.DENIED,
            "feedback": "no",
            "scope": "once",
        }
        assert mock_execute.await_args.kwargs["stream_writer"] is mock_writer
        ctx = mock_execute.await_args.kwargs["ctx"]
        assert ctx.agent_name == "gmail_agent"
        assert ctx.integration_id == "gmail"
        assert ctx.user_id == "user1"
        assert ctx.stream_id == "s1"


# ---------------------------------------------------------------------------
# handoff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHandoffTool:
    def _config(self, configurable: dict[str, object] | None = None) -> dict[str, object]:
        return {"configurable": configurable or {}, "metadata": {}}

    async def test_returns_resolve_error(self):
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={"user_id": "user1"},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(None, None, "Boom"),
            ),
        ):
            result = await handoff.coroutine(
                subagent_id="missing", task="t", config=self._config()
            )
        assert result == "Boom"

    async def test_returns_unknown_error_fallback(self):
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={"user_id": "user1"},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(None, None, None),
            ),
        ):
            result = await handoff.coroutine(
                subagent_id="missing", task="t", config=self._config()
            )
        assert result == "Unknown error resolving subagent"

    async def test_user_id_falls_back_to_metadata(self):
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(None, None, "Boom"),
            ) as mock_prepare,
        ):
            await handoff.coroutine(
                subagent_id="missing",
                task="t",
                config={"configurable": {}, "metadata": {"user_id": "meta-user"}},
            )
        assert mock_prepare.await_args.kwargs["configurable"]["user_id"] == "meta-user"

    async def test_refuses_parked_subagent(self):
        ctx = _make_ctx()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={"user_id": "user1"},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(ctx, None, None),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._run_blocking_handoff",
                new_callable=AsyncMock,
            ) as mock_blocking,
        ):
            result = await handoff.coroutine(
                subagent_id="gmail", task="t", config=self._config(), tool_call_id="tc-1"
            )
        assert result == (
            "The gmail_agent subagent is paused waiting for the user's approval. "
            "Call wait_for_subagents() to collect its outcome before sending it "
            "new tasks."
        )
        mock_blocking.assert_not_awaited()

    async def test_refuses_blocking_handoff_while_background_runs(self):
        ctx = _make_ctx()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={"user_id": "user1", "stream_id": "s1"},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(ctx, None, None),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.has_bg_integration",
                return_value=True,
            ) as mock_has_bg,
            patch(
                "app.agents.core.subagents.handoff_tools._run_blocking_handoff",
                new_callable=AsyncMock,
            ) as mock_blocking,
        ):
            result = await handoff.coroutine(
                subagent_id="gmail", task="t", config=self._config(), tool_call_id="tc-1"
            )
        assert result == (
            "A background gmail_agent subagent is already running on this "
            "integration. Call wait_for_subagents() to collect it first."
        )
        mock_has_bg.assert_called_once_with("s1", "gmail")
        mock_blocking.assert_not_awaited()

    async def test_background_without_stream_id_falls_back_to_blocking(self):
        ctx = _make_ctx()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={"user_id": "user1"},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(ctx, None, None),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.has_bg_integration",
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._run_blocking_handoff",
                new_callable=AsyncMock,
                return_value="BLOCKING",
            ) as mock_blocking,
            patch("app.agents.core.subagents.handoff_tools.log") as mock_log,
        ):
            result = await handoff.coroutine(
                subagent_id="gmail",
                task="t",
                config=self._config(),
                background=True,
                tool_call_id="tc-1",
            )
        assert result == (
            "[WARNING: background handoff fell back to blocking — "
            "stream_id not propagated into executor configurable] BLOCKING"
        )
        mock_log.warning.assert_called_once()
        mock_blocking.assert_awaited_once_with(ctx, None, "gmail_agent", "gmail", "tc-1", False)

    async def test_background_claim_conflict_refuses(self):
        ctx = _make_ctx()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={"user_id": "user1", "stream_id": "s1"},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(ctx, None, None),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.has_bg_integration",
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.claim_bg_integration",
                return_value=False,
            ) as mock_claim,
            patch(
                "app.agents.core.subagents.handoff_tools.spawn_background_task",
            ) as mock_spawn,
        ):
            result = await handoff.coroutine(
                subagent_id="gmail",
                task="t",
                config=self._config(),
                background=True,
                tool_call_id="tc-1",
            )
        assert result == (
            "A background gmail_agent subagent is already running. Call "
            "wait_for_subagents() to collect it before sending it new tasks."
        )
        mock_claim.assert_called_once_with("s1", "gmail")
        mock_spawn.assert_not_called()

    async def test_background_already_dispatched_releases_claim(self):
        ctx = _make_ctx(conversation_id="c1")
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={"user_id": "user1", "stream_id": "s1"},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(ctx, None, None),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.has_bg_integration",
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.claim_bg_integration",
                return_value=True,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.try_claim_bg_dispatch",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.release_bg_integration",
            ) as mock_release,
            patch(
                "app.agents.core.subagents.handoff_tools.spawn_background_task",
            ) as mock_spawn,
            patch(
                "app.agents.core.subagents.handoff_tools.increment_pending_subagents",
            ) as mock_increment,
        ):
            result = await handoff.coroutine(
                subagent_id="gmail",
                task="t",
                config=self._config(),
                background=True,
                tool_call_id="tc-1",
            )
        assert result == (
            "Subagent gmail_agent started in background. "
            "Call wait_for_subagents() when ready to collect results."
        )
        # Idempotent replay: the claim is released, nothing is spawned twice.
        mock_release.assert_called_once_with("s1", "gmail")
        mock_spawn.assert_not_called()
        mock_increment.assert_not_called()

    async def test_background_dispatch_spawns_task(self):
        ctx = _make_ctx(conversation_id="c1")
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={"user_id": "user1", "stream_id": "s1"},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(ctx, {"integration_id": "gmail"}, None),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.has_bg_integration",
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.claim_bg_integration",
                return_value=True,
            ) as mock_claim,
            patch(
                "app.agents.core.subagents.handoff_tools.try_claim_bg_dispatch",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_try_claim,
            patch(
                "app.agents.core.subagents.handoff_tools.uuid4",
                return_value="bg-uuid",
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._resolve_display_metadata",
                return_value=("Gmail", "https://x/icon.png", "gmail"),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.increment_pending_subagents",
            ) as mock_increment,
            patch(
                "app.agents.core.subagents.handoff_tools.run_subagent_background",
                new_callable=AsyncMock,
            ) as mock_runner,
            patch(
                "app.agents.core.subagents.handoff_tools.spawn_background_task",
            ) as mock_spawn,
            patch("app.agents.core.subagents.handoff_tools.log") as mock_log,
        ):
            result = await handoff.coroutine(
                subagent_id="gmail",
                task="t",
                config=self._config(),
                background=True,
                tool_call_id="tc-1",
            )
        assert result == (
            "Subagent gmail_agent started in background. "
            "Call wait_for_subagents() when ready to collect results."
        )
        mock_claim.assert_called_once_with("s1", "gmail")
        mock_try_claim.assert_awaited_once_with("c1", "tc-1")
        mock_increment.assert_called_once_with("s1")
        mock_runner.assert_called_once_with(
            ctx=ctx,
            stream_id="s1",
            integration_metadata={"integration_id": "gmail"},
            subagent_id="bg-uuid",
            display_name="Gmail",
            tool_category="gmail",
            icon_url="https://x/icon.png",
            integration_id="gmail",
        )
        mock_spawn.assert_called_once()
        task = mock_spawn.call_args[0][0]
        assert asyncio.iscoroutine(task)
        mock_log.info.assert_called_once_with(
            f"{LogTag.AGENT} Subagent dispatched to background",
            agent_name="gmail_agent",
            stream_id="s1",
        )

    async def test_blocking_success_returns_result(self):
        ctx = _make_ctx()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={"user_id": "user1", "stream_id": "s1"},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(ctx, None, None),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.has_bg_integration",
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._run_blocking_handoff",
                new_callable=AsyncMock,
                return_value="RESULT",
            ) as mock_blocking,
        ):
            result = await handoff.coroutine(
                subagent_id="gmail", task="t", config=self._config(), tool_call_id="tc-1"
            )
        assert result == "RESULT"
        mock_blocking.assert_awaited_once_with(ctx, None, "gmail_agent", "gmail", "tc-1", False)

    async def test_resume_replay_enables_checkpoint_probe(self):
        ctx = _make_ctx()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={"user_id": "user1", HIL_RESUME_CONFIG_KEY: True},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(ctx, None, None),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.has_bg_integration",
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._run_blocking_handoff",
                new_callable=AsyncMock,
                return_value="RESULT",
            ) as mock_blocking,
        ):
            await handoff.coroutine(
                subagent_id="gmail", task="t", config=self._config(), tool_call_id="tc-1"
            )
        # Resume replays probe the checkpoint so already-done work is not redone.
        mock_blocking.assert_awaited_once_with(ctx, None, "gmail_agent", "gmail", "tc-1", True)

    async def test_exception_returns_error_and_logs(self):
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={"user_id": "user1"},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(MagicMock(), None, None),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.has_bg_integration",
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._run_blocking_handoff",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch("app.agents.core.subagents.handoff_tools.log") as mock_log,
        ):
            result = await handoff.coroutine(
                subagent_id="gmail", task="t", config=self._config(), tool_call_id="tc-1"
            )
        assert result == "Error executing task: boom"
        mock_log.error.assert_called_once_with(
            f"{LogTag.AGENT} handoff_failed",
            subagent_id="gmail",
            user_id="user1",
            error_type="RuntimeError",
            error="boom",
            exc_info=True,
        )

    async def test_graph_bubble_up_propagates(self):
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.agent_configurable",
                return_value={"user_id": "user1"},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(MagicMock(), None, None),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.has_bg_integration",
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._run_blocking_handoff",
                new_callable=AsyncMock,
                side_effect=GraphBubbleUp(),
            ),
            patch("app.agents.core.subagents.handoff_tools.log") as mock_log,
        ):
            with pytest.raises(GraphBubbleUp):
                await handoff.coroutine(
                    subagent_id="gmail", task="t", config=self._config(), tool_call_id="tc-1"
                )
        # Control flow, not a failure — must not be swallowed into a tool error.
        mock_log.error.assert_not_called()
