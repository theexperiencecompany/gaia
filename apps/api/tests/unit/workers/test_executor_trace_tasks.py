"""The cron that closes executor runs whose process died."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from arq.worker import Function

from app.worker import TASK_FUNCTIONS
from app.workers.config.worker_settings import WorkerSettings
from app.workers.tasks.executor_trace_tasks import reap_abandoned_executor_runs


def test_the_reaper_is_registered_and_scheduled() -> None:
    """Unscheduled, a run whose process died reads as running in its trace forever."""
    registered = {fn.name if isinstance(fn, Function) else fn.__name__ for fn in TASK_FUNCTIONS}
    assert "reap_abandoned_executor_runs" in registered
    assert "cron:reap_abandoned_executor_runs" in {job.name for job in WorkerSettings.cron_jobs}


async def test_a_sweep_reports_how_many_runs_it_closed() -> None:
    with patch(
        "app.workers.tasks.executor_trace_tasks.reap_abandoned_runs",
        new_callable=AsyncMock,
        return_value=3,
    ):
        assert await reap_abandoned_executor_runs({}) == "abandoned=3"
