"""A run stopped mid tool call leaves its thread one the next run can send to a strict provider."""

from typing import Any, cast

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
import pytest

from app.agents.core.interruption import INTERRUPTED_TOOL_RESULT
from app.agents.core.subagents import subagent_runner
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    execute_subagent_stream,
)

pytestmark = pytest.mark.integration

THREAD = "executor_conv-stop"
CALL_ID = "call_research"


class _StrictProvider:
    """A model that, like OpenAI's Responses API, rejects a tool call with no tool output."""

    def __init__(self) -> None:
        self.stop_requested = False

    def __call__(self, state: MessagesState) -> dict[str, list[AnyMessage]]:
        messages = state["messages"]
        answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
        for message in messages:
            if isinstance(message, AIMessage):
                for call in message.tool_calls:
                    if call["id"] not in answered:
                        raise ValueError(f"No tool output found for function call {call['id']}.")
        if isinstance(messages[-1], HumanMessage) and messages[-1].content == "research":
            call = {"id": CALL_ID, "name": "web_search", "args": {"q": "x"}}
            self.stop_requested = True  # the user sends /stop while the tool runs
            return {"messages": [AIMessage(content="", tool_calls=[call])]}
        return {"messages": [AIMessage(content="todo added")]}


def _tools(state: MessagesState) -> dict[str, list[AnyMessage]]:
    last = cast(AIMessage, state["messages"][-1])
    return {
        "messages": [
            ToolMessage(content="results", tool_call_id=call["id"]) for call in last.tool_calls
        ]
    }


def _route(state: MessagesState) -> str:
    last = state["messages"][-1]
    return "tools" if isinstance(last, AIMessage) and last.tool_calls else END


def _graph(model: _StrictProvider) -> Any:
    builder = StateGraph(MessagesState)
    builder.add_node("agent", model)
    builder.add_node("tools", _tools)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", _route, ["tools", END])
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=InMemorySaver())


def _context(graph: Any, text: str) -> SubagentExecutionContext:
    configurable = {"thread_id": THREAD}
    return SubagentExecutionContext(
        subagent_graph=graph,
        agent_name="executor_agent",
        config=cast(Any, {"configurable": configurable}),
        configurable=cast(Any, configurable),
        integration_id="executor",
        initial_state={"messages": [HumanMessage(content=text)]},
        stream_id="stream-1",
    )


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> _StrictProvider:
    model = _StrictProvider()

    async def stop_requested(stream_id: str) -> bool:
        return model.stop_requested

    monkeypatch.setattr(subagent_runner, "stop_requested", stop_requested)
    return model


async def _thread(graph: Any) -> list[AnyMessage]:
    return (await graph.aget_state({"configurable": {"thread_id": THREAD}})).values["messages"]


async def _closed(graph: Any) -> list[tuple[object, str]]:
    thread = await _thread(graph)
    return [
        (m.content, m.status)
        for m in thread
        if isinstance(m, ToolMessage) and m.tool_call_id == CALL_ID
    ]


async def test_a_stop_mid_tool_call_leaves_the_next_run_working(model: _StrictProvider) -> None:
    """Regression for run 6 bug 24: every executor run after a /stop failed with a 400."""
    graph = _graph(model)
    first = await execute_subagent_stream(ctx=_context(graph, "research"))
    assert first.stopped

    model.stop_requested = False
    await execute_subagent_stream(ctx=_context(graph, "add a todo"))

    assert (await _thread(graph))[-1].content == "todo added"
    assert await _closed(graph) == [(INTERRUPTED_TOOL_RESULT, "error")]
