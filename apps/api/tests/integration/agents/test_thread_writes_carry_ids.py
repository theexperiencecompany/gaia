"""Integration test: every out-of-band write into an agent thread lands with a message id.

aupdate_state, unlike a node write or graph input, does not give id-less
messages an id on GAIA's DeltaChannel. An id-less message can never be targeted
by a RemoveMessage, so summarization could neither fold it away nor anchor the
summary on it. Drives the real writers against a real checkpointed State graph.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
import pytest

from app.agents.core.background.comms_narrator import (
    record_exchange_in_thread,
    record_executor_cancellation,
    record_platform_delivery,
)
from app.agents.core.interruption import record_interruption
from app.override.langgraph_bigtool.utils import State

THREAD = "thread-ids"
CONFIG: RunnableConfig = {"configurable": {"thread_id": THREAD}}


@pytest.fixture
def thread_graph() -> Iterator[CompiledStateGraph]:
    """Build a checkpointed graph over GAIA's real State and route the narrator to it."""
    builder = StateGraph(State)
    builder.add_node("tools", lambda _state: {})
    builder.set_entry_point("tools")
    graph = builder.compile(checkpointer=InMemorySaver())
    with patch(
        "app.agents.core.background.comms_narrator.GraphManager.get_graph",
        AsyncMock(return_value=graph),
    ):
        yield graph


async def _seed(graph: CompiledStateGraph, *messages: object) -> None:
    await graph.ainvoke({"messages": list(messages)}, CONFIG)


async def _ids(graph: CompiledStateGraph) -> list[str | None]:
    return [m.id for m in (await graph.aget_state(CONFIG)).values["messages"]]


@pytest.mark.integration
class TestOutOfBandThreadWritesCarryIds:
    async def test_interruption_record(self, thread_graph: CompiledStateGraph) -> None:
        await _seed(thread_graph, HumanMessage("do a thing"))

        await record_interruption(thread_graph, CONFIG)

        ids = await _ids(thread_graph)
        assert len(ids) == 2 and None not in ids

    async def test_executor_cancellation_record(self, thread_graph: CompiledStateGraph) -> None:
        await _seed(thread_graph, HumanMessage("start"))

        await record_executor_cancellation(THREAD, "task-1", "the task")

        ids = await _ids(thread_graph)
        assert len(ids) == 2 and None not in ids

    async def test_platform_delivery_and_exchange(self, thread_graph: CompiledStateGraph) -> None:
        await _seed(thread_graph, HumanMessage("start"), AIMessage("ok"))

        await record_platform_delivery(THREAD, "your report is ready")
        await record_exchange_in_thread(THREAD, "approve", "approved")

        ids = await _ids(thread_graph)
        assert len(ids) == 5 and None not in ids
