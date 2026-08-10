"""Unit tests for the reminders API endpoints.

Tests cover CRUD operations on reminders (create, get, update, delete, list)
plus pause/resume and cron validation. The reminder_scheduler service is mocked;
the endpoint's own logic — status codes, response shapes, exact service-call
args, timezone injection, and error handling — is asserted precisely.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, HTTPException
from httpx import AsyncClient
import pytest

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.endpoints.reminders import _reminder_context, create_reminder_endpoint
from app.constants.log_tags import LogTag
from app.models.reminder_models import CreateReminderRequest, ReminderStatus, ReminderUpdate
from tests.conftest import FAKE_USER

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

API = "/api/v1/reminders"
USER_ID = FAKE_USER["user_id"]
NOW = datetime.now(UTC)
FUTURE = NOW + timedelta(days=1)
NEXT_RUN = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def _reminder_model(
    reminder_id: str = "rem_1",
    status: str = "scheduled",
    repeat: str | None = None,
) -> MagicMock:
    """Return a mock that quacks like a ReminderModel from the scheduler."""
    m = MagicMock()
    m.id = reminder_id
    m.user_id = USER_ID
    m.agent = "static"
    m.repeat = repeat
    m.scheduled_at = FUTURE
    m.status = status
    m.occurrence_count = 0
    m.max_occurrences = None
    m.stop_after = None
    m.payload = {"title": "Test", "body": "Test body"}
    m.created_at = NOW
    m.updated_at = NOW
    m.model_dump.return_value = {
        "id": reminder_id,
        "user_id": USER_ID,
        "agent": "static",
        "repeat": repeat,
        "scheduled_at": FUTURE,
        "status": status,
        "occurrence_count": 0,
        "max_occurrences": None,
        "stop_after": None,
        "payload": {"title": "Test", "body": "Test body"},
        "created_at": NOW,
        "updated_at": NOW,
    }
    return m


def _expected_body(
    reminder_id: str = "rem_1",
    status: str = "scheduled",
    repeat: str | None = None,
) -> dict:
    """The exact serialized ReminderResponse body the endpoints must return."""
    return {
        "id": reminder_id,
        "user_id": USER_ID,
        "agent": "static",
        "repeat": repeat,
        "scheduled_at": FUTURE.isoformat(),
        "status": status,
        "occurrence_count": 0,
        "max_occurrences": None,
        "stop_after": None,
        "payload": {"title": "Test", "body": "Test body"},
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }


def _create_payload(scheduled_at: str | None = None) -> dict:
    """Build a valid CreateReminderRequest body."""
    at = scheduled_at or (NOW + timedelta(hours=1)).isoformat()
    return {
        "agent": "static",
        "scheduled_at": at,
        "payload": {"title": "Water plants", "body": "Don't forget"},
    }


def _endpoint_error_logs(log_error: MagicMock, message: str) -> list:
    """Calls to log.error originating from the endpoint under test.

    The app's exception-handler middleware also logs ``http_exception``
    through the same singleton, so filter for the endpoint's own message.
    """
    return [call for call in log_error.call_args_list if call.args and call.args[0] == message]


@pytest.fixture
def client_without_user_id(client: AsyncClient, test_app: FastAPI) -> AsyncClient:
    """Client whose principal dict has no user_id, exercising the 401 path.

    The endpoint (not just the auth dependency) must reject a user dict
    without a user_id.
    """
    original = test_app.dependency_overrides.get(get_current_user)
    test_app.dependency_overrides[get_current_user] = lambda: {"email": "nobody@example.com"}
    yield client
    if original is None:
        test_app.dependency_overrides.pop(get_current_user, None)
    else:
        test_app.dependency_overrides[get_current_user] = original


# ===========================================================================
# _reminder_context — wide-event context builder
# ===========================================================================


class TestReminderContext:
    """_reminder_context: wide-event fields from a reminder's real attributes."""

    def test_recurrence_and_next_run_time(self) -> None:
        reminder = _reminder_model(repeat="0 9 * * *")

        context = _reminder_context("create", reminder)

        assert context == {
            "operation": "create",
            "id": "rem_1",
            "recurrence": "0 9 * * *",
            "next_run_time": FUTURE.isoformat(),
        }

    def test_omits_recurrence_when_not_repeating(self) -> None:
        reminder = _reminder_model(repeat=None)

        context = _reminder_context("update", reminder)

        assert context == {
            "operation": "update",
            "id": "rem_1",
            "next_run_time": FUTURE.isoformat(),
        }

    def test_omits_next_run_time_when_unscheduled(self) -> None:
        reminder = _reminder_model()
        reminder.scheduled_at = None

        context = _reminder_context("get", reminder)

        assert context == {"operation": "get", "id": "rem_1"}

    def test_coerces_non_string_id(self) -> None:
        reminder = _reminder_model()
        reminder.id = 42

        context = _reminder_context("delete", reminder)

        assert context["id"] == "42"


