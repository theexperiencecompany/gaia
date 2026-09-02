"""Unit tests for the comms → executor handoff (`app/agents/tools/executor_tool.py`).

Redis is real (fakeredis) so the busy-lock and queue mechanics under test run for
real; the only mocked boundaries are the executor graph itself
(``run_executor_background``) and the WebSocket fan-out.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime
import json
import time
from typing import Any, cast
from unittest.mock import AsyncMock

import fakeredis.aioredis
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
import pytest

from app.agents.core.background.session import (
    queued_without_run,
    teardown_session,
    was_executor_spawned,
)
from app.agents.tools import executor_tool
from app.agents.tools.executor_tool import call_executor, cancel_executor, tools
from app.constants.cache import (
    EXECUTOR_BUSY_PREFIX,
    EXECUTOR_BUSY_TTL,
    EXECUTOR_QUEUE_PREFIX,
    EXECUTOR_QUEUE_TTL,
)
from app.constants.streaming import WS_EVENT_EXECUTOR_CANCELLED
from app.core.stream_manager import StreamManager
from app.core.websocket_manager import websocket_manager
from app.db.redis import redis_cache
from app.db.repositories.playbooks import playbook_repository
from app.models.playbook_models import PlaybookDocument, PlaybookRunStatus, PlaybookStep
from app.utils import background_tasks


def tool_function(tool_obj: BaseTool) -> Callable[..., Awaitable[str]]:
    """The undecorated coroutine behind a ``@tool``.

    Called directly instead of ``ainvoke`` so a test never opens a LangSmith
    trace: ``langsmith.utils.get_env_var`` is ``lru_cache``d, so a fixture that
    disabled tracing would poison every later test in the same worker.
    """
    coroutine = cast(StructuredTool, tool_obj).coroutine
    assert coroutine is not None
    return cast(Callable[..., Awaitable[str]], coroutine)


run_call_executor = tool_function(call_executor)
run_cancel_executor = tool_function(cancel_executor)


async def call_executor_with(
    config: RunnableConfig,
    task: str,
    acceptance_criteria: list[str] | None = None,
    **kwargs: Any,
) -> str:
    """Call call_executor with the now-required acceptance_criteria provided.

    The tool schema requires acceptance_criteria (never omit); tests that don't
    care about it pass a generic checklist so they exercise the dispatch path,
    not the schema default.
    """
    if acceptance_criteria is None:
        acceptance_criteria = []
    return await run_call_executor(
        config=config,
        task=task,
        acceptance_criteria=acceptance_criteria,
        **kwargs,
    )


CONVERSATION_ID = "conv-1"
LOCK_KEY = f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION_ID}"
QUEUE_KEY = f"{EXECUTOR_QUEUE_PREFIX}{CONVERSATION_ID}"


def config_for(stream_id: str | None = "stream-1", **overrides: Any) -> RunnableConfig:
    """A comms-agent RunnableConfig, shaped like the one build_agent_config produces."""
    configurable: dict[str, Any] = {
        "thread_id": CONVERSATION_ID,
        "user_id": "user-1",
        "email": "u@example.com",
        "user_name": "Dev",
        "user_message_id": "umsg-1",
    }
    if stream_id is not None:
        configurable["stream_id"] = stream_id
    configurable.update(overrides)
    return {"configurable": configurable}


def task_id_from(response: str) -> str:
    return response.split("task_id: ")[1].split(")", maxsplit=1)[0]


async def drain_background_tasks() -> None:
    """Let the spawned asyncio task run to completion and fire its done callback."""
    for _ in range(3):
        await asyncio.sleep(0)


@pytest.fixture(autouse=True)
async def fake_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    """Patch the module singleton's client so every layer below sees one real Redis."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_cache, "redis", client)
    yield client
    await client.flushall()
    await client.connection_pool.disconnect()


@pytest.fixture(autouse=True)
def _clean_sessions() -> Iterator[None]:
    yield
    for stream_id in ("stream-1", "stream-2", "new-stream", ""):
        teardown_session(stream_id)


@pytest.fixture
def spawned_runs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace the executor graph run — the one genuine external boundary here."""
    calls: list[dict[str, Any]] = []

    async def fake_run_executor_background(
        *, run: Any, task: str, configurable: dict[str, Any]
    ) -> None:
        calls.append({"run": run, "task": task, "configurable": configurable})

    monkeypatch.setattr(executor_tool, "run_executor_background", fake_run_executor_background)
    return calls


@pytest.fixture
def fast_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scale the redirect wait budget down, preserving DETECT < WAIT."""
    monkeypatch.setattr(executor_tool, "REDIRECT_CANCEL_DETECT_S", 0.1)
    monkeypatch.setattr(executor_tool, "REDIRECT_CANCEL_WAIT_S", 0.5)
    monkeypatch.setattr(executor_tool, "REDIRECT_CANCEL_POLL_S", 0.01)


