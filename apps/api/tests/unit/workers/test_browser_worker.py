"""Browser jobs run on their own ARQ queue, so their hours-long deadline stays theirs.

ARQ gives every job it starts an in-progress key that lives for the longest
function timeout on that worker, and a job whose worker died is not picked up
again until that key expires. These build the real arq Worker objects and read
the TTL arq computes, rather than restating the formula.
"""

import signal
import socket
from typing import Any

from arq.connections import RedisSettings
from arq.worker import Worker
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

    worker = Worker(
        functions=TASK_FUNCTIONS,
        redis_settings=WorkerSettings.redis_settings,
        job_timeout=WorkerSettings.job_timeout,
        handle_signals=False,
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


async def test_the_reaper_runs_every_few_seconds_on_the_main_workers_queue() -> None:
    """Never behind the browser jobs it watches: their slots are held for hours."""
    reaper = browser_worker_mod.browser_reaper_cron()

    assert reaper.name == "cron:reap_browser_jobs"
    assert reaper.second == {0, 15, 30, 45}
    assert browser_worker_mod.build_browser_worker().cron_jobs == []
