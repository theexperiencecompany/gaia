"""``WorkflowScheduler.update_task_status`` — the run-state write used by the
scheduler and the worker's re-arm paths.

Threads the caller's ``update_data`` dict into the typed ``WorkflowRearm``
the repository's ``set_status`` expects (see ``app/models/workflow_models.py``
and the refactor in commit 58a9f12fa5 that replaced a kwargs bag with this
typed object). Direct tests — the base-class tests in
``test_scheduler_service.py`` exercise a test double, never this real method.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.scheduler_models import ScheduledTaskStatus
from app.models.workflow_models import UNSET, WorkflowRearm
from app.services.workflow.scheduler import WorkflowScheduler


@pytest.fixture
def scheduler() -> WorkflowScheduler:
    with patch(
        "app.services.scheduler_service.settings",
        MagicMock(REDIS_URL="redis://localhost:6379/0"),
    ):
        svc = WorkflowScheduler(redis_settings=MagicMock())
        svc.arq_pool = AsyncMock()
        return svc


class TestUpdateTaskStatusRejectsNonRunStatuses:
    async def test_a_status_outside_the_workflow_run_states_raises(
        self, scheduler: WorkflowScheduler
    ) -> None:
        with pytest.raises(ValueError, match="refusing to write status='cancelled'"):
            await scheduler.update_task_status("wf_1", ScheduledTaskStatus.CANCELLED)

    async def test_the_repository_is_never_called_for_a_rejected_status(
        self, scheduler: WorkflowScheduler
    ) -> None:
        with patch(
            "app.services.workflow.scheduler.workflow_repository.set_status", new=AsyncMock()
        ) as mock_set_status:
            with pytest.raises(ValueError):
                await scheduler.update_task_status("wf_1", ScheduledTaskStatus.PAUSED)
        mock_set_status.assert_not_awaited()

    @pytest.mark.parametrize(
        "status",
        [
            ScheduledTaskStatus.SCHEDULED,
            ScheduledTaskStatus.EXECUTING,
            ScheduledTaskStatus.COMPLETED,
        ],
    )
    async def test_every_workflow_run_status_is_accepted(
        self, scheduler: WorkflowScheduler, status: ScheduledTaskStatus
    ) -> None:
        with patch(
            "app.services.workflow.scheduler.workflow_repository.set_status",
            new=AsyncMock(return_value=True),
        ):
            result = await scheduler.update_task_status("wf_1", status)
        assert result is True


class TestUpdateTaskStatusBuildsTheRearm:
    async def test_no_update_data_leaves_scheduled_at_and_next_run_unset(
        self, scheduler: WorkflowScheduler
    ) -> None:
        mock_set_status = AsyncMock(return_value=True)
        with patch(
            "app.services.workflow.scheduler.workflow_repository.set_status", mock_set_status
        ):
            await scheduler.update_task_status("wf_1", ScheduledTaskStatus.SCHEDULED)

        mock_set_status.assert_awaited_once_with(
            "wf_1",
            ScheduledTaskStatus.SCHEDULED,
            user_id=None,
            rearm=WorkflowRearm(
                scheduled_at=UNSET, occurrence_count=None, repeat=None, next_run=UNSET
            ),
        )

    async def test_update_data_fields_are_threaded_through_exactly(
        self, scheduler: WorkflowScheduler
    ) -> None:
        scheduled_at = datetime(2027, 1, 1, tzinfo=UTC)
        next_run = datetime(2027, 1, 2, tzinfo=UTC)
        mock_set_status = AsyncMock(return_value=True)
        with patch(
            "app.services.workflow.scheduler.workflow_repository.set_status", mock_set_status
        ):
            await scheduler.update_task_status(
                "wf_1",
                ScheduledTaskStatus.SCHEDULED,
                update_data={
                    "scheduled_at": scheduled_at,
                    "occurrence_count": 3,
                    "repeat": "0 9 * * *",
                    "trigger_config.next_run": next_run,
                },
                user_id="user-1",
            )

        mock_set_status.assert_awaited_once_with(
            "wf_1",
            ScheduledTaskStatus.SCHEDULED,
            user_id="user-1",
            rearm=WorkflowRearm(
                scheduled_at=scheduled_at,
                occurrence_count=3,
                repeat="0 9 * * *",
                next_run=next_run,
            ),
        )

    async def test_an_explicit_none_scheduled_at_clears_it_rather_than_leaving_it_unset(
        self, scheduler: WorkflowScheduler
    ) -> None:
        """The recovery scan reaps a non-recurring workflow by writing
        ``scheduled_at: None`` — that must reach the repository as a real
        ``None``, not the UNSET sentinel (which means "leave untouched")."""
        mock_set_status = AsyncMock(return_value=True)
        with patch(
            "app.services.workflow.scheduler.workflow_repository.set_status", mock_set_status
        ):
            await scheduler.update_task_status(
                "wf_1",
                ScheduledTaskStatus.SCHEDULED,
                update_data={"scheduled_at": None},
            )

        rearm = mock_set_status.call_args.kwargs["rearm"]
        assert rearm.scheduled_at is None
        assert rearm.next_run is UNSET


class TestUpdateTaskStatusOutcomes:
    async def test_a_matched_update_returns_true_and_logs_the_new_status(
        self, scheduler: WorkflowScheduler
    ) -> None:
        with (
            patch(
                "app.services.workflow.scheduler.workflow_repository.set_status",
                new=AsyncMock(return_value=True),
            ),
            patch("app.services.workflow.scheduler.log") as mock_log,
        ):
            result = await scheduler.update_task_status("wf_1", ScheduledTaskStatus.COMPLETED)

        assert result is True
        mock_log.set.assert_called_once_with(workflow={"id": "wf_1", "status": "completed"})
        mock_log.info.assert_called_once_with(
            "[WORKFLOW] Updated workflow status to",
            task_id="wf_1",
            status="completed",
        )
        mock_log.warning.assert_not_called()

    async def test_an_unmatched_update_returns_false_and_warns(
        self, scheduler: WorkflowScheduler
    ) -> None:
        with (
            patch(
                "app.services.workflow.scheduler.workflow_repository.set_status",
                new=AsyncMock(return_value=False),
            ),
            patch("app.services.workflow.scheduler.log") as mock_log,
        ):
            result = await scheduler.update_task_status(
                "wf_missing", ScheduledTaskStatus.SCHEDULED, user_id="user-1"
            )

        assert result is False
        mock_log.warning.assert_called_once_with(
            "[WORKFLOW] No workflow updated for",
            task_id="wf_missing",
            user_id="user-1",
        )
        mock_log.info.assert_not_called()

    async def test_a_repository_exception_is_caught_and_returns_false(
        self, scheduler: WorkflowScheduler
    ) -> None:
        with (
            patch(
                "app.services.workflow.scheduler.workflow_repository.set_status",
                new=AsyncMock(side_effect=RuntimeError("mongo exploded")),
            ),
            patch("app.services.workflow.scheduler.log") as mock_log,
        ):
            result = await scheduler.update_task_status(
                "wf_1", ScheduledTaskStatus.EXECUTING, user_id="user-1"
            )

        assert result is False
        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.kwargs == {
            "task_id": "wf_1",
            "error": "mongo exploded",
            "error_type": "RuntimeError",
            "user_id": "user-1",
        }
