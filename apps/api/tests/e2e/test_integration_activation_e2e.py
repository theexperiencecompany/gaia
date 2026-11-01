"""End-to-end: integration activation through the REAL executor graph.

These build the production executor graph (create_agent, the real middleware
stack, the real selected_tool_ids channel) with only the model, the two I/O
seams (store, checkpointer) and activate_integration's external lookups
replaced, so the run is deterministic and offline. They prove wiring unit tests cannot:
* activate_integration's Command(selected_tool_ids=...) still binds the
  integration's INTERNAL helpers for the model's NEXT turn in the compiled
  graph, so a follow-up call is not rejected as unbound.
* the integration tools themselves are NOT bound — their schemas arrive as
  docs in the activation reply — so a follow-up direct call IS rejected as
  unbound (the model must run them via execute).
* a per-user MCP activates in-context with nothing bound, and the executor's
  real execute proxy runs one of its tools on the next turn through the
  user's MCP client.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from bson import ObjectId
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool as lc_tool
from langgraph.store.memory import InMemoryStore
import pytest

from app.agents.core.graph_builder.build_graph import (
    EXECUTOR_INITIAL_TOOL_IDS,
    build_executor_graph,
)
from app.agents.core.subagents.integration_activation import ActivatedTools
from app.agents.core.subagents.integration_resolution import CustomMcpSubagent
from app.agents.tools.execute.execute_tool import execute
from app.agents.tools.todo_tools import TODO_TOOL_NAMES
from app.models.hil_models import HILPreferences
from tests.helpers import BindableToolsFakeModel

_ACTIVATION_MOD = "app.agents.core.subagents.integration_activation"
_BUILD_MOD = "app.agents.core.graph_builder.build_graph"
_RESOLVER_MOD = "app.agents.tools.execute.resolver"
_DISPATCH_MOD = "app.agents.tools.execute.dispatch"


def _stub_tool(name: str):
    async def _stub(query: str = "") -> str:
        return f"stub:{name}"

    _stub.__name__ = name
    _stub.__doc__ = f"Stub for {name}."
    return lc_tool(_stub)


def _stub_registry(extra_tools: tuple[str, ...] = ()) -> MagicMock:
    """Build a registry whose tool_dict holds the executor's initial tools plus extras.

    The graph injects activate_integration / todo tools itself, so those are
    left out and overwritten with the real ones.
    """
    injected_by_graph = {"activate_integration"} | TODO_TOOL_NAMES
    names = [n for n in EXECUTOR_INITIAL_TOOL_IDS if n not in injected_by_graph]
    tool_dict = {n: _stub_tool(n) for n in [*names, *extra_tools]}
    registry = MagicMock()
    registry.get_tool_dict.return_value = tool_dict
    return registry


async def _fake_retrieve_tools(store, config, query=None, exact_tool_names=None):
    """Minimal stub with proper signature for StructuredTool.from_function."""
    return {"tools_to_bind": [], "response": []}


def _run_executor(model: BindableToolsFakeModel, registry: MagicMock):
    return (
        patch(f"{_BUILD_MOD}.get_tool_registry", new_callable=AsyncMock, return_value=registry),
        patch(
            f"{_BUILD_MOD}.get_tools_store", new_callable=AsyncMock, return_value=InMemoryStore()
        ),
        patch(f"{_BUILD_MOD}.get_retrieve_tools_function", return_value=_fake_retrieve_tools),
        patch(f"{_BUILD_MOD}.get_checkpointer_manager", new_callable=AsyncMock, return_value=None),
    )


def _tool_message_for(result: dict, call_id: str) -> ToolMessage | None:
    """Build the ToolMessage answering a specific tool call.

    Matched by tool_call_id, not name: a tool that returns a Command builds its
    ToolMessage by hand without a name (activate_integration does), so name is
    unreliable while the call id always round-trips.
    """
    for m in result["messages"]:
        if isinstance(m, ToolMessage) and m.tool_call_id == call_id:
            return m
    return None


@pytest.mark.asyncio
class TestActivationThroughRealExecutorGraph:
    async def test_activated_helper_is_bound_for_the_next_turn(self) -> None:
        model = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "activate_integration",
                            "args": {"integration_id": "gmail"},
                            "id": "a1",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[{"name": "helper_tool", "args": {}, "id": "g1"}],
                ),
                AIMessage(content="done"),
            ]
        )
        registry = _stub_registry(extra_tools=("helper_tool",))

        gmail = MagicMock()
        gmail.managed_by = "composio"
        gmail.mcp_config = None

        p1, p2, p3, p4 = _run_executor(model, registry)
        with (
            p1,
            p2,
            p3,
            p4,
            patch(f"{_ACTIVATION_MOD}.get_integration_target", new=AsyncMock(return_value=gmail)),
            patch(
                f"{_ACTIVATION_MOD}.check_integration_connection", new=AsyncMock(return_value=None)
            ),
            patch(
                f"{_ACTIVATION_MOD}._activate_tools",
                new=AsyncMock(return_value=ActivatedTools(1, ["helper_tool"], [], "")),
            ),
            patch(f"{_ACTIVATION_MOD}._activation_context", new=AsyncMock(return_value="")),
        ):
            async with build_executor_graph(chat_llm=model, in_memory_checkpointer=True) as graph:
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="send an email")]},
                    config={
                        "configurable": {"thread_id": str(uuid4()), "user_id": str(ObjectId())}
                    },
                )

        activation = _tool_message_for(result, "a1")
        assert activation and "is now active" in activation.text

        # The point: activate_integration bound helper_tool for the next turn via
        # the real selected_tool_ids channel, so the follow-up call executes
        # instead of being rejected as unbound.
        sent = _tool_message_for(result, "g1")
        assert sent, "helper_tool never ran — the activated helper was not bound for the next turn"
        assert "is not bound" not in sent.text, sent.text
        assert "stub:helper_tool" in sent.text

    async def test_activated_integration_tool_is_documented_not_bound(
        self,
    ) -> None:
        model = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "activate_integration",
                            "args": {"integration_id": "gmail"},
                            "id": "a1",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[{"name": "gmail_send", "args": {}, "id": "g1"}],
                ),
                AIMessage(content="done"),
            ]
        )
        registry = _stub_registry(extra_tools=("gmail_send",))

        gmail = MagicMock()
        gmail.managed_by = "composio"
        gmail.mcp_config = None

        docs = "1 integration tool(s) preloaded below.\n## GMAIL_SEND"
        p1, p2, p3, p4 = _run_executor(model, registry)
        with (
            p1,
            p2,
            p3,
            p4,
            patch(f"{_ACTIVATION_MOD}.get_integration_target", new=AsyncMock(return_value=gmail)),
            patch(
                f"{_ACTIVATION_MOD}.check_integration_connection", new=AsyncMock(return_value=None)
            ),
            patch(
                f"{_ACTIVATION_MOD}._activate_tools",
                new=AsyncMock(return_value=ActivatedTools(1, [], ["gmail_send"], docs)),
            ),
            patch(f"{_ACTIVATION_MOD}._activation_context", new=AsyncMock(return_value="")),
        ):
            async with build_executor_graph(chat_llm=model, in_memory_checkpointer=True) as graph:
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="send an email")]},
                    config={
                        "configurable": {"thread_id": str(uuid4()), "user_id": str(ObjectId())}
                    },
                )

        activation = _tool_message_for(result, "a1")
        assert activation and "is now active" in activation.text
        # The schemas arrive as docs in the reply, marked NOT bound.
        assert "## GMAIL_SEND" in activation.text
        assert "NOT bound" in activation.text

        # And the proxy cutover holds at graph level: a direct call of the
        # preloaded tool is rejected as unbound — the model must use execute.
        sent = _tool_message_for(result, "g1")
        assert sent, "gmail_send call vanished instead of being rejected"
        assert "is not bound" in sent.text, sent.text

    async def test_a_custom_mcp_activates_and_execute_runs_its_tool_next_turn(self) -> None:
        """No per-user graph: the executor's own execute proxy reaches the MCP tool by user."""

        @lc_tool
        async def lookup_paper(query: str) -> str:
            """Look up a paper."""
            return f"paper:{query}"

        mcp_client = MagicMock()
        mcp_client.tools_for = AsyncMock(return_value=[lookup_paper])
        mcp_client.get_tools = AsyncMock(return_value=[lookup_paper])
        mcp_client.find_integration = MagicMock(return_value="abc123")
        mcp_client.resolve_tool_owner = AsyncMock(return_value="abc123")

        model = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "activate_integration",
                            "args": {"integration_id": "abc123"},
                            "id": "a1",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "execute",
                            "args": {
                                "task_description": "Looking up the paper",
                                "tool_name": "lookup_paper",
                                "data": {"query": "attention"},
                            },
                            "id": "e1",
                        }
                    ],
                ),
                AIMessage(content="done"),
            ]
        )
        registry = _stub_registry()
        # The real proxy, not a stub: the point is that it resolves the MCP tool.
        registry.get_tool_dict.return_value["execute"] = execute
        resolver_registry = MagicMock()
        resolver_registry.get_tool_meta.return_value = None
        resolver_registry.get_tool_names.return_value = []
        custom = CustomMcpSubagent(id="abc123", name="Scholar", managed_by="mcp", mcp_config={})
        docs = "1 integration tool(s) preloaded below.\n## lookup_paper"

        p1, p2, p3, p4 = _run_executor(model, registry)
        with (
            p1,
            p2,
            p3,
            p4,
            patch(f"{_ACTIVATION_MOD}.get_integration_target", new=AsyncMock(return_value=custom)),
            patch(f"{_ACTIVATION_MOD}.check_mcp_connection", new=AsyncMock(return_value=None)),
            patch(f"{_ACTIVATION_MOD}.get_mcp_client", new=AsyncMock(return_value=mcp_client)),
            patch(f"{_ACTIVATION_MOD}.render_preload_block", new=AsyncMock(return_value=docs)),
            patch(f"{_ACTIVATION_MOD}._has_several_accounts", new=AsyncMock(return_value=False)),
            patch(f"{_ACTIVATION_MOD}._activation_context", new=AsyncMock(return_value="")),
            patch(
                f"{_RESOLVER_MOD}.get_tool_registry",
                new=AsyncMock(return_value=resolver_registry),
            ),
            patch(f"{_RESOLVER_MOD}.get_mcp_client", new=AsyncMock(return_value=mcp_client)),
            patch(f"{_DISPATCH_MOD}.record_observed_shape", new=AsyncMock()),
            patch(f"{_DISPATCH_MOD}.capture"),
            patch(
                "app.services.hil.policy.get_hil_preferences",
                new=AsyncMock(return_value=HILPreferences()),
            ),
        ):
            async with build_executor_graph(chat_llm=model, in_memory_checkpointer=True) as graph:
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="find the attention paper")]},
                    config={
                        "configurable": {"thread_id": str(uuid4()), "user_id": str(ObjectId())}
                    },
                )

        activation = _tool_message_for(result, "a1")
        assert activation and "is now active with 1 tools" in activation.text
        assert "## lookup_paper" in activation.text
        assert "handoff" not in activation.text
        mcp_client.tools_for.assert_any_await("abc123")

        ran = _tool_message_for(result, "e1")
        assert ran, "execute never answered — the activated MCP tool was unreachable"
        assert "paper:attention" in ran.text, ran.text
