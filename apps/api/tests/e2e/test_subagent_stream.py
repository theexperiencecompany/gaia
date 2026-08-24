"""What a subagent puts on the chat stream, and what it hands back to its parent.

Drives the real ``execute_subagent_stream`` — the driver every handoff and
provider subagent runs through. It is not an SSE producer: it calls a
``stream_writer`` with plain dicts, which ``background/redis_writer.py``
serializes verbatim as ``data: {json}\\n\\n``. So the writer payloads *are* the
frames, and :class:`Transcript` asserts on them the same way.

Two contracts live here and nothing else covers either one:

* **subagent routing.** Every frame a subagent emits must carry its
  ``subagent_id``. The frontend reducer routes on that key alone
  (``updateSubagentInToolData`` in ``turnAccumulator.ts``); an untagged frame
  does not land in the wrong group, it lands at the *root* of the turn — the
  card appears outside the subagent it belongs to.
* **the return value.** A subagent that only narrated and never ran a tool has
  not done the work. It must tell its parent to re-issue the handoff instead of
  passing planning text off as a result.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
import pytest

from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    execute_subagent_stream,
    interrupt_payload,
    subagent_row_id,
)
from app.constants.hil import LANGGRAPH_INTERRUPT_KEY
from tests.e2e._harness import (
    Event,
    ScriptedGraph,
    Transcript,
    agent_update,
    flat,
    message,
    node_update,
    tool_message,
)

pytestmark = pytest.mark.e2e

SUB_ID = "sub_gmail_1"


@pytest.fixture(autouse=True)
def _registry(real_tool_registry):
    """Tool categories and display labels come from the real global registry."""


def _tool_call(name: str, args: dict[str, Any] | None = None, id: str | None = "tc_1") -> dict:
    return {"name": name, "args": args or {}, "id": id, "type": "tool_call"}


def _context(graph: ScriptedGraph) -> SubagentExecutionContext:
    return SubagentExecutionContext(
        subagent_graph=cast(Any, graph),
        agent_name="gmail_agent",
        config=cast(Any, {"configurable": {"thread_id": "t-1"}, "agent_name": "gmail_agent"}),
        configurable={"thread_id": "t-1"},
        integration_id="gmail",
        initial_state={"messages": []},
    )


async def run_subagent(
    events: Sequence[Event],
    *,
    subagent_id: str | None = SUB_ID,
    graph: ScriptedGraph | None = None,
) -> tuple[Transcript, Any, ScriptedGraph]:
    """Run the real subagent driver and capture everything it wrote."""
    scripted = graph if graph is not None else ScriptedGraph(events)
    written: list[dict[str, Any]] = []
    outcome = await execute_subagent_stream(
        ctx=_context(scripted),
        stream_writer=written.append,
        subagent_id=subagent_id,
    )
    return Transcript.from_events(written), outcome, scripted


# ---------------------------------------------------------------------------
# Routing: every frame must be tagged with the subagent it came from
# ---------------------------------------------------------------------------


class TestSubagentRouting:
    async def test_a_tool_call_is_tagged_with_its_subagent(self):
        """Untagged, the card renders at the root of the turn instead of inside
        the subagent's group."""
        transcript, _, _ = await run_subagent(
            flat(
                agent_update(
                    AIMessage(
                        content="",
                        tool_calls=[_tool_call("GMAIL_FETCH_MESSAGES", {"max_results": 5})],
                    )
                )
            )
        )

        call = transcript.tool_call("GMAIL_FETCH_MESSAGES")
        assert call.subagent_id == SUB_ID
        assert call.args == {"max_results": 5}

    async def test_a_tool_result_is_tagged_with_its_subagent(self):
        transcript, _, _ = await run_subagent(
            flat(tool_message("3 unread", tool_call_id="tc_1", name="GMAIL_FETCH_MESSAGES"))
        )

        assert [(o.tool_call_id, o.subagent_id) for o in transcript.outputs()] == [("tc_1", SUB_ID)]

    @pytest.mark.parametrize(
        "chunk",
        [
            pytest.param(
                AIMessageChunk(
                    content="", additional_kwargs={"reasoning_content": "Checking the inbox"}
                ),
                id="deepseek-style-kwargs",
            ),
            pytest.param(
                AIMessageChunk(content=[{"type": "reasoning", "reasoning": "Checking the inbox"}]),
                id="openrouter-style-blocks",
            ),
        ],
    )
    async def test_reasoning_deltas_are_tagged_with_their_subagent(self, chunk: AIMessageChunk):
        """Thinking text has to nest under the right step, same routing key.

        Both provider shapes are covered because both are real: LangChain
        normalizes ``additional_kwargs.reasoning_content`` into a ``reasoning``
        content block, so a reader who only sees one shape in the wild would not
        know the other is handled.
        """
        transcript, _, _ = await run_subagent(flat(message(chunk)))

        assert transcript.of_kind("reasoning") == [
            {"content": "Checking the inbox", "subagent_id": SUB_ID}
        ]

    async def test_a_chunk_with_no_thinking_emits_no_reasoning_frame(self):
        """Non-reasoning models send ordinary chunks; a blank reasoning frame per
        token would render an empty "Thinking" row on every turn."""
        transcript, _, _ = await run_subagent(
            flat(message(AIMessageChunk(content="You have 3 unread emails.")))
        )

        assert transcript.of_kind("reasoning") == []

    async def test_a_call_and_its_result_share_one_id_across_both_frames(self):
        """The frontend joins the subagent's result to its card by
        ``tool_call_id`` inside the group — the same join as the root timeline."""
        transcript, _, _ = await run_subagent(
            flat(
                agent_update(
                    AIMessage(content="", tool_calls=[_tool_call("GMAIL_FETCH_MESSAGES")])
                ),
                tool_message("3 unread", tool_call_id="tc_1", name="GMAIL_FETCH_MESSAGES"),
            )
        )

        assert transcript.result_for("GMAIL_FETCH_MESSAGES") == "3 unread"

    async def test_an_untagged_run_emits_no_subagent_key_at_all(self):
        """The executor tier runs this same driver with no subagent_id; a null
        key there would route its frames into a group that does not exist."""
        transcript, _, _ = await run_subagent(
            flat(
                agent_update(AIMessage(content="", tool_calls=[_tool_call("read")])),
                tool_message("file contents", tool_call_id="tc_1", name="read"),
            ),
            subagent_id=None,
        )

        assert transcript.tool_call("read").subagent_id is None
        assert "subagent_id" not in transcript.of_kind("tool_output")[0]


