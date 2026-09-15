"""SSE frame assembly is what decides what a live-chat eval measures.

The three harnesses that used to own a copy of this logic had each drifted, and
the drift was invisible because nothing exercised the assembly without an API:
one dropped the retracted handoff preamble and two did not, one unwrapped nested
tool names and one did not. Those are not cosmetic — the reply string is what the
judge grades, and the tool list is what "did it actually do the thing" is scored
against. So every option that survived the consolidation is pinned here.

Nothing in this file touches a network or a model: ``assemble`` takes the raw
lines, which is the whole reason it was split out of ``send_turn``.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from scripts.evals.core.live_chat import (
    NO_TEXT_REPLY,
    Turn,
    TurnOptions,
    assemble,
    bot_messages_after,
    frame_tool_names,
)

pytestmark = pytest.mark.unit


def sse(**frame: object) -> str:
    return "data: " + json.dumps(frame)


class TestReplyAssembly:
    def test_joins_response_chunks_in_order(self) -> None:
        reply, _, _ = assemble([sse(response="hey "), sse(response="there")])
        assert reply == "hey there"

    def test_empty_stream_is_the_sentinel_not_an_empty_string(self) -> None:
        """Scripts branch on this exact value to skip grading a silent turn."""
        assert assemble([])[0] == NO_TEXT_REPLY
        assert assemble([sse(response="   ")])[0] == NO_TEXT_REPLY

    def test_discarded_boundary_retracts_the_preamble(self) -> None:
        lines = [
            sse(response="let me look"),
            sse(message_boundary={"discarded": True}),
            sse(response="the answer"),
        ]
        assert assemble(lines)[0] == "the answer"

    def test_boundary_is_kept_when_the_caller_opts_out(self) -> None:
        """``first_question_personas`` never dropped it, and its scores were read
        against replies that still contained the preamble."""
        lines = [
            sse(response="let me look"),
            sse(message_boundary={"discarded": True}),
            sse(response=" the answer"),
        ]
        assert assemble(lines, drop_discarded_boundary=False)[0] == "let me look the answer"

    def test_a_boundary_that_is_not_discarded_retracts_nothing(self) -> None:
        lines = [sse(response="a"), sse(message_boundary={"discarded": False}), sse(response="b")]
        assert assemble(lines)[0] == "ab"

    @pytest.mark.parametrize(
        "line",
        [
            "event: ping",
            "",
            "data: {not json",
            "data: [1, 2, 3]",
            'data: "a string"',
        ],
    )
    def test_junk_lines_are_skipped_not_raised(self, line: str) -> None:
        """A stream that ends mid-frame is a slow lane, not a failed eval."""
        reply, _, _ = assemble([line, sse(response="ok")])
        assert reply == "ok"


class TestToolNames:
    def test_reads_a_list_payload_and_a_bare_entry_alike(self) -> None:
        assert frame_tool_names({"tool_data": [{"tool_name": "a"}, {"tool_name": "b"}]}) == [
            "a",
            "b",
        ]
        assert frame_tool_names({"tool_data": {"tool_name": "a"}}) == ["a"]

    def test_unwraps_the_tool_a_tool_calls_data_announcement_carries(self) -> None:
        frame = {"tool_data": [{"tool_name": "tool_calls_data", "data": {"tool_name": "inner"}}]}
        assert frame_tool_names(frame) == ["tool_calls_data", "inner"]

    def test_nested_name_is_omitted_when_the_caller_opts_out(self) -> None:
        frame = {"tool_data": [{"tool_name": "tool_calls_data", "data": {"tool_name": "inner"}}]}
        assert frame_tool_names(frame, include_nested=False) == ["tool_calls_data"]

    def test_inner_name_falls_back_to_the_name_key(self) -> None:
        frame = {"tool_data": [{"tool_name": "tool_calls_data", "data": {"name": "inner"}}]}
        assert frame_tool_names(frame) == ["tool_calls_data", "inner"]

    @pytest.mark.parametrize(
        "payload",
        [None, [], ["not a dict"], [{"no_tool_name": 1}], [{"tool_name": 42}]],
    )
    def test_malformed_entries_contribute_no_names(self, payload: object) -> None:
        """A non-string tool name must not reach the judge's tool list as one."""
        assert frame_tool_names({"tool_data": payload}) == []


class TestFrameKinds:
    def test_collected_only_when_asked_and_null_keys_are_dropped(self) -> None:
        lines = [sse(response="a", progress=None), sse(tool_data=[{"tool_name": "t"}])]
        assert assemble(lines, collect_frame_kinds=True)[2] == ["response", "tool_data"]

    def test_not_collected_by_default(self) -> None:
        assert assemble([sse(response="a")])[2] == []


class TestBotMessagesAfter:
    def test_matches_the_last_occurrence_of_a_repeated_user_message(self) -> None:
        """A scenario may send the same words twice; the graded turn is the last."""
        messages = [
            {"type": "user", "response": "hey"},
            {"type": "bot", "response": "first"},
            {"type": "user", "response": "hey"},
            {"type": "bot", "response": "second"},
        ]
        assert [m["response"] for m in bot_messages_after(messages, "hey")] == ["second"]

    def test_unknown_user_text_yields_nothing(self) -> None:
        assert bot_messages_after([{"type": "user", "response": "hey"}], "other") == []

    def test_whitespace_around_the_user_text_still_matches(self) -> None:
        messages = [{"type": "user", "response": " hey "}, {"type": "bot", "response": "x"}]
        assert len(bot_messages_after(messages, "hey")) == 1


class TestTurnOptions:
    """The defaults are ``chat_quality``'s behaviour and three scripts rely on
    them, so a silent change to one flips what those runs measure."""

    def test_defaults_are_the_chat_quality_shape(self) -> None:
        options = TurnOptions()
        assert options.include_nested_tool_names is True
        assert options.drop_discarded_boundary is True
        assert options.collect_frame_kinds is False
        assert options.poll_for_delivery is True
        assert options.drop_sentinel_before_delivery is False
        assert options.delivered_prefix == "\n\n[delivered later] "

    def test_is_frozen_so_one_run_cannot_change_shape_mid_flight(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            TurnOptions().collect_frame_kinds = True  # type: ignore[misc] -- the assignment to a frozen field is the behaviour under test

    def test_overrides_leave_the_other_fields_alone(self) -> None:
        options = TurnOptions(poll_for_delivery=False, timeout=12.0)
        assert options.poll_for_delivery is False
        assert options.timeout == 12.0
        assert options.drop_discarded_boundary is True


class TestTurnModel:
    @pytest.mark.parametrize("reply", ["", "   ", NO_TEXT_REPLY, f"  {NO_TEXT_REPLY}  "])
    def test_is_empty_covers_blank_and_the_sentinel(self, reply: str) -> None:
        assert Turn(message="m", reply=reply).is_empty

    def test_real_prose_is_not_empty(self) -> None:
        assert not Turn(message="m", reply="a real answer").is_empty
