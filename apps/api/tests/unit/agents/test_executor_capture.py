"""Unit tests for executor tool-event capture and drain (executor_capture.py).

Pins the contracts terminal handlers depend on:
- drain is a NON-DESTRUCTIVE read — single-ownership (not source-emptying) is
  what prevents duplicate cards, so a second drain must return the same data;
- drain runs the real shaping pipeline (output backfill, subagent grouping);
- the redis stream writer appends every event to the session collector.
"""

import json
import time
from unittest.mock import AsyncMock, call, patch

import pytest

from app.agents.core.background import redis_writer as rw, session as sess
from app.agents.core.background.executor_capture import drain_executor_tool_data
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.background.session import (
    RunKind,
    create_session,
    get_session,
)
from app.constants.browser import BROWSER_TASK_EVENT, BROWSER_TOOL_CATEGORY
from app.models.chat_models import ToolDataEntry
from app.models.stream_events import ToolOutputPayload
from app.services.chat.chunks import normalize_custom_event
from app.utils.agent_utils import (
    SubagentStartDetails,
    format_browser_action_entry,
    format_subagent_end_event,
    format_subagent_start_event,
)


def _tool_call_event(tool_call_id: str, subagent_id: str | None = None) -> dict:
    entry: dict = {
        "tool_name": "tool_calls_data",
        "data": {"tool_call_id": tool_call_id, "name": "web_search"},
    }
    if subagent_id:
        entry["subagent_id"] = subagent_id
    return {"tool_data": entry}


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

    def test_drain_backfills_outputs_only_into_tool_call_entries(self) -> None:
        """An approval card shares its gated call's tool_call_id but must not absorb that call's output."""
        session = create_session("s1", RunKind.QUEUED)
        session.tool_events.append(_tool_call_event("tc-1"))
        session.tool_events.append(
            {
                "tool_data": {
                    "tool_name": "approval_request",
                    "data": {"approval_id": "ap-1", "tool_call_id": "tc-1", "status": "pending"},
                }
            }
        )
        session.tool_events.append({"tool_output": {"tool_call_id": "tc-1", "output": "sent"}})

        entries = drain_executor_tool_data("s1")

        call, approval = entries
        assert call["data"]["output"] == "sent"
        assert approval["data"] == {
            "approval_id": "ap-1",
            "tool_call_id": "tc-1",
            "status": "pending",
        }

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
        """Draining must NOT empty the source, or a racing attach/finalize backstop would drop cards."""
        session = create_session("s1", RunKind.QUEUED)
        session.tool_events.append(_tool_call_event("tc-1"))

        first = drain_executor_tool_data("s1")
        second = drain_executor_tool_data("s1")

        assert first == second
        assert len(second) == 1


class TestCollectCoalescesReasoning:
    """Direct unit coverage of redis_writer._collect's content-merge line.

    Pins the exact defaults used when a dict is missing its content key,
    which the higher-level streaming tests never exercise (every delta they
    send already carries content).
    """

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

    async def test_an_awaited_publish_reaches_the_stream_and_its_collector_alike(self) -> None:
        """A replayed card must land on the live stream and on the message saved for a reload."""
        create_session("s1", RunKind.LIVE)
        card: dict[str, object] = {
            "tool_data": {"tool_name": "browser_task_data", "data": {"step": 1}}
        }
        with patch.object(rw, "stream_manager") as sm:
            sm.publish_chunk = AsyncMock()
            await rw.publish_to_stream("s1", card)
            await rw.publish_to_stream("unregistered", card)

        sm.publish_chunk.assert_has_awaits(
            [
                call("s1", f"data: {json.dumps(card)}\n\n"),
                call("unregistered", f"data: {json.dumps(card)}\n\n"),
            ]
        )
        session = get_session("s1")
        assert session is not None
        assert session.tool_events == [card]

    async def test_writer_without_session_does_not_crash(self) -> None:
        with patch.object(rw, "stream_manager") as sm:
            sm.publish_chunk = AsyncMock()
            writer = make_redis_stream_writer("unregistered")
            writer({"tool_data": {"x": 1}})  # publish still happens, no collector
        assert get_session("unregistered") is None

    async def test_writer_stamps_the_first_frame_once(self) -> None:
        # The stamp is the executor TTFT start, written on the first frame only. Two
        # clock reads pin both halves: never stamping leaves it None, stamping every
        # frame measures gap-to-last-frame instead of TTFT.
        create_session("s1", RunKind.QUEUED)
        session = get_session("s1")
        assert session is not None

        with (
            patch.object(rw, "stream_manager") as sm,
            patch.object(rw, "spawn_background_task"),
            patch.object(time, "perf_counter", side_effect=[42.0, 43.0]),
        ):
            sm.publish_chunk = AsyncMock()
            writer = make_redis_stream_writer("s1")
            writer({"tool_data": {"i": 1}})
            assert session.executor_first_frame_perf == 42.0
            writer({"tool_data": {"i": 2}})
            assert session.executor_first_frame_perf == 42.0