# ---------------------------------------------------------------------------
# The return value the parent acts on
# ---------------------------------------------------------------------------


class TestReturnValue:
    async def test_narration_without_any_tool_call_tells_the_parent_to_retry(self):
        """A subagent that only planned has not done the work. Returning the
        planning text would make the executor report success for nothing."""
        _, outcome, _ = await run_subagent(
            flat(message(AIMessageChunk(content="I will check your inbox shortly.")))
        )

        assert "ended without running any tool" in outcome.text
        assert "Re-issue the handoff" in outcome.text
        assert outcome.paused is False

    async def test_narration_alongside_a_real_tool_call_is_returned_as_the_answer(self):
        """Control for the guard above: once a tool ran, the text IS the result."""
        _, outcome, _ = await run_subagent(
            flat(
                agent_update(
                    AIMessage(content="", tool_calls=[_tool_call("GMAIL_FETCH_MESSAGES")])
                ),
                tool_message("3 unread", tool_call_id="tc_1", name="GMAIL_FETCH_MESSAGES"),
                message(AIMessageChunk(content="You have 3 unread emails.")),
            )
        )

        assert outcome.text == "You have 3 unread emails."

    async def test_a_resumed_run_that_only_sees_its_tool_result_is_not_narration(self):
        """After a HIL approval the subagent resumes at the tools node, so this
        invocation never sees the ``updates`` event that emitted the card — its
        ``emitted_tool_calls`` set starts empty. The ToolMessage is then the only
        evidence work happened. Miss it and the parent is told to re-issue a
        handoff whose action (sending the email) already executed.
        """
        _, outcome, _ = await run_subagent(
            flat(
                tool_message("Email sent.", tool_call_id="tc_1", name="GMAIL_SEND_EMAIL"),
                message(AIMessageChunk(content="I sent the email.")),
            )
        )

        assert outcome.text == "I sent the email."
        assert "Re-issue the handoff" not in outcome.text

    async def test_a_silent_run_reports_task_completed(self):
        _, outcome, _ = await run_subagent([])

        assert outcome.text == "Task completed"

    async def test_finish_task_content_becomes_the_result(self):
        """Subagents that terminate through ``finish_task`` carry their answer in
        the tool's return value, not in an AIMessage."""
        _, outcome, _ = await run_subagent(
            flat(
                agent_update(AIMessage(content="", tool_calls=[_tool_call("finish_task")])),
                tool_message(
                    "Drafted and saved the reply.", tool_call_id="tc_1", name="finish_task"
                ),
            )
        )

        assert outcome.text == "Drafted and saved the reply."


# ---------------------------------------------------------------------------
# Malformed and empty stream events
# ---------------------------------------------------------------------------


