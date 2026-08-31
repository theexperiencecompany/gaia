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

from app.agents.tools.core.registry import CategoryOptions, ToolRegistry
from app.constants.general import FINISH_TASK_NAME
from app.models.mcp_config import MCPConfig, SubAgentConfig
from app.models.subagent_models import Subagent
from app.services.workflow.playbook.tool_space import (
    SubagentTools,
    ToolSpace,
    handoff_tool_space,
    resolve_subagent_tools,
    tool_space_denial,
)

MODULE = "app.services.workflow.playbook.tool_space"
PROVIDER_MODULE = "app.agents.core.subagents.provider_subagents"

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
    registry._add_category(
        SUBAGENT_ID, tools=[_tool(REGISTRY_TOOL)], options=CategoryOptions(space=TOOL_SPACE)
    )
    return registry


def _subagent(
    *,
    mcp: bool,
    include_finish_task: bool = True,
    disable_retrieve_tools: bool = False,
    auto_bind_tools: list[str] | None = None,
) -> Subagent:
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
            use_direct_tools=disable_retrieve_tools,
            disable_retrieve_tools=disable_retrieve_tools,
            auto_bind_tools=auto_bind_tools,
        ),
        mcp_config=MCPConfig(server_url="https://mcp.example/sse") if mcp else None,
    )


def _lookup(subagent: Subagent):
    """A registry lookup that answers only for the id it actually holds."""
    return lambda subagent_id: subagent if subagent_id == subagent.id else None


def _composio_integration(integration_id: str) -> MagicMock:
    """The OAuth integration a Composio subagent's toolkit is read from."""
    assert integration_id == SUBAGENT_ID
    integration = MagicMock()
    integration.composio_config.toolkit = SUBAGENT_ID
    return integration


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
    @pytest.fixture(autouse=True)
    def _composio_toolkit_lookup(self):
        with patch(f"{PROVIDER_MODULE}.get_integration_by_id", _composio_integration):
            yield

    async def test_a_composio_subagent_on_a_cold_worker_loads_its_toolkit_first(self) -> None:
        """The live handoff registers a Composio toolkit on demand. A replay on a
        worker that has never handed off to that subagent must do the same, or it
        resolves an empty space and stops at the first real step (seen live:
        "no tool named 'GMAIL_FETCH_MESSAGES' is available" three minutes after
        a worker restart)."""
        subagent = _subagent(mcp=False)
        registry = ToolRegistry()

        async def register(
            toolkit_name: str,
            space_name: str,
            specific_tools: list[str] | None = None,
            exclude_tools: list[str] | None = None,
        ) -> None:
            assert (toolkit_name, space_name) == (SUBAGENT_ID, TOOL_SPACE)
            registry._add_category(
                SUBAGENT_ID,
                tools=[_tool(REGISTRY_TOOL)],
                options=CategoryOptions(space=TOOL_SPACE),
            )

        with (
            patch(f"{MODULE}.get_subagent_by_id", _lookup(subagent)),
            patch.object(registry, "register_provider_tools", side_effect=register),
        ):
            space = await resolve_subagent_tools(SUBAGENT_ID, USER_ID, registry)

        assert space is not None
        assert REGISTRY_TOOL in space.tools

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
        assert space.subagent is subagent

    async def test_the_live_tools_are_also_in_the_ids_the_handoff_binds(self) -> None:
        """Being in the space is not enough. The runner builds the handoff's
        runtime config from ``initial_tool_ids``, and a subagent that cannot
        retrieve refuses every tool outside that set — so a live MCP tool merged
        only into ``tools`` was accepted by the validator and then refused by the
        replay as "outside the bound tool set"."""
        subagent = _subagent(mcp=True)

        with (
            patch(f"{MODULE}.get_subagent_by_id", _lookup(subagent)),
            patch(f"{MODULE}.get_mcp_client", _mcp_client([_tool(LIVE_MCP_TOOL)])),
        ):
            space = await resolve_subagent_tools(SUBAGENT_ID, USER_ID, _registry())

        assert space is not None
        assert space.initial_tool_ids == [REGISTRY_TOOL, FINISH_TASK_NAME, LIVE_MCP_TOOL]

    async def test_a_live_tool_that_shadows_a_registry_one_is_bound_once(self) -> None:
        subagent = _subagent(mcp=True)

        with (
            patch(f"{MODULE}.get_subagent_by_id", _lookup(subagent)),
            patch(f"{MODULE}.get_mcp_client", _mcp_client([_tool(REGISTRY_TOOL)])),
        ):
            space = await resolve_subagent_tools(SUBAGENT_ID, USER_ID, _registry())

        assert space is not None
        assert space.initial_tool_ids == [REGISTRY_TOOL, FINISH_TASK_NAME]

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


