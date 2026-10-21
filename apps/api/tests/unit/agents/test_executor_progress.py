"""A running executor's progress record: what comms' status note shows while it runs.

The record is the busy-lock holder's own state. These tests pin that contract
over fakeredis with the real lock functions: it is renewed by the holder's
liveness beat and nothing else, deleted with the lock however the lock goes,
and a new holder never reads the previous one's. Frames are the shapes the
run's stream writer emits (tool_calls_data entries, todo_progress snapshots).
"""

import asyncio
from typing import Any
from unittest.mock import MagicMock

import fakeredis.aioredis
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from app.agents.core.background.executor_progress import (
    ProgressRecorder,
    RunProgress,
    apply_frame,
    describe_progress,
    format_call,
    progress_key,
    read_progress,
)
from app.agents.core.background.executor_queue import (
    build_lock_value,
    hold_run_alive,
    reclaim_dead_lock,
    release_lock_if_owned,
)
from app.agents.core.nodes.executor_status import executor_status_hook
from app.constants.cache import (
    EXECUTOR_ALIVE_TTL,
    EXECUTOR_BUSY_PREFIX,
    EXECUTOR_BUSY_TTL,
    EXECUTOR_DEAD_HOLDER_MIN_AGE_SECONDS,
)
from app.constants.executor import EXECUTOR_PROGRESS_MAX_CALLS, EXECUTOR_PROGRESS_TASK_NAME
from app.constants.general import CALL_EXECUTOR_NAME
from app.constants.hil import HIL_PAUSED_LOCK_TTL_SECONDS

CONV = "conv-1"
HOLDER = build_lock_value("stream-1", "task-1")
LOCK_KEY = f"{EXECUTOR_BUSY_PREFIX}{CONV}"


def _call(name: str, inputs: dict[str, Any], title: str | None = None) -> dict[str, object]:
    return {
        "tool_data": {
            "tool_name": "tool_calls_data",
            "data": {"tool_name": name, "message": title, "inputs": inputs, "tool_call_id": "c1"},
        }
    }


def _plan(todos: list[tuple[str, str]], source: str = "executor") -> dict[str, object]:
    return {
        "todo_progress": {
            "todos": [{"id": str(i), "content": c, "status": s} for i, (c, s) in enumerate(todos)],
            "source": source,
        }
    }


async def _settled() -> None:
    """Wait out the record writes the recorder scheduled."""
    tasks = [t for t in asyncio.all_tasks() if t.get_name() == EXECUTOR_PROGRESS_TASK_NAME]
    await asyncio.gather(*tasks)


async def _record(holder: str, *frames: dict[str, object]) -> list[dict[str, object]]:
    passed: list[dict[str, object]] = []
    recorder = ProgressRecorder(CONV, holder)
    writer = recorder.wrap(passed.append)
    for frame in frames:
        writer(frame)
    await recorder.settle()
    return passed


async def _hold_live_lock(client: fakeredis.aioredis.FakeRedis, holder: str = HOLDER) -> None:
    await client.set(LOCK_KEY, holder, ex=EXECUTOR_BUSY_TTL)
    await hold_run_alive(CONV, holder)


# ── What a frame contributes ─────────────────────────────────────────