# ===========================================================================
# POST /api/v1/reminders  -- create reminder
# ===========================================================================


class TestCreateReminder:
    """POST /api/v1/reminders"""

    async def test_create_reminder_success(self, client: AsyncClient) -> None:
        mock_reminder = _reminder_model("rem_new")
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.create_reminder",
                new_callable=AsyncMock,
                return_value="rem_new",
            ) as create_reminder,
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
                new_callable=AsyncMock,
                return_value=mock_reminder,
            ) as get_reminder,
            patch("app.api.v1.endpoints.reminders.log.set") as log_set,
        ):
            resp = await client.post(API, json=_create_payload())

        assert resp.status_code == 201
        assert resp.json() == _expected_body("rem_new")

        # The request's timezone is injected from the user's resolved home zone
        # before the scheduler is called (UTC for the FAKE_USER profile).
        create_call = create_reminder.await_args
        assert create_call is not None
        assert create_call.kwargs["user_id"] == USER_ID
        reminder_data = create_call.kwargs["reminder_data"]
        assert isinstance(reminder_data, CreateReminderRequest)
        assert reminder_data.timezone == "UTC"

        get_reminder.assert_awaited_once_with("rem_new", user_id=USER_ID)

        log_set.assert_any_call(user={"id": USER_ID}, reminder={"operation": "create"})
        log_set.assert_any_call(
            reminder={
                "operation": "create",
                "id": "rem_new",
                "next_run_time": FUTURE.isoformat(),
            }
        )
        log_set.assert_any_call(outcome="success")

    async def test_create_reminder_retrieve_failure(self, client: AsyncClient) -> None:
        """Created but not retrievable is a distinct 500 — not the generic one."""
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.create_reminder",
                new_callable=AsyncMock,
                return_value="rem_new",
            ),
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = await client.post(API, json=_create_payload())

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to retrieve created reminder"

    async def test_create_reminder_service_error(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.create_reminder",
                new_callable=AsyncMock,
                side_effect=Exception("DB down"),
            ),
            patch("app.api.v1.endpoints.reminders.log.error") as log_error,
        ):
            resp = await client.post(API, json=_create_payload())
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to create reminder"
        log_error.assert_any_call(
            f"{LogTag.API} Error creating reminder",
            user_id=USER_ID,
            error_type="Exception",
            error="DB down",
        )

    async def test_create_reminder_missing_user_id(
        self, client: AsyncClient, test_app: FastAPI
    ) -> None:
        """A principal without user_id is rejected 401 before the body runs.

        For the create route the tiered_rate_limit decorator fires first with
        its own message; the endpoint-level guard is exercised via the other
        endpoints (no rate-limit decorator there).
        """
        original = test_app.dependency_overrides.get(get_current_user)
        test_app.dependency_overrides[get_current_user] = lambda: {"email": "nobody@example.com"}
        try:
            resp = await client.post(API, json=_create_payload())
        finally:
            if original is None:
                test_app.dependency_overrides.pop(get_current_user, None)
            else:
                test_app.dependency_overrides[get_current_user] = original
        assert resp.status_code == 401
        assert resp.json()["detail"] == "User ID not found"

    async def test_create_reminder_endpoint_guard_direct(self) -> None:
        """The endpoint's own 401 guard fires when the rate-limit wrapper is bypassed.

        Through the router, tiered_rate_limit intercepts the missing-user-id
        case before the endpoint runs ("User ID not found"), so the endpoint
        guard — exact status 401 and "User not authenticated" detail — is only
        reachable by invoking the raw function (``__wrapped__`` behind the
        ``@wraps`` seam of the rate-limit decorator). Pin it here so a
        weakened guard (dropped detail arg, wrong status, mangled message)
        cannot slip through.
        """
        with pytest.raises(HTTPException) as exc_info:
            await create_reminder_endpoint.__wrapped__(
                reminder_data=CreateReminderRequest(**_create_payload()),
                user_timezone="UTC",
                user={"email": "nobody@example.com"},
            )

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "User not authenticated"

    async def test_create_reminder_validation_missing_payload(self, client: AsyncClient) -> None:
        resp = await client.post(API, json={"agent": "static"})
        assert resp.status_code == 422

    async def test_create_reminder_validation_missing_agent(self, client: AsyncClient) -> None:
        resp = await client.post(API, json={"payload": {"title": "X", "body": "Y"}})
        assert resp.status_code == 422

    async def test_create_reminder_validation_invalid_cron(self, client: AsyncClient) -> None:
        resp = await client.post(API, json={**_create_payload(), "repeat": "not-a-cron"})
        assert resp.status_code == 422

    async def test_create_reminder_validation_scheduled_at_in_past(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            API, json={**_create_payload(), "scheduled_at": (NOW - timedelta(days=1)).isoformat()}
        )
        assert resp.status_code == 422

    async def test_create_reminder_validation_max_occurrences_zero(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(API, json={**_create_payload(), "max_occurrences": 0})
        assert resp.status_code == 422

    async def test_create_reminder_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(API, json=_create_payload())
        assert resp.status_code == 401


# ===========================================================================
# GET /api/v1/reminders/{reminder_id}  -- get reminder
# ===========================================================================


class TestGetReminder:
    """GET /api/v1/reminders/{reminder_id}"""

    async def test_get_reminder_success(self, client: AsyncClient) -> None:
        mock_reminder = _reminder_model("rem_1")
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
                new_callable=AsyncMock,
                return_value=mock_reminder,
            ) as get_reminder,
            patch("app.api.v1.endpoints.reminders.log.set") as log_set,
        ):
            resp = await client.get(f"{API}/rem_1")

        assert resp.status_code == 200
        assert resp.json() == _expected_body("rem_1")
        get_reminder.assert_awaited_once_with("rem_1", user_id=USER_ID)
        log_set.assert_any_call(user={"id": USER_ID}, reminder={"operation": "get", "id": "rem_1"})
        log_set.assert_any_call(
            reminder={
                "operation": "get",
                "id": "rem_1",
                "next_run_time": FUTURE.isoformat(),
            }
        )
        log_set.assert_any_call(outcome="success")

    async def test_get_reminder_not_found(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.get(f"{API}/nonexistent")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Reminder nonexistent not found"

    async def test_get_reminder_service_error(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
                new_callable=AsyncMock,
                side_effect=Exception("DB down"),
            ),
            patch("app.api.v1.endpoints.reminders.log.error") as log_error,
        ):
            resp = await client.get(f"{API}/rem_1")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to retrieve reminder"
        log_error.assert_any_call(
            f"{LogTag.API} Error getting reminder",
            reminder_id="rem_1",
            user_id=USER_ID,
            error_type="Exception",
            error="DB down",
        )

    async def test_get_reminder_missing_user_id(self, client_without_user_id: AsyncClient) -> None:
        resp = await client_without_user_id.get(f"{API}/rem_1")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "User not authenticated"

    async def test_get_reminder_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/rem_1")
        assert resp.status_code == 401


