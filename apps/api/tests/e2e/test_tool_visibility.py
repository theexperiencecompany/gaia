"""The tool-call contract of the chat stream, asserted frame by frame.

Every test drives the real ``execute_graph_streaming`` — the function that
translates LangGraph's three stream modes into the SSE vocabulary the chat UI
consumes — and asserts on a parsed :class:`Transcript`, never on prose.

What is under test is the contract the frontend depends on:

* a tool call is *visible*, with its real name and its arguments, before it runs
  (``libs/shared/ts/src/chat/turnAccumulator.ts`` appends the entry to the
  message's tool list);
* its result arrives separately and is joined **only** by ``tool_call_id``
  (``mergeToolOutputIntoToolData`` in ``streaming.ts``) — a broken id means a
  tool card that renders forever without a result;
* frames that must not reach the client (stale replays from pre-model hooks,
  silent turns, executor-tier text, the ``nostream:`` marker) do not.

Only the graph is a double (see ``_harness/graph_double.py``); it exists so a
test can pin the exact LangGraph event sequence, including ones a real run
produces only under conditions a test cannot arrange.
"""

from __future__ import annotations

from collections.abc import Sequence
import re
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk
import pytest

from app.helpers.agent_helpers import execute_graph_streaming
from tests.e2e._harness import (
    DONE,
    TOOL_CALLS_DATA,
    Event,
    ScriptedGraph,
    Transcript,
    agent_update,
    custom,
    node_update,
    text,
    tool_message,
)

pytestmark = pytest.mark.e2e

#: The SSE wire format: one ``data:`` line, then the blank line that ends the event.
_SSE_FRAME = re.compile(r"data: [^\n]+\n\n")


@pytest.fixture(autouse=True)
def _registry(real_tool_registry):
    """Tool categories and display labels come from the real global registry."""


def _tool_call(name: str, args: dict[str, Any] | None = None, id: str | None = "tc_1") -> dict:
    """A LangChain ToolCall exactly as the model layer produces one."""
    return {"name": name, "args": args or {}, "id": id, "type": "tool_call"}


async def run_stream(
    events: Sequence[Event],
    *,
    agent_name: str = "comms_agent",
    graph: ScriptedGraph | None = None,
    stream_id: str | None = None,
) -> Transcript:
    """Stream a scripted LangGraph event sequence through the real translator.

    ``user_id`` is deliberately left out of the config: it only unlocks the MCP
    provenance lookups (``_resolve_mcp_integration_id`` /
    ``_resolve_mcp_ui_metadata``), which are per-user network calls and are not
    what these tests are about.
    """
    scripted = graph if graph is not None else ScriptedGraph(events)
    configurable: dict[str, str] = {"thread_id": "t-1"}
    if stream_id is not None:
        configurable["stream_id"] = stream_id
    config = {"configurable": configurable, "agent_name": agent_name}
    chunks = [chunk async for chunk in execute_graph_streaming(scripted, {}, cast(Any, config))]
    return Transcript.from_chunks(chunks)


# ---------------------------------------------------------------------------
# A tool call is visible, with its real name and arguments
# ---------------------------------------------------------------------------


