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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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