# ===========================================================================
# PUT /api/v1/reminders/{reminder_id}  -- update reminder
# ===========================================================================


class TestUpdateReminder:
    """PUT /api/v1/reminders/{reminder_id}"""

    async def test_update_reminder_success(self, client: AsyncClient) -> None:
        mock_reminder = _reminder_model("rem_1")
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.update_reminder",
                new_callable=AsyncMock,
                return_value=True,
            ) as update_reminder,
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
                new_callable=AsyncMock,
                return_value=mock_reminder,
            ) as get_reminder,
            patch("app.api.v1.endpoints.reminders.log.set") as log_set,
        ):
            resp = await client.put(
                f"{API}/rem_1",
                json={"payload": {"title": "Updated", "body": "Updated body"}},
            )

        assert resp.status_code == 200
        assert resp.json() == _expected_body("rem_1")

        # Only the sent field lands in the update: exclude_none keeps omitted
        # fields out of model_fields_set so the repository $set stays minimal.
        update_call = update_reminder.await_args
        assert update_call is not None
        assert update_call.args == ("rem_1",)
        assert update_call.kwargs["user_id"] == USER_ID
        update = update_call.kwargs["update"]
        assert isinstance(update, ReminderUpdate)
        assert update.model_fields_set == {"payload"}

        get_reminder.assert_awaited_once_with("rem_1", user_id=USER_ID)
        log_set.assert_any_call(
            user={"id": USER_ID}, reminder={"operation": "update", "id": "rem_1"}
        )
        log_set.assert_any_call(
            reminder={
                "operation": "update",
                "id": "rem_1",
                "next_run_time": FUTURE.isoformat(),
            }
        )
        log_set.assert_any_call(outcome="success")

    async def test_update_reminder_multiple_fields(self, client: AsyncClient) -> None:
        """Sent fields only: status + max_occurrences are updated, others aren't."""
        mock_reminder = _reminder_model("rem_1", status="completed")
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.update_reminder",
                new_callable=AsyncMock,
                return_value=True,
            ) as update_reminder,
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
                new_callable=AsyncMock,
                return_value=mock_reminder,
            ),
        ):
            resp = await client.put(
                f"{API}/rem_1",
                json={
                    "payload": {"title": "Updated", "body": "Updated body"},
                    "status": "completed",
                    "max_occurrences": 3,
                },
            )

        assert resp.status_code == 200
        update = update_reminder.await_args.kwargs["update"]
        assert update.model_fields_set == {"payload", "status", "max_occurrences"}
        assert update.status == ReminderStatus.COMPLETED
        assert update.max_occurrences == 3

    async def test_update_reminder_failure(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.update_reminder",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("app.api.v1.endpoints.reminders.log.error") as log_error,
        ):
            resp = await client.put(
                f"{API}/rem_1",
                json={"payload": {"title": "X", "body": "Y"}},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to update reminder"
        # A deliberate failure raise must not be logged as an exception.
        assert _endpoint_error_logs(log_error, f"{LogTag.API} Error updating reminder") == []

    async def test_update_reminder_retrieve_failure(self, client: AsyncClient) -> None:
        """Updated but not retrievable is a distinct 500 — not the update 500."""
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.update_reminder",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = await client.put(
                f"{API}/rem_1",
                json={"payload": {"title": "X", "body": "Y"}},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to retrieve updated reminder"

    async def test_update_reminder_service_error(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.update_reminder",
                new_callable=AsyncMock,
                side_effect=Exception("DB down"),
            ),
            patch("app.api.v1.endpoints.reminders.log.error") as log_error,
        ):
            resp = await client.put(
                f"{API}/rem_1",
                json={"payload": {"title": "X", "body": "Y"}},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to update reminder"
        log_error.assert_any_call(
            f"{LogTag.API} Error updating reminder",
            reminder_id="rem_1",
            user_id=USER_ID,
            error_type="Exception",
            error="DB down",
        )

    async def test_update_reminder_missing_user_id(
        self, client_without_user_id: AsyncClient
    ) -> None:
        resp = await client_without_user_id.put(
            f"{API}/rem_1",
            json={"payload": {"title": "X", "body": "Y"}},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "User not authenticated"

    async def test_update_reminder_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.put(
            f"{API}/rem_1",
            json={"payload": {"title": "X", "body": "Y"}},
        )
        assert resp.status_code == 401


# ===========================================================================
# DELETE /api/v1/reminders/{reminder_id}  -- cancel reminder
# ===========================================================================


class TestCancelReminder:
    """DELETE /api/v1/reminders/{reminder_id}"""

    async def test_cancel_reminder_success(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.cancel_task",
                new_callable=AsyncMock,
                return_value=True,
            ) as cancel_task,
            patch("app.api.v1.endpoints.reminders.log.set") as log_set,
        ):
            resp = await client.delete(f"{API}/rem_1")

        assert resp.status_code == 204
        assert resp.content == b""
        cancel_task.assert_awaited_once_with("rem_1", user_id=USER_ID)
        log_set.assert_any_call(
            user={"id": USER_ID}, reminder={"operation": "delete", "id": "rem_1"}
        )
        log_set.assert_any_call(outcome="success")

    async def test_cancel_reminder_failure(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.cancel_task",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("app.api.v1.endpoints.reminders.log.error") as log_error,
        ):
            resp = await client.delete(f"{API}/rem_1")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to cancel reminder"
        # A deliberate failure raise must not be logged as an exception.
        assert _endpoint_error_logs(log_error, f"{LogTag.API} Error cancelling reminder") == []

    async def test_cancel_reminder_service_error(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.cancel_task",
                new_callable=AsyncMock,
                side_effect=Exception("DB down"),
            ),
            patch("app.api.v1.endpoints.reminders.log.error") as log_error,
        ):
            resp = await client.delete(f"{API}/rem_1")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to cancel reminder"
        log_error.assert_any_call(
            f"{LogTag.API} Error cancelling reminder",
            reminder_id="rem_1",
            user_id=USER_ID,
            error_type="Exception",
            error="DB down",
        )

    async def test_cancel_reminder_missing_user_id(
        self, client_without_user_id: AsyncClient
    ) -> None:
        resp = await client_without_user_id.delete(f"{API}/rem_1")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "User not authenticated"

    async def test_cancel_reminder_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.delete(f"{API}/rem_1")
        assert resp.status_code == 401


