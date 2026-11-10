"""The message-scoped text hold: what the driver keeps, drops, and flushes.

Comms text that turns out to accompany a tool call is a handoff preamble, and
the wire only reveals that AFTER the text has streamed. Both drivers hold
each message's text by id and decide its fate at the message boundary.

The drivers themselves are exercised end to end in
test_agent_helpers_tool_call_silence.py (real wire, real graph). These are
the unit-level truth tables, plus — at the bottom — the same bookkeeping
driven through both drivers over a scripted astream, to reach shapes a real
OpenAI wire never produces: an id-less message, tool-call deltas arriving
BEFORE their text, a tool-call whose arguments never parse, and a retraction
landing mid-node.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
import json
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk
import pytest

from app.agents.core.held_replies import HeldReplies, announces_tool_call, drop_retracted_text
from app.constants.general import NEW_MESSAGE_BREAKER
from app.helpers.agent_helpers import execute_graph_silent, execute_graph_streaming
from tests.helpers import (
    GraphStreamEvent,
    ScriptedGraph,
    agent_update_event,
    message_chunk_event,
)


@pytest.mark.unit
class TestAnnouncesToolCall:
    """Both wire shapes mean the model is handing off, so riding text is narration, not a reply."""

    def test_a_finished_message_announces_through_tool_calls(self) -> None:
        message = AIMessage(
            content="let me get the tasks created",
            tool_calls=[{"name": "call_executor", "args": {"task": "x"}, "id": "c1"}],
        )

        assert announces_tool_call(message) is True

    def test_a_still_assembling_chunk_announces_before_its_args_parse(self) -> None:
        """A chunk cut mid-JSON has no parsed tool_calls, only tool_call_chunks."""
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
    """A run that ends without its closing node update still owes the user what it streamed."""

    def test_held_text_is_appended_as_its_own_bubble(self) -> None:
        """Concatenating directly turned "fixing it." and "fixing it now" into one glued word."""
        flushed = HeldReplies(texts={"m1": "second"}).flush("first")

        assert flushed == f"first{NEW_MESSAGE_BREAKER}second"

    def test_nothing_held_leaves_the_message_untouched(self) -> None:
        assert HeldReplies().flush("first") == "first"

    def test_an_empty_hold_does_not_open_a_bubble(self) -> None:
        assert HeldReplies(texts={"m1": ""}).flush("first") == "first"


@pytest.mark.unit
class TestDropRetractedText:
    """The style guard retracts a draft mid-node, between the draft's tokens and the rewrite's."""

    def test_a_discarded_boundary_forgets_that_message_s_text(self) -> None:
        held = {"m1": "draft", "m2": "kept"}

        drop_retracted_text({"message_boundary": {"message_id": "m1", "discarded": True}}, held)

        assert held == {"m2": "kept"}

    def test_a_retraction_for_text_that_was_never_held_is_a_no_op(self) -> None:
        """The custom stream carries retractions for messages this driver never held."""
        held = {"m1": "kept"}

        drop_retracted_text({"message_boundary": {"message_id": "gone", "discarded": True}}, held)

        assert held == {"m1": "kept"}

    def test_a_retraction_of_an_id_less_message_drops_the_unkeyed_text(self) -> None:
        """An id-less chunk is held under the empty key (chunk.id or ""); the retraction must match it."""
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


def _custom(payload: Any) -> GraphStreamEvent:
    return ((), "custom", payload)


#: The still-assembling shape from ``TestAnnouncesToolCall``: the chunk carries a
#: tool call, the finished message does not, because the arguments never parsed.
_UNPARSEABLE_CALL: dict[str, Any] = {
    "tool_call_chunks": [
        {"name": "call_executor", "args": '{"task": "x"]]]', "id": "c1", "index": 0}
    ]
}

_CONFIG: Any = {"agent_name": "comms_agent", "configurable": {"user_id": "u1"}}


async def _run_silent(events: list[GraphStreamEvent]) -> str:
    message, _ = await execute_graph_silent(ScriptedGraph(events), {}, _CONFIG)
    return message


async def _run_streaming(events: list[GraphStreamEvent]) -> list[str]:
    return [frame async for frame in execute_graph_streaming(ScriptedGraph(events), {}, _CONFIG)]


def _frames(frames: list[str], key: str) -> list[Any]:
    """Every data: frame carrying key, in order."""
    out = []
    for frame in frames:
        if not frame.startswith("data: "):
            continue
        payload = frame[len("data: ") :].strip()
        if payload == "[DONE]":
            continue
        data = json.loads(payload)
        if key in data:
            out.append(data[key])
    return out


def _streamed_message(frames: list[str]) -> str:
    marker = next(f for f in frames if f.startswith("nostream: "))
    return str(json.loads(marker.removeprefix("nostream: "))["complete_message"])


@pytest.fixture
def resolved_tool_cards() -> Any:
    """Tool-card formatting reaches the ChromaDB registry, which a graded boundary must get past."""
    with patch(
        "app.helpers.agent_helpers.format_tool_call_entry",
        new_callable=AsyncMock,
        return_value={"tool_name": "tool_calls_data", "data": {}},
    ) as entry:
        yield entry


@pytest.mark.unit
class TestBoundaryBookkeeping:
    """What each driver does with held text when a message ends."""

    async def test_a_boundary_with_nothing_held_adds_no_text(self) -> None:
        """The driver must treat "nothing was held" as nothing, not as a value."""
        events = [agent_update_event(AIMessage(id="m1", content=""))]

        assert await _run_silent(events) == ""
        assert _streamed_message(await _run_streaming(events)) == ""

    async def test_text_from_a_message_the_provider_gave_no_id_is_still_kept(self) -> None:
        """chunk.id or "" holds an id-less message under the empty key; the boundary must resolve to it too."""
        events = [
            message_chunk_event(message_id=None, content="hey"),
            agent_update_event(AIMessage(id=None, content="hey")),
        ]

        assert await _run_silent(events) == "hey"
        frames = await _run_streaming(events)
        assert _streamed_message(frames) == "hey"
        assert _frames(frames, "message_boundary") == [{"message_id": "", "discarded": False}]

    async def test_narration_from_an_id_less_message_is_still_dropped(
        self, resolved_tool_cards: Any
    ) -> None:
        """If the boundary resolves to a different key than the hold did, the preamble leaks to the user."""
        events = [
            message_chunk_event(message_id=None, content="let me get that set up"),
            agent_update_event(
                AIMessage(
                    id=None,
                    content="let me get that set up",
                    tool_calls=[{"name": "call_executor", "args": {"task": "x"}, "id": "c1"}],
                )
            ),
        ]

        assert await _run_silent(events) == ""

    async def test_a_preamble_is_dropped_even_when_no_chunk_announced_the_call(
        self, resolved_tool_cards: Any
    ) -> None:
        """The two halves of discarded are alternatives: a finished message can carry a tool call no chunk announced."""
        events = [
            message_chunk_event(message_id="m1", content="let me get that set up"),
            agent_update_event(
                AIMessage(
                    id="m1",
                    content="let me get that set up",
                    tool_calls=[{"name": "call_executor", "args": {"task": "x"}, "id": "c1"}],
                )
            ),
        ]

        assert await _run_silent(events) == ""
        assert _streamed_message(await _run_streaming(events)) == ""

    async def test_a_message_s_chunks_are_joined_not_replaced(self) -> None:
        """Text arrives one delta at a time; holding only the newest would lose most of every reply."""
        events = [
            message_chunk_event(message_id="m1", content="all "),
            message_chunk_event(message_id="m1", content="set up now."),
            agent_update_event(AIMessage(id="m1", content="all set up now.")),
        ]

        assert await _run_silent(events) == "all set up now."
        assert _streamed_message(await _run_streaming(events)) == "all set up now."

    async def test_two_kept_messages_are_separated_by_the_break_sentinel(self) -> None:
        """Silent mode persists the whole turn, so two replies in one run must stay two bubbles."""
        events = [
            message_chunk_event(message_id="m1", content="on it."),
            agent_update_event(AIMessage(id="m1", content="on it.")),
            message_chunk_event(message_id="m2", content="all done."),
            agent_update_event(AIMessage(id="m2", content="all done.")),
        ]

        assert await _run_silent(events) == f"on it.{NEW_MESSAGE_BREAKER}all done."


_EXECUTOR_CONFIG: Any = {"agent_name": "executor_agent", "configurable": {"user_id": "u1"}}
_WORKING_EVENTS = [
    message_chunk_event(message_id="m1", content="working on it."),
    agent_update_event(AIMessage(id="m1", content="working on it.")),
]


@pytest.mark.unit
class TestOnlyTheReplyTierSpeaks:
    """Only comms text is a reply: an executor run through these drivers answers through its tool results."""

    async def test_a_silent_run_of_another_tier_keeps_no_text(self) -> None:
        message, _ = await execute_graph_silent(
            ScriptedGraph(_WORKING_EVENTS), {}, _EXECUTOR_CONFIG
        )

        assert message == ""

    async def test_a_streamed_run_of_another_tier_streams_and_keeps_no_text(self) -> None:
        frames = [
            frame
            async for frame in execute_graph_streaming(
                ScriptedGraph(_WORKING_EVENTS), {}, _EXECUTOR_CONFIG
            )
        ]

        assert _frames(frames, "response") == []
        assert _frames(frames, "message_boundary") == []
        assert _streamed_message(frames) == ""

    async def test_the_same_events_from_comms_are_kept(self) -> None:
        """Control: the config is the only difference between this and the two tests above."""
        assert await _run_silent(_WORKING_EVENTS) == "working on it."


@pytest.mark.unit
class TestChunkLevelSilence:
    """The per-chunk guard, on the delta order where it is the only guard."""

    async def test_text_that_follows_its_own_tool_call_never_reaches_the_user(self) -> None:
        """Anthropic-shaped ordering: the tool call announces first, then the narration; only that chunk knows."""
        events = [
            message_chunk_event(message_id="m1", **_UNPARSEABLE_CALL),
            message_chunk_event(message_id="m1", content="let me get that set up"),
            agent_update_event(AIMessage(id="m1", content="let me get that set up")),
        ]

        assert await _run_silent(events) == ""
        frames = await _run_streaming(events)
        assert _frames(frames, "response") == []
        assert _streamed_message(frames) == ""


@pytest.mark.unit
class TestRetractionMidNode:
    """The style guard retracts a draft on the custom stream, before any boundary."""

    async def test_a_retracted_id_less_draft_is_forgotten(self) -> None:
        """An id-less draft is held under the empty key and retracted under a null id: both must normalise to match."""
        events = [
            message_chunk_event(message_id=None, content="Great question! Let me unpack that."),
            _custom({"message_boundary": {"message_id": None, "discarded": True}}),
        ]

        assert await _run_silent(events) == ""
        assert _streamed_message(await _run_streaming(events)) == ""

    async def test_a_kept_draft_survives_the_custom_stream(self) -> None:
        events = [
            message_chunk_event(message_id=None, content="all set up now."),
            _custom({"message_boundary": {"message_id": None, "discarded": False}}),
        ]

        assert await _run_silent(events) == "all set up now."
        assert _streamed_message(await _run_streaming(events)) == "all set up now."


class _OneChunkThenFails:
    """A graph that streams one chunk and fails the test if the driver reads further."""

    def astream(self, *_args: Any, **_kwargs: Any) -> AsyncGenerator[tuple[Any, ...], None]:
        async def stream() -> AsyncGenerator[tuple[Any, ...], None]:
            yield message_chunk_event(message_id="m1", content="Hello")
            raise AssertionError("the driver read the next event before publishing the first chunk")

        return stream()


def _one_message(message_id: str | None, *pieces: str) -> list[GraphStreamEvent]:
    """Build the events of one kept message streamed as pieces."""
    return [
        *(message_chunk_event(message_id=message_id, content=piece) for piece in pieces),
        agent_update_event(AIMessage(id=message_id, content="".join(pieces))),
    ]


@pytest.mark.unit
class TestDirectiveHoldback:
    """A directive bubble never reaches the wire as text; every other bubble does, in order."""

    @pytest.mark.parametrize(
        "pieces",
        [
            ("<EM", "OJI>👍</EM", "OJI>"),
            ("<SILENCE>", "nothing new</SILENCE>", "<NEW_MESSAGE_BREAK>"),
            ("REACT", ": 😎"),
        ],
    )
    async def test_a_directive_turn_emits_no_text_but_keeps_its_boundary(
        self, pieces: tuple[str, ...]
    ) -> None:
        frames = await _run_streaming(_one_message("m1", *pieces))

        assert _frames(frames, "response") == []
        assert _frames(frames, "message_boundary") == [{"message_id": "m1", "discarded": False}]
        assert _streamed_message(frames) == "".join(pieces)

    @pytest.mark.parametrize(
        ("pieces", "shown"),
        [
            (("Hello there.", "<NEW_MESSAGE_B", "REAK><SIL", "ENCE>x</SILENCE>"), "Hello there."),
            (
                ("On it.", f"{NEW_MESSAGE_BREAKER}<EMO", "JI>👍</EMOJI>", NEW_MESSAGE_BREAKER),
                "On it.",
            ),
            (
                (
                    "First.",
                    f"{NEW_MESSAGE_BREAKER}<SILENCE>x</SILENCE>",
                    f"{NEW_MESSAGE_BREAKER}Last.",
                ),
                f"First.{NEW_MESSAGE_BREAKER}Last.",
            ),
            (("Done.", f"{NEW_MESSAGE_BREAKER}SILENCE: routine"), "Done."),
            (("<EMOJI>👍</EMOJI>", NEW_MESSAGE_BREAKER, "and more"), "and more"),
        ],
    )
    @pytest.mark.regression
    async def test_a_directive_bubble_beside_text_never_reaches_the_wire(
        self, pieces: tuple[str, ...], shown: str
    ) -> None:
        frames = await _run_streaming(_one_message("m1", *pieces))

        texts = _frames(frames, "response")
        assert "".join(texts) == shown
        assert _frames(frames, "message_boundary") == [{"message_id": "m1", "discarded": False}]

    async def test_a_message_s_text_goes_out_ahead_of_its_boundary(self) -> None:
        """Clients settle the text before a boundary into that message; released after it, a retraction would eat it."""
        frames = await _run_streaming(
            [*_one_message("m1", "<EMOJI>👍</EMOJI>"), *_one_message("m2", "Re", ": trip")]
        )

        payloads = [json.loads(f[len("data: ") :]) for f in frames if f.startswith("data: {")]
        assert payloads == [
            {"message_boundary": {"message_id": "m1", "discarded": False}},
            {"response": "Re: trip"},
            {"message_boundary": {"message_id": "m2", "discarded": False}},
        ]

    async def test_a_retracted_directive_shaped_preamble_does_not_hold_its_tool_card(
        self, resolved_tool_cards: Any
    ) -> None:
        events = [
            message_chunk_event(message_id="m1", content="REACT"),
            agent_update_event(
                AIMessage(
                    id="m1",
                    content="REACT",
                    tool_calls=[{"name": "call_executor", "args": {"task": "x"}, "id": "c1"}],
                )
            ),
        ]

        frames = await _run_streaming(events)

        assert _frames(frames, "response") == []
        assert _frames(frames, "tool_data") == [{"tool_name": "tool_calls_data", "data": {}}]
        assert _frames(frames, "message_boundary") == [{"message_id": "m1", "discarded": True}]

    @pytest.mark.parametrize("text", ["Sure", "REACT"])
    async def test_a_run_cut_short_still_releases_its_visible_text(self, text: str) -> None:
        """A cancelled run never reaches its boundary; what the user may see must still go out."""
        frames = await _run_streaming([message_chunk_event(message_id="m1", content=text)])

        assert _frames(frames, "response") == [text]

    @pytest.mark.parametrize("message_id", ["m1", None])
    async def test_text_held_to_the_end_goes_out_just_before_its_boundary(
        self, message_id: str | None
    ) -> None:
        """A bare REACT could have become a directive until the message ended; then it is text."""
        frames = await _run_streaming(_one_message(message_id, "REACT"))

        payloads = [json.loads(f[len("data: ") :]) for f in frames if f.startswith("data: {")]
        assert payloads == [
            {"response": "REACT"},
            {"message_boundary": {"message_id": message_id or "", "discarded": False}},
        ]

    async def test_a_message_with_no_text_sends_none(self) -> None:
        frames = await _run_streaming([agent_update_event(AIMessage(id="m1", content=""))])

        assert _frames(frames, "response") == []

    async def test_a_second_message_under_the_same_id_streams_whole(self) -> None:
        """Id-less messages share one key: what the first streamed must not eat into the next."""
        frames = await _run_streaming([*_one_message(None, "on it."), *_one_message(None, "done.")])

        assert _frames(frames, "response") == ["on it.", "done."]

    async def test_a_retracted_draft_does_not_eat_into_its_rewrite(self) -> None:
        """The style guard retracts a draft mid-node; the rewrite reuses the id-less key."""
        frames = await _run_streaming(
            [
                message_chunk_event(message_id=None, content="Great question!"),
                _custom({"message_boundary": {"message_id": None, "discarded": True}}),
                *_one_message(None, "Sure."),
            ]
        )

        assert _frames(frames, "response") == ["Great question!", "Sure."]

    async def test_ordinary_text_is_published_before_the_next_event_is_read(self) -> None:
        frames = execute_graph_streaming(_OneChunkThenFails(), {}, _CONFIG)

        first = await anext(frames)
        await frames.aclose()

        assert json.loads(first[len("data: ") :]) == {"response": "Hello"}


def _attempt_chunk(
    message_id: str, content: str, node_run: str = "agent:run-1"
) -> GraphStreamEvent:
    """One streamed chunk of a model attempt inside the node run node_run."""
    metadata = {"langgraph_checkpoint_ns": node_run}
    return ((), "messages", (AIMessageChunk(id=message_id, content=content), metadata))


#: A model call that failed after streaming, then succeeded on retry: each attempt
#: streams under its own message id, and only the last one reaches the node update.
_RETRIED_CALL = (
    _attempt_chunk("attempt-1", "Partial "),
    _attempt_chunk("attempt-1", "text"),
    _attempt_chunk("attempt-2", "Partial "),
    _attempt_chunk("attempt-2", "text"),
    agent_update_event(AIMessage(id="attempt-2", content="Partial text")),
)


@pytest.mark.unit
class TestRetriedModelAttempt:
    """A retried model call must leave its reply on screen and on record exactly once."""

    @pytest.mark.regression
    async def test_the_abandoned_attempt_is_retracted_before_the_retry_streams(self) -> None:
        frames = await _run_streaming(list(_RETRIED_CALL))

        boundaries = _frames(frames, "message_boundary")
        assert boundaries[0] == {"message_id": "attempt-1", "discarded": True}
        retraction = next(
            i for i, f in enumerate(frames) if "message_boundary" in f and "attempt-1" in f
        )
        assert "".join(_frames(frames[retraction:], "response")) == "Partial text"

    @pytest.mark.regression
    async def test_the_saved_reply_holds_the_text_once(self) -> None:
        assert _streamed_message(await _run_streaming(list(_RETRIED_CALL))) == "Partial text"
        assert await _run_silent(list(_RETRIED_CALL)) == "Partial text"

    async def test_messages_from_different_node_runs_are_never_retracted(self) -> None:
        events = [
            _attempt_chunk("m1", "first", node_run="agent:run-1"),
            _attempt_chunk("m2", "second", node_run="agent:run-2"),
        ]

        frames = await _run_streaming(events)

        assert _frames(frames, "message_boundary") == []
        assert _streamed_message(frames) == f"first{NEW_MESSAGE_BREAKER}second"
