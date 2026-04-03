"""Unit tests for reminder scheduler service."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId

from app.models.reminder_models import (
    AgentType,
    CreateReminderRequest,
    ReminderModel,
    ReminderStatus,
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


class _AsyncCursorMock:
    """Mock for MongoDB async cursor that supports async iteration."""

    def __init__(self, documents: list) -> None:
        self._documents = documents
        self._index = 0

    def __aiter__(self):
        self._index = 0
        return self

    async def __anext__(self):
        if self._index >= len(self._documents):
            raise StopAsyncIteration
        doc = self._documents[self._index]
        self._index += 1
        return doc


@pytest.fixture
def mock_reminders_collection():
    with patch("app.services.reminder_service.reminders_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_scheduler_base():
    """Patch BaseSchedulerService.schedule_task and reschedule_task."""
    with (
        patch.object(
            ReminderScheduler, "schedule_task", new_callable=AsyncMock
        ) as m_schedule,
        patch.object(
            ReminderScheduler, "reschedule_task", new_callable=AsyncMock
        ) as m_reschedule,
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
    return datetime.now(timezone.utc) + timedelta(hours=1)


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
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


# ---------------------------------------------------------------------------
# create_reminder
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateReminder:
    async def test_creates_one_time_reminder(
        self,
        scheduler,
        mock_reminders_collection,
        mock_scheduler_base,
        future_time,
        sample_payload,
    ):
        m_schedule, _m_reschedule = mock_scheduler_base
        oid = ObjectId()
        insert_result = MagicMock(inserted_id=oid)
        mock_reminders_collection.insert_one = AsyncMock(return_value=insert_result)

        request = CreateReminderRequest(
            agent=AgentType.STATIC,
            payload=sample_payload,
            scheduled_at=future_time,
        )

        reminder_id = await scheduler.create_reminder(request, FAKE_USER_ID)

        assert reminder_id == str(oid)
        mock_reminders_collection.insert_one.assert_called_once()
        m_schedule.assert_called_once()

    async def test_creates_recurring_reminder_with_cron(
        self,
        scheduler,
        mock_reminders_collection,
        mock_scheduler_base,
        future_time,
        sample_payload,
    ):
        m_schedule, _ = mock_scheduler_base
        oid = ObjectId()
        insert_result = MagicMock(inserted_id=oid)
        mock_reminders_collection.insert_one = AsyncMock(return_value=insert_result)

        request = CreateReminderRequest(
            agent=AgentType.STATIC,
            payload=sample_payload,
            scheduled_at=future_time,
            repeat="0 9 * * *",
        )

        reminder_id = await scheduler.create_reminder(request, FAKE_USER_ID)

        assert reminder_id == str(oid)

    async def test_raises_when_no_scheduled_at_and_no_repeat(
        self,
        scheduler,
        mock_reminders_collection,
        mock_scheduler_base,
        sample_payload,
    ):
        """When scheduled_at is None and no repeat pattern, should raise ValueError."""
        m_schedule, _ = mock_scheduler_base
        oid = ObjectId()
        insert_result = MagicMock(inserted_id=oid)
        mock_reminders_collection.insert_one = AsyncMock(return_value=insert_result)

        # Build a request manually bypassing validator (scheduled_at=None, repeat=None)
        request = MagicMock(spec=CreateReminderRequest)
        request.scheduled_at = None
        request.repeat = None
        request.max_occurrences = None
        request.stop_after = None
        request.base_time = None
        request.model_dump.return_value = {
            "agent": "static",
            "payload": {"title": "Test", "body": "Body"},
            "scheduled_at": None,
            "repeat": None,
        }

        with pytest.raises(ValueError, match="scheduled_at must be provided"):
            await scheduler.create_reminder(request, FAKE_USER_ID)

    async def test_uses_cron_for_scheduled_at_when_only_repeat_given(
        self,
        scheduler,
        mock_reminders_collection,
        mock_scheduler_base,
        sample_payload,
    ):
        m_schedule, _ = mock_scheduler_base
        oid = ObjectId()
        insert_result = MagicMock(inserted_id=oid)
        mock_reminders_collection.insert_one = AsyncMock(return_value=insert_result)

        future = datetime.now(timezone.utc) + timedelta(hours=2)
        with patch(
            "app.services.reminder_service.get_next_run_time", return_value=future
        ):
            request = MagicMock(spec=CreateReminderRequest)
            request.scheduled_at = None
            request.repeat = "0 9 * * *"
            request.max_occurrences = None
            request.stop_after = None
            request.base_time = None
            request.model_dump.return_value = {
                "agent": "static",
                "payload": {"title": "Test", "body": "Body"},
                "scheduled_at": future,
                "repeat": "0 9 * * *",
            }

            reminder_id = await scheduler.create_reminder(request, FAKE_USER_ID)

        assert reminder_id == str(oid)


# ---------------------------------------------------------------------------
# update_reminder
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateReminder:
    async def test_updates_reminder_successfully(
        self, scheduler, mock_reminders_collection, mock_scheduler_base
    ):
        update_result = MagicMock(modified_count=1)
        mock_reminders_collection.update_one = AsyncMock(return_value=update_result)

        result = await scheduler.update_reminder(
            str(ObjectId()), {"status": "scheduled"}, FAKE_USER_ID
        )

        assert result is True

    async def test_returns_false_when_not_modified(
        self, scheduler, mock_reminders_collection, mock_scheduler_base
    ):
        update_result = MagicMock(modified_count=0)
        mock_reminders_collection.update_one = AsyncMock(return_value=update_result)

        result = await scheduler.update_reminder(
            str(ObjectId()), {"status": "completed"}, FAKE_USER_ID
        )

        assert result is False

    async def test_reschedules_when_scheduled_at_and_status_updated(
        self, scheduler, mock_reminders_collection, mock_scheduler_base
    ):
        _, m_reschedule = mock_scheduler_base
        update_result = MagicMock(modified_count=1)
        mock_reminders_collection.update_one = AsyncMock(return_value=update_result)

        future_iso = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        update_data = {
            "scheduled_at": future_iso,
            "status": ReminderStatus.SCHEDULED,
        }

        result = await scheduler.update_reminder(
            str(ObjectId()), update_data, FAKE_USER_ID
        )

        assert result is True
        m_reschedule.assert_called_once()

    async def test_does_not_reschedule_if_only_scheduled_at(
        self, scheduler, mock_reminders_collection, mock_scheduler_base
    ):
        """Rescheduling only happens when BOTH scheduled_at and status are in update_data."""
        _, m_reschedule = mock_scheduler_base
        update_result = MagicMock(modified_count=1)
        mock_reminders_collection.update_one = AsyncMock(return_value=update_result)

        future_iso = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        update_data = {"scheduled_at": future_iso}

        await scheduler.update_reminder(str(ObjectId()), update_data, FAKE_USER_ID)

        m_reschedule.assert_not_called()

    async def test_filter_includes_user_id(
        self, scheduler, mock_reminders_collection, mock_scheduler_base
    ):
        update_result = MagicMock(modified_count=1)
        mock_reminders_collection.update_one = AsyncMock(return_value=update_result)

        oid = str(ObjectId())
        await scheduler.update_reminder(oid, {"status": "scheduled"}, FAKE_USER_ID)

        call_args = mock_reminders_collection.update_one.call_args
        filters = call_args[0][0]
        assert filters["user_id"] == FAKE_USER_ID

    async def test_filter_excludes_user_id_when_empty(
        self, scheduler, mock_reminders_collection, mock_scheduler_base
    ):
        update_result = MagicMock(modified_count=1)
        mock_reminders_collection.update_one = AsyncMock(return_value=update_result)

        oid = str(ObjectId())
        await scheduler.update_reminder(oid, {"status": "scheduled"}, "")

        call_args = mock_reminders_collection.update_one.call_args
        filters = call_args[0][0]
        assert "user_id" not in filters


# ---------------------------------------------------------------------------
# list_user_reminders
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListUserReminders:
    async def test_lists_all_reminders_for_user(
        self, scheduler, mock_reminders_collection, sample_reminder_doc
    ):
        cursor = MagicMock()
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.to_list = AsyncMock(return_value=[sample_reminder_doc])
        mock_reminders_collection.find.return_value = cursor

        result = await scheduler.list_user_reminders(FAKE_USER_ID)

        assert len(result) == 1
        assert isinstance(result[0], ReminderModel)

    async def test_filters_by_status(
        self, scheduler, mock_reminders_collection, sample_reminder_doc
    ):
        cursor = MagicMock()
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.to_list = AsyncMock(return_value=[sample_reminder_doc])
        mock_reminders_collection.find.return_value = cursor

        await scheduler.list_user_reminders(
            FAKE_USER_ID, status=ReminderStatus.SCHEDULED
        )

        call_args = mock_reminders_collection.find.call_args[0][0]
        assert call_args["status"] == ReminderStatus.SCHEDULED

    async def test_applies_skip_and_limit(self, scheduler, mock_reminders_collection):
        cursor = MagicMock()
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.to_list = AsyncMock(return_value=[])
        mock_reminders_collection.find.return_value = cursor

        await scheduler.list_user_reminders(FAKE_USER_ID, limit=10, skip=5)

        cursor.skip.assert_called_once_with(5)
        cursor.limit.assert_called_once_with(10)

    async def test_returns_empty_list_when_no_reminders(
        self, scheduler, mock_reminders_collection
    ):
        cursor = MagicMock()
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.to_list = AsyncMock(return_value=[])
        mock_reminders_collection.find.return_value = cursor

        result = await scheduler.list_user_reminders(FAKE_USER_ID)

        assert result == []


# ---------------------------------------------------------------------------
# get_reminder / get_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetReminder:
    async def test_get_task_returns_reminder_model(
        self, scheduler, mock_reminders_collection, sample_reminder_doc
    ):
        mock_reminders_collection.find_one = AsyncMock(return_value=sample_reminder_doc)

        result = await scheduler.get_task(sample_reminder_doc["_id"])

        assert isinstance(result, ReminderModel)

    async def test_get_task_returns_none_when_not_found(
        self, scheduler, mock_reminders_collection
    ):
        mock_reminders_collection.find_one = AsyncMock(return_value=None)

        result = await scheduler.get_task(str(ObjectId()))

        assert result is None

    async def test_get_task_with_user_id_filter(
        self, scheduler, mock_reminders_collection
    ):
        mock_reminders_collection.find_one = AsyncMock(return_value=None)

        await scheduler.get_task(str(ObjectId()), user_id=FAKE_USER_ID)

        call_args = mock_reminders_collection.find_one.call_args[0][0]
        assert call_args["user_id"] == FAKE_USER_ID

    async def test_get_reminder_returns_none_for_non_reminder(
        self, scheduler, mock_reminders_collection
    ):
        """get_reminder returns None when get_task returns a non-ReminderModel."""
        with patch.object(scheduler, "get_task", new_callable=AsyncMock) as m:
            m.return_value = "not a ReminderModel"
            result = await scheduler.get_reminder(str(ObjectId()))

        assert result is None

    async def test_get_reminder_returns_model_when_valid(
        self, scheduler, mock_reminders_collection, sample_reminder_doc
    ):
        reminder = ReminderModel(**sample_reminder_doc)
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

    async def test_returns_failure_on_execution_error(
        self, scheduler, sample_reminder_doc
    ):
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
    async def test_updates_status_with_additional_data(
        self, scheduler, mock_reminders_collection
    ):
        update_result = MagicMock(modified_count=1)
        mock_reminders_collection.update_one = AsyncMock(return_value=update_result)

        oid = str(ObjectId())
        result = await scheduler.update_task_status(
            oid,
            ScheduledTaskStatus.COMPLETED,
            {"occurrence_count": 5},
        )

        assert result is True
        call_args = mock_reminders_collection.update_one.call_args
        update_fields = call_args[0][1]["$set"]
        assert update_fields["status"] == ScheduledTaskStatus.COMPLETED
        assert update_fields["occurrence_count"] == 5

    async def test_adds_updated_at_when_missing(
        self, scheduler, mock_reminders_collection
    ):
        update_result = MagicMock(modified_count=1)
        mock_reminders_collection.update_one = AsyncMock(return_value=update_result)

        oid = str(ObjectId())
        await scheduler.update_task_status(oid, ScheduledTaskStatus.EXECUTING)

        call_args = mock_reminders_collection.update_one.call_args
        update_fields = call_args[0][1]["$set"]
        assert "updated_at" in update_fields

    async def test_returns_false_when_not_modified(
        self, scheduler, mock_reminders_collection
    ):
        update_result = MagicMock(modified_count=0)
        mock_reminders_collection.update_one = AsyncMock(return_value=update_result)

        result = await scheduler.update_task_status(
            str(ObjectId()), ScheduledTaskStatus.FAILED
        )

        assert result is False

    async def test_includes_user_id_filter_when_provided(
        self, scheduler, mock_reminders_collection
    ):
        update_result = MagicMock(modified_count=1)
        mock_reminders_collection.update_one = AsyncMock(return_value=update_result)

        oid = str(ObjectId())
        await scheduler.update_task_status(
            oid, ScheduledTaskStatus.CANCELLED, user_id=FAKE_USER_ID
        )

        call_args = mock_reminders_collection.update_one.call_args
        filters = call_args[0][0]
        assert filters["user_id"] == FAKE_USER_ID


# ---------------------------------------------------------------------------
# get_pending_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPendingTask:
    async def test_returns_pending_reminders(
        self, scheduler, mock_reminders_collection, sample_reminder_doc
    ):
        mock_reminders_collection.find.return_value = _AsyncCursorMock(
            [sample_reminder_doc]
        )

        now = datetime.now(timezone.utc)
        result = await scheduler.get_pending_task(now)

        assert len(result) == 1
        assert isinstance(result[0], ReminderModel)

    async def test_returns_empty_when_no_pending(
        self, scheduler, mock_reminders_collection
    ):
        mock_reminders_collection.find.return_value = _AsyncCursorMock([])

        now = datetime.now(timezone.utc)
        result = await scheduler.get_pending_task(now)

        assert result == []

    async def test_converts_objectid_to_string(
        self, scheduler, mock_reminders_collection, sample_reminder_doc
    ):
        oid = ObjectId()
        doc = {**sample_reminder_doc, "_id": oid}

        mock_reminders_collection.find.return_value = _AsyncCursorMock([doc])

        now = datetime.now(timezone.utc)
        result = await scheduler.get_pending_task(now)

        assert result[0].id == str(oid)


# ---------------------------------------------------------------------------
# _serialize_reminder
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSerializeReminder:
    def test_removes_none_id(self, scheduler, future_time, sample_payload):
        reminder = ReminderModel(
            user_id=FAKE_USER_ID,
            agent=AgentType.STATIC,
            payload=sample_payload,
            scheduled_at=future_time,
        )
        serialized = scheduler._serialize_reminder(reminder)

        assert "_id" not in serialized

    def test_preserves_existing_id(self, scheduler, future_time, sample_payload):
        reminder = ReminderModel(
            _id="existing_id",
            user_id=FAKE_USER_ID,
            agent=AgentType.STATIC,
            payload=sample_payload,
            scheduled_at=future_time,
        )
        serialized = scheduler._serialize_reminder(reminder)

        assert serialized["_id"] == "existing_id"

    def test_get_job_name(self, scheduler):
        assert scheduler.get_job_name() == "process_reminder"