class TestApplyFrame:
    def test_a_tool_call_is_kept_with_its_title_and_inputs(self) -> None:
        progress = RunProgress()

        changed = apply_frame(
            progress, _call("GMAIL_FETCH_EMAILS", {"query": "newer_than:30d"}, "Fetch emails")
        )

        assert changed is True
        assert describe_progress(progress) == (
            "Latest tool calls (inputs only, results not shown):\n"
            '- Fetch emails: GMAIL_FETCH_EMAILS(query="newer_than:30d")'
        )

    def test_a_call_without_a_title_is_named_by_its_tool(self) -> None:
        progress = RunProgress()
        apply_frame(progress, _call("search", {"q": "x"}))

        assert progress.calls[0].title == "search"

    def test_several_calls_in_one_frame_all_count(self) -> None:
        progress = RunProgress()
        frame = {"tool_data": [_call("a", {})["tool_data"], _call("b", {})["tool_data"]]}

        apply_frame(progress, frame)

        assert [c.call for c in progress.calls] == ["a()", "b()"]

    def test_the_plan_is_the_latest_snapshot_per_source(self) -> None:
        progress = RunProgress()
        apply_frame(progress, _plan([("find promo emails", "in_progress"), ("archive", "pending")]))
        apply_frame(
            progress, _plan([("find promo emails", "completed"), ("archive", "in_progress")])
        )
        apply_frame(progress, _plan([("draft reply", "pending")], source="gmail"))

        assert describe_progress(progress) == (
            "Plan (executor):\n- [completed] find promo emails\n- [in_progress] archive\n"
            "Plan (gmail):\n- [pending] draft reply"
        )

    def test_only_the_latest_calls_are_kept(self) -> None:
        progress = RunProgress()
        for i in range(EXECUTOR_PROGRESS_MAX_CALLS + 5):
            apply_frame(progress, _call("search", {"n": i}))

        assert len(progress.calls) == EXECUTOR_PROGRESS_MAX_CALLS
        assert progress.calls[0].call == "search(n=5)"
        assert progress.calls[-1].call == f"search(n={EXECUTOR_PROGRESS_MAX_CALLS + 4})"

    @pytest.mark.parametrize(
        "frame",
        [
            {"response": "streamed text"},
            {"reasoning": {"content": "thinking"}},
            {"tool_output": {"tool_call_id": "c1", "output": "secret result"}},
            {"subagent_start": {"subagent_id": "s"}},
            {"tool_data": {"tool_name": "email_fetch_data", "data": {"emails": ["private"]}}},
            _call("plan_tasks", {"tasks": [{"content": "x"}]}),
            _call("update_tasks", {"updates": []}),
            _call(CALL_EXECUTOR_NAME, {"task": "comms' own hand-off"}),
        ],
        ids=[
            "text",
            "reasoning",
            "tool_output",
            "lifecycle",
            "result_card",
            "plan_tasks",
            "update_tasks",
            "handoff",
        ],
    )
    def test_outputs_text_and_plumbing_are_not_progress(self, frame: dict[str, object]) -> None:
        progress = RunProgress()

        assert apply_frame(progress, frame) is False
        assert describe_progress(progress) == ""

    def test_long_values_are_cut_short(self) -> None:
        rendered = format_call("send", {"body": "x" * 500})

        assert rendered.startswith('send(body="xxx')
        assert rendered.endswith("...)")
        assert len(rendered) < 120


# ── The recorder: pass-through and writes ────────────────────────────


