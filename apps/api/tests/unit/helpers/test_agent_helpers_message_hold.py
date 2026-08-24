"""The message-scoped text hold: what the driver keeps, drops, and flushes.

Comms text that turns out to accompany a tool call is a handoff preamble, and
the wire only reveals that AFTER the text has streamed. So both drivers hold
each message's text by id and decide its fate at the message boundary. Three
tiny functions carry that decision, and every one of them is a silent failure
when it is wrong: the user either sees narration they were never meant to see,
or loses a reply that was meant for them.

The drivers themselves are exercised end to end in
``test_agent_helpers_tool_call_silence.py`` (real wire, real graph). These are
the unit-level truth tables underneath, including the branches a full run does
not reliably reach.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, AIMessageChunk
import pytest

from app.constants.general import NEW_MESSAGE_BREAKER
from app.helpers.agent_helpers import (
    _flush_held_messages,
    announces_tool_call,
    drop_retracted_text,
)


@pytest.mark.unit
class TestAnnouncesToolCall:
    """Both wire shapes mean the same thing: the model is handing off, so the
    text riding along is narration rather than a reply."""

    def test_a_finished_message_announces_through_tool_calls(self) -> None:
        message = AIMessage(
            content="let me get the tasks created",
            tool_calls=[{"name": "call_executor", "args": {"task": "x"}, "id": "c1"}],
        )

        assert announces_tool_call(message) is True

    def test_a_still_assembling_chunk_announces_before_its_args_parse(self) -> None:
        """A chunk cut mid-JSON has no parsed ``tool_calls`` at all — only the
        raw ``tool_call_chunks``. Reading just the parsed list would let the
        preamble through for exactly as long as the arguments take to arrive."""
        chunk = AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "name": "call_executor",
                    "args": '{"task": "x"]]]',
                    "id": "c1",
                    "index": 0,
                    "type": "tool_call_chunk",
                }
            ],
        )
        assert chunk.tool_calls == []

        assert announces_tool_call(chunk) is True

    def test_plain_text_announces_nothing(self) -> None:
        assert announces_tool_call(AIMessage(content="yeah, all set up now.")) is False


@pytest.mark.unit
class TestFlushHeldMessages:
    """A run that ends without its closing node update — a cancellation, or a
    graph that never returns to the agent node — still owes the user what it
    streamed."""

    def test_held_text_is_appended_as_its_own_bubble(self) -> None:
        """Concatenating directly is what turned "fixing it." and "fixing it
        now" into "fixing it.fixing it now" in a persisted reply."""
        flushed = _flush_held_messages("first", {"m1": "second"})

        assert flushed == f"first{NEW_MESSAGE_BREAKER}second"

    def test_nothing_held_leaves_the_message_untouched(self) -> None:
        assert _flush_held_messages("first", {}) == "first"

    def test_an_empty_hold_does_not_open_a_bubble(self) -> None:
        assert _flush_held_messages("first", {"m1": ""}) == "first"


@pytest.mark.unit
class TestDropRetractedText:
    """The style guard retracts a draft mid-node, on the custom stream, between
    the draft's tokens and the rewrite's. Honouring it there is the only thing
    stopping a draft that vanished on screen from being persisted anyway."""

    def test_a_discarded_boundary_forgets_that_message_s_text(self) -> None:
        held = {"m1": "draft", "m2": "kept"}

        drop_retracted_text({"message_boundary": {"message_id": "m1", "discarded": True}}, held)

        assert held == {"m2": "kept"}

    def test_a_retraction_for_text_that_was_never_held_is_a_no_op(self) -> None:
        """The custom stream carries retractions for messages this driver never
        held — a subagent's, or one whose boundary already passed."""
        held = {"m1": "kept"}

        drop_retracted_text({"message_boundary": {"message_id": "gone", "discarded": True}}, held)

        assert held == {"m1": "kept"}

    def test_a_retraction_of_an_id_less_message_drops_the_unkeyed_text(self) -> None:
        """A chunk the provider gave no id is held under the empty key, because
        that is what ``chunk.id or ""`` produces. The retraction has to resolve
        to the same key or the draft survives its own retraction."""
        held = {"": "draft"}

        drop_retracted_text({"message_boundary": {"message_id": None, "discarded": True}}, held)

        assert held == {}

    def test_a_kept_boundary_drops_nothing(self) -> None:
        held = {"m1": "kept"}

        drop_retracted_text({"message_boundary": {"message_id": "m1", "discarded": False}}, held)

        assert held == {"m1": "kept"}

    def test_a_payload_that_is_not_a_frame_is_ignored(self) -> None:
        held = {"m1": "kept"}

        drop_retracted_text("tool progress, not a boundary", held)

        assert held == {"m1": "kept"}
