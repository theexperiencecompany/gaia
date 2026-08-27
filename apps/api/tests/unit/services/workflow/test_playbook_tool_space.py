"""Resolving the tool space a playbook handoff is allowed to reach.

The validator and the replay runner both resolve a handoff through this one
function, so whatever it decides is the definition of "this tool exists". Get
it wrong and the failure is silent and one-sided: a correct playbook is refused
for naming a tool the user really has, or a playbook is accepted and then
replayed against a tool space that never contained it. The MCP case is the one
that proved it, because those tools live only on the user's own client and are
absent from the global registry entirely.
"""

from unittest.mock import MagicMock, patch

from langchain_core.tools import BaseTool
import pytest

from app.agents.tools.core.registry import ToolRegistry
from app.constants.general import FINISH_TASK_NAME
from app.models.mcp_config import MCPConfig, SubAgentConfig
from app.models.subagent_models import Subagent
from app.services.workflow.playbook.tool_space import resolve_subagent_tools

MODULE = "app.services.workflow.playbook.tool_space"

USER_ID = "user-1"
SUBAGENT_ID = "posthog"
TOOL_SPACE = "posthog_space"
REGISTRY_TOOL = "posthog_read_insight"
LIVE_MCP_TOOL = "posthog_exec"


def _tool(name: str) -> BaseTool:
    tool = MagicMock(spec=BaseTool)
    tool.name = name
    return tool


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry._add_category(SUBAGENT_ID, tools=[_tool(REGISTRY_TOOL)], space=TOOL_SPACE)
    return registry


def _subagent(*, mcp: bool, include_finish_task: bool = True) -> Subagent:
    return Subagent(
        id=SUBAGENT_ID,
        name="PostHog",
        provider=SUBAGENT_ID,
        managed_by="mcp" if mcp else "composio",
        config=SubAgentConfig(
            agent_name=f"{SUBAGENT_ID}_agent",
            tool_space=TOOL_SPACE,
            handoff_tool_name=f"handoff_to_{SUBAGENT_ID}",
            domain="analytics",
            capabilities="c",
            use_cases="u",
            system_prompt="p",
            include_finish_task=include_finish_task,
        ),
        mcp_config=MCPConfig(server_url="https://mcp.example/sse") if mcp else None,
    )


def _lookup(subagent: Subagent):
    """A registry lookup that answers only for the id it actually holds."""
    return lambda subagent_id: subagent if subagent_id == subagent.id else None


def _mcp_client(tools: list[BaseTool]):
    """A client that hands back ``tools`` only for this user and this subagent."""

    async def ensure_connected(subagent_id: str) -> list[BaseTool]:
        assert subagent_id == SUBAGENT_ID
        return tools

    client = MagicMock()
    client.ensure_connected = ensure_connected

    async def get_client(user_id: str) -> MagicMock:
        if user_id != USER_ID:
            raise LookupError(f"no MCP client for {user_id!r}")
        return client

    return get_client


@pytest.mark.unit
class TestSubagentResolution:
    async def test_an_unknown_subagent_resolves_to_nothing(self) -> None:
        """A handoff naming a subagent that does not exist has no tool space at all.

        The caller distinguishes "no such subagent" from "subagent with no
        reachable tools", and only the first is an authoring mistake worth
        refusing the playbook over.
        """
        with patch(f"{MODULE}.get_subagent_by_id", _lookup(_subagent(mcp=False))):
            assert await resolve_subagent_tools("not_a_subagent", USER_ID, _registry()) is None

    async def test_a_non_mcp_subagent_resolves_to_its_registry_scoped_tools(self) -> None:
        """A Composio-style subagent's space comes from the registry category.

        This is the path the validator takes for most handoffs, so a step naming
        a tool in the category must resolve, and the ids the subagent binds at
        startup must come back with it.
        """
        subagent = _subagent(mcp=False)

        with patch(f"{MODULE}.get_subagent_by_id", _lookup(subagent)):
            space = await resolve_subagent_tools(SUBAGENT_ID, USER_ID, _registry())

        assert space is not None
        assert REGISTRY_TOOL in space.tools
        assert space.initial_tool_ids == [REGISTRY_TOOL, FINISH_TASK_NAME]
        assert space.subagent is subagent

    async def test_a_subagent_that_never_finishes_explicitly_binds_no_finish_task(self) -> None:
        """``include_finish_task`` is honoured, not assumed.

        A read-only subagent terminates with an AIMessage instead; binding
        finish_task anyway would let a replay name a tool the live run cannot.
        """
        subagent = _subagent(mcp=False, include_finish_task=False)

        with patch(f"{MODULE}.get_subagent_by_id", _lookup(subagent)):
            space = await resolve_subagent_tools(SUBAGENT_ID, USER_ID, _registry())

        assert space is not None
        assert space.initial_tool_ids == [REGISTRY_TOOL]
        assert FINISH_TASK_NAME not in space.tools


