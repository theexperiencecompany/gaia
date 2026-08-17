"""Smoke tests for the ARQ worker entry point (app.worker).

The worker module registers every task function and cron job on
WorkerSettings at import time; pinning that registry keeps the entry point
from silently losing a task — app.worker.py was at 0% coverage.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from app.workers.queue import enqueue_worker_job


async def test_enqueue_worker_job_forwards_every_kwarg_to_pool() -> None:
    """Every ARQ scheduling kwarg (_job_id, _queue_name, _defer_until,
    _defer_by, _expires, _job_try) plus arbitrary **kwargs must reach
    pool.enqueue_job unchanged — a mutant that swaps any one for None, drops
    it from the call, or drops **kwargs entirely would silently break
    deduping, queue routing, deferral, expiry, retry counting, or the task's
    own arguments."""
    pool = AsyncMock()
    defer_until = datetime(2026, 1, 1, tzinfo=UTC)

    with patch("app.workers.queue.get_trace_id", return_value=None):
        await enqueue_worker_job(
            pool,
            "my_function",
            "positional_arg",
            _job_id="job-123",
            _queue_name="custom_queue",
            _defer_until=defer_until,
            _defer_by=30,
            _expires=60,
            _job_try=2,
            extra_kwarg="task_payload",
        )

    pool.enqueue_job.assert_awaited_once_with(
        "my_function",
        "positional_arg",
        _job_id="job-123",
        _queue_name="custom_queue",
        _defer_until=defer_until,
        _defer_by=30,
        _expires=60,
        _job_try=2,
        extra_kwarg="task_payload",
    )


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
