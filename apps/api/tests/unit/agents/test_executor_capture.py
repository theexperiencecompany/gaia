"""Unit tests for executor tool-event capture and drain (executor_capture.py).

Pins the contracts terminal handlers depend on:
- drain is a NON-DESTRUCTIVE read — single-ownership (not source-emptying) is
  what prevents duplicate cards, so a second drain must return the same data;
- drain runs the real shaping pipeline (output backfill, subagent grouping);
- the redis stream writer appends every event to the session collector.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.background import redis_writer as rw, session as sess
from app.agents.core.background.executor_capture import (
    await_executor_done,
    build_returned_to_frontend_note,
    drain_executor_tool_data,
    register_executor_capture,
    teardown_executor_capture,
)
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.background.session import (
    RunKind,
    create_session,
    get_session,
    signal_executor_done,
)
from app.constants.agents import AgentTag, wrap_agent_payload


@pytest.fixture(autouse=True)
def _clean_registry():
    sess._sessions.clear()
    yield
    sess._sessions.clear()


def _tool_call_event(tool_call_id: str, subagent_id: str | None = None) -> dict:
    entry: dict = {
        "tool_name": "tool_calls_data",
        "data": {"tool_call_id": tool_call_id, "name": "web_search"},
    }
    if subagent_id:
        entry["subagent_id"] = subagent_id
    return {"tool_data": entry}


class TestRegisterAndDone:
    def test_register_creates_live_session_and_returns_its_done_event(self) -> None:
        done = register_executor_capture("s1")
        session = get_session("s1")
        assert session is not None
        assert session.kind is RunKind.LIVE
        assert done is session.done_event

    async def test_await_returns_immediately_when_no_executor_spawned(self) -> None:
        register_executor_capture("s1")
        # No mark_executor_spawned — must not block on the done event.
        await await_executor_done("s1")

    async def test_await_unblocks_when_executor_signals_done(self) -> None:
        session = create_session("s1", RunKind.LIVE)
        session.executor_spawned = True
        signal_executor_done("s1")
        await await_executor_done("s1")  # returns because the event is set


class TestDrain:
    def test_drain_without_session_returns_empty(self) -> None:
        assert drain_executor_tool_data("missing") == []

    def test_drain_backfills_tool_outputs_into_entries(self) -> None:
        session = create_session("s1", RunKind.QUEUED)
        session.tool_events.append(_tool_call_event("tc-1"))
        session.tool_events.append(
            {"tool_output": {"tool_call_id": "tc-1", "output": "42 results"}}
        )

        entries = drain_executor_tool_data("s1")

        assert len(entries) == 1
        assert entries[0]["tool_name"] == "tool_calls_data"
        assert entries[0]["data"]["output"] == "42 results"

    def test_drain_groups_subagent_events(self) -> None:
        session = create_session("s1", RunKind.QUEUED)
        session.tool_events.append(
            {
                "subagent_start": {
                    "subagent_id": "sub-1",
                    "subagent_name": "gmail",
                    "agent_type": "handoff",
                }
            }
        )
        session.tool_events.append(_tool_call_event("tc-1", subagent_id="sub-1"))
        session.tool_events.append({"subagent_end": {"subagent_id": "sub-1", "duration_ms": 120}})

        entries = drain_executor_tool_data("s1")

        groups = [e for e in entries if e.get("tool_name") == "subagent_group"]
        assert len(groups) == 1
        group = groups[0]["data"]
        assert group["subagent_id"] == "sub-1"
        assert group["subagent_name"] == "gmail"
        assert group["duration_ms"] == 120
        assert len(group["tool_calls"]) == 1
        assert group["tool_calls"][0]["tool_call_id"] == "tc-1"

    def test_drain_is_non_destructive(self) -> None:
        """Single-ownership depends on this: draining must NOT empty the source.

        If someone "optimizes" drain into a destructive pop, the comms attach
        and a finalize backstop racing would silently drop cards instead of
        deduping by ownership.
        """
        session = create_session("s1", RunKind.QUEUED)
        session.tool_events.append(_tool_call_event("tc-1"))

        first = drain_executor_tool_data("s1")
        second = drain_executor_tool_data("s1")

        assert first == second
        assert len(second) == 1

    def test_teardown_clears_collected_events(self) -> None:
        session = create_session("s1", RunKind.QUEUED)
        session.tool_events.append(_tool_call_event("tc-1"))
        teardown_executor_capture("s1")
        assert drain_executor_tool_data("s1") == []


class TestReturnedToFrontendNote:
    """The note is comms' only record of which cards the frontend already has.

    Reduced to (name, count) it says a todo card exists but not which system
    produced it, so comms had nothing to contradict an executor summary that
    filed eight GAIA todos under "Todoist".
    """

    def test_cards_from_a_subagent_name_the_subagent_that_produced_them(self) -> None:
        session = create_session("s1", RunKind.QUEUED)
        session.tool_events.append(
            {
                "subagent_start": {
                    "subagent_id": "sub-1",
                    "subagent_name": "Todos",
                    "agent_type": "handoff",
                }
            }
        )
        for _ in range(8):
            session.tool_events.append(
                {
                    "tool_data": {
                        "tool_name": "todo_data",
                        "data": [{"id": "x"}],
                        "subagent_id": "sub-1",
                    }
                }
            )

        note = build_returned_to_frontend_note("s1")

        assert "  - todo_data (8 todo, via subagent:Todos)\n" in note

    def test_a_card_the_executor_emitted_itself_carries_no_provenance(self) -> None:
        session = create_session("s1", RunKind.QUEUED)
        session.tool_events.append(
            {"tool_data": {"tool_name": "weather_data", "data": {"temp": 20}}}
        )

        note = build_returned_to_frontend_note("s1")

        assert "  - weather_data (1 weather)\n" in note

    def test_two_subagents_emitting_the_same_card_stay_separate_rows(self) -> None:
        session = create_session("s1", RunKind.QUEUED)
        for sid, name in (("sub-1", "Todos"), ("sub-2", "Todoist")):
            session.tool_events.append(
                {
                    "subagent_start": {
                        "subagent_id": sid,
                        "subagent_name": name,
                        "agent_type": "handoff",
                    }
                }
            )
            session.tool_events.append(
                {"tool_data": {"tool_name": "todo_data", "data": [{"id": sid}], "subagent_id": sid}}
            )

        note = build_returned_to_frontend_note("s1")

        assert "  - todo_data (1 todo, via subagent:Todos)\n" in note
        assert "  - todo_data (1 todo, via subagent:Todoist)\n" in note

    def test_an_unattributable_card_is_never_credited_to_a_producer(self) -> None:
        """A subagent that started without a name produces cards nothing can
        credit — and neither can the executor's own cards. Both must land on the
        SAME unattributed row: two ways of having no producer are one fact, and
        splitting them into two rows tells comms two different things happened.
        """
        session = create_session("s1", RunKind.QUEUED)
        session.tool_events.append({"subagent_start": {"subagent_id": "sub-9"}})
        session.tool_events.append(
            {"tool_data": {"tool_name": "todo_data", "data": [{"id": "a"}], "subagent_id": "sub-9"}}
        )
        session.tool_events.append({"tool_data": {"tool_name": "todo_data", "data": [{"id": "b"}]}})

        note = build_returned_to_frontend_note("s1")

        assert "  - todo_data (2 todo)\n" in note
        assert "via subagent" not in note

    def test_a_malformed_group_row_is_skipped_not_fatal(self) -> None:
        """``subagent_group`` rows also arrive pre-formed from child streams, so
        the shape is not this module's to guarantee. One bad row must cost its
        own provenance, never the whole note."""
        session = create_session("s1", RunKind.QUEUED)
        session.tool_events.append({"tool_data": {"tool_name": "subagent_group", "data": None}})
        session.tool_events.append({"tool_data": {"tool_name": "todo_data", "data": [{"id": "a"}]}})

        assert "  - todo_data (1 todo)\n" in build_returned_to_frontend_note("s1")

    def test_nothing_card_worthy_yields_no_note(self) -> None:
        create_session("s1", RunKind.QUEUED)
        assert build_returned_to_frontend_note("s1") == ""

    def test_the_full_note_is_pinned_verbatim_for_a_named_subagent_card(self) -> None:
        """Exact rendered text — not a substring — so a dropped tool name, an
        emptied subagent name, or a vanished data lookup all go red here even
        if a looser 'in note' check would not notice the surrounding text."""
        session = create_session("s1", RunKind.QUEUED)
        session.tool_events.append(
            {
                "subagent_start": {
                    "subagent_id": "sub-1",
                    "subagent_name": "Todos",
                    "agent_type": "handoff",
                }
            }
        )
        session.tool_events.append(
            {
                "tool_data": {
                    "tool_name": "todo_data",
                    "data": [{"id": "x"}],
                    "subagent_id": "sub-1",
                }
            }
        )

        note = build_returned_to_frontend_note("s1")

        assert note == wrap_agent_payload(
            AgentTag.RETURNED_TO_FRONTEND,
            "These native cards are already on the user's screen this turn:\n"
            "  - todo_data (1 todo, via subagent:Todos)\n"
            "They visually render the RAW items, so don't re-type those items "
            "row-by-row and don't re-emit them as OpenUI — that literal duplication "
            "is the ONLY thing to avoid here.\n"
            "The cards are visual aids, NOT your reply. You still owe the user the "
            "ANSWER in your own voice — the substance the executor produced: what it "
            "found, grouped and counted, the few items that actually matter (and "
            'why), and the natural next step. This synthesis is never "card '
            'contents"; suppressing it because a card exists is the worst failure '
            "you can have.\n"
            "Match the depth to the work: a quick outcome gets a line or two; a "
            "large, comprehensive result (a full triage, a multi-item analysis) gets "
            "a real structured rundown — never a one-liner. Replying just \"here's "
            'the list 👇" with no substance, when the executor did real work, fails '
            "the user. Point them to the card for the granular rows AFTER you've "
            "actually delivered the gist.\n"
            "CRITICAL EXCEPTION — LONG-FORM DELIVERABLE: if the executor's result is "
            "itself a finished written piece (a research report, an article, an "
            "analysis, a document), that is the ANSWER, not raw card rows. The cards "
            "above were just the research/loading steps along the way. Deliver the "
            "deliverable IN FULL per the long-form rule — every section, point, and "
            "citation — and do NOT compress it to a 'here's the breakdown' summary. "
            "This note never authorizes shrinking a report; it only stops you "
            "re-typing rows a card already lists.",
        )


class TestCollectCoalescesReasoning:
    """Direct unit coverage of ``redis_writer._collect``'s content-merge line —
    pins the exact defaults used when a dict is missing its ``content`` key,
    which the higher-level streaming tests never exercise (every delta they
    send already carries content)."""

    def test_two_consecutive_deltas_concatenate_exactly(self) -> None:
        session = create_session("s1", RunKind.QUEUED)
        rw._collect(session, {"reasoning": {"content": "hello ", "subagent_id": None}})
        rw._collect(session, {"reasoning": {"content": "world", "subagent_id": None}})

        assert session.tool_events == [
            {"reasoning": {"content": "hello world", "subagent_id": None}}
        ]

    def test_a_previous_entry_with_no_content_key_defaults_to_empty_not_the_word_none(
        self,
    ) -> None:
        session = create_session("s1", RunKind.QUEUED)
        session.tool_events.append({"reasoning": {"subagent_id": None}})  # no "content" key

        rw._collect(session, {"reasoning": {"content": "world", "subagent_id": None}})

        assert session.tool_events[-1]["reasoning"]["content"] == "world"

    def test_an_incoming_delta_with_no_content_key_leaves_the_previous_content_unchanged(
        self,
    ) -> None:
        session = create_session("s1", RunKind.QUEUED)
        rw._collect(session, {"reasoning": {"content": "hello", "subagent_id": None}})

        rw._collect(session, {"reasoning": {"subagent_id": None}})  # no "content" key

        assert session.tool_events[-1]["reasoning"]["content"] == "hello"


class TestRedisStreamWriter:
    async def test_writer_appends_event_to_session_and_publishes(self) -> None:
        create_session("s1", RunKind.QUEUED)
        with patch.object(rw, "stream_manager") as sm:
            sm.publish_chunk = AsyncMock()
            writer = make_redis_stream_writer("s1")
            writer({"tool_data": {"tool_name": "web_search_data", "data": []}})

        session = get_session("s1")
        assert session is not None
        assert session.tool_events == [{"tool_data": {"tool_name": "web_search_data", "data": []}}]

    async def test_writer_without_session_does_not_crash(self) -> None:
        with patch.object(rw, "stream_manager") as sm:
            sm.publish_chunk = AsyncMock()
            writer = make_redis_stream_writer("unregistered")
            writer({"tool_data": {"x": 1}})  # publish still happens, no collector
        assert get_session("unregistered") is None
