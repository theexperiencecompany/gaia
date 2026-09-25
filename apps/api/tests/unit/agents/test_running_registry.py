"""The running-subagent registry — the executor's addressable handle on live workers.

Proves the executor can enumerate exactly what is running and name one by id, that a
finished subagent leaves the registry (so a stale id can never be steered), and that
one checkpoint thread carries at most one live run.
"""

from unittest.mock import patch

import fakeredis.aioredis
import pytest

from app.agents.core.background import running_registry as registry
from app.agents.core.background.running_registry import RunningSubagents
from app.constants.cache import (
    RUNNING_SUBAGENT_THREAD_PREFIX,
    RUNNING_SUBAGENTS_PREFIX,
    RUNNING_SUBAGENTS_TTL,
)
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.models.agent_models import RunningSubagent
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

CONV = "conv-1"


def _sub(subagent_id: str, integration: str = "gmail", thread: str = "") -> RunningSubagent:
    return RunningSubagent(
        subagent_id=subagent_id,
        subagent_thread_id=thread or f"{integration}_executor_{CONV}",
        integration_id=integration,
        agent_name=f"{integration}_agent",
        task_summary="search mail",
        started_at="2026-09-05T10:00:00Z",
    )


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    with patch.object(registry, "redis_cache") as cache:
        cache.client = client
        yield client
    await client.aclose()


class TestRunningSubagents:
    async def test_register_then_list_and_get_by_id(self, redis) -> None:
        reg = RunningSubagents(CONV)
        sub = _sub("s1")
        assert await reg.claim(sub)
        assert await reg.live() == [sub]
        assert await reg.get("s1") == sub

    async def test_deregister_removes_only_the_named_one(self, redis) -> None:
        reg = RunningSubagents(CONV)
        assert await reg.claim(_sub("s1", "gmail"))
        assert await reg.claim(_sub("s2", "slack"))
        await reg.deregister(_sub("s1", "gmail"))
        remaining = await reg.live()
        assert [s.subagent_id for s in remaining] == ["s2"]
        assert await reg.get("s1") is None

    async def test_a_finished_subagent_cannot_be_addressed(self, redis) -> None:
        reg = RunningSubagents(CONV)
        assert await reg.claim(_sub("s1"))
        await reg.deregister(_sub("s1"))
        assert await reg.live() == []
        assert await reg.get("s1") is None

    async def test_registries_are_isolated_per_conversation(self, redis) -> None:
        assert await RunningSubagents(CONV).claim(_sub("s1"))
        assert await RunningSubagents("other-conv").live() == []

    async def test_an_unreadable_record_is_skipped_and_reported(self, redis) -> None:
        reg = RunningSubagents(CONV)
        assert await reg.claim(_sub("s1"))
        await redis.hset(f"{RUNNING_SUBAGENTS_PREFIX}{CONV}", mapping={"s2": "not json"})

        async with captured_wide_event() as event:
            live = await reg.live()

        assert [s.subagent_id for s in live] == ["s1"]
        assert [w["msg"] for w in event["warnings"]] == [
            f"{LogTag.AGENT} Discarding unreadable running-subagent record"
        ]


class TestThreadClaim:
    async def test_a_second_run_on_a_held_thread_is_refused(self, redis) -> None:
        reg = RunningSubagents(CONV)
        assert await reg.claim(_sub("s1", thread="notion-mcp_executor_conv-1"))
        refused = _sub("s2", thread="notion-mcp_executor_conv-1")
        assert not await reg.claim(refused)
        assert [s.subagent_id for s in await reg.live()] == ["s1"]
        assert await reg.holds_thread("notion-mcp_executor_conv-1")

    async def test_the_thread_frees_when_its_run_deregisters(self, redis) -> None:
        reg = RunningSubagents(CONV)
        first = _sub("s1", thread="spawn_conv-1_call-1")
        assert await reg.claim(first)
        await reg.deregister(first)
        assert not await reg.holds_thread("spawn_conv-1_call-1")
        assert await reg.claim(_sub("s1", thread="spawn_conv-1_call-1"))

    async def test_a_claimed_thread_lapses_so_a_dead_run_cannot_hold_it(self, redis) -> None:
        assert await RunningSubagents(CONV).claim(_sub("s1", thread="spawn_conv-1_a"))

        ttl = await redis.ttl(f"{RUNNING_SUBAGENT_THREAD_PREFIX}spawn_conv-1_a")

        assert ttl == RUNNING_SUBAGENTS_TTL

    async def test_without_redis_every_run_is_allowed(self) -> None:
        with patch.object(registry, "redis_cache") as cache:
            cache.client = None
            assert await RunningSubagents(CONV).claim(_sub("s1")) is True

    async def test_distinct_threads_run_side_by_side(self, redis) -> None:
        reg = RunningSubagents(CONV)
        assert await reg.claim(_sub("s1", thread="spawn_conv-1_a"))
        assert await reg.claim(_sub("s2", thread="spawn_conv-1_b"))
        assert {s.subagent_id for s in await reg.live()} == {"s1", "s2"}


