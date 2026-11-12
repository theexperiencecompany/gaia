"""Integration test: every out-of-band write into an agent thread lands with a message id.

aupdate_state, unlike a node write or graph input, does not give id-less
messages an id on GAIA's DeltaChannel. An id-less message can never be targeted
by a RemoveMessage, so summarization could neither fold it away nor anchor the
summary on it. Drives the real writers against a real checkpointed State graph.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
import pytest

from app.agents.core.interruption import record_interruption
from app.override.langgraph_bigtool.utils import State

THREAD = "thread-ids"
CONFIG: RunnableConfig = {"configurable": {"thread_id": THREAD}}


async def _seed(graph: CompiledStateGraph, *messages: object) -> None:
    await graph.ainvoke({"messages": list(messages)}, CONFIG)


async def _ids(graph: CompiledStateGraph) -> list[str | None]:
    return [m.id for m in (await graph.aget_state(CONFIG)).values["messages"]]


@pytest.fixture
def thread_graph() -> CompiledStateGraph:
    """Build a checkpointed graph over GAIA's real State."""
    builder = StateGraph(State)
    builder.add_node("tools", lambda _state: {})
    builder.set_entry_point("tools")
    return builder.compile(checkpointer=InMemorySaver())


@pytest.mark.integration
class TestOutOfBandThreadWritesCarryIds:
    async def test_interruption_record(self, thread_graph: CompiledStateGraph) -> None:
        await _seed(thread_graph, HumanMessage("do a thing"))

        await record_interruption(thread_graph, CONFIG)

        ids = await _ids(thread_graph)
        assert len(ids) == 2 and None not in ids

    async def test_interruption_write_is_attributed_to_the_tool_node(self) -> None:
        # Without as_node the write inherits the model node that last wrote, so
        # the checkpoint would queue a tools re-entry on resume.
        builder = StateGraph(State)
        builder.add_node("tools", lambda _state: {})
        builder.add_node("model", lambda _state: {})
        builder.set_entry_point("model")
        builder.add_edge("model", "tools")
        builder.add_edge("tools", END)
        graph = builder.compile(checkpointer=InMemorySaver(), interrupt_after=["model"])

        await graph.ainvoke({"messages": [HumanMessage("do a thing")]}, CONFIG)
        assert (await graph.aget_state(CONFIG)).next == ("tools",)

        await record_interruption(graph, CONFIG)

        snapshot = await graph.aget_state(CONFIG)
        assert snapshot.next == ()
        assert None not in [message.id for message in snapshot.values["messages"]]
