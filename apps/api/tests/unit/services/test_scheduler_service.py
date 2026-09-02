"""Unit tests for BaseSchedulerService."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ConfigDict
import pytest

from app.models.scheduler_models import (
    BaseScheduledTask,
    ScheduleConfig,
    ScheduledTaskStatus,
    TaskExecutionResult,
)
from app.services.scheduler_service import STALE_EXECUTING_THRESHOLD, BaseSchedulerService
from app.utils.timezone import Timezone

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
        self.mock_claim_task = AsyncMock(return_value=True)
        self.mock_find_stale_executing = AsyncMock(return_value=[])

    async def get_task(self, task_id: str, user_id: str | None = None) -> BaseScheduledTask | None:
        return await self.mock_get_task(task_id, user_id)

    async def execute_task(self, task: BaseScheduledTask) -> TaskExecutionResult:
        return await self.mock_execute_task(task)

    async def update_task_status(
        self,
        task_id: str,
        status: ScheduledTaskStatus,
        update_data: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> bool:
        return await self.mock_update_task_status(task_id, status, update_data, user_id)

    async def get_pending_task(self, current_time: datetime) -> list[BaseScheduledTask]:
        return await self.mock_get_pending_task(current_time)

    async def find_stale_executing(self, cutoff: datetime) -> list[BaseScheduledTask]:
        return await self.mock_find_stale_executing(cutoff)

    async def claim_task_for_execution(
        self, task_id: str, expected_occurrence: datetime | None = None
    ) -> bool:
        return await self.mock_claim_task(task_id, expected_occurrence)

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
        scheduled_at=datetime.now(UTC) + timedelta(hours=1),
        status=ScheduledTaskStatus.SCHEDULED,
        occurrence_count=0,
    )


@pytest.fixture
def recurring_task():
    return BaseScheduledTask(
        _id="task_recurring",
        user_id="user1",
        repeat="0 9 * * *",
        scheduled_at=datetime.now(UTC) + timedelta(hours=1),
        status=ScheduledTaskStatus.SCHEDULED,
        occurrence_count=0,
    )


@pytest.fixture
def recurring_task_max_occurrences():
    return BaseScheduledTask(
        _id="task_max",
        user_id="user1",
        repeat="0 9 * * *",
        scheduled_at=datetime.now(UTC) + timedelta(hours=1),
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
        scheduled_at=datetime.now(UTC) + timedelta(hours=1),
        status=ScheduledTaskStatus.SCHEDULED,
        occurrence_count=0,
        stop_after=datetime.now(UTC) + timedelta(hours=2),
    )


# ---------------------------------------------------------------------------
# initialize / close
# ---------------------------------------------------------------------------


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


class TestScheduleTask:
    async def test_schedule_with_scheduled_at(self, service):
        future = datetime.now(UTC) + timedelta(hours=1)
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
            return_value=datetime.now(UTC) + timedelta(hours=1),
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


class TestRescheduleTask:
    async def test_reschedule(self, service):
        future = datetime.now(UTC) + timedelta(hours=2)
        mock_job = MagicMock(job_id="job2")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        result = await service.reschedule_task("task1", future)

        assert result is True


# ---------------------------------------------------------------------------
# process_task_execution
# ---------------------------------------------------------------------------


class TestReapStaleExecuting:
    """A claim with no lease needs a reaper, or a dead worker wedges a task forever."""

    async def test_a_wedged_recurring_task_is_returned_to_scheduled_and_rearmed(
        self, service, recurring_task
    ):
        """The claim flips SCHEDULED -> EXECUTING and nothing releases it.

        If the worker is SIGKILLed mid-run (an ordinary rolling deploy), or arq
        cancels the job and the retry finds the row already claimed, the row
        stays EXECUTING. The due-scan filters on ``status="scheduled"``, so
        nothing can ever see it again and the task simply never fires.
        """
        recurring_task.status = ScheduledTaskStatus.EXECUTING
        service.mock_find_stale_executing.return_value = [recurring_task]
        mock_job = MagicMock(job_id="rearmed")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with patch(
            "app.services.scheduler_service.get_next_run_time",
            return_value=datetime.now(UTC) + timedelta(days=1),
        ):
            reaped = await service.reap_stale_executing()

        assert reaped == 1
        statuses = [call[0][1] for call in service.mock_update_task_status.call_args_list]
        assert ScheduledTaskStatus.SCHEDULED in statuses

    async def test_a_wedged_one_shot_is_rearmed_at_its_original_time(self, service, sample_task):
        """A one-shot has no next occurrence — it must go back to SCHEDULED at the
        time it was armed for, not be dropped for want of a cron expression."""
        sample_task.status = ScheduledTaskStatus.EXECUTING
        service.mock_find_stale_executing.return_value = [sample_task]
        service.arq_pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="j"))

        assert await service.reap_stale_executing() == 1
        statuses = [call[0][1] for call in service.mock_update_task_status.call_args_list]
        assert ScheduledTaskStatus.SCHEDULED in statuses

    async def test_nothing_stale_reaps_nothing(self, service):
        assert await service.reap_stale_executing() == 0
        service.mock_update_task_status.assert_not_awaited()


class TestProcessTaskExecution:
    async def test_task_not_found(self, service):
        service.mock_get_task.return_value = None

        result = await service.process_task_execution("task_missing")

        assert result.success is False
        assert "not found" in result.message

    async def test_task_no_longer_scheduled_is_not_executed(self, service, sample_task):
        """A task that is not SCHEDULED any more fails the claim and must not run."""
        sample_task.status = ScheduledTaskStatus.COMPLETED
        service.mock_get_task.return_value = sample_task
        service.mock_claim_task.return_value = False

        result = await service.process_task_execution("task123")

        assert result.success is False
        assert "not in scheduled status" in result.message
        service.mock_execute_task.assert_not_awaited()

    async def test_only_one_worker_executes_a_task_two_workers_picked_up(
        self, service, sample_task
    ):
        """Two workers holding a job for the same task must not both execute it.

        Two ARQ jobs for one reminder is the normal case, not a contrived race:
        the startup scan runs in every replica and every worker, and its job id
        is derived from each process's own ``now`` (past-due reminders get
        shifted to ``now + 120s``), so the ids differ and ARQ does not dedup
        them. Both jobs then read status=SCHEDULED and run — the user gets the
        reminder twice and GAIA pays for two agent turns.

        The claim has to be the atomic SCHEDULED -> EXECUTING transition itself,
        the way ``workflow_repository.claim_for_execution`` already does it.
        """
        service.mock_get_task.return_value = sample_task
        claimed: list[str] = []

        async def claim_once(task_id: str, expected_occurrence=None) -> bool:
            if task_id in claimed:
                return False
            claimed.append(task_id)
            return True

        service.mock_claim_task = AsyncMock(side_effect=claim_once)

        first, second = await asyncio.gather(
            service.process_task_execution("task123"),
            service.process_task_execution("task123"),
        )

        assert service.mock_execute_task.await_count == 1, (
            "both workers executed the same reminder — the user gets it twice "
            "and both agent turns are billed"
        )
        assert [first.success, second.success].count(True) == 1

    async def test_one_time_task_executed_and_completed(self, service, sample_task):
        service.mock_get_task.return_value = sample_task
        service.mock_execute_task.return_value = TaskExecutionResult(success=True, message="done")

        result = await service.process_task_execution("task123")

        assert result.success is True
        # EXECUTING is the claim itself (one atomic transition), then COMPLETED.
        service.mock_claim_task.assert_awaited_once_with("task123", None)
        status_calls = [call[0][1] for call in service.mock_update_task_status.call_args_list]
        assert ScheduledTaskStatus.COMPLETED in status_calls

    async def test_recurring_task_rescheduled(self, service, recurring_task):
        service.mock_get_task.return_value = recurring_task
        mock_job = MagicMock(job_id="rescheduled")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with patch(
            "app.services.scheduler_service.get_next_run_time",
            return_value=datetime.now(UTC) + timedelta(days=1),
        ):
            result = await service.process_task_execution("task_recurring")

        assert result.success is True
        # EXECUTING is the claim itself; the re-arm puts it back to SCHEDULED.
        service.mock_claim_task.assert_awaited_once_with("task_recurring", None)
        status_calls = [call[0][1] for call in service.mock_update_task_status.call_args_list]
        assert ScheduledTaskStatus.SCHEDULED in status_calls

    async def test_recurring_task_max_occurrences_reached(
        self, service, recurring_task_max_occurrences
    ):
        service.mock_get_task.return_value = recurring_task_max_occurrences
        mock_job = MagicMock(job_id="j")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with patch(
            "app.services.scheduler_service.get_next_run_time",
            return_value=datetime.now(UTC) + timedelta(days=1),
        ):
            result = await service.process_task_execution("task_max")

        assert result.success is True
        # Should be marked as COMPLETED since max_occurrences reached
        status_calls = [call[0][1] for call in service.mock_update_task_status.call_args_list]
        assert ScheduledTaskStatus.COMPLETED in status_calls

    async def test_recurring_task_stop_after_reached(self, service, recurring_task_stop_after):
        service.mock_get_task.return_value = recurring_task_stop_after
        mock_job = MagicMock(job_id="j")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        # Return a next_run time that is beyond stop_after
        far_future = datetime.now(UTC) + timedelta(days=30)
        with patch(
            "app.services.scheduler_service.get_next_run_time",
            return_value=far_future,
        ):
            result = await service.process_task_execution("task_stop")

        assert result.success is True
        status_calls = [call[0][1] for call in service.mock_update_task_status.call_args_list]
        assert ScheduledTaskStatus.COMPLETED in status_calls

    async def test_execution_exception_marks_failed(self, service, sample_task):
        service.mock_get_task.return_value = sample_task
        service.mock_execute_task.side_effect = Exception("Execution error")

        result = await service.process_task_execution("task123")

        assert result.success is False
        assert "Execution error" in result.message
        status_calls = [call[0][1] for call in service.mock_update_task_status.call_args_list]
        assert ScheduledTaskStatus.FAILED in status_calls


# ---------------------------------------------------------------------------
# cancel_task
# ---------------------------------------------------------------------------


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


class TestScanAndSchedulePendingTasks:
    async def test_schedules_pending_tasks(self, service):
        tasks = [
            BaseScheduledTask(
                _id="t1",
                user_id="u1",
                scheduled_at=datetime.now(UTC) + timedelta(hours=1),
            ),
            BaseScheduledTask(
                _id="t2",
                user_id="u1",
                scheduled_at=datetime.now(UTC) + timedelta(hours=2),
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
                scheduled_at=datetime.now(UTC) + timedelta(hours=1),
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
# handle_recurring_task
# ---------------------------------------------------------------------------


class TestHandleRecurringTask:
    async def test_no_repeat_returns_early(self, service, sample_task):
        sample_task.repeat = None

        await service.handle_recurring_task(sample_task, 1)

        # Should not try to reschedule
        service.arq_pool.enqueue_job.assert_not_awaited()

    async def test_no_task_id_returns_early(self, service, recurring_task):
        recurring_task.id = None

        await service.handle_recurring_task(recurring_task, 1)

        service.arq_pool.enqueue_job.assert_not_awaited()

    async def test_reschedules_when_should_continue(self, service, recurring_task):
        mock_job = MagicMock(job_id="j")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with patch(
            "app.services.scheduler_service.get_next_run_time",
            return_value=datetime.now(UTC) + timedelta(days=1),
        ):
            await service.handle_recurring_task(recurring_task, 1)

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
            return_value=datetime.now(UTC) + timedelta(days=1),
        ):
            await service.handle_recurring_task(recurring_task, 1)

        # Should still reschedule because next_run < stop_after
        status_call = service.mock_update_task_status.call_args
        assert status_call[0][1] == ScheduledTaskStatus.SCHEDULED

    async def test_extracts_timezone_from_trigger_config(self, service):
        """If task has trigger_config.timezone, use it for next_run calculation."""

        class TaskWithTriggerConfig(BaseScheduledTask):
            model_config = ConfigDict(arbitrary_types_allowed=True)
            trigger_config: MagicMock | None = None

        trigger_config = MagicMock()
        trigger_config.timezone = "America/New_York"
        task = TaskWithTriggerConfig(
            _id="task_tz",
            user_id="user1",
            repeat="0 9 * * *",
            scheduled_at=datetime.now(UTC) + timedelta(hours=1),
            status=ScheduledTaskStatus.SCHEDULED,
            trigger_config=trigger_config,
        )
        mock_job = MagicMock(job_id="j")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with patch(
            "app.services.scheduler_service.get_next_run_time",
            return_value=datetime.now(UTC) + timedelta(days=1),
        ) as mock_next_run:
            await service.handle_recurring_task(task, 1)

            mock_next_run.assert_called_once()
            call_args = mock_next_run.call_args
            # get_next_run_time now receives a Timezone value object, not a raw str.
            assert call_args[0][2].value == "America/New_York"


# ---------------------------------------------------------------------------
# _enqueue_task
# ---------------------------------------------------------------------------


class TestEnqueueTask:
    async def test_enqueue_success(self, service):
        future = datetime.now(UTC) + timedelta(hours=1)
        mock_job = MagicMock(job_id="job1")

        with patch(
            "app.services.scheduler_service.enqueue_worker_job",
            new=AsyncMock(return_value=mock_job),
        ) as mock_enqueue:
            result = await service._enqueue_task("task1", future)

        assert result is True
        mock_enqueue.assert_awaited_once_with(
            service.arq_pool,
            "test_job",
            "task1",
            _job_id=f"test_job:task1:{int(future.timestamp())}",
            _defer_until=future,
        )

    async def test_enqueue_no_pool(self, service):
        service.arq_pool = None

        result = await service._enqueue_task("task1", datetime.now(UTC))

        assert result is False

    async def test_enqueue_failed_returns_false(self, service):
        future = datetime.now(UTC) + timedelta(hours=1)
        service.arq_pool.enqueue_job = AsyncMock(return_value=None)

        result = await service._enqueue_task("task1", future)

        assert result is False

    async def test_enqueue_past_time_rescheduled(self, service):
        past = datetime.now(UTC) - timedelta(hours=1)
        mock_job = MagicMock(job_id="job1")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        result = await service._enqueue_task("task1", past)

        assert result is True
        call_args = service.arq_pool.enqueue_job.call_args
        defer_until = call_args[1]["_defer_until"]
        # Should be in the future (now + 120s buffer)
        assert defer_until > datetime.now(UTC)

    async def test_a_past_due_fire_keeps_its_own_job_key(self, service):
        """Seen live: a workflow created on a cron boundary had next_run == now.
        The enqueue shifted the fire 120 s out but keyed the ARQ job on the
        SHIFTED time while stamping the context with the armed time. Activation
        then armed the real next occurrence at that same shifted minute, and
        ARQ deduped it against the past-due job. The one job that fired carried
        the stale stamp, the claim rejected it, and the workflow never fired
        again. The job key must name the occurrence the job was armed for."""
        past = datetime.now(UTC) - timedelta(seconds=30)
        mock_job = MagicMock(job_id="job1")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        await service._enqueue_task("task1", past)

        call_args = service.arq_pool.enqueue_job.call_args
        assert call_args[1]["_job_id"] == f"test_job:task1:{int(past.timestamp())}"
        assert call_args[1]["_defer_until"] > datetime.now(UTC)

    async def test_enqueue_naive_datetime_gets_utc(self, service):
        naive_future = datetime(2099, 1, 1, 12, 0, 0)  # no tzinfo
        mock_job = MagicMock(job_id="job1")
        service.arq_pool.enqueue_job = AsyncMock(return_value=mock_job)

        result = await service._enqueue_task("task1", naive_future)

        assert result is True
        call_args = service.arq_pool.enqueue_job.call_args
        defer_until = call_args[1]["_defer_until"]
        assert defer_until.tzinfo is not None


# ---------------------------------------------------------------------------
# reap_stale_executing — exact recovery behaviour
# ---------------------------------------------------------------------------

_REAP_MSG = "Reaped task stuck in EXECUTING; reset to SCHEDULED"


def _stale(**over) -> SimpleNamespace:
    base = dict(
        id="t-rec",
        repeat="0 9 * * *",
        scheduled_at=datetime(2099, 1, 1, 9, 0, tzinfo=UTC),
        trigger_config=SimpleNamespace(next_run=None, timezone=None),
        updated_at=datetime.now(UTC) - timedelta(seconds=120),
    )
    base.update(over)
    return SimpleNamespace(**base)


class TestReapStaleExecutingExact:
    async def test_recurring_reset_reschedule_and_log(self, service):
        now_before = datetime.now(UTC)
        task = _stale(trigger_config=SimpleNamespace(next_run=None, timezone="America/New_York"))
        service.mock_find_stale_executing.return_value = [task]
        service.reschedule_task = AsyncMock()
        next_run = datetime(2099, 1, 2, 9, 0, tzinfo=UTC)
        fake_log = MagicMock()
        with (
            patch(
                "app.services.scheduler_service.get_next_run_time", return_value=next_run
            ) as gnrt,
            patch("app.services.scheduler_service.log", fake_log),
        ):
            reaped = await service.reap_stale_executing()
        now_after = datetime.now(UTC)

        assert reaped == 1
        # cutoff is now - threshold (past, never future).
        cutoff = service.mock_find_stale_executing.await_args.args[0]
        assert (
            now_before - STALE_EXECUTING_THRESHOLD - timedelta(seconds=5)
            <= cutoff
            <= now_after - STALE_EXECUTING_THRESHOLD + timedelta(seconds=5)
        )
        repeat_arg, now_arg, tz_arg = gnrt.call_args.args
        assert repeat_arg == task.repeat
        assert isinstance(now_arg, datetime)
        assert tz_arg == Timezone.parse("America/New_York")
        service.mock_update_task_status.assert_awaited_once_with(
            "t-rec",
            ScheduledTaskStatus.SCHEDULED,
            {"scheduled_at": next_run, "trigger_config.next_run": next_run},
            None,
        )
        service.reschedule_task.assert_awaited_once_with("t-rec", next_run)
        fake_log.warning.assert_called_once()
        msg = fake_log.warning.call_args.args[0]
        kw = fake_log.warning.call_args.kwargs
        assert msg == _REAP_MSG
        assert kw["task_id"] == "t-rec"
        assert kw["scheduler_class"] == "ConcreteSchedulerService"
        assert kw["next_run"] == next_run
        assert isinstance(kw["stuck_seconds"], int) and 100 <= kw["stuck_seconds"] <= 140

    async def test_one_shot_reset_to_its_original_time_without_trigger_next_run(self, service):
        task = _stale(id="t-one", repeat=None)
        service.mock_find_stale_executing.return_value = [task]
        service.reschedule_task = AsyncMock()

        assert await service.reap_stale_executing() == 1
        # No next occurrence: scheduled_at stays, and trigger_config.next_run is NOT written.
        service.mock_update_task_status.assert_awaited_once_with(
            "t-one", ScheduledTaskStatus.SCHEDULED, {"scheduled_at": task.scheduled_at}, None
        )
        service.reschedule_task.assert_awaited_once_with("t-one", task.scheduled_at)

    async def test_missing_updated_at_reports_minus_one(self, service):
        task = SimpleNamespace(
            id="t-miss",
            repeat=None,
            scheduled_at=datetime(2099, 1, 1, 9, 0, tzinfo=UTC),
            trigger_config=None,
        )
        service.mock_find_stale_executing.return_value = [task]
        service.reschedule_task = AsyncMock()
        fake_log = MagicMock()
        with patch("app.services.scheduler_service.log", fake_log):
            await service.reap_stale_executing()
        assert fake_log.warning.call_args.kwargs["stuck_seconds"] == -1

    async def test_naive_updated_at_is_normalized_not_crashed(self, service):
        # A naive updated_at must be treated as UTC; otherwise now(aware) - naive
        # raises and the reap dies before resetting the task.
        naive_120s_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=120)
        task = _stale(repeat=None, trigger_config=None, updated_at=naive_120s_ago)
        service.mock_find_stale_executing.return_value = [task]
        service.reschedule_task = AsyncMock()
        fake_log = MagicMock()
        with patch("app.services.scheduler_service.log", fake_log):
            assert await service.reap_stale_executing() == 1
        assert 100 <= fake_log.warning.call_args.kwargs["stuck_seconds"] <= 200

    async def test_a_task_without_an_id_is_skipped_but_the_scan_continues(self, service):
        no_id = _stale(id=None)
        good = _stale(id="t-good", repeat=None, trigger_config=None)
        service.mock_find_stale_executing.return_value = [no_id, good]
        service.reschedule_task = AsyncMock()

        # The id-less one is skipped (continue, not break), so the next is reaped.
        assert await service.reap_stale_executing() == 1
        service.reschedule_task.assert_awaited_once_with("t-good", good.scheduled_at)

    async def test_the_count_accumulates_across_every_reaped_task(self, service):
        service.mock_find_stale_executing.return_value = [
            _stale(id="a", repeat=None, trigger_config=None),
            _stale(id="b", repeat=None, trigger_config=None),
        ]
        service.reschedule_task = AsyncMock()
        assert await service.reap_stale_executing() == 2


# ---------------------------------------------------------------------------
# _recurrence_timezone
# ---------------------------------------------------------------------------


class TestRecurrenceTimezone:
    def test_trigger_config_timezone_wins(self):
        task = SimpleNamespace(
            trigger_config=SimpleNamespace(timezone="America/New_York"), timezone="UTC"
        )
        assert BaseSchedulerService._recurrence_timezone(task) == "America/New_York"

    def test_falls_back_to_the_task_timezone(self):
        task = SimpleNamespace(trigger_config=None, timezone="Europe/London")
        assert BaseSchedulerService._recurrence_timezone(task) == "Europe/London"


class TestProcessTaskClaim:
    async def test_a_task_claimed_by_another_run_is_skipped_with_a_warning(
        self, service, sample_task
    ):
        occurrence = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)
        service.mock_get_task.return_value = sample_task
        service.mock_claim_task.return_value = False
        fake_log = MagicMock()
        with patch("app.services.scheduler_service.log", fake_log):
            result = await service.process_task_execution("task123", expected_occurrence=occurrence)

        service.mock_claim_task.assert_awaited_once_with("task123", occurrence)
        fake_log.warning.assert_called_once_with(
            "Task already claimed by another run", task_id="task123"
        )
        assert result.success is False
