"""HeldReplies: what a run answers with, told apart from the narration around its tool calls."""

from langchain_core.messages import AIMessage, AIMessageChunk
import pytest

from app.agents.core.held_replies import HeldChunk, HeldReplies
from app.models.agent_models import StreamChunkMetadata
from shared.py.conversation_wire import NEW_MESSAGE_BREAKER

_NODE: StreamChunkMetadata = {"langgraph_checkpoint_ns": "agent:1"}


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


def _handoff_part(args: str, *, first: bool = False) -> AIMessageChunk:
    return AIMessageChunk(
        content="",
        id="m1",
        tool_call_chunks=[
            {
                "name": "call_executor" if first else None,
                "args": args,
                "id": "tc" if first else None,
                "index": 0,
            }
        ],
    )


def _stream(held: HeldReplies, pieces: list[str]) -> list[str]:
    """Hold each streamed fragment of one hand-off's arguments; return the text each one held."""
    return [
        held.hold(_handoff_part(piece, first=index == 0), _NODE).text
        for index, piece in enumerate(pieces)
    ]


def _whole_call(name: str, args: str, message_id: str) -> AIMessageChunk:
    return AIMessageChunk(
        content="",
        id=message_id,
        tool_call_chunks=[{"name": name, "args": args, "id": f"tc-{message_id}", "index": 0}],
    )


@pytest.mark.unit
class TestHandoffAck:
    def test_the_ack_is_held_once_exactly_when_its_value_is_whole(self) -> None:
        held = HeldReplies()

        texts = _stream(held, ['{"ack": "on', ' it"', ', "ta', 'sk": "clean', ' my inbox"}'])

        assert texts == ["", "", "", "on it", ""]
        assert held.texts == {"m1": "on it"}

    def test_an_ack_written_last_is_held_when_the_arguments_close(self) -> None:
        held = HeldReplies()

        texts = _stream(held, ['{"task": "clean my inbox", ', '"ack": "on it"', "}"])

        assert texts == ["", "", "on it"]

    def test_an_escaped_quote_does_not_end_the_ack(self) -> None:
        held = HeldReplies()

        texts = _stream(held, ['{"ack": "the \\"big\\" one', ' now", "task": "x"}'])

        assert texts == ["", 'the "big" one now']

    def test_another_tools_arguments_hold_nothing(self) -> None:
        held = HeldReplies()

        chunk = held.hold(_whole_call("lookup", '{"ack": "x", "q": 1}', "m1"), _NODE)

        assert chunk.text == ""
        assert held.texts == {}

    def test_a_blank_ack_holds_nothing(self) -> None:
        held = HeldReplies()

        assert _stream(held, ['{"ack": "  ", "task": "x"}']) == [""]

    def test_a_second_hand_off_in_the_run_does_not_say_it_twice(self) -> None:
        held = HeldReplies()
        _stream(held, ['{"ack": "on it", "task": "x"}'])

        again = held.hold(
            _whole_call("call_executor", '{"ack": "on it", "task": "x"}', "m2"),
            {"langgraph_checkpoint_ns": "agent:2"},
        )

        assert again.text == ""
        assert held.texts == {"m1": "on it"}

    def test_a_tier_whose_text_is_never_the_answer_holds_no_ack(self) -> None:
        held = HeldReplies()
        chunk = _whole_call("call_executor", '{"ack": "on it", "task": "x"}', "m1")

        assert held.hold(chunk, {}, reply_tier=False).text == ""

    def test_a_finished_message_that_never_streamed_holds_its_ack(self) -> None:
        held = HeldReplies()
        message = AIMessage(
            content="",
            id="m1",
            tool_calls=[
                {"name": "call_executor", "args": {"ack": "on it", "task": "x"}, "id": "tc"}
            ],
        )

        assert held.hold_handoff(message).text == "on it"
        assert held.hold_handoff(message).text == ""
        assert held.settle([message], "") == ("on it", "m1")
