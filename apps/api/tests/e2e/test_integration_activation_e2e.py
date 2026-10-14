"""End-to-end: integration activation through the REAL executor graph.

These build the production executor graph (create_agent, the real middleware
stack, the real selected_tool_ids channel) with only the model and the two I/O
seams (store, checkpointer) replaced, plus activate_integration's external
lookups stubbed so the run is deterministic and offline. What they prove is the
wiring unit tests cannot:

* activate_integration's Command(selected_tool_ids=...) still binds the
  integration's INTERNAL helpers for the model's NEXT turn in the compiled
  graph, so a follow-up call is not rejected as unbound.
* the integration tools themselves are NOT bound — their schemas arrive as
  docs in the activation reply — so a follow-up direct call IS rejected as
  unbound (the model must run them via execute).
* a per-user MCP id is routed to handoff by the tool running inside the graph.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool as lc_tool
from langgraph.store.memory import InMemoryStore
import pytest

from app.agents.core.graph_builder.build_graph import (
    EXECUTOR_INITIAL_TOOL_IDS,
    build_executor_graph,
)
from app.agents.core.subagents.handoff_tools import CustomMcpSubagent
from app.agents.tools.todo_tools import TODO_TOOL_NAMES
from tests.helpers import BindableToolsFakeModel

_ACTIVATION_MOD = "app.agents.core.subagents.integration_activation"
_BUILD_MOD = "app.agents.core.graph_builder.build_graph"
_HANDOFF_MOD = "app.agents.core.subagents.handoff_tools"


def _stub_tool(name: str):
    async def _stub(query: str = "") -> str:
        return f"stub:{name}"

    _stub.__name__ = name
    _stub.__doc__ = f"Stub for {name}."
    return lc_tool(_stub)


def _stub_registry(extra_tools: tuple[str, ...] = ()) -> MagicMock:
    """Build a registry whose tool_dict holds the executor's initial tools plus extras.

    The graph injects handoff / activate_integration / todo tools itself, so
    those are left out and overwritten with the real ones.
    """
    injected_by_graph = {"handoff", "activate_integration"} | TODO_TOOL_NAMES
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
            patch(f"{_ACTIVATION_MOD}._get_subagent_by_id", new=AsyncMock(return_value=gmail)),
            patch(
                f"{_ACTIVATION_MOD}.check_integration_connection", new=AsyncMock(return_value=None)
            ),
            patch(
                f"{_ACTIVATION_MOD}._activate_tools",
                new=AsyncMock(return_value=(1, ["helper_tool"], [], "")),
            ),
            patch(f"{_ACTIVATION_MOD}._activation_context", new=AsyncMock(return_value="")),
        ):
            async with build_executor_graph(chat_llm=model, in_memory_checkpointer=True) as graph:
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="send an email")]},
                    config={"configurable": {"thread_id": str(uuid4()), "user_id": str(uuid4())}},
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
            patch(f"{_ACTIVATION_MOD}._get_subagent_by_id", new=AsyncMock(return_value=gmail)),
            patch(
                f"{_ACTIVATION_MOD}.check_integration_connection", new=AsyncMock(return_value=None)
            ),
            patch(
                f"{_ACTIVATION_MOD}._activate_tools",
                new=AsyncMock(return_value=(1, [], ["gmail_send"], docs)),
            ),
            patch(f"{_ACTIVATION_MOD}._activation_context", new=AsyncMock(return_value="")),
        ):
            async with build_executor_graph(chat_llm=model, in_memory_checkpointer=True) as graph:
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="send an email")]},
                    config={"configurable": {"thread_id": str(uuid4()), "user_id": str(uuid4())}},
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

    async def test_per_user_mcp_is_routed_to_handoff(self) -> None:
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
                AIMessage(content="ok"),
            ]
        )
        registry = _stub_registry()
        custom = CustomMcpSubagent(id="abc123", name="My MCP", managed_by="mcp", mcp_config={})

        p1, p2, p3, p4 = _run_executor(model, registry)
        with (
            p1,
            p2,
            p3,
            p4,
            patch(f"{_ACTIVATION_MOD}._get_subagent_by_id", new=AsyncMock(return_value=custom)),
            patch(f"{_ACTIVATION_MOD}._activate_tools", new=AsyncMock()) as activate_tools,
        ):
            async with build_executor_graph(chat_llm=model, in_memory_checkpointer=True) as graph:
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="use my mcp")]},
                    config={"configurable": {"thread_id": str(uuid4()), "user_id": str(uuid4())}},
                )

        activation = _tool_message_for(result, "a1")
        assert activation and "handoff(" in activation.text
        activate_tools.assert_not_awaited()

    async def test_handoff_runs_when_the_agent_follows_the_redirect(self) -> None:
        """The other half of the redirect: handoff must actually work."""

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
                            "name": "handoff",
                            "args": {"subagent_id": "abc123", "task": "do the thing"},
                            "id": "h1",
                        }
                    ],
                ),
                AIMessage(content="done"),
            ]
        )
        registry = _stub_registry()
        custom = CustomMcpSubagent(id="abc123", name="My MCP", managed_by="mcp", mcp_config={})

        # Short-circuit handoff at its resolution seam: a returned error string is
        # proof its body executed, without building a real per-user graph here.
        resolved = AsyncMock(return_value=(None, None, "SUBAGENT_RAN::abc123"))

        p1, p2, p3, p4 = _run_executor(model, registry)
        with (
            p1,
            p2,
            p3,
            p4,
            patch(f"{_ACTIVATION_MOD}._get_subagent_by_id", new=AsyncMock(return_value=custom)),
            patch(f"{_HANDOFF_MOD}.prepare_subagent_execution", new=resolved),
        ):
            async with build_executor_graph(chat_llm=model, in_memory_checkpointer=True) as graph:
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="use my mcp")]},
                    config={"configurable": {"thread_id": str(uuid4()), "user_id": str(uuid4())}},
                )

        activation = _tool_message_for(result, "a1")
        assert activation and "handoff(" in activation.text

        handed_off = _tool_message_for(result, "h1")
        assert handed_off, "handoff never ran — the redirect points at an unreachable tool"
        assert "is not bound" not in handed_off.text, handed_off.text
        assert "SUBAGENT_RAN::abc123" in handed_off.text
        resolved.assert_awaited_once()
