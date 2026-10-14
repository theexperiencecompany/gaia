"""Behavior tests for app.agents.core.background.thread_record.

A message that bypassed the comms graph must still land in the thread the next
turn reads: the comms graph's checkpoint, written as the tools node.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.agents.core.background.thread_record import (
    record_exchange_in_thread,
    record_platform_delivery,
)
from app.constants.log_tags import LogTag
from tests.helpers import captured_wide_event

MODULE = "app.agents.core.background.thread_record"
CONVERSATION_ID = "conv-1"


def _fake_comms_graph() -> MagicMock:
    graph = MagicMock()
    graph.aupdate_state = AsyncMock()
    return graph


def _patch_graph(graph: MagicMock) -> MagicMock:
    return patch(f"{MODULE}.GraphManager.get_graph", AsyncMock(return_value=graph))


class TestRecordPlatformDelivery:
    async def test_delivered_message_is_appended_to_the_checkpoint(self) -> None:
        graph = _fake_comms_graph()
        get_graph = AsyncMock(return_value=graph)
        with patch(f"{MODULE}.GraphManager.get_graph", get_graph):
            await record_platform_delivery(CONVERSATION_ID, "Report is ready. It has 3 pages.")

        # The comms graph specifically — a wrong graph writes into a thread
        # whose next turn would read a message it never sent.
        get_graph.assert_awaited_once_with("comms_agent")
        graph.aupdate_state.assert_awaited_once()
        call = graph.aupdate_state.await_args
        assert call.args[0] == {"configurable": {"thread_id": CONVERSATION_ID}}
        # as_node="tools": as "agent" makes aupdate_state evaluate should_continue,
        # which needs a store it cannot inject, so the write raises and is lost.
        assert call.kwargs["as_node"] == "tools"
        messages = call.args[1]["messages"]
        assert len(messages) == 1
        assert isinstance(messages[0], AIMessage)
        assert messages[0].content == "Report is ready. It has 3 pages."

    async def test_blank_text_is_a_no_op(self) -> None:
        graph = _fake_comms_graph()
        with _patch_graph(graph):
            await record_platform_delivery(CONVERSATION_ID, "   ")

        graph.aupdate_state.assert_not_called()

    async def test_failure_to_record_is_swallowed_and_reported_on_the_wide_event(self) -> None:
        """A checkpoint failure must not break the caller, but log.error must land in the wide event's errors[]."""
        graph = _fake_comms_graph()
        graph.aupdate_state = AsyncMock(side_effect=RuntimeError("checkpoint down"))
        with _patch_graph(graph):
            async with captured_wide_event() as event:
                await record_platform_delivery(CONVERSATION_ID, "hello")

        (error,) = [e for e in event["errors"] if "Failed to record" in e["msg"]]
        assert error["msg"] == (f"{LogTag.AGENT} Failed to record messages in conversation thread")
        assert error["conversation_id"] == CONVERSATION_ID
        assert error["error"] == "checkpoint down"


class TestRecordExchangeInThread:
    async def test_the_user_message_and_reply_are_appended_in_order(self) -> None:
        """A reply that resolved a paused task never ran the graph; the thread must still hold both turns."""
        graph = _fake_comms_graph()
        with _patch_graph(graph):
            await record_exchange_in_thread(CONVERSATION_ID, "cancel that step", "Cancelled it.")

        call = graph.aupdate_state.await_args
        assert call.args[0] == {"configurable": {"thread_id": CONVERSATION_ID}}
        assert call.kwargs["as_node"] == "tools"
        user_turn, reply = call.args[1]["messages"]
        assert isinstance(user_turn, HumanMessage)
        assert user_turn.content == "cancel that step"
        assert isinstance(reply, AIMessage)
        assert reply.content == "Cancelled it."