@pytest.fixture
def release_lock_on_attempt(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> Callable[[int], None]:
    """Free the busy lock on the N-th ``try_acquire_lock`` call.

    Replaces real-time releaser tasks racing the DETECT/WAIT windows: the
    redirect poll loop calls ``try_acquire_lock`` exactly once per POLL
    iteration, so a release tied to the attempt count lands at a fixed
    ``waited`` value (overall attempt K with the pre-redirect attempt at
    #1 ⇒ redirect wait (K-2)*POLL) — deterministic by construction.
    """

    real_acquire = executor_tool.try_acquire_lock
    state = {"attempt": 0, "release": -1}

    async def wrapped_acquire(lock_key: str, lock_value: str) -> bool:
        state["attempt"] += 1
        if state["attempt"] == state["release"]:
            await fake_redis.delete(lock_key)
        return await real_acquire(lock_key, lock_value)

    monkeypatch.setattr(executor_tool, "try_acquire_lock", wrapped_acquire)

    def schedule(release_attempt: int) -> None:
        state["release"] = release_attempt

    return schedule


@pytest.fixture(autouse=True)
def closed_approvals(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """The HIL boundary (Mongo-backed): which conversations had their approvals closed."""
    mock = AsyncMock(return_value=[])
    monkeypatch.setattr(executor_tool, "cancel_conversation_approvals", mock)
    return mock


@pytest.fixture
def broadcast(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr(websocket_manager, "broadcast_to_user", mock)
    return mock


# ── call_executor: dispatch ──────────────────────────────────────────


class TestCallExecutorDispatch:
    async def test_spawns_executor_and_reports_its_task_id(
        self, fake_redis: fakeredis.aioredis.FakeRedis, spawned_runs: list[dict[str, Any]]
    ) -> None:
        response = await call_executor_with(config=config_for(), task="check my calendar")
        await drain_background_tasks()

        assert len(spawned_runs) == 1
        run = spawned_runs[0]["run"]
        assert spawned_runs[0]["task"] == "check my calendar"
        assert run.task_id == task_id_from(response)
        assert run.stream_id == "stream-1"
        assert run.conversation_id == CONVERSATION_ID
        assert run.user_message_id == "umsg-1"
        assert run.user["user_id"] == "user-1"
        assert run.kind.value == "live"
        assert was_executor_spawned("stream-1") is True

    async def test_a_dispatch_with_no_stream_carries_an_empty_stream_id(
        self, fake_redis: fakeredis.aioredis.FakeRedis, spawned_runs: list[dict[str, Any]]
    ) -> None:
        """A run with no live client still gets a run identity. The absent stream is
        the empty string — a placeholder would be treated as a real stream by every
        session lookup downstream."""
        await call_executor_with(config=config_for(stream_id=None), task="check my calendar")
        await drain_background_tasks()

        assert spawned_runs[0]["run"].stream_id == ""

    async def test_holds_the_busy_lock_with_its_own_value_and_a_ttl(
        self, fake_redis: fakeredis.aioredis.FakeRedis, spawned_runs: list[dict[str, Any]]
    ) -> None:
        response = await call_executor_with(config=config_for(), task="x")

        assert await fake_redis.get(LOCK_KEY) == f"stream-1:{task_id_from(response)}"
        # No TTL would wedge the conversation forever if the worker died mid-run.
        assert await fake_redis.ttl(LOCK_KEY) == EXECUTOR_BUSY_TTL

    async def test_background_task_is_kept_alive_then_released(
        self, fake_redis: fakeredis.aioredis.FakeRedis, spawned_runs: list[dict[str, Any]]
    ) -> None:
        # The registry is process-global — other test files in the same
        # worker may leave entries behind. Assert the DELTA, not an
        # absolute count, so the check is order-independent.
        baseline = set(background_tasks._background_tasks)
        await call_executor_with(config=config_for(), task="x")
        assert (
            len(background_tasks._background_tasks) == len(baseline) + 1
        )  # GC protection while in flight

        await drain_background_tasks()
        assert background_tasks._background_tasks == baseline

    async def test_active_todo_binding_reaches_the_executor_without_mutating_comms_config(
        self, fake_redis: fakeredis.aioredis.FakeRedis, spawned_runs: list[dict[str, Any]]
    ) -> None:
        config = config_for()
        await call_executor_with(config=config, task="continue todo", active_todo_id="todo-9")
        await drain_background_tasks()

        assert spawned_runs[0]["configurable"]["active_todo_id"] == "todo-9"
        assert "active_todo_id" not in config["configurable"]

    async def test_without_active_todo_no_binding_is_injected(
        self, fake_redis: fakeredis.aioredis.FakeRedis, spawned_runs: list[dict[str, Any]]
    ) -> None:
        await call_executor_with(config=config_for(), task="generic")
        await drain_background_tasks()

        assert "active_todo_id" not in spawned_runs[0]["configurable"]

    async def test_missing_thread_id_refuses_instead_of_running_unanchored(
        self, fake_redis: fakeredis.aioredis.FakeRedis, spawned_runs: list[dict[str, Any]]
    ) -> None:
        response = await call_executor_with(config=RunnableConfig(configurable={}), task="x")

        assert response == "Internal error: conversation context unavailable. Please try again."
        assert spawned_runs == []
        assert await fake_redis.keys(f"{EXECUTOR_BUSY_PREFIX}*") == []

    async def test_each_conversation_has_its_own_lock(
        self, fake_redis: fakeredis.aioredis.FakeRedis, spawned_runs: list[dict[str, Any]]
    ) -> None:
        await call_executor_with(config=config_for(), task="a")
        other: RunnableConfig = {"configurable": {"thread_id": "conv-2", "stream_id": "stream-2"}}

        response = await call_executor_with(config=other, task="b")

        assert response.startswith("Task accepted")
        await drain_background_tasks()
        assert len(spawned_runs) == 2
        assert await fake_redis.get(f"{EXECUTOR_BUSY_PREFIX}conv-2") is not None


# ── call_executor: lock contention ───────────────────────────────────


class TestCallExecutorLockContention:
    async def test_second_call_in_the_same_turn_is_rejected_not_queued(
        self, fake_redis: fakeredis.aioredis.FakeRedis, spawned_runs: list[dict[str, Any]]
    ) -> None:
        """Queuing a same-turn duplicate ran deep research twice for one message."""
        first = await call_executor_with(config=config_for(), task="research")
        lock_before = await fake_redis.get(LOCK_KEY)

        second = await call_executor_with(config=config_for(), task="research")
        await drain_background_tasks()

        assert second == (
            "That task is already running from this same message, not "
            "starting it again. The results are on the way."
        )
        assert first.startswith("Task accepted")
        assert await fake_redis.llen(QUEUE_KEY) == 0
        assert await fake_redis.get(LOCK_KEY) == lock_before
        assert len(spawned_runs) == 1

    async def test_a_different_turn_is_queued_with_its_full_run_context(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        spawned_runs: list[dict[str, Any]],
        fast_redirect: None,
    ) -> None:
        await call_executor_with(config=config_for("stream-1"), task="first")

        response = await call_executor_with(
            config=config_for("stream-2"), task="second", active_todo_id="todo-3"
        )
        await drain_background_tasks()

        queued_id = task_id_from(response)
        assert response == (
            "I'm already working on a task for this conversation. "
            f"Your request has been queued (task_id: {queued_id}) "
            "and I'll handle it right after."
        )
        assert len(spawned_runs) == 1  # queued task must NOT run now
        items = [json.loads(raw) for raw in await fake_redis.lrange(QUEUE_KEY, 0, -1)]
        assert len(items) == 1
        assert items[0]["task"] == "second"
        assert items[0]["task_id"] == queued_id
        assert items[0]["conversation_id"] == CONVERSATION_ID
        assert items[0]["user_message_id"] == "umsg-1"
        assert items[0]["configurable"]["stream_id"] == "stream-2"
        assert items[0]["configurable"]["active_todo_id"] == "todo-3"
        assert await fake_redis.ttl(QUEUE_KEY) == EXECUTOR_QUEUE_TTL

    async def test_a_queued_dispatch_is_recorded_on_its_stream_not_only_in_its_prose(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        spawned_runs: list[dict[str, Any]],
        fast_redirect: None,
    ) -> None:
        """The queue acknowledgement above is written for the comms model.

        A silent caller — a workflow fire — has to know whether work actually
        STARTED before it writes an execution record, and that string is the
        wrong thing to ask: it is prose, the model may re-voice it, and it says
        nothing the caller can trust. The session carries the fact instead.
        """
        await call_executor_with(config=config_for("stream-1"), task="first")

        response = await call_executor_with(config=config_for("stream-2"), task="second")
        await drain_background_tasks()

        assert queued_without_run("stream-2") == task_id_from(response)
        # The stream that actually ran deferred nothing, and says so.
        assert was_executor_spawned("stream-1") is True
        assert queued_without_run("stream-1") is None

    async def test_holder_without_a_stream_id_is_never_waited_on(
        self, fake_redis: fakeredis.aioredis.FakeRedis, spawned_runs: list[dict[str, Any]]
    ) -> None:
        """No stream id means no cancel can be observed — queue immediately."""
        await fake_redis.set(LOCK_KEY, ":held-task", ex=EXECUTOR_BUSY_TTL)

        started = time.monotonic()
        response = await call_executor_with(config=config_for("stream-2"), task="b")

        assert response.startswith("I'm already working on a task")
        assert time.monotonic() - started < 0.1
        assert await fake_redis.llen(QUEUE_KEY) == 1


# ── call_executor: same-turn redirect ("stop X, do Y") ───────────────


class TestRedirectAcquire:
    async def test_redirect_runs_live_when_the_cancel_frees_the_lock(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        spawned_runs: list[dict[str, Any]],
        fast_redirect: None,
        release_lock_on_attempt: Callable[[int], None],
    ) -> None:
        await fake_redis.set(LOCK_KEY, "old-stream:old-task", ex=EXECUTOR_BUSY_TTL)
        await StreamManager.cancel_stream("old-stream")

        # Release on the 14th acquire attempt (1 pre-redirect + 13 redirect
        # polls, waited=0.12): past DETECT (0.1), inside WAIT (0.5) — the
        # observed cancel must keep the loop polling past the detect window.
        release_lock_on_attempt(14)
        response = await call_executor_with(config=config_for("new-stream"), task="do Y")
        await drain_background_tasks()

        assert response.startswith("Task accepted")
        assert await fake_redis.llen(QUEUE_KEY) == 0
        assert len(spawned_runs) == 1
        assert await fake_redis.get(LOCK_KEY) == f"new-stream:{task_id_from(response)}"

    async def test_lock_freed_without_a_cancel_signal_is_still_taken_live(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        spawned_runs: list[dict[str, Any]],
        fast_redirect: None,
        release_lock_on_attempt: Callable[[int], None],
    ) -> None:
        """cancel_executor drops the busy key without cancel_stream for blank stream
        ids, so is_cancelled may never flip — acquisition must not be gated on it."""
        await fake_redis.set(LOCK_KEY, "old-stream:old-task", ex=EXECUTOR_BUSY_TTL)

        # Release on the 3rd acquire attempt (2nd redirect poll, waited=0.01 —
        # inside DETECT=0.1): no cancel signal ever flips, yet the free lock
        # must still be taken.
        release_lock_on_attempt(3)
        response = await call_executor_with(config=config_for("new-stream"), task="do Y")
        await drain_background_tasks()

        assert response.startswith("Task accepted")
        assert len(spawned_runs) == 1

    async def test_gives_up_at_the_detect_window_when_no_cancel_is_in_flight(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        spawned_runs: list[dict[str, Any]],
        fast_redirect: None,
    ) -> None:
        """A genuinely busy other turn must be queued fast, not waited on for WAIT_S."""
        await fake_redis.set(LOCK_KEY, "old-stream:old-task", ex=EXECUTOR_BUSY_TTL)

        started = time.monotonic()
        response = await call_executor_with(config=config_for("new-stream"), task="do Y")
        elapsed = time.monotonic() - started

        assert response.startswith("I'm already working on a task")
        assert 0.1 <= elapsed < 0.4  # DETECT (0.1) reached, WAIT (0.5) not
        assert await fake_redis.llen(QUEUE_KEY) == 1

    async def test_queues_after_the_full_wait_when_the_cancel_never_lands(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        spawned_runs: list[dict[str, Any]],
        fast_redirect: None,
    ) -> None:
        await fake_redis.set(LOCK_KEY, "old-stream:old-task", ex=EXECUTOR_BUSY_TTL)
        await StreamManager.cancel_stream("old-stream")

        started = time.monotonic()
        response = await call_executor_with(config=config_for("new-stream"), task="do Y")
        elapsed = time.monotonic() - started

        assert response.startswith("I'm already working on a task")
        assert elapsed >= 0.5  # waited the full budget because a cancel was seen
        assert await fake_redis.llen(QUEUE_KEY) == 1
        assert spawned_runs == []

    async def test_cancel_and_call_in_one_turn_stream_into_the_same_turn(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        spawned_runs: list[dict[str, Any]],
        broadcast: AsyncMock,
    ) -> None:
        """The headline case: the tool node runs both tool calls concurrently."""
        await fake_redis.set(LOCK_KEY, "old-stream:old-task", ex=EXECUTOR_BUSY_TTL)
        config = config_for("new-stream")

        cancel_response, call_response = await asyncio.gather(
            run_cancel_executor(config=config, task_ids=[]),
            call_executor_with(config=config, task="do Y instead"),
        )
        await drain_background_tasks()

        assert cancel_response == "Cancelled: old-task."
        assert call_response.startswith("Task accepted")
        assert len(spawned_runs) == 1
        assert await fake_redis.llen(QUEUE_KEY) == 0  # ran live, not as a queued card


# ── call_executor: failure handling ──────────────────────────────────


class TestCallExecutorFailures:
    async def test_failure_after_acquiring_releases_this_dispatch_lock(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        spawned_runs: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def explode(stream_id: str) -> None:
            raise RuntimeError("session registry down")

        monkeypatch.setattr(executor_tool, "mark_executor_spawned", explode)

        response = await call_executor_with(config=config_for(), task="x")

        assert response == "Error starting task: session registry down"
        assert await fake_redis.get(LOCK_KEY) is None
        assert spawned_runs == []

    async def test_failure_in_the_queue_branch_never_frees_a_foreign_lock(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        spawned_runs: list[dict[str, Any]],
        fast_redirect: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An unconditional release here let a second executor run concurrently."""
        await fake_redis.set(LOCK_KEY, "stream-1:live-task", ex=EXECUTOR_BUSY_TTL)

        async def explode(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("redis write failed")

        monkeypatch.setattr(executor_tool, "enqueue_task", explode)

        response = await call_executor_with(config=config_for("stream-2"), task="b")

        assert response == "Error starting task: redis write failed"
        assert await fake_redis.get(LOCK_KEY) == "stream-1:live-task"


# ── cancel_executor ──────────────────────────────────────────────────


class TestCancelExecutor:
    async def test_without_a_conversation_there_is_nothing_to_cancel(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        assert (
            await run_cancel_executor(config=RunnableConfig(configurable={}), task_ids=[])
            == "No conversation context available."
        )

    async def test_reports_when_nothing_is_running_or_queued(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        response = await run_cancel_executor(config=config_for(), task_ids=[])

        assert response == "No executor tasks are running or queued for this conversation."

    async def test_empty_task_ids_cancels_the_run_and_the_whole_queue(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        broadcast: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cancelled_streams: list[str] = []
        monkeypatch.setattr(
            StreamManager,
            "cancel_stream",
            AsyncMock(side_effect=cancelled_streams.append),
        )
        await fake_redis.set(LOCK_KEY, "stream-1:running-task", ex=EXECUTOR_BUSY_TTL)
        await fake_redis.rpush(QUEUE_KEY, json.dumps({"task_id": "q1"}))
        await fake_redis.rpush(QUEUE_KEY, json.dumps({"task_id": "q2"}))

        response = await run_cancel_executor(config=config_for(), task_ids=[])

        assert response == "Cancelled: running-task, 2 queued task(s)."
        assert cancelled_streams == ["stream-1"]
        assert await fake_redis.get(LOCK_KEY) is None
        assert await fake_redis.llen(QUEUE_KEY) == 0

    async def test_cancelling_only_the_running_task(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        broadcast: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(StreamManager, "cancel_stream", AsyncMock())
        await fake_redis.set(LOCK_KEY, "stream-1:running-task", ex=EXECUTOR_BUSY_TTL)

        response = await run_cancel_executor(config=config_for(), task_ids=["running-task"])

        assert response == "Cancelled: running-task."
        assert await fake_redis.get(LOCK_KEY) is None

    async def test_cancelling_a_queued_task_leaves_the_running_one_alone(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        broadcast: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cancel_stream = AsyncMock()
        monkeypatch.setattr(StreamManager, "cancel_stream", cancel_stream)
        await fake_redis.set(LOCK_KEY, "stream-1:running-task", ex=EXECUTOR_BUSY_TTL)
        await fake_redis.rpush(QUEUE_KEY, json.dumps({"task_id": "q1", "task": "keep"}))
        await fake_redis.rpush(QUEUE_KEY, json.dumps({"task_id": "q2", "task": "kill"}))

        response = await run_cancel_executor(config=config_for(), task_ids=["q2"])

        assert response == (
            "Cancelled: q2. Currently running task was not in the cancel list, still running."
        )
        assert await fake_redis.get(LOCK_KEY) == "stream-1:running-task"
        cancel_stream.assert_not_awaited()
        remaining = [json.loads(raw) for raw in await fake_redis.lrange(QUEUE_KEY, 0, -1)]
        assert [item["task_id"] for item in remaining] == ["q1"]
        assert await fake_redis.ttl(QUEUE_KEY) == EXECUTOR_QUEUE_TTL

    async def test_removing_the_last_queued_task_drops_the_queue_key(
        self, fake_redis: fakeredis.aioredis.FakeRedis, broadcast: AsyncMock
    ) -> None:
        await fake_redis.rpush(QUEUE_KEY, json.dumps({"task_id": "q1"}))

        response = await run_cancel_executor(config=config_for(), task_ids=["q1"])

        assert response == "Cancelled: q1."
        assert await fake_redis.exists(QUEUE_KEY) == 0

    async def test_queue_only_cancel_all_when_no_run_holds_the_lock(
        self, fake_redis: fakeredis.aioredis.FakeRedis, broadcast: AsyncMock
    ) -> None:
        await fake_redis.rpush(QUEUE_KEY, json.dumps({"task_id": "q1"}))

        response = await run_cancel_executor(config=config_for(), task_ids=[])

        assert response == "Cancelled: 1 queued task(s)."

    async def test_unmatched_task_ids_change_nothing(
        self, fake_redis: fakeredis.aioredis.FakeRedis, broadcast: AsyncMock
    ) -> None:
        await fake_redis.set(LOCK_KEY, "stream-1:running-task", ex=EXECUTOR_BUSY_TTL)
        await fake_redis.rpush(QUEUE_KEY, json.dumps({"task_id": "q1"}))

        response = await run_cancel_executor(config=config_for(), task_ids=["unknown"])

        assert response == "None of the specified task_ids matched any running or queued tasks."
        assert await fake_redis.get(LOCK_KEY) == "stream-1:running-task"
        assert await fake_redis.llen(QUEUE_KEY) == 1
        broadcast.assert_not_awaited()

    @pytest.mark.parametrize("blank_stream_id", ["", "1"])
    async def test_placeholder_stream_ids_are_not_cancelled_as_streams(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        broadcast: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
        blank_stream_id: str,
    ) -> None:
        cancel_stream = AsyncMock()
        monkeypatch.setattr(StreamManager, "cancel_stream", cancel_stream)
        await fake_redis.set(LOCK_KEY, f"{blank_stream_id}:held-task", ex=EXECUTOR_BUSY_TTL)

        response = await run_cancel_executor(config=config_for(), task_ids=[])

        assert response == "Cancelled: held-task."
        cancel_stream.assert_not_awaited()
        assert await fake_redis.get(LOCK_KEY) is None

    async def test_legacy_lock_value_without_a_task_id(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        broadcast: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(StreamManager, "cancel_stream", AsyncMock())
        await fake_redis.set(LOCK_KEY, "bare-stream-id", ex=EXECUTOR_BUSY_TTL)

        assert await run_cancel_executor(config=config_for(), task_ids=[]) == "Cancelled: running."

    async def test_a_failed_cancel_leaves_the_running_task_lock_intact(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        broadcast: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Freeing the lock of a run we failed to stop allows two live executors."""
        monkeypatch.setattr(
            StreamManager,
            "cancel_stream",
            AsyncMock(side_effect=RuntimeError("redis connection reset")),
        )
        await fake_redis.set(LOCK_KEY, "stream-1:running-task", ex=EXECUTOR_BUSY_TTL)

        response = await run_cancel_executor(config=config_for(), task_ids=[])

        assert response == "Cancellation attempted but hit an error: redis connection reset"
        assert await fake_redis.get(LOCK_KEY) == "stream-1:running-task"
        broadcast.assert_not_awaited()


class TestCancelClosesHilApprovals:
    """A parked run's approval card is a live way back into the run.

    The record outlives both the busy lock and the stream cancel flag, and a resume
    runs under a fresh stream id the cancel never covered — so a still-pending
    approval re-dispatches exactly the run the user asked to stop.
    """

    async def test_stopping_the_running_task_closes_its_pending_approvals(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        broadcast: AsyncMock,
        closed_approvals: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(StreamManager, "cancel_stream", AsyncMock())
        await fake_redis.set(LOCK_KEY, "stream-1:running-task", ex=EXECUTOR_BUSY_TTL)

        await run_cancel_executor(config=config_for(), task_ids=[])

        closed_approvals.assert_awaited_once_with(CONVERSATION_ID, "user-1")

    async def test_sparing_the_running_task_leaves_its_approvals_alone(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        broadcast: AsyncMock,
        closed_approvals: AsyncMock,
    ) -> None:
        # Only a queued task is cancelled; the parked run is still waiting on its
        # approval, so closing it would break a task the user never stopped.
        await fake_redis.set(LOCK_KEY, "stream-1:running-task", ex=EXECUTOR_BUSY_TTL)
        await fake_redis.rpush(QUEUE_KEY, json.dumps({"task_id": "q1"}))

        await run_cancel_executor(config=config_for(), task_ids=["q1"])

        closed_approvals.assert_not_awaited()

    async def test_nothing_matched_closes_nothing(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        broadcast: AsyncMock,
        closed_approvals: AsyncMock,
    ) -> None:
        await fake_redis.set(LOCK_KEY, "stream-1:running-task", ex=EXECUTOR_BUSY_TTL)

        await run_cancel_executor(config=config_for(), task_ids=["unknown"])

        closed_approvals.assert_not_awaited()

    async def test_a_failure_closing_approvals_surfaces_and_keeps_the_lock(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        broadcast: AsyncMock,
        closed_approvals: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Reporting a clean cancel while approvals stayed pending would leave the
        # user believing a stopped action can no longer run.
        monkeypatch.setattr(StreamManager, "cancel_stream", AsyncMock())
        closed_approvals.side_effect = RuntimeError("mongo unavailable")
        await fake_redis.set(LOCK_KEY, "stream-1:running-task", ex=EXECUTOR_BUSY_TTL)

        response = await run_cancel_executor(config=config_for(), task_ids=[])

        assert response == "Cancellation attempted but hit an error: mongo unavailable"
        broadcast.assert_not_awaited()


# ── cancel_executor: malformed queue items ───────────────────────────


class TestCancelWithMalformedQueueItems:
    async def test_unparseable_items_are_kept_not_dropped(
        self, fake_redis: fakeredis.aioredis.FakeRedis, broadcast: AsyncMock
    ) -> None:
        await fake_redis.rpush(QUEUE_KEY, "not-json-at-all")
        await fake_redis.rpush(QUEUE_KEY, json.dumps({"task_id": "q1"}))
        await fake_redis.rpush(QUEUE_KEY, json.dumps({"task_id": "q2"}))

        response = await run_cancel_executor(config=config_for(), task_ids=["q2"])

        assert response == "Cancelled: q2."
        assert await fake_redis.lrange(QUEUE_KEY, 0, -1) == [
            "not-json-at-all",
            json.dumps({"task_id": "q1"}),
        ]

    async def test_a_json_scalar_item_does_not_abort_the_cancellation(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        broadcast: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`json.loads("5")` is an int; `.get` on it raised outside the ValueError
        handler, aborting the cancel and destroying the running task's lock."""
        monkeypatch.setattr(StreamManager, "cancel_stream", AsyncMock())
        await fake_redis.set(LOCK_KEY, "stream-1:running-task", ex=EXECUTOR_BUSY_TTL)
        await fake_redis.rpush(QUEUE_KEY, "5")
        await fake_redis.rpush(QUEUE_KEY, json.dumps({"task_id": "q1"}))

        response = await run_cancel_executor(config=config_for(), task_ids=["q1"])

        assert response == (
            "Cancelled: q1. Currently running task was not in the cancel list, still running."
        )
        assert await fake_redis.get(LOCK_KEY) == "stream-1:running-task"
        assert await fake_redis.lrange(QUEUE_KEY, 0, -1) == ["5"]

    async def test_queued_item_without_a_task_id_is_never_matched(
        self, fake_redis: fakeredis.aioredis.FakeRedis, broadcast: AsyncMock
    ) -> None:
        await fake_redis.rpush(QUEUE_KEY, json.dumps({"task": "orphan"}))

        response = await run_cancel_executor(config=config_for(), task_ids=["q1"])

        assert response == "None of the specified task_ids matched any running or queued tasks."
        assert await fake_redis.llen(QUEUE_KEY) == 1


# ── cancel broadcast ─────────────────────────────────────────────────


class TestCancelBroadcast:
    async def test_clients_are_told_about_an_agent_initiated_cancel(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        broadcast: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(StreamManager, "cancel_stream", AsyncMock())
        await fake_redis.set(LOCK_KEY, "stream-1:running-task", ex=EXECUTOR_BUSY_TTL)

        await run_cancel_executor(config=config_for(), task_ids=[])

        broadcast.assert_awaited_once_with(
            "user-1",
            {
                "type": WS_EVENT_EXECUTOR_CANCELLED,
                "conversation_id": CONVERSATION_ID,
                "cancelled": ["running-task"],
            },
        )

    async def test_no_user_id_means_no_broadcast_attempt(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        broadcast: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(StreamManager, "cancel_stream", AsyncMock())
        await fake_redis.set(LOCK_KEY, "stream-1:running-task", ex=EXECUTOR_BUSY_TTL)
        config = config_for()
        del config["configurable"]["user_id"]

        response = await run_cancel_executor(config=config, task_ids=[])

        assert response == "Cancelled: running-task."
        broadcast.assert_not_awaited()

    async def test_a_broken_websocket_does_not_fail_the_cancellation(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        broadcast: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(StreamManager, "cancel_stream", AsyncMock())
        broadcast.side_effect = RuntimeError("rabbitmq unavailable")
        await fake_redis.set(LOCK_KEY, "stream-1:running-task", ex=EXECUTOR_BUSY_TTL)

        response = await run_cancel_executor(config=config_for(), task_ids=[])

        assert response == "Cancelled: running-task."
        assert await fake_redis.get(LOCK_KEY) is None


# ── module surface ───────────────────────────────────────────────────


def test_both_executor_tools_are_exported_for_the_comms_agent() -> None:
    assert [tool.name for tool in tools] == ["call_executor", "cancel_executor"]


@pytest.mark.unit
class TestDispatchThreadsTheTurnsIdentity:
    """What the comms turn hands the executor about *which* turn it is.

    ``bot_message_id`` is the original live turn's message: a HIL pause resumes
    onto it rather than minting a rival placeholder, so losing it here is the
    same user-visible split as losing it in the queue — the client renders a
    second bubble with its own tool accordion and the first one never finishes.
    """

    async def test_the_bot_message_id_reaches_the_executor_run(
        self, fake_redis: fakeredis.aioredis.FakeRedis, spawned_runs: list[dict[str, Any]]
    ) -> None:
        await call_executor_with(
            config=config_for(bot_message_id="bmsg-7"), task="check my calendar"
        )
        await drain_background_tasks()

        assert spawned_runs[0]["run"].bot_message_id == "bmsg-7"

    async def test_a_turn_without_one_dispatches_with_none(
        self, fake_redis: fakeredis.aioredis.FakeRedis, spawned_runs: list[dict[str, Any]]
    ) -> None:
        """Only a HIL pause sets it; a plain live turn must dispatch cleanly
        rather than carrying a stale id from the configurable."""
        await call_executor_with(config=config_for(), task="check my calendar")
        await drain_background_tasks()

        assert spawned_runs[0]["run"].bot_message_id is None

    async def test_the_users_own_wording_reaches_the_executor(
        self, fake_redis: fakeredis.aioredis.FakeRedis, spawned_runs: list[dict[str, Any]]
    ) -> None:
        """The executor's brief carries the verbatim request alongside comms'
        paraphrase, so a detail comms dropped is still recoverable downstream.

        Sourced from the configurable, so it rides along whatever the comms model
        did or did not emit — the tool call below passes no verbatim argument
        because the schema no longer has one.
        """
        await call_executor_with(
            config=config_for(user_request="pls archive the junk mail and flag the offer thing"),
            task="triage the inbox",
        )
        await drain_background_tasks()

        brief = spawned_runs[0]["task"]
        assert brief.startswith(
            "Original request (verbatim):\npls archive the junk mail and flag the offer thing"
        )
        assert "triage the inbox" in brief

    async def test_identifiers_survive_a_paraphrase_that_mangles_them(
        self, fake_redis: fakeredis.aioredis.FakeRedis, spawned_runs: list[dict[str, Any]]
    ) -> None:
        """Regression: a pasted billing table went to the executor with 3 of its 4
        recipient addresses corrupted by the comms model's rewrite, and no verbatim
        copy to check against. The brief must still carry the exact bytes even when
        the model's `task` gets the identifiers wrong."""
        pasted = (
            "writetokhair@gmail.com\tFailed\t$30.00\tsub_0Ni7oWIA6kMF0ogWiKC3x\n"
            "tmunson750@gmail.com\tCancelled\t$30.00\tsub_0NfdUP7ekmLIw59KBtWwa"
        )
        await call_executor_with(
            config=config_for(user_request=pasted),
            task="email writetokhair@gmail.com and tmndo.send@gmail.com about sub_0Ni7cWqI5",
        )
        await drain_background_tasks()

        brief = spawned_runs[0]["task"]
        assert pasted in brief
        assert "sub_0NfdUP7ekmLIw59KBtWwa" in brief


FALLBACK_NOTE = (
    "<playbook_fallback>\n"
    "The playbook for this workflow was replayed first and it stopped partway.\n\n"
    "These steps ALREADY RAN in this same execution, and their effects are real:\n"
    "- events (list_events) -> 12 events\n\n"
    "Do not repeat them. Pick up from where the replay stopped and finish the workflow.\n"
    "</playbook_fallback>"
)


def _failed_playbook() -> PlaybookDocument:
    now = datetime.now(UTC)
    return PlaybookDocument(
        playbook_id="pb-1",
        workflow_id="wf-1",
        user_id="user-1",
        workflow_hash="h",
        description="d",
        steps=[PlaybookStep(id="events", tool="list_events", args={})],
        synthesize="s",
        last_run_status=PlaybookRunStatus.FAILED,
        last_run_reason="stopped at step 2 (send_email)",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.unit
class TestStoppedReplayRecordReachesTheExecutor:
    """A workflow fire whose replay stopped partway is finished by the executor.

    The replay's record used to reach only comms, as part of the trigger
    message, while the executor got the heal brief alone: "do the work properly
    yourself" with no word that half of it had already happened. The record now
    rides the configurable, like the verbatim request, and lands in the brief
    exactly as the worker wrote it.
    """

    async def test_the_fallback_note_reaches_the_brief_verbatim(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        spawned_runs: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(executor_tool, "get_last_run_brief", AsyncMock(return_value=""))
        monkeypatch.setattr(
            playbook_repository, "get_for_workflow", AsyncMock(return_value=_failed_playbook())
        )

        await call_executor_with(
            config=config_for(workflow_id="wf-1", playbook_fallback=FALLBACK_NOTE),
            task="finish the agenda run",
        )
        await drain_background_tasks()

        brief = spawned_runs[0]["task"]
        assert FALLBACK_NOTE in brief
        assert "stopped at step 2 (send_email)" in brief, "still the heal brief"
        assert brief.index("finish the agenda run") < brief.index(FALLBACK_NOTE)

    async def test_a_fire_without_a_stopped_replay_carries_no_record(
        self,
        fake_redis: fakeredis.aioredis.FakeRedis,
        spawned_runs: list[dict[str, Any]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(executor_tool, "get_last_run_brief", AsyncMock(return_value=""))
        monkeypatch.setattr(
            playbook_repository, "get_for_workflow", AsyncMock(return_value=_failed_playbook())
        )

        await call_executor_with(config=config_for(workflow_id="wf-1"), task="run the agenda")
        await drain_background_tasks()

        assert "playbook_fallback" not in spawned_runs[0]["task"]


@pytest.mark.unit
class TestDispatchAcknowledgement:
    """Comms writes its user-facing reply from this string, before the executor
    has run a single tool. It is the one place where the wording *is* the
    behaviour: it must not read as completion, and it has to name the approval
    gate the user may be about to see. Asserted verbatim rather than by
    substring — a reworded clause that quietly drops "Nothing has run yet" or
    the approval sentence is exactly the regression that would ship a bot
    announcing work it has not done.
    """

    async def test_the_acknowledgement_is_exact(
        self, fake_redis: fakeredis.aioredis.FakeRedis, spawned_runs: list[dict[str, Any]]
    ) -> None:
        response = await call_executor_with(config=config_for(), task="send the email")
        task_id = task_id_from(response)

        assert response == (
            f"Task accepted (task_id: {task_id}). Nothing has run yet: this only means the "
            "work has STARTED. Do not tell the user anything was sent, created, deleted, or "
            "finished. Risky actions pause for the user's approval first and they see an "
            "approval card; if that happens the work waits on them, not on you. Acknowledge "
            "that you are on it, and say the action is waiting for their approval if one is "
            "pending. This guidance applies ONLY to this acknowledgment. The real result "
            "arrives later as its own message and supersedes it completely: by then the gate "
            "is settled, so report what happened and never ask again for an approval the "
            "user has already given."
        )