class TestToolCallVisibility:
    async def test_tool_call_streams_before_its_result(self):
        """The client must see the call itself, not just the final answer."""
        transcript = await run_stream(
            [
                agent_update(
                    AIMessage(content="", tool_calls=[_tool_call("call_executor", {"task": "hi"})])
                ),
                tool_message("Task accepted", tool_call_id="tc_1"),
                text("Done."),
            ]
        )

        assert transcript.tool_names() == ["call_executor"]
        assert transcript.args("call_executor") == {"task": "hi"}
        assert transcript.result_for("call_executor") == "Task accepted"

    async def test_real_tool_name_is_nested_under_the_envelope(self):
        """``tool_name`` on the entry is always the envelope literal; the tool
        the model called is at ``data.tool_name``. Flattening it would make the
        frontend render every tool card as "tool_calls_data"."""
        transcript = await run_stream(
            [agent_update(AIMessage(content="", tool_calls=[_tool_call("call_executor")]))]
        )

        entry = transcript.of_kind("tool_data")[0]
        assert entry["tool_name"] == TOOL_CALLS_DATA
        assert entry["data"]["tool_name"] == "call_executor"

    async def test_arguments_survive_the_wire_verbatim(self):
        """Nested objects, lists, unicode and empty strings all reach the client
        unchanged — the tool card renders these as the call's inputs."""
        args = {
            "title": "Café ☕ meeting",
            "attendees": ["a@x.com", "b@x.com"],
            "meta": {"nested": {"depth": 2}, "flag": False},
            "note": "",
        }
        transcript = await run_stream(
            [agent_update(AIMessage(content="", tool_calls=[_tool_call("call_executor", args)]))]
        )

        assert transcript.args("call_executor") == args

    async def test_curated_special_tool_carries_its_category_and_label(self):
        """``call_executor`` is one of the nine curated tools: the frontend keys
        the executor card off ``tool_category`` and drops the category prefix
        when ``show_category`` is false."""
        transcript = await run_stream(
            [agent_update(AIMessage(content="", tool_calls=[_tool_call("call_executor")]))]
        )

        call = transcript.tool_call("call_executor")
        assert call.category == "executor"
        assert call.message == "Delegating to executor"
        assert call.show_category is False

    async def test_handoff_label_names_the_target_subagent(self):
        """A handoff card must say who it handed off to — the subagent id is
        resolved to a display name, not shown raw."""
        transcript = await run_stream(
            [
                agent_update(
                    AIMessage(
                        content="",
                        tool_calls=[
                            _tool_call("handoff", {"subagent_id": "gmail", "task": "read inbox"})
                        ],
                    )
                )
            ]
        )

        call = transcript.tool_call("handoff")
        assert call.category == "handoff"
        assert call.message == "Handing off to Gmail"
        assert call.args["subagent_id"] == "gmail"

    async def test_several_tool_calls_in_one_message_all_stream_in_order(self):
        """A model turn may carry more than one call; dropping any of them
        loses a card the user was shown mid-turn."""
        transcript = await run_stream(
            [
                agent_update(
                    AIMessage(
                        content="",
                        tool_calls=[
                            _tool_call("add_memory", {"content": "likes tea"}, id="tc_a"),
                            _tool_call("search_memory", {"query": "tea"}, id="tc_b"),
                        ],
                    )
                )
            ]
        )

        assert transcript.tool_names() == ["add_memory", "search_memory"]

    async def test_calls_across_turns_keep_their_emission_order(self):
        transcript = await run_stream(
            [
                agent_update(AIMessage(content="", tool_calls=[_tool_call("add_memory", id="a")])),
                tool_message("stored", tool_call_id="a"),
                agent_update(
                    AIMessage(content="", tool_calls=[_tool_call("search_memory", id="b")])
                ),
                tool_message("found", tool_call_id="b"),
            ]
        )

        assert transcript.tool_names() == ["add_memory", "search_memory"]
        assert transcript.result_for("add_memory") == "stored"
        assert transcript.result_for("search_memory") == "found"


# ---------------------------------------------------------------------------
# Deduplication and skip guards
# ---------------------------------------------------------------------------


class TestToolCallEmissionGuards:
    async def test_a_repeated_tool_call_id_is_emitted_once(self):
        """LangGraph re-sends the same ``AIMessage`` across updates within a
        turn. Without the dedup set the user sees the same card twice."""
        message = AIMessage(content="", tool_calls=[_tool_call("call_executor", id="tc_dup")])
        transcript = await run_stream([agent_update(message), agent_update(message)])

        assert transcript.tool_names() == ["call_executor"]

    async def test_a_tool_call_without_an_id_is_not_streamed(self):
        """An id-less call can never be joined to its result, so streaming it
        would strand a card with no output forever."""
        transcript = await run_stream(
            [agent_update(AIMessage(content="", tool_calls=[_tool_call("call_executor", id=None)]))]
        )

        assert transcript.of_kind("tool_data") == []

    async def test_two_distinct_calls_to_the_same_tool_both_stream(self):
        """Dedup is per call id, not per tool name — a tool legitimately called
        twice in a turn must show two cards."""
        transcript = await run_stream(
            [
                agent_update(
                    AIMessage(content="", tool_calls=[_tool_call("add_memory", id="tc_1")])
                ),
                agent_update(
                    AIMessage(content="", tool_calls=[_tool_call("add_memory", id="tc_2")])
                ),
            ]
        )

        assert transcript.tool_names() == ["add_memory", "add_memory"]

    async def test_messages_without_tool_calls_produce_no_tool_frames(self):
        transcript = await run_stream([agent_update(AIMessage(content="Just talking."))])

        assert transcript.of_kind("tool_data") == []