@pytest.mark.unit
class TestToolSpaceDenial:
    """One answer to "may this step run here", read by the validator at write
    time and the runner at replay. A subagent's scoped dict holds more than it
    can bind (the always-available tools), so membership alone accepted
    playbooks the replay then refused at the first child step."""

    ALWAYS_AVAILABLE = "grep"

    def _space(self, subagent: Subagent | None) -> ToolSpace:
        return handoff_tool_space(
            SubagentTools(
                tools={REGISTRY_TOOL: _tool(REGISTRY_TOOL), self.ALWAYS_AVAILABLE: _tool("grep")},
                initial_tool_ids=[REGISTRY_TOOL],
                subagent=subagent,
            )
        )

    def test_a_subagent_that_cannot_retrieve_refuses_a_tool_it_only_sees(self) -> None:
        space = self._space(_subagent(mcp=False, disable_retrieve_tools=True))

        assert tool_space_denial(self.ALWAYS_AVAILABLE, space) == (
            "grep is outside the bound tool set of this handoff, which cannot retrieve"
        )
        assert tool_space_denial(REGISTRY_TOOL, space) is None

    def test_a_subagent_that_can_retrieve_runs_anything_in_its_space(self) -> None:
        space = self._space(_subagent(mcp=False))

        assert tool_space_denial(self.ALWAYS_AVAILABLE, space) is None
        assert tool_space_denial(REGISTRY_TOOL, space) is None

    def test_the_handoff_space_carries_the_subagents_identity(self) -> None:
        space = self._space(_subagent(mcp=False, disable_retrieve_tools=True))

        assert space.subagent_id == SUBAGENT_ID
        assert space.runtime is not None
        assert space.runtime.enable_retrieve_tools is False
        assert REGISTRY_TOOL in space.runtime.initial_tool_names

    def test_the_handoff_runtime_binds_exactly_what_the_subagent_declares(self) -> None:
        """The validator and the runner build this runtime from the same call, so
        the bound set has to be the subagent's own: its auto-bind tools and its
        finish_task, in the order the builder produces them. A set that quietly
        loses either is a playbook accepted at write time and refused at replay."""
        space = self._space(_subagent(mcp=False, auto_bind_tools=["posthog_fast"]))

        assert space.runtime is not None
        assert space.runtime.initial_tool_names == [
            "search_memory",
            "read",
            "bash",
            "finish_task",
            "posthog_fast",
        ]

    def test_an_answer_only_subagent_binds_no_finish_task(self) -> None:
        """``include_finish_task=False`` is how an answer-only subagent terminates
        with a plain message; defaulting it back to True binds a tool the live
        subagent never had."""
        space = self._space(_subagent(mcp=False, include_finish_task=False))

        assert space.runtime is not None
        assert space.runtime.initial_tool_names == ["search_memory", "read", "bash"]

    def test_tools_with_no_subagent_behind_them_have_no_runtime_bound(self) -> None:
        space = self._space(None)

        assert space.runtime is None
        assert space.subagent_id is None
        assert tool_space_denial(self.ALWAYS_AVAILABLE, space) is None

    def test_a_tool_missing_from_a_handoff_names_the_space(self) -> None:
        space = self._space(_subagent(mcp=False))

        assert tool_space_denial("send_owl", space) == (
            "no tool named 'send_owl' is available in this run's tool space"
        )

    def test_a_tool_missing_at_top_level_simply_does_not_exist(self) -> None:
        space = ToolSpace(
            tools={REGISTRY_TOOL: _tool(REGISTRY_TOOL)}, runtime=None, subagent_id=None
        )

        assert tool_space_denial("send_owl", space) == "no tool named 'send_owl' exists"
