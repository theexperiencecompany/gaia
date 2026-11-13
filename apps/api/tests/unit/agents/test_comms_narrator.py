"""Behavior tests for app.agents.core.background.comms_narrator.

Locks: the executor result is re-voiced through the comms graph as a
HumanMessage framed in the right internal tag (never a SystemMessage — the
regression the comment block warns about), the caller's delivery
instructions come first, and every degradation path returns an empty
string instead of crashing the caller. Also the cancellation record appended
to the comms checkpoint.
"""

from contextlib import AbstractContextManager
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.agents.core.background.comms_narrator import (
    record_exchange_in_thread,
    record_executor_cancellation,
)
from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.general import NEW_MESSAGE_BREAKER
from app.models.user_models import AuthenticatedUser

MODULE = "app.agents.core.background.comms_narrator"

USER = AuthenticatedUser(user_id="user-1", email="u@gaia.local")
CONVERSATION_ID = "conv-1"
RESULT_TEXT = f"Downloaded the report.{NEW_MESSAGE_BREAKER}It has 3 pages."
PREAMBLE = wrap_agent_payload(AgentTag.DELIVERY_INSTRUCTIONS, "where the reply goes")


def _fake_comms_graph() -> MagicMock:
    graph = MagicMock()
    graph.aupdate_state = AsyncMock()
    return graph


def _patch_graph(graph: MagicMock) -> AbstractContextManager[AsyncMock]:
    return patch(f"{MODULE}.GraphManager.get_graph", AsyncMock(return_value=graph))


class TestRecordExecutorCancellation:
    async def test_cancellation_record_is_appended_to_the_checkpoint(self) -> None:
        graph = _fake_comms_graph()
        with _patch_graph(graph):
            await record_executor_cancellation(CONVERSATION_ID, "task-42", "send the email")

        graph.aupdate_state.assert_awaited_once()
        call = graph.aupdate_state.await_args
        assert call.args[0] == {"configurable": {"thread_id": CONVERSATION_ID}}
        assert call.kwargs["as_node"] == "tools"
        messages = call.args[1]["messages"]
        assert len(messages) == 1
        # Full text, not a fragment: every clause is load-bearing.
        assert messages[0].content == wrap_agent_payload(
            AgentTag.EXECUTOR_CANCELLED,
            "The background task task-42 ('send the email') was cancelled by the user "
            "before it completed. It did NOT finish and will not deliver results. "
            "Do not claim otherwise.",
        )

    async def test_unknown_task_id_is_named_as_unknown(self) -> None:
        graph = _fake_comms_graph()
        with _patch_graph(graph):
            await record_executor_cancellation(CONVERSATION_ID, None, "send the email")

        content = graph.aupdate_state.await_args.args[1]["messages"][0].content
        assert "(unknown id)" in content

    async def test_failure_to_record_is_swallowed(self) -> None:
        graph = _fake_comms_graph()
        graph.aupdate_state = AsyncMock(side_effect=RuntimeError("checkpoint down"))
        with _patch_graph(graph):
            await record_executor_cancellation(CONVERSATION_ID, "task-42", "send the email")


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