# ---------------------------------------------------------------------------
# The node gate — the reason stale tool cards do not replay
# ---------------------------------------------------------------------------


class TestNodeGate:
    @pytest.mark.parametrize(
        "node", ["filter_messages", "manage_system_prompts", "tools", "follow_up_actions"]
    )
    async def test_only_the_agent_node_streams_tool_cards(self, node: str):
        """Pre-model hooks replay historical ``AIMessage``s that still carry
        last turn's ``tool_calls``. Emitting those would replay stale tool cards
        into the current turn."""
        historical = AIMessage(content="", tool_calls=[_tool_call("add_memory", id="old_1")])
        transcript = await run_stream([node_update(node, historical)])

        assert transcript.of_kind("tool_data") == []

    async def test_a_hook_replay_does_not_suppress_the_real_call(self):
        """The gate must filter by node, not by "first seen wins" — the same
        call replayed by a hook *before* the agent node must still stream."""
        call = AIMessage(content="", tool_calls=[_tool_call("add_memory", id="tc_live")])
        transcript = await run_stream([node_update("filter_messages", call), agent_update(call)])

        assert transcript.tool_names() == ["add_memory"]


# ---------------------------------------------------------------------------
# Response text gating
# ---------------------------------------------------------------------------


class TestResponseText:
    async def test_comms_agent_text_streams_as_response_deltas(self):
        transcript = await run_stream([text("Hel"), text("lo!")])

        assert transcript.of_kind("response") == ["Hel", "lo!"]
        assert transcript.final_text() == "Hello!"

    async def test_executor_text_never_reaches_the_client(self):
        """Only ``comms_agent`` talks to the user. Executor-tier text on the
        same stream would duplicate the reply the comms agent is about to give."""
        transcript = await run_stream([text("internal reasoning")], agent_name="executor_agent")

        assert transcript.of_kind("response") == []
        assert transcript.complete_message() == ""

    async def test_silent_turns_emit_no_text(self):
        """Silent runs (workflows, background turns) share this code path; their
        text must not surface in a user-facing stream."""
        transcript = await run_stream([text("silent output", silent=True)])

        assert transcript.of_kind("response") == []

    async def test_completion_marker_carries_the_text_that_gets_persisted(self):
        """The ``nostream:`` marker is where the persisted bot message comes
        from — it must equal what the user actually saw."""
        transcript = await run_stream([text("Part one. "), text("Part two.")])

        assert transcript.complete_message() == "Part one. Part two."
        assert transcript.complete_message() == transcript.final_text()

    async def test_empty_text_chunks_emit_no_frame(self):
        """Providers routinely send empty deltas (role-only or usage-only
        chunks); forwarding them is dead weight on the wire."""
        transcript = await run_stream([text(""), text("real")])

        assert transcript.of_kind("response") == ["real"]


# ---------------------------------------------------------------------------
# tool_output rules
# ---------------------------------------------------------------------------


