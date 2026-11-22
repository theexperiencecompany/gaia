"""Smoke tests for the ARQ worker entry point (app.worker).

The worker module registers every task function and cron job on
WorkerSettings at import time; pinning that registry keeps the entry point
from silently losing a task — app.worker.py was at 0% coverage.
"""

import importlib

from arq.worker import Function

from app.constants.onboarding import INTELLIGENCE_TASK


def _registered_names() -> set[str]:
    from app.workers.config.worker_settings import WorkerSettings

    importlib.import_module("app.worker")  # it fills the settings in as it loads

    return {fn.name if isinstance(fn, Function) else fn.__name__ for fn in WorkerSettings.functions}


def test_worker_settings_registers_all_task_functions() -> None:
    from app.workers.config.worker_settings import WorkerSettings

    importlib.import_module("app.worker")  # it fills the settings in as it loads

    assert len(WorkerSettings.functions) >= 15


def test_worker_settings_registers_the_task_engine() -> None:
    assert {"run_task", "resume_task", "finish_task_run"} <= _registered_names()


def test_the_personalization_task_keeps_no_result() -> None:
    """The per-user job id doubles as the one-run-at-a-time claim; a kept result would make ARQ refuse the next enqueue for an hour after a failed run."""
    from app.workers.config.worker_settings import WorkerSettings

    importlib.import_module("app.worker")  # it fills the settings in as it loads

    task = next(
        fn
        for fn in WorkerSettings.functions
        if isinstance(fn, Function) and fn.name == INTELLIGENCE_TASK
    )
    assert task.keep_result_s == 0


def test_worker_settings_has_cron_jobs() -> None:
    from app.workers.config.worker_settings import WorkerSettings

    importlib.import_module("app.worker")  # it fills the settings in as it loads

    assert len(WorkerSettings.cron_jobs) >= 1


def test_worker_settings_schedules_the_abandoned_registration_sweep() -> None:
    """Registered but unscheduled would leak Photon pool seats in silence."""
    from app.workers.config.worker_settings import WorkerSettings

    importlib.import_module("app.worker")  # it fills the settings in as it loads

    assert "sweep_abandoned_imessage_registrations" in _registered_names()
    assert "cron:sweep_abandoned_imessage_registrations" in {
        job.name for job in WorkerSettings.cron_jobs
    }


def test_worker_settings_schedules_the_browser_reaper() -> None:
    """Unscheduled, a browser job whose worker died spins forever and its result is never told."""
    from app.workers.config.worker_settings import WorkerSettings

    importlib.import_module("app.worker")  # it fills the settings in as it loads

    assert "cron:reap_browser_jobs" in {job.name for job in WorkerSettings.cron_jobs}