# ===========================================================================
# GET /api/v1/reminders  -- list reminders
# ===========================================================================


class TestListReminders:
    """GET /api/v1/reminders"""

    async def test_list_reminders_success(self, client: AsyncClient) -> None:
        reminders = [_reminder_model("r1"), _reminder_model("r2")]
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.list_user_reminders",
                new_callable=AsyncMock,
                return_value=reminders,
            ) as list_user_reminders,
            patch("app.api.v1.endpoints.reminders.log.set") as log_set,
        ):
            resp = await client.get(API)

        assert resp.status_code == 200
        assert resp.json() == [_expected_body("r1"), _expected_body("r2")]
        list_user_reminders.assert_awaited_once_with(
            user_id=USER_ID, status=None, limit=100, skip=0
        )
        log_set.assert_any_call(user={"id": USER_ID}, reminder={"operation": "list"})
        log_set.assert_any_call(reminder={"operation": "list", "result_count": 2})
        log_set.assert_any_call(outcome="success")

    async def test_list_reminders_with_filters(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.reminders.reminder_scheduler.list_user_reminders",
            new_callable=AsyncMock,
            return_value=[],
        ) as list_user_reminders:
            resp = await client.get(API, params={"status": "scheduled", "limit": 5, "skip": 2})

        assert resp.status_code == 200
        list_user_reminders.assert_awaited_once_with(
            user_id=USER_ID, status=ReminderStatus.SCHEDULED, limit=5, skip=2
        )

    async def test_list_reminders_empty(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.reminders.reminder_scheduler.list_user_reminders",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await client.get(API)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_reminders_validation_error_bad_limit(self, client: AsyncClient) -> None:
        resp = await client.get(API, params={"limit": 0})
        assert resp.status_code == 422

    async def test_list_reminders_validation_limit_too_high(self, client: AsyncClient) -> None:
        resp = await client.get(API, params={"limit": 1001})
        assert resp.status_code == 422

    async def test_list_reminders_validation_bad_skip(self, client: AsyncClient) -> None:
        resp = await client.get(API, params={"skip": -1})
        assert resp.status_code == 422

    async def test_list_reminders_service_error(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.list_user_reminders",
                new_callable=AsyncMock,
                side_effect=Exception("DB down"),
            ),
            patch("app.api.v1.endpoints.reminders.log.error") as log_error,
        ):
            resp = await client.get(API)
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to list reminders"
        log_error.assert_any_call(
            f"{LogTag.API} Error listing reminders",
            user_id=USER_ID,
            error_type="Exception",
            error="DB down",
        )

    async def test_list_reminders_missing_user_id(
        self, client_without_user_id: AsyncClient
    ) -> None:
        resp = await client_without_user_id.get(API)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "User not authenticated"

    async def test_list_reminders_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(API)
        assert resp.status_code == 401


