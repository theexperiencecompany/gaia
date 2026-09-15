"""Guards the bug where record_platform_delivery's write used as_node="agent", whose store-dependent branch made aupdate_state raise and get silently swallowed, so delivered results were never recorded for the next turn."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage
import pytest

from app.agents.core.background.comms_narrator import record_platform_delivery
from tests.e2e._harness.graph_run import comms_graph

pytestmark = pytest.mark.e2e

_FRAME = (
    '[Delivered to the user on Telegram — result of reminder "Standup" (id rem-1)]: '
    "**Standup**\nJoin now"
)


async def _thread_messages(graph: object, thread_id: str) -> list[object]:
    state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    return state.values.get("messages", [])


@pytest.mark.regression
async def test_record_platform_delivery_lands_in_the_real_thread() -> None:
    thread_id = f"conv-{uuid4()}"
    async with comms_graph(["ok"]) as graph:
        with patch(
            "app.agents.core.background.comms_narrator.GraphManager.get_graph",
            new=AsyncMock(return_value=graph),
        ):
            await record_platform_delivery(thread_id, _FRAME)

        messages = await _thread_messages(graph, thread_id)

    # The record is what the NEXT turn reads. With the as_node="agent" bug the
    # write raised on the store key and was swallowed, leaving the thread empty.
    contents = [getattr(m, "content", "") for m in messages]
    assert _FRAME in contents, f"frame not recorded in thread; got {contents!r}"


async def test_as_node_agent_needs_a_store_the_write_cannot_supply() -> None:
    """Pins why the write uses as_node="tools": the agent node's outgoing branch needs a store aupdate_state can't inject, so as_node="agent" raises."""
    thread_id = f"conv-{uuid4()}"
    async with comms_graph(["ok"]) as graph:
        with pytest.raises(ValueError, match="store"):
            await graph.aupdate_state(
                {"configurable": {"thread_id": thread_id}},
                {"messages": [AIMessage(content=_FRAME)]},
                as_node="agent",
            )
        # The tools node's edge is unconditional, so the same write lands there.
        await graph.aupdate_state(
            {"configurable": {"thread_id": thread_id}},
            {"messages": [AIMessage(content=_FRAME)]},
            as_node="tools",
        )
        contents = [getattr(m, "content", "") for m in await _thread_messages(graph, thread_id)]
    assert _FRAME in contents
