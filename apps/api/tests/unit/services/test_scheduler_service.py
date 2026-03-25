"""Unit tests for BaseSchedulerService."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.scheduler_models import (
    BaseScheduledTask,
    ScheduleConfig,
    ScheduledTaskStatus,
    TaskExecutionResult,
)
from app.services.scheduler_service import BaseSchedulerService


# ---------------------------------------------------------------------------
# Concrete subclass for testing
# ---------------------------------------------------------------------------


class ConcreteSchedulerService(BaseSchedulerService):
    """Concrete implementation for testing the abstract base class."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mock_get_task = AsyncMock(return_value=None)
        self.mock_execute_task = AsyncMock(
            return_value=TaskExecutionResult(success=True, message="ok")
        )
        self.mock_update_task_status = AsyncMock(return_value=True)
        self.mock_get_pending_task = AsyncMock(return_value=[])

    async def get_task(
        self, task_id: str, user_id: Optional[str] = None
    ) -> Optional[BaseScheduledTask]:
        return await self.mock_get_task(task_id, user_id)

    async def execute_task(self, task: BaseScheduledTask) -> TaskExecutionResult:
        return await self.mock_execute_task(task)

    async def update_task_status(
        self,
        task_id: str,
        status: ScheduledTaskStatus,
        update_data: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        return await self.mock_update_task_status(task_id, status, update_data, user_id)

    async def get_pending_task(self, current_time: datetime) -> List[BaseScheduledTask]:
        return await self.mock_get_pending_task(current_time)

    def get_job_name(self) -> str:
        return "test_job"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    with patch(
        "app.services.scheduler_service.settings",
        MagicMock(REDIS_URL="redis://localhost:6379/0"),
    ):
        svc = ConcreteSchedulerService(redis_settings=MagicMock())
        svc.arq_pool = AsyncMock()
        return svc


@pytest.fixture
def sample_task():
    return BaseScheduledTask(
        _id="task123",
        user_id="user1",
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status=ScheduledTaskStatus.SCHEDULED,
        occurrence_count=0,
    )


@pytest.fixture
def recurring_task():
    return BaseScheduledTask(
        _id="task_recurring",
        user_id="user1",
        repeat="0 9 * * *",
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status=ScheduledTaskStatus.SCHEDULED,
        occurrence_count=0,
    )


@pytest.fixture
def recurring_task_max_occurrences():
    return BaseScheduledTask(
        _id="task_max",
        user_id="user1",
        repeat="0 9 * * *",
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status=ScheduledTaskStatus.SCHEDULED,
        occurrence_count=4,
        max_occurrences=5,
    )


@pytest.fixture
def recurring_task_stop_after():
    return BaseScheduledTask(
        _id="task_stop",
        user_id="user1",
        repeat="0 9 * * *",
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status=ScheduledTaskStatus.SCHEDULED,
        occurrence_count=0,
        stop_after=datetime.now(timezone.utc) + timedelta(hours=2),
    )


# ---------------------------------------------------------------------------
# initialize / close
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInitializeClose:
    async def test_initialize_creates_pool(self):
        with (
            patch(
                "app.services.scheduler_service.settings",
                MagicMock(REDIS_URL="redis://localhost:6379/0"),
            ),
            patch(
                "app.services.scheduler_service.create_pool",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ) as mock_create_pool,
        ):
            svc = ConcreteSchedulerService(redis_settings=MagicMock())
            await svc.initialize()

            mock_create_pool.assert_awaited_once()
            assert svc.arq_pool is not None

    async def test_close_closes_pool(self, service):
        mock_pool = AsyncMock()
        service.arq_pool = mock_pool

        await service.close()

        mock_pool.aclose.assert_awaited_once()

    async def test_close_no_pool(self, service):
        service.arq_pool = None

        # Should not raise
        await service.close()


# ---------------------------------------------------------------------------
# schedule_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScheduleTask:
    async def test_schedule_with_scheduled_at(self, service):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        config = ScheduleConfig(scheduled_at=future)
        mock_job = MagicMock(job_id="job1")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        result = await service.schedule_task("task1", config)

        assert result is True
        service.arq_pool.enqueue_job.assert_awaited_once()

    async def test_schedule_with_repeat_no_scheduled_at(self, service):
        config = ScheduleConfig(repeat="0 9 * * *")
        mock_job = MagicMock(job_id="job1")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with patch(
            "app.services.scheduler_service.get_next_run_time",
            return_value=datetime.now(timezone.utc) + timedelta(hours=1),
        ):
            result = await service.schedule_task("task1", config)

        assert result is True

    async def test_schedule_raises_when_no_time_no_repeat(self, service):
        config = ScheduleConfig()

        with pytest.raises(
            ValueError,
            match="scheduled_at must be provided or repeat must be specified",
        ):
            await service.schedule_task("task1", config)


# ---------------------------------------------------------------------------
# reschedule_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRescheduleTask:
    async def test_reschedule(self, service):
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        mock_job = MagicMock(job_id="job2")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        result = await service.reschedule_task("task1", future)

        assert result is True


# ---------------------------------------------------------------------------
# process_task_execution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessTaskExecution:
    async def test_task_not_found(self, service):
        service.mock_get_task.return_value = None

        result = await service.process_task_execution("task_missing")

        assert result.success is False
        assert "not found" in result.message

    async def test_task_not_scheduled_status(self, service, sample_task):
        sample_task.status = ScheduledTaskStatus.COMPLETED
        service.mock_get_task.return_value = sample_task

        result = await service.process_task_execution("task123")

        assert result.success is False
        assert "not in scheduled status" in result.message

    async def test_one_time_task_executed_and_completed(self, service, sample_task):
        service.mock_get_task.return_value = sample_task
        service.mock_execute_task.return_value = TaskExecutionResult(
            success=True, message="done"
        )

        result = await service.process_task_execution("task123")

        assert result.success is True
        # Should be marked as EXECUTING then COMPLETED
        status_calls = [
            call[0][1] for call in service.mock_update_task_status.call_args_list
        ]
        assert ScheduledTaskStatus.EXECUTING in status_calls
        assert ScheduledTaskStatus.COMPLETED in status_calls

    async def test_recurring_task_rescheduled(self, service, recurring_task):
        service.mock_get_task.return_value = recurring_task
        mock_job = MagicMock(job_id="rescheduled")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with patch(
            "app.services.scheduler_service.get_next_run_time",
            return_value=datetime.now(timezone.utc) + timedelta(days=1),
        ):
            result = await service.process_task_execution("task_recurring")

        assert result.success is True
        # Should update status to SCHEDULED for next run
        status_calls = [
            call[0][1] for call in service.mock_update_task_status.call_args_list
        ]
        assert ScheduledTaskStatus.EXECUTING in status_calls
        assert ScheduledTaskStatus.SCHEDULED in status_calls

    async def test_recurring_task_max_occurrences_reached(
        self, service, recurring_task_max_occurrences
    ):
        service.mock_get_task.return_value = recurring_task_max_occurrences
        mock_job = MagicMock(job_id="j")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with patch(
            "app.services.scheduler_service.get_next_run_time",
            return_value=datetime.now(timezone.utc) + timedelta(days=1),
        ):
            result = await service.process_task_execution("task_max")

        assert result.success is True
        # Should be marked as COMPLETED since max_occurrences reached
        status_calls = [
            call[0][1] for call in service.mock_update_task_status.call_args_list
        ]
        assert ScheduledTaskStatus.COMPLETED in status_calls

    async def test_recurring_task_stop_after_reached(
        self, service, recurring_task_stop_after
    ):
        service.mock_get_task.return_value = recurring_task_stop_after
        mock_job = MagicMock(job_id="j")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        # Return a next_run time that is beyond stop_after
        far_future = datetime.now(timezone.utc) + timedelta(days=30)
        with patch(
            "app.services.scheduler_service.get_next_run_time",
            return_value=far_future,
        ):
            result = await service.process_task_execution("task_stop")

        assert result.success is True
        status_calls = [
            call[0][1] for call in service.mock_update_task_status.call_args_list
        ]
        assert ScheduledTaskStatus.COMPLETED in status_calls

    async def test_execution_exception_marks_failed(self, service, sample_task):
        service.mock_get_task.return_value = sample_task
        service.mock_execute_task.side_effect = Exception("Execution error")

        result = await service.process_task_execution("task123")

        assert result.success is False
        assert "Execution error" in result.message
        status_calls = [
            call[0][1] for call in service.mock_update_task_status.call_args_list
        ]
        assert ScheduledTaskStatus.FAILED in status_calls


# ---------------------------------------------------------------------------
# cancel_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCancelTask:
    async def test_cancel_success(self, service):
        service.mock_update_task_status.return_value = True

        result = await service.cancel_task("task1", "user1")

        assert result is True
        call_args = service.mock_update_task_status.call_args
        assert call_args[0][0] == "task1"
        assert call_args[0][1] == ScheduledTaskStatus.CANCELLED
        assert call_args[0][3] == "user1"

    async def test_cancel_failure(self, service):
        service.mock_update_task_status.return_value = False

        result = await service.cancel_task("task1", "user1")

        assert result is False


# ---------------------------------------------------------------------------
# scan_and_schedule_pending_tasks
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScanAndSchedulePendingTasks:
    async def test_schedules_pending_tasks(self, service):
        tasks = [
            BaseScheduledTask(
                _id="t1",
                user_id="u1",
                scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            BaseScheduledTask(
                _id="t2",
                user_id="u1",
                scheduled_at=datetime.now(timezone.utc) + timedelta(hours=2),
            ),
        ]
        service.mock_get_pending_task.return_value = tasks
        mock_job = MagicMock(job_id="j")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        await service.scan_and_schedule_pending_tasks()

        assert service.arq_pool.enqueue_job.await_count == 2

    async def test_skips_tasks_without_id(self, service):
        tasks = [
            BaseScheduledTask(
                user_id="u1",
                scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),  # No _id
        ]
        service.mock_get_pending_task.return_value = tasks

        await service.scan_and_schedule_pending_tasks()

        service.arq_pool.enqueue_job.assert_not_awaited()

    async def test_handles_empty_pending_list(self, service):
        service.mock_get_pending_task.return_value = []

        await service.scan_and_schedule_pending_tasks()

        service.arq_pool.enqueue_job.assert_not_awaited()


# ---------------------------------------------------------------------------
# _handle_recurring_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleRecurringTask:
    async def test_no_repeat_returns_early(self, service, sample_task):
        sample_task.repeat = None

        await service._handle_recurring_task(sample_task, 1)

        # Should not try to reschedule
        service.arq_pool.enqueue_job.assert_not_awaited()

    async def test_no_task_id_returns_early(self, service, recurring_task):
        recurring_task.id = None

        await service._handle_recurring_task(recurring_task, 1)

        service.arq_pool.enqueue_job.assert_not_awaited()

    async def test_reschedules_when_should_continue(self, service, recurring_task):
        mock_job = MagicMock(job_id="j")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with patch(
            "app.services.scheduler_service.get_next_run_time",
            return_value=datetime.now(timezone.utc) + timedelta(days=1),
        ):
            await service._handle_recurring_task(recurring_task, 1)

        service.mock_update_task_status.assert_awaited()
        status_call = service.mock_update_task_status.call_args
        assert status_call[0][1] == ScheduledTaskStatus.SCHEDULED

    async def test_stop_after_naive_datetime(self, service, recurring_task):
        """Naive stop_after should be treated as UTC."""
        recurring_task.stop_after = datetime(2099, 12, 31)  # naive datetime
        mock_job = MagicMock(job_id="j")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with patch(
            "app.services.scheduler_service.get_next_run_time",
            return_value=datetime.now(timezone.utc) + timedelta(days=1),
        ):
            await service._handle_recurring_task(recurring_task, 1)

        # Should still reschedule because next_run < stop_after
        status_call = service.mock_update_task_status.call_args
        assert status_call[0][1] == ScheduledTaskStatus.SCHEDULED

    async def test_extracts_timezone_from_trigger_config(self, service):
        """If task has trigger_config.timezone, use it for next_run calculation."""

        class TaskWithTriggerConfig(BaseScheduledTask):
            model_config = {"arbitrary_types_allowed": True}
            trigger_config: Optional[MagicMock] = None

        trigger_config = MagicMock()
        trigger_config.timezone = "America/New_York"
        task = TaskWithTriggerConfig(
            _id="task_tz",
            user_id="user1",
            repeat="0 9 * * *",
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
            status=ScheduledTaskStatus.SCHEDULED,
            trigger_config=trigger_config,
        )
        mock_job = MagicMock(job_id="j")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with patch(
            "app.services.scheduler_service.get_next_run_time",
            return_value=datetime.now(timezone.utc) + timedelta(days=1),
        ) as mock_next_run:
            await service._handle_recurring_task(task, 1)

            mock_next_run.assert_called_once()
            call_args = mock_next_run.call_args
            assert call_args[0][2] == "America/New_York"


# ---------------------------------------------------------------------------
# _enqueue_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnqueueTask:
    async def test_enqueue_success(self, service):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_job = MagicMock(job_id="job1")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        result = await service._enqueue_task("task1", future)

        assert result is True
        service.arq_pool.enqueue_job.assert_awaited_once_with(
            "test_job", "task1", _defer_until=future
        )

    async def test_enqueue_no_pool(self, service):
        service.arq_pool = None

        result = await service._enqueue_task("task1", datetime.now(timezone.utc))

        assert result is False

    async def test_enqueue_failed_returns_false(self, service):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        service.arq_pool.enqueue_job = AsyncMock(return_value=None)

        result = await service._enqueue_task("task1", future)

        assert result is False

    async def test_enqueue_past_time_rescheduled(self, service):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        mock_job = MagicMock(job_id="job1")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        result = await service._enqueue_task("task1", past)

        assert result is True
        call_args = service.arq_pool.enqueue_job.call_args
        defer_until = call_args[1]["_defer_until"]
        # Should be in the future (now + 120s buffer)
        assert defer_until > datetime.now(timezone.utc)

    async def test_enqueue_naive_datetime_gets_utc(self, service):
        naive_future = datetime(2099, 1, 1, 12, 0, 0)  # no tzinfo
        mock_job = MagicMock(job_id="job1")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        result = await service._enqueue_task("task1", naive_future)

        assert result is True
        call_args = service.arq_pool.enqueue_job.call_args
        defer_until = call_args[1]["_defer_until"]
        assert defer_until.tzinfo is not None