# ===========================================================================
# POST /api/v1/reminders/{reminder_id}/pause
# ===========================================================================


class TestPauseReminder:
    """POST /api/v1/reminders/{reminder_id}/pause"""

    async def test_pause_success(self, client: AsyncClient) -> None:
        mock_reminder = _reminder_model("rem_1", status="paused")
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.update_reminder",
                new_callable=AsyncMock,
                return_value=True,
            ) as update_reminder,
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
                new_callable=AsyncMock,
                return_value=mock_reminder,
            ) as get_reminder,
            patch("app.api.v1.endpoints.reminders.log.set") as log_set,
        ):
            resp = await client.post(f"{API}/rem_1/pause")

        assert resp.status_code == 200
        assert resp.json() == _expected_body("rem_1", status="paused")

        pause_call = update_reminder.await_args
        assert pause_call is not None
        assert pause_call.args == ("rem_1", ReminderUpdate(status=ReminderStatus.PAUSED))
        assert pause_call.kwargs["user_id"] == USER_ID

        get_reminder.assert_awaited_once_with("rem_1", user_id=USER_ID)
        log_set.assert_any_call(user={"id": USER_ID}, reminder={"id": "rem_1"})

    async def test_pause_failure(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.update_reminder",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("app.api.v1.endpoints.reminders.log.error") as log_error,
        ):
            resp = await client.post(f"{API}/rem_1/pause")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to pause reminder"
        # A deliberate failure raise must not be logged as an exception.
        assert _endpoint_error_logs(log_error, f"{LogTag.API} Error pausing reminder") == []

    async def test_pause_retrieve_failure(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.update_reminder",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = await client.post(f"{API}/rem_1/pause")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to retrieve updated reminder"

    async def test_pause_service_error(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.update_reminder",
                new_callable=AsyncMock,
                side_effect=Exception("DB down"),
            ),
            patch("app.api.v1.endpoints.reminders.log.error") as log_error,
        ):
            resp = await client.post(f"{API}/rem_1/pause")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to pause reminder"
        log_error.assert_any_call(
            f"{LogTag.API} Error pausing reminder",
            reminder_id="rem_1",
            user_id=USER_ID,
            error_type="Exception",
            error="DB down",
        )

    async def test_pause_missing_user_id(self, client_without_user_id: AsyncClient) -> None:
        resp = await client_without_user_id.post(f"{API}/rem_1/pause")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "User not authenticated"

    async def test_pause_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(f"{API}/rem_1/pause")
        assert resp.status_code == 401