class TestRecorder:
    async def test_every_frame_still_reaches_the_stream_unchanged(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        frames = [{"response": "hi"}, _call("search", {"q": "x"}), {"reasoning": {"content": "r"}}]

        passed = await _record(HOLDER, *frames)

        assert passed == frames

    async def test_the_record_is_written_under_its_holder_with_the_liveness_ttl(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await _record(HOLDER, _call("search", {"q": "x"}))

        assert (await read_progress(CONV, HOLDER)).calls[0].call == 'search(q="x")'
        assert 0 < await fake_redis.ttl(progress_key(CONV, HOLDER)) <= EXECUTOR_ALIVE_TTL

    async def test_frames_with_no_progress_write_nothing(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await _record(HOLDER, {"response": "hi"}, {"reasoning": {"content": "r"}})

        assert await fake_redis.exists(progress_key(CONV, HOLDER)) == 0

    async def test_a_burst_ends_on_the_latest_state(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        recorder = ProgressRecorder(CONV, HOLDER)
        writer = recorder.wrap(lambda _frame: None)
        for i in range(30):
            writer(_plan([("step", "completed" if i == 29 else "in_progress")]))
            writer(_call("search", {"n": i}))
        await recorder.settle()

        stored = await read_progress(CONV, HOLDER)
        assert stored.plans["executor"][0].status == "completed"
        assert stored.calls[-1].call == "search(n=29)"

    async def test_a_burst_is_coalesced_into_few_writes(
        self, fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        writes = 0
        real_set = fake_redis.set

        async def counting_set(*args: Any, **kwargs: Any) -> Any:
            nonlocal writes
            writes += 1
            return await real_set(*args, **kwargs)

        monkeypatch.setattr(fake_redis, "set", counting_set)
        recorder = ProgressRecorder(CONV, HOLDER)
        writer = recorder.wrap(lambda _frame: None)
        for i in range(50):  # synchronous, as a burst of stream frames arrives
            writer(_call("search", {"n": i}))
        await recorder.settle()

        assert writes <= 2


# ── Lifetime: the holder's, exactly ──────────────────────────────────


class TestLifetime:
    async def test_the_liveness_beat_renews_the_record(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await _record(HOLDER, _call("search", {"q": "x"}))
        await fake_redis.expire(progress_key(CONV, HOLDER), 5)

        await hold_run_alive(CONV, HOLDER)

        assert await fake_redis.ttl(progress_key(CONV, HOLDER)) > 5

    @pytest.mark.regression
    async def test_a_long_silent_tool_call_keeps_its_progress_while_the_run_lives(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        """A tool call that emits nothing for longer than the record's TTL: the beat, not frames, keeps it."""
        await _record(HOLDER, _call("deep_research", {"topic": "x"}))
        for _ in range(3):
            await fake_redis.expire(progress_key(CONV, HOLDER), 1)
            await hold_run_alive(CONV, HOLDER, ttl_seconds=2)
            await asyncio.sleep(1.1)

        assert (await read_progress(CONV, HOLDER)).calls

    async def test_once_the_beat_stops_the_record_expires(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await _record(HOLDER, _call("search", {"q": "x"}))
        await hold_run_alive(CONV, HOLDER, ttl_seconds=1)

        await asyncio.sleep(1.2)

        assert describe_progress(await read_progress(CONV, HOLDER)) == ""

    async def test_a_paused_run_keeps_its_progress_for_the_approval_window(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await _record(HOLDER, _call("GMAIL_SEND", {"to": "a@b.c"}))

        await hold_run_alive(CONV, HOLDER, HIL_PAUSED_LOCK_TTL_SECONDS)

        assert await fake_redis.ttl(progress_key(CONV, HOLDER)) > EXECUTOR_ALIVE_TTL

    async def test_the_beat_never_creates_a_record(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await hold_run_alive(CONV, HOLDER)

        assert await fake_redis.exists(progress_key(CONV, HOLDER)) == 0

    async def test_releasing_the_lock_deletes_the_record(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await _hold_live_lock(fake_redis)
        await _record(HOLDER, _call("search", {"q": "x"}))

        await release_lock_if_owned(CONV, "stream-1", "task-1")

        assert await fake_redis.exists(progress_key(CONV, HOLDER)) == 0

    async def test_a_stale_finalize_leaves_the_newer_holders_record(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        newer = build_lock_value("stream-2", "task-2")
        await _hold_live_lock(fake_redis, newer)
        await _record(newer, _call("search", {"q": "new"}))

        await release_lock_if_owned(CONV, "stream-1", "task-1")

        assert (await read_progress(CONV, newer)).calls

    async def test_reclaiming_a_dead_lock_deletes_its_record(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        age = EXECUTOR_DEAD_HOLDER_MIN_AGE_SECONDS + 5
        await fake_redis.set(LOCK_KEY, HOLDER, ex=EXECUTOR_BUSY_TTL - age)
        await fake_redis.set(progress_key(CONV, HOLDER), RunProgress().model_dump_json())

        assert await reclaim_dead_lock(CONV) is True
        assert await fake_redis.exists(progress_key(CONV, HOLDER)) == 0


# ── What comms sees ──────────────────────────────────────────────────


def _dispatched() -> list:
    return [
        HumanMessage(content="archive the promo emails"),
        AIMessage(content="", tool_calls=[{"name": CALL_EXECUTOR_NAME, "args": {}, "id": "c1"}]),
        ToolMessage(content="Handed to the executor (task_id: task-1).", tool_call_id="c1"),
        HumanMessage(content="how's it going?"),
    ]


async def _status_frame(config: dict | None = None) -> str | None:
    messages = _dispatched()
    out = await executor_status_hook(
        {"messages": messages}, config or {"configurable": {"thread_id": CONV}}, MagicMock()
    )
    added = out["messages"][len(messages) :]
    return str(added[0].content) if added else None


class TestStatusNote:
    @pytest.mark.regression
    async def test_comms_sees_what_a_running_executor_has_done(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        """Asked mid-run, comms had nothing but "it's running": the only reply comes at the end."""
        await _hold_live_lock(fake_redis)
        await _record(
            HOLDER,
            _plan([("find promo emails", "completed"), ("archive them", "in_progress")]),
            _call("GMAIL_FETCH_EMAILS", {"query": "promotions"}, "Fetch emails"),
        )

        frame = await _status_frame()

        assert frame is not None
        assert "running right now (task_id: task-1). Its result has not arrived yet." in frame
        assert "What it has done so far:\nPlan (executor):" in frame
        assert "[in_progress] archive them" in frame
        assert 'Fetch emails: GMAIL_FETCH_EMAILS(query="promotions")' in frame

    async def test_a_running_executor_that_has_done_nothing_yet_shows_only_that_it_runs(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await _hold_live_lock(fake_redis)

        frame = await _status_frame()

        assert frame is not None
        assert "done so far" not in frame

    async def test_a_new_run_never_shows_the_previous_runs_progress(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await _record(HOLDER, _call("search", {"q": "old run"}))
        await _hold_live_lock(fake_redis, build_lock_value("stream-2", "task-2"))

        frame = await _status_frame()

        assert frame is not None
        assert "old run" not in frame

    async def test_a_dead_run_shows_no_progress(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        age = EXECUTOR_DEAD_HOLDER_MIN_AGE_SECONDS + 5
        await fake_redis.set(LOCK_KEY, HOLDER, ex=EXECUTOR_BUSY_TTL - age)
        await _record(HOLDER, _call("search", {"q": "half done"}))

        frame = await _status_frame()

        assert frame is not None
        assert "stopped before it finished" in frame
        assert "half done" not in frame

    async def test_result_narration_shows_nothing(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await _hold_live_lock(fake_redis)
        await _record(HOLDER, _call("search", {"q": "x"}))

        frame = await _status_frame(
            {"configurable": {"thread_id": CONV, "is_result_narration": True}}
        )

        assert frame is None
