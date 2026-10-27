"""HeldReplies: what a run answers with, told apart from the narration around its tool calls."""

from langchain_core.messages import AIMessage, AIMessageChunk
import pytest

from app.agents.core.held_replies import HeldChunk, HeldReplies
from app.constants.general import NEW_MESSAGE_BREAKER

_NODE = {"langgraph_checkpoint_ns": "agent:1"}


def _announcing(message_id: str, content: str) -> AIMessageChunk:
    return AIMessageChunk(
        content=content,
        id=message_id,
        tool_call_chunks=[{"name": "lookup", "args": "{}", "id": "tc", "index": 0}],
    )


@pytest.mark.unit
class TestHold:
    def test_a_chunk_is_held_under_its_message(self) -> None:
        held = HeldReplies()

        first = held.hold(AIMessageChunk(content="half ", id="m1"), {})
        held.hold(AIMessageChunk(content="a reply", id="m1"), {})

        assert first == HeldChunk("m1", "half ")
        assert held.texts == {"m1": "half a reply"}

    def test_a_tier_whose_text_is_never_the_answer_holds_nothing(self) -> None:
        held = HeldReplies()

        chunk = held.hold(AIMessageChunk(content="chatter", id="m1"), {}, reply_tier=False)

        assert chunk == HeldChunk("m1", "")
        assert held.texts == {}

    def test_text_after_the_tool_call_in_the_same_message_is_not_held(self) -> None:
        held = HeldReplies()
        held.hold(_announcing("m1", ""), {})

        chunk = held.hold(AIMessageChunk(content="trailing", id="m1"), {})

        assert chunk.text == ""

    def test_a_retried_attempt_replaces_the_one_before_it(self) -> None:
        held = HeldReplies()
        held.hold(AIMessageChunk(content="first try", id="m1"), _NODE)

        retry = held.hold(AIMessageChunk(content="second try", id="m2"), _NODE)

        assert retry.abandoned_id == "m1"
        assert held.texts == {"m2": "second try"}

    def test_messages_from_different_node_runs_are_both_kept(self) -> None:
        held = HeldReplies()
        held.hold(AIMessageChunk(content="one", id="m1"), {"langgraph_checkpoint_ns": "agent:1"})

        later = held.hold(
            AIMessageChunk(content="two", id="m2"), {"langgraph_checkpoint_ns": "agent:2"}
        )

        assert later.abandoned_id is None
        assert held.texts == {"m1": "one", "m2": "two"}


@pytest.mark.unit
class TestReplyText:
    def test_narration_beside_a_tool_call_is_not_the_reply(self) -> None:
        held = HeldReplies()
        held.hold(AIMessageChunk(content="Let me check ", id="m1"), {})
        held.hold(_announcing("m1", "the mail."), {})
        held.hold(AIMessageChunk(content="1 needs you", id="m2"), {})

        assert held.reply_text() == "1 needs you"

    def test_a_message_the_chunks_never_flagged_is_dropped_once_its_finished_form_calls_a_tool(
        self,
    ) -> None:
        """A provider can stream a tool call's text without its tool_call_chunks; the node update still carries the call."""
        held = HeldReplies()
        held.hold(AIMessageChunk(content="Let me check the mail.", id="m1"), {})

        held.mark_announced(
            AIMessage(id="m1", content="", tool_calls=[{"name": "lookup", "args": {}, "id": "tc"}])
        )

        assert held.reply_text() == ""

    def test_a_finished_message_with_no_tool_call_stays_a_reply(self) -> None:
        held = HeldReplies()
        held.hold(AIMessageChunk(content="All done.", id="m1"), {})

        held.mark_announced(AIMessage(id="m1", content="All done."))

        assert held.reply_text() == "All done."

    def test_two_replies_are_two_bubbles(self) -> None:
        """Gluing them gave "fixing it.fixing it now" in a persisted reply."""
        held = HeldReplies()
        held.hold(AIMessageChunk(content="fixing it.", id="m1"), {})
        held.hold(AIMessageChunk(content="fixing it now", id="m2"), {})

        assert held.reply_text() == f"fixing it.{NEW_MESSAGE_BREAKER}fixing it now"

    def test_a_run_that_said_nothing_has_no_reply(self) -> None:
        assert HeldReplies().reply_text() == ""