# ===========================================================================
# POST /api/v1/reminders/{reminder_id}/resume
# ===========================================================================


class TestResumeReminder:
    """POST /api/v1/reminders/{reminder_id}/resume"""

    async def test_resume_success(self, client: AsyncClient) -> None:
        paused_reminder = _reminder_model("rem_1", status="paused")
        resumed_reminder = _reminder_model("rem_1", status="scheduled")
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
                new_callable=AsyncMock,
                side_effect=[paused_reminder, resumed_reminder],
            ) as get_reminder,
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.update_reminder",
                new_callable=AsyncMock,
                return_value=True,
            ) as update_reminder,
            patch(
                "app.api.v1.endpoints.reminders.get_next_run_time",
                return_value=NEXT_RUN,
            ) as get_next_run_time,
            patch("app.api.v1.endpoints.reminders.log.set") as log_set,
        ):
            resp = await client.post(f"{API}/rem_1/resume")

        assert resp.status_code == 200
        assert resp.json() == _expected_body("rem_1", status="scheduled")

        # Both the existence check and the post-update fetch are scoped to the
        # same reminder and user.
        for call in get_reminder.await_args_list:
            assert call.args == ("rem_1",)
            assert call.kwargs == {"user_id": USER_ID}

        # One-shot reminder: just flips status back to scheduled, no re-arm.
        resume_call = update_reminder.await_args
        assert resume_call is not None
        assert resume_call.args[0] == "rem_1"
        assert resume_call.kwargs["user_id"] == USER_ID
        update = resume_call.args[1]
        assert isinstance(update, ReminderUpdate)
        assert update.model_fields_set == {"status"}
        assert update.status == ReminderStatus.SCHEDULED
        assert update.scheduled_at is None

        get_next_run_time.assert_not_called()
        log_set.assert_any_call(user={"id": USER_ID}, reminder={"id": "rem_1"})

    async def test_resume_recurring_rearms_next_run(self, client: AsyncClient) -> None:
        """A recurring paused reminder gets its next run time recomputed."""
        paused_reminder = _reminder_model("rem_1", status="paused", repeat="0 9 * * *")
        resumed_reminder = _reminder_model("rem_1", status="scheduled", repeat="0 9 * * *")
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
                new_callable=AsyncMock,
                side_effect=[paused_reminder, resumed_reminder],
            ),
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.update_reminder",
                new_callable=AsyncMock,
                return_value=True,
            ) as update_reminder,
            patch(
                "app.api.v1.endpoints.reminders.get_next_run_time",
                return_value=NEXT_RUN,
            ) as get_next_run_time,
        ):
            resp = await client.post(f"{API}/rem_1/resume")

        assert resp.status_code == 200
        get_next_run_time.assert_called_once_with("0 9 * * *")
        update = update_reminder.await_args.args[1]
        assert update.model_fields_set == {"status", "scheduled_at"}
        assert update.status == ReminderStatus.SCHEDULED
        assert update.scheduled_at == NEXT_RUN

    async def test_resume_not_paused(self, client: AsyncClient) -> None:
        """Resuming a reminder that isn't paused should fail with 400."""
        active_reminder = _reminder_model("rem_1", status="scheduled")
        with patch(
            "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
            new_callable=AsyncMock,
            return_value=active_reminder,
        ):
            resp = await client.post(f"{API}/rem_1/resume")

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Reminder rem_1 is not paused (current status: scheduled)"

    async def test_resume_not_found(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(f"{API}/nonexistent/resume")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Reminder nonexistent not found"

    async def test_resume_failure(self, client: AsyncClient) -> None:
        paused_reminder = _reminder_model("rem_1", status="paused")
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
                new_callable=AsyncMock,
                return_value=paused_reminder,
            ),
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.update_reminder",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("app.api.v1.endpoints.reminders.log.error") as log_error,
        ):
            resp = await client.post(f"{API}/rem_1/resume")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to resume reminder"
        # A deliberate failure raise must not be logged as an exception.
        assert _endpoint_error_logs(log_error, f"{LogTag.API} Error resuming reminder") == []

    async def test_resume_retrieve_failure(self, client: AsyncClient) -> None:
        paused_reminder = _reminder_model("rem_1", status="paused")
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
                new_callable=AsyncMock,
                side_effect=[paused_reminder, None],
            ),
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.update_reminder",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            resp = await client.post(f"{API}/rem_1/resume")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to retrieve updated reminder"

    async def test_resume_service_error(self, client: AsyncClient) -> None:
        paused_reminder = _reminder_model("rem_1", status="paused")
        with (
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.get_reminder",
                new_callable=AsyncMock,
                return_value=paused_reminder,
            ),
            patch(
                "app.api.v1.endpoints.reminders.reminder_scheduler.update_reminder",
                new_callable=AsyncMock,
                side_effect=Exception("DB down"),
            ),
            patch("app.api.v1.endpoints.reminders.log.error") as log_error,
        ):
            resp = await client.post(f"{API}/rem_1/resume")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to resume reminder"
        log_error.assert_any_call(
            f"{LogTag.API} Error resuming reminder",
            reminder_id="rem_1",
            user_id=USER_ID,
            error_type="Exception",
            error="DB down",
        )

    async def test_resume_missing_user_id(self, client_without_user_id: AsyncClient) -> None:
        resp = await client_without_user_id.post(f"{API}/rem_1/resume")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "User not authenticated"

    async def test_resume_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(f"{API}/rem_1/resume")
        assert resp.status_code == 401