@pytest.mark.unit
class TestAnExecutorThatNeverFinishes:
    """Seen live: an executor stopped mid-run and never signalled done.

    The silent path waited the whole EXECUTOR_WAIT_TIMEOUT, which equals the
    worker's job timeout, so the job was cut first and the record stayed
    'running'. The wait now ends before the job does, counts as the executor
    failing, and says what was still running.
    """

    def test_the_background_wait_ends_before_the_job_that_awaits_it(self) -> None:
        from app.constants.cache import BACKGROUND_EXECUTOR_WAIT_TIMEOUT
        from app.workers.config.worker_settings import WORKER_JOB_TIMEOUT_SECONDS

        assert BACKGROUND_EXECUTOR_WAIT_TIMEOUT < WORKER_JOB_TIMEOUT_SECONDS


def _drained(events: list[dict]) -> list[ToolDataEntry]:
    """Drain events as a detached stream's session collected them, as its close saves them."""
    session = create_session("stream-browser-feed", RunKind.QUEUED)
    session.tool_events.extend(events)
    try:
        return drain_executor_tool_data("stream-browser-feed")
    finally:
        sess.teardown_session("stream-browser-feed")


class TestDrainingABrowserJobsFeed:
    """A background browser job's cards, relayed onto its own stream, saved into the turn's message."""

    @staticmethod
    def _browser_feed() -> list[dict]:
        """Build the frames a browser job publishes, through the formatters the job runner calls."""
        session_card = {"kind": "session", "session_id": "sess-1", "status": "running"}
        step_card = {"kind": "step", "index": 1, "goal": "open the menu"}
        raw: list[dict] = [
            {BROWSER_TASK_EVENT: session_card},
            {
                "subagent_start": format_subagent_start_event(
                    subagent_name="Browser",
                    agent_type="spawned",
                    subagent_id="browser:sess-1",
                    details=SubagentStartDetails(tool_category=BROWSER_TOOL_CATEGORY),
                )
            },
            {
                "tool_data": format_browser_action_entry(
                    name="click",
                    inputs={"index": 2},
                    target="Menu",
                    subagent_id="browser:sess-1",
                    tool_call_id="browser:sess-1:1:0",
                )
            },
            {
                "tool_output": ToolOutputPayload(
                    tool_call_id="browser:sess-1:1:0",
                    output="clicked Menu",
                    subagent_id="browser:sess-1",
                ).model_dump(mode="json")
            },
            {BROWSER_TASK_EVENT: step_card},
            {
                "subagent_end": format_subagent_end_event(
                    subagent_id="browser:sess-1", duration_ms=5
                )
            },
        ]
        return [normalize_custom_event(frame) for frame in raw]

    def test_an_empty_feed_reconstructs_nothing(self) -> None:
        assert _drained([]) == []

    def test_the_cards_come_back_in_the_order_the_run_published_them(self) -> None:
        entries = _drained(self._browser_feed())

        cards = [e for e in entries if e["tool_name"] == BROWSER_TASK_EVENT]
        assert [c["data"]["kind"] for c in cards] == ["session", "step"]

    def test_the_actions_are_grouped_under_the_runs_browser_row(self) -> None:
        # Ungrouped, every action would render as its own top-level card in the
        # saved message instead of one collapsible "Browser" row.
        entries = _drained(self._browser_feed())

        (group,) = [e for e in entries if e["tool_name"] == "subagent_group"]
        assert group["data"]["subagent_name"] == "Browser"
        assert group["data"]["duration_ms"] == 5
        assert [call["tool_name"] for call in group["data"]["tool_calls"]] == ["click"]

    def test_each_actions_result_is_carried_on_its_row(self) -> None:
        entries = _drained(self._browser_feed())

        (group,) = [e for e in entries if e["tool_name"] == "subagent_group"]
        assert group["data"]["tool_calls"][0]["output"] == "clicked Menu"
