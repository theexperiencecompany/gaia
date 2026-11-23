"""The queue workers beside the main worker: brief fires and scout refreshes on their own queues, and their lifecycle.

The worker objects are real arq Workers; only the lifecycle tests stand a fake in for one,
because a real one would consume the live Redis queue.
"""

import asyncio
from collections.abc import Callable
import signal
from typing import Any, cast
from unittest.mock import MagicMock

from arq.connections import RedisSettings
from arq.worker import Worker
import pytest

from app.constants.brief_slots import (
    BRIEF_QUEUE,
    BRIEF_QUEUE_MAX_JOBS,
    SCOUT_QUEUE,
    SCOUT_QUEUE_MAX_JOBS,
)
from app.constants.scouts import REFRESH_SCOUTS_TASK
from app.constants.workflows import EXECUTE_WORKFLOW_TASK
from app.workers import queue_workers
from app.workers.brief_workers import build_brief_worker, build_scout_worker
from app.workers.config.worker_settings import (
    ARQ_BACKSTOP_GRACE_SECONDS,
    WORKER_JOB_TIMEOUT_SECONDS,
    WorkerSettings,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("build", "queue", "task", "max_jobs"),
    [
        (build_brief_worker, BRIEF_QUEUE, EXECUTE_WORKFLOW_TASK, BRIEF_QUEUE_MAX_JOBS),
        (build_scout_worker, SCOUT_QUEUE, REFRESH_SCOUTS_TASK, SCOUT_QUEUE_MAX_JOBS),
    ],
)
async def test_each_brief_queue_is_served_by_its_own_worker_at_its_own_concurrency(
    build: Any, queue: str, task: str, max_jobs: int
) -> None:
    worker: Worker = build()

    assert worker.queue_name == queue
    assert list(worker.functions) == [task]
    assert worker.max_jobs == max_jobs
    assert worker.max_jobs != WorkerSettings.max_jobs
    assert worker.functions[task].timeout_s == (
        WORKER_JOB_TIMEOUT_SECONDS + ARQ_BACKSTOP_GRACE_SECONDS
    )
    assert worker.redis_settings == WorkerSettings.redis_settings
    assert worker.health_check_key == queue_workers.queue_worker_health_key(queue)
    assert worker.keep_result_s == 0
    assert worker.allow_abort_jobs is True


async def test_a_queue_worker_shares_the_main_workers_redis_and_health_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured away from arq's defaults, so a worker that fell back to them would show it."""
    monkeypatch.setattr(
        WorkerSettings, "redis_settings", RedisSettings(host="redis.worker", port=6390)
    )
    monkeypatch.setattr(WorkerSettings, "health_check_interval", 7)

    worker = build_brief_worker()

    assert worker.redis_settings == RedisSettings(host="redis.worker", port=6390)
    assert worker.health_check_interval == 7


async def test_building_a_queue_worker_leaves_the_processs_signals_to_the_main_worker() -> None:
    """Two workers both handling SIGTERM would each run their own shutdown; only the main one may."""
    before = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)

    build_scout_worker()

    assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)) == before


async def test_the_main_worker_still_runs_a_workflow_fire_armed_before_its_queue_moved() -> None:
    """A brief armed on the shared queue before this release still has a worker to run it."""
    from app.worker import TASK_FUNCTIONS

    names = {getattr(f, "name", getattr(f, "__name__", None)) for f in TASK_FUNCTIONS}

    assert EXECUTE_WORKFLOW_TASK in names


class _FakeWorker:
    """Stands in for arq's Worker: runs until closed, or dies when told to."""

    def __init__(self, queue: str = "arq:queue:fake", dies_with: Exception | None = None) -> None:
        self.queue_name = queue
        self.dies_with = dies_with
        self.closed = False
        self._stop = asyncio.Event()

    async def async_run(self) -> None:
        if self.dies_with is not None:
            raise self.dies_with
        await self._stop.wait()
        raise asyncio.CancelledError

    async def close(self) -> None:
        self.closed = True
        self._stop.set()


def _built(fake: _FakeWorker) -> Callable[[], Worker]:
    """Hand the fake to start_queue_workers as the Worker it stands in for."""
    return lambda: cast(Worker, fake)


@pytest.fixture
def raised_signals(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    raise_signal = MagicMock()
    monkeypatch.setattr(signal, "raise_signal", raise_signal)
    return raise_signal


async def test_every_queue_worker_runs_beside_the_main_one_and_stops_with_it(
    raised_signals: MagicMock,
) -> None:
    fakes = [_FakeWorker("arq:queue:a"), _FakeWorker("arq:queue:b")]
    ctx: dict[str, Any] = {}

    queue_workers.start_queue_workers(ctx, [_built(fakes[0]), _built(fakes[1])])
    await asyncio.sleep(0)
    await queue_workers.stop_queue_workers(ctx)

    assert [fake.closed for fake in fakes] == [True, True]
    assert queue_workers.QUEUE_WORKERS_CTX_KEY not in ctx
    raised_signals.assert_not_called()


async def test_a_queue_worker_that_dies_takes_the_process_down_to_be_restarted(
    raised_signals: MagicMock,
) -> None:
    ctx: dict[str, Any] = {}

    queue_workers.start_queue_workers(
        ctx, [_built(_FakeWorker(dies_with=ConnectionError("redis went away")))]
    )
    for _ in range(3):
        await asyncio.sleep(0)

    raised_signals.assert_called_once_with(signal.SIGTERM)
    await queue_workers.stop_queue_workers(ctx)


async def test_a_dying_queue_worker_says_which_queue_took_the_process_down(
    monkeypatch: pytest.MonkeyPatch, raised_signals: MagicMock
) -> None:
    fake_log = MagicMock()
    monkeypatch.setattr(queue_workers, "log", fake_log)
    task = MagicMock(cancelled=MagicMock(return_value=False))
    task.get_name.return_value = "arq:queue:brief:worker"

    queue_workers._stop_process_if_it_ended(task)

    (message,), fields = fake_log.error.call_args
    assert "Queue worker stopped" in message
    assert fields == {"task": "arq:queue:brief:worker"}


async def test_each_queue_workers_task_is_named_for_its_queue(raised_signals: MagicMock) -> None:
    """The name is what a stuck-task dump or an unobserved failure reports it by."""
    ctx: dict[str, Any] = {}

    queue_workers.start_queue_workers(ctx, [_built(_FakeWorker("arq:queue:brief"))])
    try:
        [running] = ctx[queue_workers.QUEUE_WORKERS_CTX_KEY].started
        assert running.task.get_name() == "arq:queue:brief:worker"
    finally:
        await queue_workers.stop_queue_workers(ctx)


async def test_a_build_that_fails_leaves_the_queues_already_started_stoppable(
    raised_signals: MagicMock,
) -> None:
    started = _FakeWorker("arq:queue:a")
    ctx: dict[str, Any] = {}

    def broken() -> Worker:
        raise RuntimeError("cannot build")

    with pytest.raises(RuntimeError):
        queue_workers.start_queue_workers(ctx, [_built(started), broken])
    await queue_workers.stop_queue_workers(ctx)

    assert started.closed


async def test_shutdown_after_a_startup_that_never_started_them_is_a_no_op() -> None:
    await queue_workers.stop_queue_workers({})
