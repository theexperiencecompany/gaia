"""End-to-end: ENABLE_INTEGRATION_ACTIVATION through the REAL executor graph.

These build the production executor graph (create_agent, the real middleware
stack, the real selected_tool_ids channel) with only the model and the two I/O
seams (store, checkpointer) replaced, plus activate_integration's external
lookups stubbed so the run is deterministic and offline. What they prove is the
wiring unit tests cannot:

* activate_integration's Command(selected_tool_ids=...) actually binds the
  integration's tools for the model's NEXT turn in the compiled graph, so a
  follow-up call is not rejected as unbound.
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
from app.agents.tools.todo_tools import TODO_TOOL_NAMES
from app.config.settings import settings
from app.constants.general import WAIT_FOR_SUBAGENTS_NAME
from tests.helpers import BindableToolsFakeModel

_ACTIVATION_MOD = "app.agents.core.subagents.integration_activation"
_BUILD_MOD = "app.agents.core.graph_builder.build_graph"


def _stub_tool(name: str):
    async def _stub(query: str = "") -> str:
        return f"stub:{name}"

    _stub.__name__ = name
    _stub.__doc__ = f"Stub for {name}."
    return lc_tool(_stub)


def _stub_registry(extra_tools: tuple[str, ...] = ()) -> MagicMock:
    """A registry whose tool_dict holds the executor's initial tools plus extras.

    The graph injects handoff / wait_for_subagents / activate_integration / todo
    tools itself, so those are left out and overwritten with the real ones.
    """
    injected_by_graph = {
        "handoff",
        "activate_integration",
        WAIT_FOR_SUBAGENTS_NAME,
    } | TODO_TOOL_NAMES
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
    """The ToolMessage answering a specific tool call.

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
    async def test_activated_tool_is_bound_for_the_next_turn(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ENABLE_INTEGRATION_ACTIVATION", True)

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
                new=AsyncMock(return_value=(1, ["gmail_send"])),
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

        # The point: activate_integration bound gmail_send for the next turn via
        # the real selected_tool_ids channel, so the follow-up call executes
        # instead of being rejected as unbound.
        sent = _tool_message_for(result, "g1")
        assert sent, "gmail_send never ran — the activated tool was not bound for the next turn"
        assert "is not bound" not in sent.text, sent.text
        assert "stub:gmail_send" in sent.text

    async def test_per_user_mcp_is_routed_to_handoff(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ENABLE_INTEGRATION_ACTIVATION", True)

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
        custom = {"id": "abc123", "name": "My MCP", "managed_by": "mcp", "mcp_config": {}}

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
