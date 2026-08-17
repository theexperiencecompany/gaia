"""Smoke tests for the ARQ worker entry point (app.worker).

The worker module registers every task function and cron job on
WorkerSettings at import time; pinning that registry keeps the entry point
from silently losing a task — app.worker.py was at 0% coverage.
"""


def test_worker_settings_registers_all_task_functions() -> None:
    from app.worker import WorkerSettings

    assert len(WorkerSettings.functions) >= 15


def test_worker_settings_registers_tracked_todo_execution() -> None:
    from app.worker import WorkerSettings

    names = {fn.__name__ for fn in WorkerSettings.functions}
    assert "execute_tracked_todo" in names


def test_worker_settings_has_cron_jobs() -> None:
    from app.worker import WorkerSettings

    assert len(WorkerSettings.cron_jobs) >= 1


def test_worker_settings_schedules_the_abandoned_registration_sweep() -> None:
    """Registered but unscheduled would leak Photon pool seats in silence."""
    from app.worker import WorkerSettings

    assert "sweep_abandoned_imessage_registrations" in {
        fn.__name__ for fn in WorkerSettings.functions
    }
    assert "cron:sweep_abandoned_imessage_registrations" in {
        job.name for job in WorkerSettings.cron_jobs
    }