@pytest.mark.unit
class TestMcpBackedSubagent:
    """An MCP subagent's tools exist only on the user's own client.

    They are fetched per user at connect time, so a recorded step naming one is
    absent from the global registry. If they are not merged in here, every such
    playbook is refused for naming a tool that genuinely exists.
    """

    async def test_it_merges_the_users_live_tools_over_the_scoped_ones(self) -> None:
        subagent = _subagent(mcp=True)

        with (
            patch(f"{MODULE}.get_subagent_by_id", _lookup(subagent)),
            patch(f"{MODULE}.get_mcp_client", _mcp_client([_tool(LIVE_MCP_TOOL)])),
        ):
            space = await resolve_subagent_tools(SUBAGENT_ID, USER_ID, _registry())

        assert space is not None
        assert LIVE_MCP_TOOL in space.tools
        assert REGISTRY_TOOL in space.tools
        assert space.initial_tool_ids == [REGISTRY_TOOL, FINISH_TASK_NAME]
        assert space.subagent is subagent

    async def test_an_unreachable_integration_yields_an_empty_tool_set(self) -> None:
        """A briefly down integration must not kill authoring or replay.

        The caller decides what an empty tool space means. Raising here would
        instead fail the whole workflow run over a transient connection error.
        """
        subagent = _subagent(mcp=True)

        async def unreachable(user_id: str) -> MagicMock:
            client = MagicMock()

            async def ensure_connected(subagent_id: str) -> list[BaseTool]:
                raise ConnectionError("integration is down")

            client.ensure_connected = ensure_connected
            return client

        with (
            patch(f"{MODULE}.get_subagent_by_id", _lookup(subagent)),
            patch(f"{MODULE}.get_mcp_client", unreachable),
        ):
            space = await resolve_subagent_tools(SUBAGENT_ID, USER_ID, _registry())

        assert space is not None
        assert space.tools == {}
        assert space.initial_tool_ids == [REGISTRY_TOOL, FINISH_TASK_NAME]
        assert space.subagent is subagent

    async def test_the_unreachable_warning_names_the_subagent_and_the_failure(self) -> None:
        """An empty tool space is indistinguishable from a real one without this.

        A playbook refused because an integration was down and one refused
        because the tool was never there produce the same user-visible outcome,
        so the wide event is the only way to tell them apart in production.
        """
        subagent = _subagent(mcp=True)

        async def unreachable(user_id: str) -> MagicMock:
            raise TimeoutError("connect timed out")

        with (
            patch(f"{MODULE}.get_subagent_by_id", _lookup(subagent)),
            patch(f"{MODULE}.get_mcp_client", unreachable),
            patch(f"{MODULE}.log") as log,
        ):
            await resolve_subagent_tools(SUBAGENT_ID, USER_ID, _registry())

        assert log.warning.call_count == 1
        assert "Could not reach an integration's tools" in log.warning.call_args.args[0]
        assert log.warning.call_args.kwargs["subagent_id"] == SUBAGENT_ID
        assert log.warning.call_args.kwargs["error_type"] == "TimeoutError"
