"""Unit tests for reminder scheduler service."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
import pytest

from app.models.reminder_models import (
    AgentType,
    CreateReminderRequest,
    ReminderDocument,
    ReminderModel,
    ReminderStatus,
    ReminderUpdate,
    StaticReminderPayload,
)
from app.models.scheduler_models import (
    BaseScheduledTask,
    ScheduledTaskStatus,
    TaskExecutionResult,
)
from app.services.reminder_service import ReminderScheduler

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"


@pytest.fixture
def mock_repo():
    """Patch the reminder_repository seam the scheduler delegates to. Mongo shape,
    ObjectId codec and $set/filter details are the repository's contract (proven in
    tests/contracts/test_reminders_repository.py); here we assert delegation."""
    with (
        patch(
            "app.services.reminder_service.reminder_repository.create", new_callable=AsyncMock
        ) as m_create,
        patch(
            "app.services.reminder_service.reminder_repository.update_for_user",
            new_callable=AsyncMock,
        ) as m_update,
        patch(
            "app.services.reminder_service.reminder_repository.list_for_user",
            new_callable=AsyncMock,
        ) as m_list,
        patch(
            "app.services.reminder_service.reminder_repository.get", new_callable=AsyncMock
        ) as m_get,
        patch(
            "app.services.reminder_service.reminder_repository.get_for_user",
            new_callable=AsyncMock,
        ) as m_get_for_user,
        patch(
            "app.services.reminder_service.reminder_repository.set_status", new_callable=AsyncMock
        ) as m_set_status,
    ):
        yield SimpleNamespace(
            create=m_create,
            update_for_user=m_update,
            list_for_user=m_list,
            get=m_get,
            get_for_user=m_get_for_user,
            set_status=m_set_status,
        )


def _reminder_document(**overrides) -> ReminderDocument:
    data = {
        "id": str(ObjectId()),
        "user_id": FAKE_USER_ID,
        "agent": AgentType.STATIC,
        "payload": StaticReminderPayload(title="Test Reminder", body="Don't forget!"),
        "scheduled_at": datetime.now(UTC) + timedelta(hours=1),
        "status": ScheduledTaskStatus.SCHEDULED,
    }
    data.update(overrides)
    return ReminderDocument(**data)


@pytest.fixture
def mock_scheduler_base():
    """Patch BaseSchedulerService.schedule_task and reschedule_task."""
    with (
        patch.object(ReminderScheduler, "schedule_task", new_callable=AsyncMock) as m_schedule,
        patch.object(ReminderScheduler, "reschedule_task", new_callable=AsyncMock) as m_reschedule,
    ):
        yield m_schedule, m_reschedule


@pytest.fixture
def scheduler():
    with patch("app.services.reminder_service.BaseSchedulerService.__init__"):
        s = ReminderScheduler.__new__(ReminderScheduler)
        s.redis_settings = None
        s.arq_pool = None
        return s


@pytest.fixture
def future_time():
    return datetime.now(UTC) + timedelta(hours=1)


@pytest.fixture
def sample_payload():
    return StaticReminderPayload(title="Test Reminder", body="Don't forget!")


@pytest.fixture
def sample_reminder_doc(future_time, sample_payload):
    oid = ObjectId()
    return {
        "_id": str(oid),
        "user_id": FAKE_USER_ID,
        "agent": AgentType.STATIC,
        "payload": sample_payload.model_dump(),
        "repeat": None,
        "scheduled_at": future_time,
        "status": ScheduledTaskStatus.SCHEDULED,
        "occurrence_count": 0,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


# ---------------------------------------------------------------------------
# create_reminder
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateReminder:
    async def test_creates_one_time_reminder(
        self, scheduler, mock_repo, mock_scheduler_base, future_time, sample_payload
    ):
        m_schedule, _m_reschedule = mock_scheduler_base
        oid = str(ObjectId())
        mock_repo.create.return_value = _reminder_document(id=oid)

        request = CreateReminderRequest(
            agent=AgentType.STATIC, payload=sample_payload, scheduled_at=future_time
        )

        reminder_id = await scheduler.create_reminder(request, FAKE_USER_ID)

        assert reminder_id == oid
        mock_repo.create.assert_awaited_once()
        m_schedule.assert_called_once()

    async def test_creates_recurring_reminder_with_cron(
        self, scheduler, mock_repo, mock_scheduler_base, future_time, sample_payload
    ):
        oid = str(ObjectId())
        mock_repo.create.return_value = _reminder_document(id=oid)

        request = CreateReminderRequest(
            agent=AgentType.STATIC,
            payload=sample_payload,
            scheduled_at=future_time,
            repeat="0 9 * * *",
        )

        reminder_id = await scheduler.create_reminder(request, FAKE_USER_ID)

        assert reminder_id == oid

    async def test_recurring_reminder_persists_timezone(
        self, scheduler, mock_repo, mock_scheduler_base, future_time, sample_payload
    ):
        """A recurring reminder persists its schedule timezone so the re-arm path
        (handle_recurring_task) computes the next occurrence in that zone, not UTC."""
        mock_repo.create.return_value = _reminder_document()
        request = CreateReminderRequest(
            agent=AgentType.STATIC,
            payload=sample_payload,
            scheduled_at=future_time,
            repeat="0 9 * * *",
            timezone="Asia/Kolkata",
        )

        await scheduler.create_reminder(request, FAKE_USER_ID)

        # The document handed to the repository carries the schedule timezone.
        persisted = mock_repo.create.call_args.args[0]
        assert persisted.timezone == "Asia/Kolkata"

    async def test_reminder_without_timezone_has_null_timezone(
        self, scheduler, mock_repo, mock_scheduler_base, future_time, sample_payload
    ):
        """No timezone on the request => None persisted => recurrence stays UTC."""
        mock_repo.create.return_value = _reminder_document()
        request = CreateReminderRequest(
            agent=AgentType.STATIC,
            payload=sample_payload,
            scheduled_at=future_time,
            repeat="0 9 * * *",
        )

        await scheduler.create_reminder(request, FAKE_USER_ID)

        persisted = mock_repo.create.call_args.args[0]
        assert persisted.timezone is None

    async def test_raises_when_no_scheduled_at_and_no_repeat(
        self, scheduler, mock_repo, mock_scheduler_base, sample_payload
    ):
        """When scheduled_at is None and no repeat pattern, should raise ValueError."""
        request = MagicMock(spec=CreateReminderRequest)
        request.scheduled_at = None
        request.repeat = None
        request.max_occurrences = None
        request.stop_after = None
        request.timezone = None
        request.model_dump.return_value = {
            "agent": "static",
            "payload": {"title": "Test", "body": "Body"},
            "scheduled_at": None,
            "repeat": None,
        }

        with pytest.raises(ValueError, match="scheduled_at must be provided"):
            await scheduler.create_reminder(request, FAKE_USER_ID)
        mock_repo.create.assert_not_awaited()

    async def test_uses_cron_for_scheduled_at_when_only_repeat_given(
        self, scheduler, mock_repo, mock_scheduler_base, sample_payload
    ):
        oid = str(ObjectId())
        mock_repo.create.return_value = _reminder_document(id=oid)

        future = datetime.now(UTC) + timedelta(hours=2)
        with patch("app.services.reminder_service.get_next_run_time", return_value=future):
            request = MagicMock(spec=CreateReminderRequest)
            request.scheduled_at = None
            request.repeat = "0 9 * * *"
            request.max_occurrences = None
            request.stop_after = None
            request.timezone = None
            request.model_dump.return_value = {
                "agent": "static",
                "payload": {"title": "Test", "body": "Body"},
                "scheduled_at": future,
                "repeat": "0 9 * * *",
            }

            reminder_id = await scheduler.create_reminder(request, FAKE_USER_ID)

        assert reminder_id == oid


# ---------------------------------------------------------------------------
# update_reminder
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateReminder:
    async def test_updates_reminder_successfully(self, scheduler, mock_repo, mock_scheduler_base):
        mock_repo.update_for_user.return_value = _reminder_document()

        result = await scheduler.update_reminder(
            str(ObjectId()), ReminderUpdate(status=ReminderStatus.SCHEDULED), FAKE_USER_ID
        )

        assert result is True

    async def test_returns_false_when_not_found(self, scheduler, mock_repo, mock_scheduler_base):
        mock_repo.update_for_user.return_value = None

        result = await scheduler.update_reminder(
            str(ObjectId()), ReminderUpdate(status=ReminderStatus.COMPLETED), FAKE_USER_ID
        )

        assert result is False

    async def test_reschedules_when_scheduled_at_and_status_updated(
        self, scheduler, mock_repo, mock_scheduler_base
    ):
        _, m_reschedule = mock_scheduler_base
        mock_repo.update_for_user.return_value = _reminder_document()

        future = datetime.now(UTC) + timedelta(hours=2)
        update = ReminderUpdate(scheduled_at=future, status=ReminderStatus.SCHEDULED)

        result = await scheduler.update_reminder(str(ObjectId()), update, FAKE_USER_ID)

        assert result is True
        m_reschedule.assert_called_once()

    async def test_does_not_reschedule_if_only_scheduled_at(
        self, scheduler, mock_repo, mock_scheduler_base
    ):
        """Rescheduling only happens when BOTH scheduled_at and status are in update_data."""
        _, m_reschedule = mock_scheduler_base
        mock_repo.update_for_user.return_value = _reminder_document()

        future = datetime.now(UTC) + timedelta(hours=2)

        await scheduler.update_reminder(
            str(ObjectId()), ReminderUpdate(scheduled_at=future), FAKE_USER_ID
        )

        m_reschedule.assert_not_called()

    async def test_delegates_with_owner_and_typed_update(
        self, scheduler, mock_repo, mock_scheduler_base
    ):
        mock_repo.update_for_user.return_value = _reminder_document()

        oid = str(ObjectId())
        await scheduler.update_reminder(
            oid, ReminderUpdate(status=ReminderStatus.SCHEDULED), FAKE_USER_ID
        )

        args = mock_repo.update_for_user.call_args.args
        assert args[0] == oid and args[1] == FAKE_USER_ID
        assert args[2].status == ReminderStatus.SCHEDULED  # ReminderUpdate


# ---------------------------------------------------------------------------
# list_user_reminders
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListUserReminders:
    async def test_lists_all_reminders_for_user(self, scheduler, mock_repo):
        mock_repo.list_for_user.return_value = [_reminder_document()]

        result = await scheduler.list_user_reminders(FAKE_USER_ID)

        assert len(result) == 1
        assert isinstance(result[0], ReminderModel)

    async def test_delegates_status_skip_and_limit(self, scheduler, mock_repo):
        mock_repo.list_for_user.return_value = []

        await scheduler.list_user_reminders(
            FAKE_USER_ID, status=ReminderStatus.SCHEDULED, limit=10, skip=5
        )

        kwargs = mock_repo.list_for_user.call_args.kwargs
        assert mock_repo.list_for_user.call_args.args[0] == FAKE_USER_ID
        assert kwargs == {"status": ReminderStatus.SCHEDULED, "limit": 10, "skip": 5}

    async def test_returns_empty_list_when_no_reminders(self, scheduler, mock_repo):
        mock_repo.list_for_user.return_value = []

        result = await scheduler.list_user_reminders(FAKE_USER_ID)

        assert result == []


# ---------------------------------------------------------------------------
# get_reminder / get_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetReminder:
    async def test_get_task_without_user_uses_global_get(self, scheduler, mock_repo):
        doc = _reminder_document()
        mock_repo.get.return_value = doc

        result = await scheduler.get_task(doc.id)

        assert isinstance(result, ReminderModel)
        mock_repo.get.assert_awaited_once_with(doc.id)
        mock_repo.get_for_user.assert_not_awaited()

    async def test_get_task_returns_none_when_not_found(self, scheduler, mock_repo):
        mock_repo.get.return_value = None

        result = await scheduler.get_task(str(ObjectId()))

        assert result is None

    async def test_get_task_with_user_id_uses_owner_scoped_get(self, scheduler, mock_repo):
        mock_repo.get_for_user.return_value = None

        oid = str(ObjectId())
        await scheduler.get_task(oid, user_id=FAKE_USER_ID)

        mock_repo.get_for_user.assert_awaited_once_with(oid, FAKE_USER_ID)
        mock_repo.get.assert_not_awaited()

    async def test_get_reminder_returns_none_for_non_reminder(self, scheduler):
        """get_reminder returns None when get_task returns a non-ReminderModel."""
        with patch.object(scheduler, "get_task", new_callable=AsyncMock) as m:
            m.return_value = "not a ReminderModel"
            result = await scheduler.get_reminder(str(ObjectId()))

        assert result is None

    async def test_get_reminder_returns_model_when_valid(self, scheduler):
        reminder = _reminder_document()
        with patch.object(scheduler, "get_task", new_callable=AsyncMock) as m:
            m.return_value = reminder
            result = await scheduler.get_reminder(str(ObjectId()))

        assert result is reminder


# ---------------------------------------------------------------------------
# execute_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteTask:
    async def test_executes_reminder_successfully(self, scheduler, sample_reminder_doc):
        reminder = ReminderModel(**sample_reminder_doc)

        with patch(
            "app.tasks.reminder_tasks.execute_reminder_by_agent",
            new_callable=AsyncMock,
        ):
            result = await scheduler.execute_task(reminder)

        assert isinstance(result, TaskExecutionResult)
        assert result.success is True

    async def test_returns_failure_for_non_reminder_task(self, scheduler):
        mock_task = MagicMock(spec=BaseScheduledTask)
        mock_task.__class__ = BaseScheduledTask

        result = await scheduler.execute_task(mock_task)

        assert result.success is False
        assert "not a ReminderModel" in (result.message or "")

    async def test_returns_failure_on_execution_error(self, scheduler, sample_reminder_doc):
        reminder = ReminderModel(**sample_reminder_doc)

        with patch(
            "app.tasks.reminder_tasks.execute_reminder_by_agent",
            new_callable=AsyncMock,
            side_effect=Exception("agent crashed"),
        ):
            result = await scheduler.execute_task(reminder)

        assert result.success is False
        assert "agent crashed" in (result.message or "")


# ---------------------------------------------------------------------------
# update_task_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateTaskStatus:
    async def test_threads_status_and_rearm_fields(self, scheduler, mock_repo):
        mock_repo.set_status.return_value = True

        oid = str(ObjectId())
        result = await scheduler.update_task_status(
            oid, ScheduledTaskStatus.COMPLETED, {"occurrence_count": 5}
        )

        assert result is True
        kwargs = mock_repo.set_status.call_args.kwargs
        assert mock_repo.set_status.call_args.args == (oid, ScheduledTaskStatus.COMPLETED)
        assert kwargs["occurrence_count"] == 5

    async def test_no_extra_data_passes_none(self, scheduler, mock_repo):
        mock_repo.set_status.return_value = True

        await scheduler.update_task_status(str(ObjectId()), ScheduledTaskStatus.EXECUTING)

        kwargs = mock_repo.set_status.call_args.kwargs
        assert kwargs["occurrence_count"] is None and kwargs["scheduled_at"] is None

    async def test_returns_false_when_not_matched(self, scheduler, mock_repo):
        mock_repo.set_status.return_value = False

        result = await scheduler.update_task_status(str(ObjectId()), ScheduledTaskStatus.FAILED)

        assert result is False

    async def test_passes_user_id_guard_when_provided(self, scheduler, mock_repo):
        mock_repo.set_status.return_value = True

        oid = str(ObjectId())
        await scheduler.update_task_status(oid, ScheduledTaskStatus.CANCELLED, user_id=FAKE_USER_ID)

        assert mock_repo.set_status.call_args.kwargs["user_id"] == FAKE_USER_ID


# ---------------------------------------------------------------------------
# get_pending_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPendingTask:
    """The due-scan (and its ObjectId->string mapping) now lives on
    ``reminder_repository.find_pending_before`` — contract-tested against real Mongo
    in tests/contracts/test_reminders_repository.py. Here we verify the scheduler
    delegates to it and passes the scan time through."""

    async def test_returns_pending_reminders(self, scheduler, future_time, sample_payload):
        reminder = ReminderModel(
            user_id=FAKE_USER_ID,
            agent=AgentType.STATIC,
            payload=sample_payload,
            scheduled_at=future_time,
        )
        with patch(
            "app.services.reminder_service.reminder_repository.find_pending_before",
            AsyncMock(return_value=[reminder]),
        ):
            result = await scheduler.get_pending_task(datetime.now(UTC))

        assert len(result) == 1
        assert isinstance(result[0], ReminderModel)

    async def test_returns_empty_when_no_pending(self, scheduler):
        with patch(
            "app.services.reminder_service.reminder_repository.find_pending_before",
            AsyncMock(return_value=[]),
        ):
            result = await scheduler.get_pending_task(datetime.now(UTC))

        assert result == []

    async def test_passes_scan_time_to_repository(self, scheduler):
        find_pending = AsyncMock(return_value=[])
        with patch(
            "app.services.reminder_service.reminder_repository.find_pending_before",
            find_pending,
        ):
            now = datetime.now(UTC)
            await scheduler.get_pending_task(now)

        find_pending.assert_awaited_once_with(now)


# ---------------------------------------------------------------------------
# misc
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestJobName:
    def test_get_job_name(self, scheduler):
        assert scheduler.get_job_name() == "process_reminder"
