"""Exact-output and exact-argument behaviour of integration_activation helpers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.subagents.integration_activation import (
    ActivatedTools,
    _activate_mcp_tools,
    _activation_header,
    _connect_and_activate,
    _overview_section,
)
from app.agents.core.subagents.integration_resolution import CustomMcpSubagent
from app.agents.core.subagents.registry import all_subagents
from app.constants.mcp import MCP_PRELOAD_ALL_MAX
from app.models.subagent_models import Subagent

_MOD = "app.agents.core.subagents.integration_activation"


def _tool(name: str) -> MagicMock:
    mock = MagicMock()
    mock.name = name
    return mock


def _tools(count: int) -> list[MagicMock]:
    return [_tool(f"tool_{i}") for i in range(count)]


def _client(tools: list[MagicMock]) -> MagicMock:
    client = MagicMock()
    client.ensure_connected = AsyncMock(return_value=tools)
    return client


@pytest.mark.unit
@pytest.mark.asyncio
class TestActivateMcpTools:
    async def test_connects_the_callers_client_and_renders_docs_for_this_server(self) -> None:
        target = CustomMcpSubagent(id="abc123", name="My MCP")
        client = _client(_tools(2))
        get_client = AsyncMock(return_value=client)
        render = AsyncMock(return_value="DOCS")
        with (
            patch(f"{_MOD}.get_mcp_client", new=get_client),
            patch(f"{_MOD}._render_preload", new=render),
        ):
            activated = await _activate_mcp_tools("user1", target)

        get_client.assert_awaited_once_with("user1")
        client.ensure_connected.assert_awaited_once_with("abc123")
        render.assert_awaited_once_with("abc123", "user1", ["tool_0", "tool_1"])
        assert activated == ActivatedTools(
            total=2, bind=[], preload=["tool_0", "tool_1"], docs="DOCS", preload_capped=False
        )

    async def test_a_server_with_no_tools_is_not_reported_as_capped(self) -> None:
        target = CustomMcpSubagent(id="abc123", name="My MCP")
        with (
            patch(f"{_MOD}.get_mcp_client", new=AsyncMock(return_value=_client([]))),
            patch(f"{_MOD}._render_preload", new=AsyncMock(return_value="")),
        ):
            activated = await _activate_mcp_tools("user1", target)

        assert activated.preload_capped is False

    async def test_a_custom_server_above_the_cap_preloads_nothing_and_is_capped(self) -> None:
        target = CustomMcpSubagent(id="abc123", name="My MCP")
        with (
            patch(
                f"{_MOD}.get_mcp_client",
                new=AsyncMock(return_value=_client(_tools(MCP_PRELOAD_ALL_MAX + 1))),
            ),
            patch(f"{_MOD}._render_preload", new=AsyncMock(return_value="")),
        ):
            activated = await _activate_mcp_tools("user1", target)

        assert activated.preload == []
        assert activated.preload_capped is True


@pytest.mark.unit
@pytest.mark.asyncio
class TestOverviewSection:
    @pytest.mark.parametrize("doc", [None, SimpleNamespace(description="")])
    async def test_a_custom_mcp_without_a_description_has_no_overview(
        self, doc: SimpleNamespace | None
    ) -> None:
        repo = MagicMock()
        repo.get = AsyncMock(return_value=doc)
        with patch(f"{_MOD}.integration_repository", repo):
            result = await _overview_section(CustomMcpSubagent(id="abc123", name="My MCP"))

        assert result == ""
        repo.get.assert_awaited_once_with("abc123")


#: Phrases that only make sense to a delegated worker reporting to a parent. The
#: executor reads these notes about itself, acting in its own turn, so any of them
#: tells it to stop after one call, hand back a report, or call a tool it must not.
_WORKER_ONLY_PHRASES = (
    "delegated task",
    "PRIMARY DIRECTIVE",
    "finish_task",
    "main agent",
    "the parent",
    "activity report",
    "one successful tool call",
)

_PLATFORM_INTEGRATIONS = [sa for sa in all_subagents() if sa.config.system_prompt]


@pytest.mark.unit
@pytest.mark.asyncio
class TestOperatingNotesAddressTheExecutor:
    """The notes activation injects are read by the executor about its own work.

    They were written for per-integration worker graphs that no longer exist, so
    they told the executor it was a delegated worker that stops after one read and
    reports to a parent, which pulls against sweeps that should be split up.
    """

    @pytest.mark.parametrize("subagent", _PLATFORM_INTEGRATIONS, ids=lambda sa: sa.id)
    async def test_notes_carry_no_worker_scaffolding(self, subagent: Subagent) -> None:
        notes = await _overview_section(subagent)

        found = [phrase for phrase in _WORKER_ONLY_PHRASES if phrase.lower() in notes.lower()]
        assert not found, f"{subagent.id} notes still address a delegated worker: {found}"


@pytest.mark.unit
class TestActivationHeader:
    def test_stamped_capped_mcp_server_points_at_retrieve_tools(self) -> None:
        activated = ActivatedTools(total=11, bind=[], preload=[], docs="", preload_capped=True)

        header = _activation_header("posthog", activated, stamped=True)

        assert header == (
            "Integration 'posthog' is now active with 11 tools. "
            f"It exposes more than {MCP_PRELOAD_ALL_MAX} tools, so none are preloaded — "
            "find the ones this task needs with retrieve_tools. "
            "Anything you spawn inherits the bound tools.\n\n"
        )


@pytest.mark.unit
@pytest.mark.asyncio
class TestConnectAndActivateOwnership:
    async def test_custom_mcp_ownership_is_checked_for_this_user_and_integration(self) -> None:
        target = CustomMcpSubagent(id="abc123", name="My MCP")
        owns = AsyncMock(return_value=False)
        with patch(f"{_MOD}.check_user_has_integration", new=owns):
            result = await _connect_and_activate(target, "user1")

        assert result == "Unknown integration 'abc123'."
        owns.assert_awaited_once_with("user1", "abc123")
