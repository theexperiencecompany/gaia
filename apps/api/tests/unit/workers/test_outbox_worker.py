"""Outbox jobs run on their own queue and Worker, so a long run on the main queue cannot hold them."""

import signal
import socket

from arq.worker import create_worker
import pytest

from app.config.settings import settings
from app.constants.outbox import OUTBOX_INTAKE_TASK, OUTBOX_JOB_QUEUE
from app.constants.outbox_attention import OUTBOX_FLUSH_TASK
from app.worker import TASK_FUNCTIONS, WorkerSettings
from app.workers import outbox_worker as outbox_worker_mod

pytestmark = pytest.mark.unit

OUTBOX_TASKS = {OUTBOX_INTAKE_TASK, OUTBOX_FLUSH_TASK, "cron:outbox_flush_sweep"}


async def test_the_outbox_worker_serves_the_outbox_jobs_on_their_own_queue() -> None:
    worker = outbox_worker_mod.build_outbox_worker()

    assert worker.queue_name == OUTBOX_JOB_QUEUE
    assert set(worker.functions) == OUTBOX_TASKS
    assert (
        worker.functions[OUTBOX_INTAKE_TASK].max_tries
        == worker.functions[OUTBOX_FLUSH_TASK].max_tries
    )


async def test_the_main_worker_no_longer_serves_the_outbox_jobs() -> None:
    """A job the main queue never gets must not also be registered there, or a stray enqueue runs on the wrong slots."""
    main = create_worker(
        WorkerSettings, functions=TASK_FUNCTIONS, cron_jobs=[], handle_signals=False
    )

    assert not OUTBOX_TASKS & set(main.functions)
    assert not any(job.name.endswith("outbox_flush_sweep") for job in WorkerSettings.cron_jobs)


async def test_the_lost_flush_sweep_runs_on_the_outbox_worker() -> None:
    worker = outbox_worker_mod.build_outbox_worker()

    assert [job.name for job in worker.cron_jobs] == ["cron:outbox_flush_sweep"]


async def test_the_outbox_worker_has_its_own_slots() -> None:
    """Its slots are the outbox's alone: sized apart from the main worker's, whatever that is set to."""
    worker = outbox_worker_mod.build_outbox_worker()

    assert worker.max_jobs == settings.ARQ_OUTBOX_MAX_JOBS


async def test_each_host_reports_its_outbox_worker_health_under_its_own_key() -> None:
    worker = outbox_worker_mod.build_outbox_worker()

    assert worker.health_check_key == f"{OUTBOX_JOB_QUEUE}:health:{socket.gethostname()}"
    assert worker.health_check_key != WorkerSettings.health_check_key


async def test_building_the_outbox_worker_leaves_the_processs_signals_to_the_main_worker() -> None:
    before = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)

    outbox_worker_mod.build_outbox_worker()

    assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)) == before