class TestMalformedEvents:
    async def test_a_state_update_that_is_not_a_mapping_is_skipped(self):
        """Nodes may yield a list, a string, or None. The extractor's isinstance
        guard is what stops that becoming a TypeError mid-turn."""
        transcript, outcome, _ = await run_subagent(
            [("updates", {"agent": ["not", "a", "mapping"]}), ("updates", {"agent": None})]
        )

        assert transcript.frames() == []
        assert outcome.text == "Task completed"

    async def test_a_state_update_with_no_messages_key_is_skipped(self):
        transcript, _, _ = await run_subagent([("updates", {"agent": {"todos": []}})])

        assert transcript.frames() == []

    async def test_a_tool_call_with_no_name_emits_no_card(self):
        """``format_tool_call_entry`` returns None for it; emitting the ``None``
        would put a frame with a null payload on the wire."""
        transcript, _, _ = await run_subagent(
            flat(
                agent_update(
                    AIMessage(
                        content="",
                        tool_calls=[{"name": "", "args": {}, "id": "tc_1", "type": "tool_call"}],
                    )
                )
            )
        )

        assert transcript.frames() == []

    async def test_a_tool_call_with_no_id_emits_no_card(self):
        """No id means the result can never join back to the card."""
        transcript, _, _ = await run_subagent(
            flat(
                agent_update(
                    AIMessage(content="", tool_calls=[_tool_call("GMAIL_FETCH_MESSAGES", id=None)])
                )
            )
        )

        assert transcript.frames() == []

    async def test_an_empty_tool_result_still_ships_a_frame(self):
        """A tool that returns nothing is not the same as a tool that never
        finished — without the frame the card spins forever."""
        transcript, _, _ = await run_subagent(
            flat(tool_message("", tool_call_id="tc_1", name="GMAIL_FETCH_MESSAGES"))
        )

        assert transcript.of_kind("tool_output") == [
            {"tool_call_id": "tc_1", "output": "", "subagent_id": SUB_ID}
        ]

    async def test_the_same_tool_call_replayed_emits_one_card(self):
        msg = AIMessage(content="", tool_calls=[_tool_call("GMAIL_FETCH_MESSAGES", id="tc_dup")])
        transcript, _, _ = await run_subagent(flat(agent_update(msg), agent_update(msg)))

        assert transcript.tool_names() == ["GMAIL_FETCH_MESSAGES"]

    @pytest.mark.parametrize("node", ["filter_messages", "manage_system_prompts", "tools"])
    async def test_only_the_agent_node_emits_cards(self, node: str):
        """Same stale-replay hazard as the comms stream: pre-model hooks re-emit
        historical AIMessages carrying last run's tool calls."""
        historical = AIMessage(
            content="", tool_calls=[_tool_call("GMAIL_FETCH_MESSAGES", id="old_1")]
        )
        transcript, _, _ = await run_subagent(flat(node_update(node, historical)))

        assert transcript.frames() == []

    async def test_three_tuple_events_are_ignored(self):
        """This driver streams without subgraphs, so a 3-tuple is not a shape it
        can unpack — it must skip, not crash."""
        transcript, outcome, _ = await run_subagent(
            [agent_update(AIMessage(content="", tool_calls=[_tool_call("read")]))]
        )

        assert transcript.frames() == []
        assert outcome.text == "Task completed"

    async def test_silent_payloads_emit_nothing_and_do_not_accumulate(self):
        transcript, outcome, _ = await run_subagent(
            [
                ("messages", (AIMessageChunk(content="hidden"), {"silent": True})),
                (
                    "messages",
                    (ToolMessage(content="hidden", tool_call_id="tc_1"), {"silent": True}),
                ),
            ]
        )

        assert transcript.frames() == []
        assert outcome.text == "Task completed"

    async def test_inline_media_is_stripped_from_a_subagent_result(self):
        transcript, _, _ = await run_subagent(
            flat(
                tool_message(
                    [
                        {"type": "text", "text": "Attachment saved"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                    ],
                    tool_call_id="tc_1",
                    name="GMAIL_FETCH_MESSAGES",
                )
            )
        )

        assert transcript.outputs()[0].output == "Attachment saved"


# ---------------------------------------------------------------------------
# HIL pause
# ---------------------------------------------------------------------------


class TestApprovalPause:
    async def test_a_paused_run_reports_the_approval_and_drains_the_stream(self):
        """A pause is not an answer — but the stream still has to be drained.

        It used to break here. Under ``durability="exit"`` the run-exit save is the
        only checkpoint write there is, so abandoning the generator skipped it and the
        writes of every task that had already COMPLETED in the interrupting step were
        lost — LangGraph then re-ran them on resume, which is how an ungated tool call
        beside a gated one executed twice. See
        ``tests/unit/agents/test_pause_checkpointing.py``.

        Draining is safe because the outcome is still marked paused: every caller keys
        off ``outcome.paused`` and never reads the text of a paused run.
        """
        graph = ScriptedGraph(
            [
                *flat(message(AIMessageChunk(content="About to send. "))),
                ("updates", {LANGGRAPH_INTERRUPT_KEY: ({"approval_id": "ap_1"},)}),
                *flat(message(AIMessageChunk(content="after the pause"))),
            ]
        )
        transcript, outcome, _ = await run_subagent([], graph=graph)

        assert outcome.paused is True, "a pause must never be reported as a result"
        assert outcome.interrupt == {"approval_id": "ap_1"}
        assert graph.yielded == 3, (
            "the whole stream must be consumed, or the run-exit checkpoint never lands"
        )
        assert transcript.frames() == []

    async def test_every_paused_call_is_reported_not_just_the_last(self):
        """One ``__interrupt__`` event per paused task, so they must accumulate.

        The caller stamps re-dispatch context onto every id reported here. An approval
        left out gets no ``resume_item``, and deciding it later raises
        ApprovalNotResumableError — the user presses Approve and nothing can ever happen.
        """
        graph = ScriptedGraph(
            [
                ("updates", {LANGGRAPH_INTERRUPT_KEY: ({"approval_id": "ap_1"},)}),
                ("updates", {LANGGRAPH_INTERRUPT_KEY: ({"approval_id": "ap_2"},)}),
            ]
        )
        _transcript, outcome, _ = await run_subagent([], graph=graph)

        assert outcome.paused is True
        assert outcome.interrupt is not None
        assert outcome.interrupt.get("approval_ids") == ["ap_1", "ap_2"], (
            f"both approvals must be reported, got {outcome.interrupt}"
        )

    async def test_an_unreadable_interrupt_is_an_empty_payload_not_a_crash(self):
        """Downstream denies on an empty payload; a raised error here would
        abort the turn instead."""
        assert interrupt_payload(("not-a-dict",)) == {}
        assert interrupt_payload(()) == {}
        assert interrupt_payload(None) == {}


# ---------------------------------------------------------------------------
# Row identity and run configuration
# ---------------------------------------------------------------------------


class TestRunShape:
    async def test_a_subagent_row_id_is_stable_across_replays_of_one_call(self):
        """A subagent that pauses for approval and resumes must reuse its row.
        A fresh uuid per replay orphans the paused row — left spinning forever —
        and emits a duplicate for the resumed run."""
        first_replay = subagent_row_id("tc_abc")
        second_replay = subagent_row_id("tc_abc")
        assert first_replay == second_replay
        assert first_replay != subagent_row_id("tc_def")

    async def test_a_blank_tool_call_id_still_yields_a_unique_row(self):
        first_call = subagent_row_id("")
        second_call = subagent_row_id("")
        assert first_call != second_call

    async def test_the_run_subscribes_to_all_three_stream_modes(self):
        _, _, graph = await run_subagent([])

        assert set(graph.astream_kwargs["stream_mode"]) == {"messages", "custom", "updates"}

    async def test_checkpoints_are_written_once_at_exit(self):
        """``durability="exit"`` collapses O(steps) Postgres checkpoint writes to
        one per run. LangGraph's default is per-step."""
        _, _, graph = await run_subagent([])

        assert graph.astream_kwargs["durability"] == "exit"

    async def test_the_subagent_id_is_threaded_into_the_run_config(self):
        """Nested ``spawn_subagent`` calls read it back as their
        ``parent_subagent_id``; without it a nested subagent renders as a
        sibling of its own parent."""
        _, _, graph = await run_subagent([])

        assert graph.astream_kwargs["config"]["configurable"]["subagent_id"] == SUB_ID

    async def test_custom_events_from_the_subagent_are_forwarded(self):
        transcript, _, _ = await run_subagent([("custom", {"progress": "Fetching page 2"})])

        assert transcript.of_kind("progress") == ["Fetching page 2"]

    async def test_a_cancelled_subagent_stops_pulling_from_its_graph(self):
        graph = ScriptedGraph(
            flat(
                message(AIMessageChunk(content="one ")),
                message(AIMessageChunk(content="two ")),
                message(AIMessageChunk(content="three")),
            )
        )
        ctx = _context(graph)
        ctx.stream_id = "s-1"
        written: list[dict[str, Any]] = []

        with patch(
            "app.agents.core.subagents.subagent_runner.stream_manager.is_cancelled",
            new=AsyncMock(side_effect=[False, True]),
        ):
            outcome = await execute_subagent_stream(
                ctx=ctx, stream_writer=written.append, subagent_id=SUB_ID
            )

        assert graph.yielded == 2
        assert "two" not in outcome.text