def _run(subagent_id: str, stream_id: str | None, dispatched_by: str | None) -> RunningSubagent:
    return RunningSubagent(
        subagent_id=subagent_id,
        subagent_thread_id=f"spawn_{CONV}_{subagent_id}",
        integration_id="gmail",
        agent_name="gmail_agent",
        task_summary="search mail",
        started_at="2026-09-05T10:00:00Z",
        stream_id=stream_id,
        dispatched_by=dispatched_by,
    )


@pytest.mark.usefixtures("fake_redis")
class TestStopStream:
    """A background run outlives the stream that dispatched it; stopping that stream must still reach it."""

    @pytest.mark.regression
    async def test_stops_what_the_stream_dispatched_however_deep(self) -> None:
        reg = RunningSubagents(CONV)
        child = _run("child", "subagent_child", dispatched_by="turn")
        grandchild = _run("grandchild", "subagent_grandchild", dispatched_by="subagent_child")
        for run in (child, grandchild):
            assert await reg.claim(run)

        stopped = await registry.stop_stream(CONV, "turn")

        assert {s.subagent_id for s in stopped} == {"child", "grandchild"}
        for stream_id in ("turn", "subagent_child", "subagent_grandchild"):
            assert await stream_manager.is_cancelled(stream_id)

    async def test_leaves_runs_another_stream_dispatched(self) -> None:
        reg = RunningSubagents(CONV)
        assert await reg.claim(_run("mine", "subagent_mine", dispatched_by="turn"))
        assert await reg.claim(_run("theirs", "subagent_theirs", dispatched_by="other-turn"))

        stopped = await registry.stop_stream(CONV, "turn")

        assert [s.subagent_id for s in stopped] == ["mine"]
        assert not await stream_manager.is_cancelled("subagent_theirs")

    async def test_a_run_on_the_stopped_stream_itself_is_not_stopped_twice(self) -> None:
        reg = RunningSubagents(CONV)
        assert await reg.claim(_run("blocking", "turn", dispatched_by="turn"))

        assert await registry.stop_stream(CONV, "turn") == []
        assert await stream_manager.is_cancelled("turn")

    async def test_a_run_the_user_resumed_is_not_stopped_with_the_turn_that_first_dispatched_it(
        self,
    ) -> None:
        reg = RunningSubagents(CONV)
        assert await reg.claim(_run("resumed", "subagent_resumed", dispatched_by=None))

        assert await registry.stop_stream(CONV, "turn") == []
        assert not await stream_manager.is_cancelled("subagent_resumed")


@pytest.mark.usefixtures("fake_redis")
class TestStopAll:
    @pytest.mark.regression
    async def test_stops_every_live_run_including_ones_whose_dispatcher_finished(self) -> None:
        reg = RunningSubagents(CONV)
        assert await reg.claim(_run("orphan", "subagent_orphan", dispatched_by="finished-turn"))
        assert await reg.claim(_run("resumed", "subagent_resumed", dispatched_by=None))

        stopped = await reg.stop_all()

        assert {s.subagent_id for s in stopped} == {"orphan", "resumed"}
        assert await stream_manager.is_cancelled("subagent_orphan")
        assert await stream_manager.is_cancelled("subagent_resumed")

    async def test_a_record_written_before_runs_carried_streams_still_decodes(self) -> None:
        reg = RunningSubagents(CONV)
        legacy = _sub("legacy")
        assert await reg.claim(legacy)

        assert await reg.live() == [legacy]
        assert await reg.stop_all() == [legacy]