class TestToolOutput:
    async def test_output_joins_its_call_by_id_not_by_position(self):
        """Two calls complete out of order — each result must land on its own
        card. Joining by arrival order would swap them."""
        transcript = await run_stream(
            [
                agent_update(
                    AIMessage(
                        content="",
                        tool_calls=[
                            _tool_call("add_memory", id="tc_a"),
                            _tool_call("search_memory", id="tc_b"),
                        ],
                    )
                ),
                tool_message("second finished first", tool_call_id="tc_b"),
                tool_message("first finished second", tool_call_id="tc_a"),
            ]
        )

        assert transcript.result_for("add_memory") == "first finished second"
        assert transcript.result_for("search_memory") == "second finished first"

    async def test_an_output_for_an_unknown_id_joins_to_nothing(self):
        """The frame still ships, but it must not attach to an unrelated card."""
        transcript = await run_stream(
            [
                agent_update(
                    AIMessage(content="", tool_calls=[_tool_call("add_memory", id="tc_real")])
                ),
                tool_message("orphan", tool_call_id="tc_other"),
            ]
        )

        assert transcript.result_for("add_memory") is None
        assert [o.tool_call_id for o in transcript.outputs()] == ["tc_other"]

    async def test_output_payload_omits_the_subagent_key_when_absent(self):
        """``exclude_none`` keeps root-level results free of a null
        ``subagent_id``, which the frontend routes on."""
        transcript = await run_stream([tool_message("plain result", tool_call_id="tc_1")])

        assert transcript.of_kind("tool_output") == [
            {"tool_call_id": "tc_1", "output": "plain result"}
        ]

    @pytest.mark.parametrize("suppressed", ["plan_tasks", "update_tasks"])
    async def test_todo_tool_results_are_suppressed(self, suppressed: str):
        """Todo tools already stream ``todo_progress``; a second result frame
        renders a duplicate card next to the todo list."""
        transcript = await run_stream([tool_message("[]", tool_call_id="tc_1", name=suppressed)])

        assert transcript.of_kind("tool_output") == []

    async def test_todo_flagged_tools_are_suppressed_by_their_marker(self):
        """Tracked-todo helpers are not named ``plan_tasks``; they carry the
        ``todo_tool`` marker instead."""
        transcript = await run_stream(
            [
                tool_message(
                    "ok",
                    tool_call_id="tc_1",
                    name="some_tracked_helper",
                    additional_kwargs={"todo_tool": True},
                )
            ]
        )

        assert transcript.of_kind("tool_output") == []

    async def test_a_non_todo_tool_result_is_not_suppressed(self):
        """Control for the two suppression tests above — without it, a bug that
        suppressed every result would still look correct."""
        transcript = await run_stream(
            [tool_message("real result", tool_call_id="tc_1", name="add_memory")]
        )

        assert transcript.of_kind("tool_output") == [
            {"tool_call_id": "tc_1", "output": "real result"}
        ]

    async def test_inline_media_is_stripped_out_of_the_result(self):
        """A base64 image block in a tool result would ship megabytes into the
        SSE frame and into the persisted message."""
        transcript = await run_stream(
            [
                tool_message(
                    [
                        {"type": "text", "text": "Here is the chart"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                    ],
                    tool_call_id="tc_1",
                )
            ]
        )

        output = transcript.outputs()[0].output
        assert output == "Here is the chart"
        assert "base64" not in output


# ---------------------------------------------------------------------------
# Model fallback
# ---------------------------------------------------------------------------


class TestModelFallback:
    async def test_fallback_is_announced_once_per_stream(self):
        """The frontend shows it as a toast; one downgrade must not produce a
        toast per model chunk."""
        fell_back = AIMessage(
            content="",
            response_metadata={"gaia_fell_back": True, "gaia_fallback_model": "grok-4"},
        )
        transcript = await run_stream([agent_update(fell_back), agent_update(fell_back)])

        assert transcript.of_kind("model_fallback") == [{"model": "grok-4"}]

    async def test_no_fallback_frame_on_a_normal_turn(self):
        transcript = await run_stream(
            [agent_update(AIMessage(content="hi", response_metadata={"model_name": "grok-4"}))]
        )

        assert transcript.of_kind("model_fallback") == []


# ---------------------------------------------------------------------------
# Custom events — how subagents and reasoning reach the same stream
# ---------------------------------------------------------------------------


class TestCustomEvents:
    async def test_subagent_lifecycle_and_reasoning_ride_the_same_stream(self):
        """Subagent activity is published onto the comms stream id, not a
        nested channel — one subscription must see all of it."""
        transcript = await run_stream(
            [
                custom(
                    {
                        "subagent_start": {
                            "subagent_id": "sub_1",
                            "subagent_name": "Gmail",
                            "agent_type": "handoff",
                            "started_at": "2026-01-01T00:00:00Z",
                        }
                    }
                ),
                custom({"reasoning": {"content": "Checking ", "subagent_id": "sub_1"}}),
                custom({"reasoning": {"content": "the inbox.", "subagent_id": "sub_1"}}),
                custom({"subagent_end": {"subagent_id": "sub_1", "duration_ms": 120}}),
            ]
        )

        assert transcript.subagent_ids() == ["sub_1"]
        assert transcript.reasoning_text() == "Checking the inbox."
        assert transcript.of_kind("subagent_end") == [{"subagent_id": "sub_1", "duration_ms": 120}]

    async def test_subagent_tool_calls_are_visible_and_tagged(self):
        """A tool run inside a subagent must still show up as a tool call, and
        carry the ``subagent_id`` the frontend groups it under."""
        transcript = await run_stream(
            [
                custom(
                    {
                        "subagent_start": {
                            "subagent_id": "sub_1",
                            "subagent_name": "Gmail",
                            "agent_type": "handoff",
                            "started_at": "2026-01-01T00:00:00Z",
                        }
                    }
                ),
                custom(
                    {
                        "tool_data": {
                            "tool_name": TOOL_CALLS_DATA,
                            "tool_category": "gmail",
                            "subagent_id": "sub_1",
                            "data": {
                                "tool_name": "GMAIL_FETCH_MESSAGES",
                                "inputs": {"max_results": 5},
                                "tool_call_id": "tc_sub",
                                "message": "Reading your inbox",
                            },
                            "timestamp": "2026-01-01T00:00:01Z",
                        }
                    }
                ),
                custom(
                    {
                        "tool_output": {
                            "tool_call_id": "tc_sub",
                            "output": "3 unread",
                            "subagent_id": "sub_1",
                        }
                    }
                ),
            ]
        )

        call = transcript.tool_call("GMAIL_FETCH_MESSAGES")
        assert call.subagent_id == "sub_1"
        assert call.args == {"max_results": 5}
        assert transcript.result_for("GMAIL_FETCH_MESSAGES") == "3 unread"

    async def test_progress_frames_pass_through_untouched(self):
        transcript = await run_stream([custom({"progress": "Downloading attachment"})])

        assert transcript.of_kind("progress") == ["Downloading attachment"]


# ---------------------------------------------------------------------------
# Stream shape and the internal marker
# ---------------------------------------------------------------------------


class TestStreamShape:
    async def test_stream_terminates_with_done_as_its_last_frame(self):
        transcript = await run_stream([text("hi")])

        assert transcript.kinds()[-1] == DONE
        assert transcript.kinds().count(DONE) == 1

    async def test_every_frame_is_a_well_formed_sse_event(self):
        """``data: <json>\\n\\n``, no exceptions. A frame missing its blank line
        is folded into the next event by every EventSource implementation, so a
        single malformed frame silently corrupts the rest of the turn."""
        transcript = await run_stream(
            [
                agent_update(AIMessage(content="", tool_calls=[_tool_call("call_executor")])),
                tool_message("done", tool_call_id="tc_1"),
                custom({"progress": "working"}),
                text("hi"),
            ]
        )

        wire = [chunk for chunk in transcript.raw() if not chunk.startswith("nostream: ")]
        # tool_data, tool_output, message_boundary (the agent update closes that
        # message), progress, response, [DONE].
        assert len(wire) == 6
        for chunk in wire:
            assert _SSE_FRAME.fullmatch(chunk), f"malformed SSE frame: {chunk!r}"

    async def test_the_completion_marker_is_not_an_sse_frame(self):
        """``nostream:`` is consumed by the chat service before the wire. If it
        were emitted as ``data:`` it would be an unparseable frame for every
        client — and it carries the raw persisted text."""
        transcript = await run_stream([text("hi")])

        markers = [chunk for chunk in transcript.raw() if chunk.startswith("nostream: ")]
        assert len(markers) == 1
        assert not markers[0].startswith("data: ")
        assert all("nostream" not in frame.payload for frame in transcript.frames())

    async def test_the_marker_precedes_the_done_terminator(self):
        """The service reads the marker to persist the turn; it must arrive
        before the client is told the stream is over."""
        raw = (await run_stream([text("hi")])).raw()

        assert raw[-2].startswith("nostream: ")
        assert raw[-1] == "data: [DONE]\n\n"

    async def test_an_empty_run_still_terminates(self):
        """A turn the model answers with nothing must not leave the client
        waiting on a stream that never closes."""
        transcript = await run_stream([])

        assert transcript.is_done
        assert transcript.complete_message() == ""

    async def test_two_tuple_events_are_still_translated(self):
        """LangGraph yields 2-tuples when a mode emits outside a subgraph
        namespace; dropping them would silently lose frames."""
        transcript = await run_stream(
            [("messages", (AIMessageChunk(content="from a 2-tuple"), {}))]
        )

        assert transcript.final_text() == "from a 2-tuple"

    async def test_the_graph_is_streamed_with_subgraphs_and_all_three_modes(self):
        """Executor and subagent activity only reaches this stream because the
        run subscribes to subgraph namespaces and to the ``custom`` mode."""
        graph = ScriptedGraph([])
        await run_stream([], graph=graph)

        assert graph.astream_kwargs["subgraphs"] is True
        assert set(graph.astream_kwargs["stream_mode"]) == {"messages", "custom", "updates"}


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


class TestCancellation:
    async def test_a_cancelled_stream_stops_pulling_from_the_graph(self):
        """Cancel must abandon the run, not merely stop forwarding its output.

        Both graphs are scripted identically, so the only difference is the
        cancel flag — which pins down what "not cancelled" looks like and makes
        the truncation assertion mean something. ``yielded`` is the load-bearing
        check: a run that keeps draining events is a graph still doing work
        (and still burning tokens) after the user pressed stop.
        """
        events = [text("one "), text("two "), text("three")]
        cancelled_graph = ScriptedGraph(events)
        control_graph = ScriptedGraph(events)

        with patch(
            "app.helpers.agent_helpers.stream_manager.is_cancelled",
            new=AsyncMock(side_effect=[False, True, True]),
        ):
            cancelled = await run_stream([], graph=cancelled_graph, stream_id="s-cancel")

        with patch(
            "app.helpers.agent_helpers.stream_manager.is_cancelled",
            new=AsyncMock(return_value=False),
        ):
            control = await run_stream([], graph=control_graph, stream_id="s-control")

        assert cancelled.cancelled is True
        assert cancelled.final_text() == "one "
        assert cancelled.is_done
        assert cancelled_graph.yielded == 2

        assert control.cancelled is False
        assert control.final_text() == "one two three"
        assert control_graph.yielded == 3

    async def test_cancelling_closes_the_run_before_recording_the_interruption(self):
        """``record_interruption`` reads the checkpoint, so the run must already
        be stopped — otherwise it records a state the run then overwrites."""
        graph = ScriptedGraph(
            [text("one "), text("two ")],
            state_values={
                "messages": [
                    AIMessage(content="", tool_calls=[_tool_call("add_memory", id="tc_open")])
                ]
            },
        )

        with patch(
            "app.helpers.agent_helpers.stream_manager.is_cancelled",
            new=AsyncMock(side_effect=[False, True]),
        ):
            transcript = await run_stream([], graph=graph, stream_id="s-1")

        assert transcript.cancelled is True
        assert graph.closed is True, "the run was never explicitly closed"
        assert graph.updates_at_close == 0, (
            "the checkpoint was written before the run was stopped, so it records "
            "a state the run could still overwrite"
        )
        assert graph.state_updates, "the interruption was never written to the checkpoint"
        assert graph.state_updates[0]["as_node"] == "tools"

    async def test_no_cancellation_check_without_a_stream_id(self):
        """Silent/background runs carry no stream id; they must not be probed
        for a cancel flag that can never be set."""
        with patch(
            "app.helpers.agent_helpers.stream_manager.is_cancelled", new=AsyncMock()
        ) as is_cancelled:
            transcript = await run_stream([text("hi")])

        is_cancelled.assert_not_awaited()
        assert transcript.cancelled is False
