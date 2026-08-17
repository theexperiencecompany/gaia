"""Unit tests for the dormancy sweep ARQ task."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services.workflow.dormancy import DormancySweepResult
from app.workers.tasks.workflow_dormancy_tasks import sweep_dormant_user_workflows

_MOD = "app.workers.tasks.workflow_dormancy_tasks"

_CUTOFF = datetime(2026, 7, 12, tzinfo=UTC)


def _result(**overrides) -> DormancySweepResult:
    defaults = {
        "dry_run": False,
        "cutoff": _CUTOFF,
        "dormant_users": 3,
        "workflows_paused": 7,
        "failures": 1,
        "candidates": [],
    }
    return DormancySweepResult(**{**defaults, **overrides})


@pytest.mark.unit
class TestSweepDormantUserWorkflowsTask:
    async def test_it_reports_what_the_sweep_did(self):
        with patch(
            f"{_MOD}.sweep_dormant_workflows", new_callable=AsyncMock, return_value=_result()
        ):
            summary = await sweep_dormant_user_workflows({})

        assert "7 workflow(s)" in summary
        assert "3 dormant user(s)" in summary
        assert "1 failure(s)" in summary

    async def test_it_runs_for_real_not_as_a_dry_run(self):
        """A cron that silently previewed would pause nothing and still look healthy."""
        sweep = AsyncMock(return_value=_result())
        with patch(f"{_MOD}.sweep_dormant_workflows", sweep):
            await sweep_dormant_user_workflows({})

        assert sweep.await_args.kwargs.get("dry_run") in (None, False)

    async def test_the_sweep_counts_land_on_the_wide_event(self):
        from shared.py.wide_events import log

        log.reset()
        with patch(
            f"{_MOD}.sweep_dormant_workflows", new_callable=AsyncMock, return_value=_result()
        ):
            await sweep_dormant_user_workflows({})

        event = log.get()
        assert event["dormant_users"] == 3
        assert event["workflows_paused"] == 7
        assert event["pause_failures"] == 1
        assert event["cutoff"] == _CUTOFF.isoformat()

    async def test_a_sweep_that_paused_nothing_still_reports(self):
        with patch(
            f"{_MOD}.sweep_dormant_workflows",
            new_callable=AsyncMock,
            return_value=_result(dormant_users=0, workflows_paused=0, failures=0),
        ):
            summary = await sweep_dormant_user_workflows({})

        assert "0 workflow(s)" in summary
        assert "0 dormant user(s)" in summary