# ===========================================================================
# GET /api/v1/reminders/cron/validate
# ===========================================================================


class TestCronValidate:
    """GET /api/v1/reminders/cron/validate"""

    async def test_valid_cron_expression(self, client: AsyncClient) -> None:
        """The real cron utilities run: 5 next runs, ISO-stamped, ascending."""
        with patch("app.api.v1.endpoints.reminders.log.set") as log_set:
            resp = await client.get(
                f"{API}/cron/validate",
                params={"expression": "0 9 * * *"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["expression"] == "0 9 * * *"
        assert data["valid"] is True
        assert data["error"] is None
        assert len(data["next_runs"]) == 5
        runs = [datetime.fromisoformat(run) for run in data["next_runs"]]
        assert all(run.tzinfo is not None for run in runs)
        assert runs == sorted(runs)
        assert runs[0] > datetime.now(UTC)
        # isoformat uses the T separator; str(datetime) would use a space.
        assert all("T" in run for run in data["next_runs"])
        log_set.assert_any_call(reminder={"operation": "validate_cron"})

    async def test_invalid_cron_expression(self, client: AsyncClient) -> None:
        """The real validator runs and the endpoint short-circuits."""
        resp = await client.get(
            f"{API}/cron/validate",
            params={"expression": "not-a-cron"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["expression"] == "not-a-cron"
        assert data["valid"] is False
        assert data["next_runs"] == []
        assert data["error"] is None

    async def test_cron_validation_exception_reports_error(self, client: AsyncClient) -> None:
        with (
            patch(
                "app.api.v1.endpoints.reminders.validate_cron_expression",
                side_effect=ValueError("boom"),
            ),
            patch("app.api.v1.endpoints.reminders.log.error") as log_error,
        ):
            resp = await client.get(
                f"{API}/cron/validate",
                params={"expression": "0 9 * * *"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["expression"] == "0 9 * * *"
        assert data["valid"] is False
        assert data["next_runs"] == []
        assert data["error"] == "boom"
        log_error.assert_any_call(
            f"{LogTag.API} Error validating cron expression",
            expression="0 9 * * *",
            error_type="ValueError",
            error="boom",
        )

    async def test_cron_validate_missing_expression(self, client: AsyncClient) -> None:
        resp = await client.get(f"{API}/cron/validate")
        assert resp.status_code == 422
