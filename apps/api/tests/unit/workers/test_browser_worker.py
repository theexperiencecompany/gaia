"""Browser jobs run on their own ARQ queue, so their hours-long deadline stays theirs.

ARQ gives every job it starts an in-progress key that lives for the longest
function timeout on that worker, and a job whose worker died is not picked up
again until that key expires. These build the real arq Worker objects and read
the TTL arq computes, rather than restating the formula.
"""

import asyncio
import signal
import socket
from typing import Any
from unittest.mock import MagicMock

from arq.connections import RedisSettings
from arq.worker import create_worker
import pytest

from app.constants.browser import BROWSER_JOB_QUEUE, BROWSER_JOB_TASK
from app.services.browser.job_lifetime import browser_job_deadline_seconds
from app.workers import browser_worker as browser_worker_mod
from app.workers.config.worker_settings import (
    ARQ_BACKSTOP_GRACE_SECONDS,
    WORKER_JOB_TIMEOUT_SECONDS,
    WorkerSettings,
)

pytestmark = pytest.mark.unit

#: arq adds this to the longest function timeout for the in-progress key's TTL.
ARQ_IN_PROGRESS_PADDING_SECONDS = 10


async def test_a_crashed_workers_ordinary_jobs_wait_only_their_own_timeout() -> None:
    from app.worker import TASK_FUNCTIONS

    worker = create_worker(
        WorkerSettings, functions=TASK_FUNCTIONS, cron_jobs=[], handle_signals=False
    )

    assert BROWSER_JOB_TASK not in worker.functions
    assert worker.in_progress_timeout_s == (
        WORKER_JOB_TIMEOUT_SECONDS + ARQ_BACKSTOP_GRACE_SECONDS + ARQ_IN_PROGRESS_PADDING_SECONDS
    )


async def test_a_browser_job_runs_once_and_leaves_no_result_behind() -> None:
    """A run may already have submitted a form, so ARQ must not retry it; its result lives in the job state, not arq's."""
    worker = browser_worker_mod.build_browser_worker()
    job = worker.functions[BROWSER_JOB_TASK]

    assert job.max_tries == 1
    assert job.keep_result_s == 0
    assert worker.keep_result_s == 0


async def test_the_browser_job_is_registered_under_the_name_enqueuers_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enqueuers address the job by BROWSER_JOB_TASK, whatever the task function happens to be called."""

    async def _renamed_task(ctx: Any, payload: dict[str, object]) -> str:
        return "done"

    monkeypatch.setattr(browser_worker_mod, "run_browser_job", _renamed_task)

    assert list(browser_worker_mod.build_browser_worker().functions) == [BROWSER_JOB_TASK]


async def test_the_browser_worker_shares_the_main_workers_redis_and_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured away from arq's defaults, so a worker that fell back to them would show it."""
    monkeypatch.setattr(
        WorkerSettings, "redis_settings", RedisSettings(host="redis.worker", port=6390)
    )
    monkeypatch.setattr(WorkerSettings, "max_jobs", 3)

    worker = browser_worker_mod.build_browser_worker()

    assert worker.redis_settings == WorkerSettings.redis_settings
    assert worker.max_jobs == WorkerSettings.max_jobs
    assert worker.health_check_interval == WorkerSettings.health_check_interval


async def test_each_host_reports_its_browser_worker_health_under_its_own_key() -> None:
    worker = browser_worker_mod.build_browser_worker()

    assert worker.health_check_key == f"{BROWSER_JOB_QUEUE}:health:{socket.gethostname()}"
    assert worker.health_check_key != WorkerSettings.health_check_key


async def test_a_browser_job_can_be_aborted() -> None:
    """Cancelling a browser task aborts its arq job; without abort support it would run to its hours-long deadline."""
    worker = browser_worker_mod.build_browser_worker()

    assert worker.allow_abort_jobs is True


async def test_building_the_browser_worker_leaves_the_processs_signals_to_the_main_worker() -> None:
    """Two workers both handling SIGTERM would each run their own shutdown; only the main one may."""
    before = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)

    browser_worker_mod.build_browser_worker()

    assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)) == before


async def test_the_browser_worker_serves_only_browser_jobs_on_their_own_queue() -> None:
    worker = browser_worker_mod.build_browser_worker()

    assert worker.queue_name == BROWSER_JOB_QUEUE
    assert list(worker.functions) == [BROWSER_JOB_TASK]
    assert worker.functions[BROWSER_JOB_TASK].timeout_s == (
        browser_job_deadline_seconds() + ARQ_BACKSTOP_GRACE_SECONDS
    )
    assert worker.in_progress_timeout_s == (
        browser_job_deadline_seconds()
        + ARQ_BACKSTOP_GRACE_SECONDS
        + ARQ_IN_PROGRESS_PADDING_SECONDS
    )


class _FakeWorker:
    """Stands in for arq's Worker: runs until closed, or dies when told to."""

    def __init__(self, dies_with: Exception | None = None) -> None:
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


@pytest.fixture
def raised_signals(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    raise_signal = MagicMock()
    monkeypatch.setattr(browser_worker_mod.signal, "raise_signal", raise_signal)
    return raise_signal


async def test_the_browser_worker_runs_beside_the_main_one_and_stops_with_it(
    monkeypatch: pytest.MonkeyPatch, raised_signals: MagicMock
) -> None:
    fake = _FakeWorker()
    monkeypatch.setattr(browser_worker_mod, "build_browser_worker", lambda: fake)
    ctx: dict[str, Any] = {}

    browser_worker_mod.start_browser_worker(ctx)
    await asyncio.sleep(0)
    await browser_worker_mod.stop_browser_worker(ctx)

    assert fake.closed
    raised_signals.assert_not_called()


async def test_a_browser_worker_that_dies_takes_the_process_down_to_be_restarted(
    monkeypatch: pytest.MonkeyPatch, raised_signals: MagicMock
) -> None:
    fake = _FakeWorker(dies_with=ConnectionError("redis went away"))
    monkeypatch.setattr(browser_worker_mod, "build_browser_worker", lambda: fake)
    ctx: dict[str, Any] = {}

    browser_worker_mod.start_browser_worker(ctx)
    for _ in range(3):
        await asyncio.sleep(0)

    raised_signals.assert_called_once_with(browser_worker_mod.signal.SIGTERM)
    await browser_worker_mod.stop_browser_worker(ctx)


async def test_a_dying_browser_worker_says_why_the_process_is_going_down(
    monkeypatch: pytest.MonkeyPatch, raised_signals: MagicMock
) -> None:
    fake_log = MagicMock()
    monkeypatch.setattr(browser_worker_mod, "log", fake_log)
    task = MagicMock(cancelled=MagicMock(return_value=False))

    browser_worker_mod._stop_process_if_it_ended(task)

    (message,), _ = fake_log.error.call_args
    assert "Browser worker stopped" in message


async def test_the_browser_workers_task_is_named_for_it(
    monkeypatch: pytest.MonkeyPatch, raised_signals: MagicMock
) -> None:
    """The name is what a stuck-task dump or an unobserved failure reports it by."""
    monkeypatch.setattr(browser_worker_mod, "build_browser_worker", _FakeWorker)
    ctx: dict[str, Any] = {}

    browser_worker_mod.start_browser_worker(ctx)
    try:
        assert ctx[browser_worker_mod.BROWSER_WORKER_CTX_KEY].task.get_name() == "browser_worker"
    finally:
        await browser_worker_mod.stop_browser_worker(ctx)


async def test_shutdown_after_a_startup_that_never_started_it_is_a_no_op() -> None:
    await browser_worker_mod.stop_browser_worker({})
