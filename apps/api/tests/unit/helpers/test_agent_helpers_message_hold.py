"""The message-scoped text hold: what the driver keeps, drops, and flushes.

Comms text that turns out to accompany a tool call is a handoff preamble, and
the wire only reveals that AFTER the text has streamed. So both drivers hold
each message's text by id and decide its fate at the message boundary. Three
tiny functions carry that decision, and every one of them is a silent failure
when it is wrong: the user either sees narration they were never meant to see,
or loses a reply that was meant for them.

The drivers themselves are exercised end to end in
``test_agent_helpers_tool_call_silence.py`` (real wire, real graph). These are
the unit-level truth tables underneath, plus — at the bottom — the same
bookkeeping driven through both drivers over a scripted ``astream``, which is
the only way to reach the shapes a real OpenAI wire never produces: a message
the provider gave no id, tool-call deltas arriving BEFORE their text, a
tool-call whose arguments never parse, and a retraction landing mid-node.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
import json
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk
import pytest

from app.constants.general import NEW_MESSAGE_BREAKER
from app.helpers.agent_helpers import (
    _flush_held_messages,
    announces_tool_call,
    drop_retracted_text,
    execute_graph_silent,
    execute_graph_streaming,
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


class _ScriptedGraph:
    """A graph whose ``astream`` replays exactly the triples handed to it.

    The loopback-wire harness in ``test_agent_helpers_tool_call_silence.py``
    proves the drivers against the real OpenAI delta order. It cannot script the
    shapes that order never produces — an id-less message, a tool call announced
    before its text, args that never parse — and those are precisely where the
    hold bookkeeping goes wrong silently. Driving ``astream`` directly is the
    same driver code over the same triple shape, with the wire's accidents
    removed.
    """

    def __init__(self, events: list[tuple[tuple[str, ...], str, Any]]) -> None:
        self._events = events

    def astream(self, *_args: Any, **_kwargs: Any) -> AsyncGenerator[tuple[Any, ...], None]:
        events = self._events

        async def stream() -> AsyncGenerator[tuple[Any, ...], None]:
            for event in events:
                yield event

        return stream()


def _chunk(*, id: str | None, content: str = "", **kwargs: Any) -> tuple[tuple[str, ...], str, Any]:
    """A ``messages`` triple carrying one assistant chunk."""
    return ((), "messages", (AIMessageChunk(id=id, content=content, **kwargs), {}))


def _boundary(message: AIMessage) -> tuple[tuple[str, ...], str, Any]:
    """An ``updates`` triple closing the agent node with ``message`` as its reply."""
    return ((), "updates", {"agent": {"messages": [message]}})


def _custom(payload: Any) -> tuple[tuple[str, ...], str, Any]:
    return ((), "custom", payload)


#: The still-assembling shape from ``TestAnnouncesToolCall``: the chunk carries a
#: tool call, the finished message does not, because the arguments never parsed.
_UNPARSEABLE_CALL: dict[str, Any] = {
    "tool_call_chunks": [
        {"name": "call_executor", "args": '{"task": "x"]]]', "id": "c1", "index": 0}
    ]
}

_CONFIG: Any = {"agent_name": "comms_agent", "configurable": {"user_id": "u1"}}


async def _run_silent(events: list[tuple[tuple[str, ...], str, Any]]) -> str:
    message, _ = await execute_graph_silent(_ScriptedGraph(events), {}, _CONFIG)
    return message


async def _run_streaming(events: list[tuple[tuple[str, ...], str, Any]]) -> list[str]:
    return [frame async for frame in execute_graph_streaming(_ScriptedGraph(events), {}, _CONFIG)]


def _frames(frames: list[str], key: str) -> list[Any]:
    """Every ``data:`` frame carrying ``key``, in order."""
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
    """Tool-card formatting reaches the ChromaDB registry; a boundary that
    announces a tool call has to get past it to be graded at all."""
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
        """A message that streamed no text still reaches a boundary — a reply
        that is purely a tool call, or one whose text was already retracted. The
        driver has to treat "nothing was held" as nothing, not as a value."""
        events = [_boundary(AIMessage(id="m1", content=""))]

        assert await _run_silent(events) == ""
        assert _streamed_message(await _run_streaming(events)) == ""

    async def test_text_from_a_message_the_provider_gave_no_id_is_still_kept(self) -> None:
        """``chunk.id or ""`` holds an id-less message under the empty key, so
        the boundary has to resolve to that same key or the reply is stranded."""
        events = [_chunk(id=None, content="hey"), _boundary(AIMessage(id=None, content="hey"))]

        assert await _run_silent(events) == "hey"
        frames = await _run_streaming(events)
        assert _streamed_message(frames) == "hey"
        assert _frames(frames, "message_boundary") == [{"message_id": "", "discarded": False}]

    async def test_narration_from_an_id_less_message_is_still_dropped(
        self, resolved_tool_cards: Any
    ) -> None:
        """The mirror case, and the one that leaks: if the boundary resolves to a
        different key than the hold did, the preamble is never popped and the
        end-of-run flush ships it to the user anyway."""
        events = [
            _chunk(id=None, content="let me get that set up"),
            _boundary(
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
        """The two halves of ``discarded`` are alternatives, not requirements.

        A finished message can carry a tool call that no chunk ever announced —
        a non-streaming provider, or a call assembled entirely in the node
        update. Requiring both signals lets that preamble through.
        """
        events = [
            _chunk(id="m1", content="let me get that set up"),
            _boundary(
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
        """Text arrives one delta at a time; holding only the newest loses all
        but the last few characters of every reply."""
        events = [
            _chunk(id="m1", content="all "),
            _chunk(id="m1", content="set up now."),
            _boundary(AIMessage(id="m1", content="all set up now.")),
        ]

        assert await _run_silent(events) == "all set up now."
        assert _streamed_message(await _run_streaming(events)) == "all set up now."

    async def test_two_kept_messages_are_separated_by_the_break_sentinel(self) -> None:
        """Silent mode persists the whole turn, so two replies in one run are two
        bubbles — concatenating them glues two sentences into one."""
        events = [
            _chunk(id="m1", content="on it."),
            _boundary(AIMessage(id="m1", content="on it.")),
            _chunk(id="m2", content="all done."),
            _boundary(AIMessage(id="m2", content="all done.")),
        ]

        assert await _run_silent(events) == f"on it.{NEW_MESSAGE_BREAKER}all done."


@pytest.mark.unit
class TestChunkLevelSilence:
    """The per-chunk guard, on the delta order where it is the only guard."""

    async def test_text_that_follows_its_own_tool_call_never_reaches_the_user(self) -> None:
        """Anthropic-shaped ordering: the tool call announces first, then the
        narration. Nothing downstream can catch it — the finished message's
        arguments never parsed, so the boundary sees no tool call at all. Only
        the chunk that carried ``tool_call_chunks`` knows.
        """
        events = [
            _chunk(id="m1", **_UNPARSEABLE_CALL),
            _chunk(id="m1", content="let me get that set up"),
            _boundary(AIMessage(id="m1", content="let me get that set up")),
        ]

        assert await _run_silent(events) == ""
        frames = await _run_streaming(events)
        assert _frames(frames, "response") == []
        assert _streamed_message(frames) == ""


@pytest.mark.unit
class TestRetractionMidNode:
    """The style guard retracts a draft on the custom stream, before any
    boundary — the driver has to forget it there or it is persisted anyway."""

    async def test_a_retracted_id_less_draft_is_forgotten(self) -> None:
        """An id-less draft is held under the empty key and retracted under a
        null id: both sides have to normalise to the same key, and the retraction
        has to be handed the hold it is meant to edit."""
        events = [
            _chunk(id=None, content="Great question! Let me unpack that."),
            _custom({"message_boundary": {"message_id": None, "discarded": True}}),
        ]

        assert await _run_silent(events) == ""
        assert _streamed_message(await _run_streaming(events)) == ""

    async def test_a_kept_draft_survives_the_custom_stream(self) -> None:
        events = [
            _chunk(id=None, content="all set up now."),
            _custom({"message_boundary": {"message_id": None, "discarded": False}}),
        ]

        assert await _run_silent(events) == "all set up now."
        assert _streamed_message(await _run_streaming(events)) == "all set up now."
