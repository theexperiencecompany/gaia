"""Unit tests for calendar API endpoints.

Tests the calendar endpoints with mocked service layer and integration
dependency to verify routing, status codes, response bodies, and validation.

All calendar endpoints use ``require_integration("calendar")`` which calls
``check_integration_status`` under the hood.  We patch that function to
return ``True`` so the authenticated ``client`` fixture from conftest.py
can reach the endpoint logic.
"""

from typing import ClassVar
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.models.calendar_models import (
    CalendarEventPageResponse,
    CalendarEventsResponse,
    CalendarListResponse,
    CalendarPreferencesResponse,
    CalendarPreferencesUpdateResponse,
    EventDeleteResponse,
    GoogleCalendarEventResource,
    GoogleCalendarListEntry,
)
from app.services.analytics_service import AnalyticsEvents
from tests.conftest import FAKE_USER

API = "/api/v1"
USER_ID = FAKE_USER["user_id"]
ANALYTICS_PATCH = "app.api.v1.endpoints.calendar.capture_context_event"


@pytest.fixture(autouse=True)
def _noop_analytics():
    """Neutralize capture_context_event for every test in this module.

    The test app runs a no-op lifespan, so the PostHog provider is never
    registered; a bare capture_context_event call would raise KeyError on the
    missing provider. Tests that assert on captures patch the call site again
    and assert on their own mock.
    """
    with patch(ANALYTICS_PATCH):
        yield


# All calendar endpoints go through require_integration("calendar") which
# calls check_integration_status.  We patch it globally for this module so
# every request reaches the actual endpoint handler.
INTEGRATION_PATCH = "app.api.v1.dependencies.google_scope_dependencies.check_integration_status"
SVC_PATCH = "app.api.v1.endpoints.calendar.calendar_service"
DELETE_PATCH = "app.api.v1.endpoints.calendar.delete_calendar_event"
UPDATE_PATCH = "app.api.v1.endpoints.calendar.update_calendar_event"


# ---------------------------------------------------------------------------
# GET /api/v1/calendar/list
# ---------------------------------------------------------------------------


class TestGetCalendarList:
    """GET /api/v1/calendar/list"""

    async def test_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.list_calendars.return_value = CalendarListResponse(
                items=[GoogleCalendarListEntry(id="primary", summary="Main Calendar")]
            )
            resp = await client.get(f"{API}/calendar/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"][0]["id"] == "primary"

    async def test_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.list_calendars.side_effect = Exception("boom")
            resp = await client.get(f"{API}/calendar/list")
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/calendar/list")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/calendar/events/query
# ---------------------------------------------------------------------------


class TestQueryEvents:
    """POST /api/v1/calendar/events/query"""

    async def test_query_events_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = CalendarEventsResponse(
                events=[GoogleCalendarEventResource(id="ev1", summary="Meeting")],
                selected_calendars=["primary"],
                has_more=False,
                calendars_truncated=[],
            )
            resp = await client.post(
                f"{API}/calendar/events/query",
                json={
                    "selected_calendars": ["primary"],
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-31",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1

    async def test_query_events_without_dates(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = CalendarEventsResponse(
                events=[],
                selected_calendars=["primary"],
                has_more=False,
                calendars_truncated=[],
            )
            resp = await client.post(
                f"{API}/calendar/events/query",
                json={"selected_calendars": ["primary"]},
            )
        assert resp.status_code == 200

    async def test_query_events_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events.side_effect = Exception("API down")
            resp = await client.post(
                f"{API}/calendar/events/query",
                json={"selected_calendars": ["primary"]},
            )
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/calendar/events/query",
            json={"selected_calendars": ["primary"]},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/calendar/events
# ---------------------------------------------------------------------------


class TestGetEvents:
    """GET /api/v1/calendar/events"""

    async def test_get_events_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = CalendarEventsResponse(
                events=[],
                selected_calendars=[],
                has_more=False,
                calendars_truncated=[],
            )
            resp = await client.get(f"{API}/calendar/events")
        assert resp.status_code == 200

    async def test_get_events_with_date_range(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = CalendarEventsResponse(
                events=[],
                selected_calendars=[],
                has_more=False,
                calendars_truncated=[],
            )
            resp = await client.get(
                f"{API}/calendar/events",
                params={"start_date": "2026-03-01", "end_date": "2026-03-31"},
            )
        assert resp.status_code == 200

    async def test_get_events_with_selected_calendars(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = CalendarEventsResponse(
                events=[],
                selected_calendars=[],
                has_more=False,
                calendars_truncated=[],
            )
            resp = await client.get(
                f"{API}/calendar/events",
                params={"selected_calendars": ["primary", "work"]},
            )
        assert resp.status_code == 200

    async def test_get_events_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events.side_effect = Exception("Fail")
            resp = await client.get(f"{API}/calendar/events")
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/calendar/events")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/calendar/{calendar_id}/events
# ---------------------------------------------------------------------------


class TestGetEventsByCalendar:
    """GET /api/v1/calendar/{calendar_id}/events"""

    async def test_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events_by_id.return_value = CalendarEventPageResponse(
                events=[GoogleCalendarEventResource(id="ev2")]
            )
            resp = await client.get(f"{API}/calendar/my-cal-id/events")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1

    async def test_with_date_filters(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events_by_id.return_value = CalendarEventPageResponse(events=[])
            resp = await client.get(
                f"{API}/calendar/primary/events",
                params={"start_date": "2026-01-01", "end_date": "2026-12-31"},
            )
        assert resp.status_code == 200

    async def test_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_calendar_events_by_id.side_effect = Exception("Fail")
            resp = await client.get(f"{API}/calendar/primary/events")
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/calendar/primary/events")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/calendar/event
# ---------------------------------------------------------------------------


class TestCreateEvent:
    """POST /api/v1/calendar/event"""

    async def test_create_event_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.create_calendar_event.return_value = GoogleCalendarEventResource(
                id="ev-new", summary="Lunch"
            )
            resp = await client.post(
                f"{API}/calendar/event",
                json={
                    "summary": "Lunch",
                    "start": "2026-03-20T12:00:00+00:00",
                    "end": "2026-03-20T13:00:00+00:00",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == "ev-new"

    async def test_create_event_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.create_calendar_event.side_effect = Exception("API error")
            resp = await client.post(
                f"{API}/calendar/event",
                json={
                    "summary": "Lunch",
                    "start": "2026-03-20T12:00:00+00:00",
                    "end": "2026-03-20T13:00:00+00:00",
                },
            )
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/calendar/event",
            json={
                "summary": "Lunch",
                "start": "2026-03-20T12:00:00+00:00",
                "end": "2026-03-20T13:00:00+00:00",
            },
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/v1/calendar/event
# ---------------------------------------------------------------------------


class TestDeleteEvent:
    """DELETE /api/v1/calendar/event"""

    async def test_delete_event_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(
                DELETE_PATCH,
                new_callable=AsyncMock,
                return_value=EventDeleteResponse(
                    success=True, message="Event deleted successfully"
                ),
            ),
        ):
            resp = await client.request(
                "DELETE",
                f"{API}/calendar/event",
                json={"event_id": "ev-001", "calendar_id": "primary"},
            )
        assert resp.status_code == 200

    async def test_delete_event_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(DELETE_PATCH, new_callable=AsyncMock, side_effect=Exception("Not found")),
        ):
            resp = await client.request(
                "DELETE",
                f"{API}/calendar/event",
                json={"event_id": "ev-001", "calendar_id": "primary"},
            )
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.request(
            "DELETE",
            f"{API}/calendar/event",
            json={"event_id": "ev-001", "calendar_id": "primary"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /api/v1/calendar/event
# ---------------------------------------------------------------------------


class TestUpdateEvent:
    """PUT /api/v1/calendar/event"""

    async def test_update_event_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(
                UPDATE_PATCH,
                new_callable=AsyncMock,
                return_value=GoogleCalendarEventResource(id="ev-001", summary="Updated"),
            ),
        ):
            resp = await client.put(
                f"{API}/calendar/event",
                json={"event_id": "ev-001", "summary": "Updated"},
            )
        assert resp.status_code == 200
        assert resp.json()["summary"] == "Updated"

    async def test_update_event_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(UPDATE_PATCH, new_callable=AsyncMock, side_effect=Exception("Update failed")),
        ):
            resp = await client.put(
                f"{API}/calendar/event",
                json={"event_id": "ev-001", "summary": "Updated"},
            )
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.put(
            f"{API}/calendar/event",
            json={"event_id": "ev-001", "summary": "Updated"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/calendar/preferences
# ---------------------------------------------------------------------------


class TestGetCalendarPreferences:
    """GET /api/v1/calendar/preferences"""

    async def test_get_preferences_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_user_calendar_preferences.return_value = CalendarPreferencesResponse(
                selected_calendars=["primary"]
            )
            resp = await client.get(f"{API}/calendar/preferences")
        assert resp.status_code == 200
        # Serialized under the camelCase alias the web client reads.
        assert resp.json() == {"selectedCalendars": ["primary"]}

    async def test_get_preferences_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.get_user_calendar_preferences.side_effect = Exception("DB error")
            resp = await client.get(f"{API}/calendar/preferences")
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/calendar/preferences")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /api/v1/calendar/preferences
# ---------------------------------------------------------------------------


class TestUpdateCalendarPreferences:
    """PUT /api/v1/calendar/preferences"""

    async def test_update_preferences_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.update_user_calendar_preferences.return_value = (
                CalendarPreferencesUpdateResponse(message="Preferences updated")
            )
            resp = await client.put(
                f"{API}/calendar/preferences",
                json={"selected_calendars": ["primary", "work"]},
            )
        assert resp.status_code == 200

    async def test_update_preferences_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.update_user_calendar_preferences.side_effect = Exception("DB error")
            resp = await client.put(
                f"{API}/calendar/preferences",
                json={"selected_calendars": ["primary"]},
            )
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.put(
            f"{API}/calendar/preferences",
            json={"selected_calendars": ["primary"]},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/calendar/events/batch (create)
# ---------------------------------------------------------------------------


class TestBatchCreateEvents:
    """POST /api/v1/calendar/events/batch"""

    async def test_batch_create_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.create_calendar_event.return_value = GoogleCalendarEventResource(
                id="ev-batch-1"
            )
            resp = await client.post(
                f"{API}/calendar/events/batch",
                json={
                    "events": [
                        {
                            "summary": "Event 1",
                            "start": "2026-03-20T10:00:00+00:00",
                            "end": "2026-03-20T11:00:00+00:00",
                        }
                    ]
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "successful" in data
        assert "failed" in data
        assert len(data["successful"]) == 1

    async def test_batch_create_partial_failure(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.create_calendar_event.side_effect = [
                GoogleCalendarEventResource(id="ev-ok"),
                Exception("Failed"),
            ]
            resp = await client.post(
                f"{API}/calendar/events/batch",
                json={
                    "events": [
                        {
                            "summary": "Good",
                            "start": "2026-03-20T10:00:00+00:00",
                            "end": "2026-03-20T11:00:00+00:00",
                        },
                        {
                            "summary": "Bad",
                            "start": "2026-03-20T12:00:00+00:00",
                            "end": "2026-03-20T13:00:00+00:00",
                        },
                    ]
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["successful"]) == 1
        assert len(data["failed"]) == 1

    async def test_batch_create_per_event_failure_does_not_500(self, client: AsyncClient) -> None:
        # Per-event failures are recorded in results["failed"] and the endpoint
        # still returns 200. The outer 500 path is only reachable when the
        # per-event loop setup fails — no longer testable now that token
        # fetching has moved into the proxy client.
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
        ):
            mock_svc.create_calendar_event.side_effect = Exception("boom")
            resp = await client.post(
                f"{API}/calendar/events/batch",
                json={
                    "events": [
                        {
                            "summary": "Event 1",
                            "start": "2026-03-20T10:00:00+00:00",
                            "end": "2026-03-20T11:00:00+00:00",
                        }
                    ]
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["successful"] == []
        assert len(data["failed"]) == 1

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/calendar/events/batch",
            json={
                "events": [
                    {
                        "summary": "Event 1",
                        "start": "2026-03-20T10:00:00+00:00",
                        "end": "2026-03-20T11:00:00+00:00",
                    }
                ]
            },
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /api/v1/calendar/events/batch (update)
# ---------------------------------------------------------------------------


class TestBatchUpdateEvents:
    """PUT /api/v1/calendar/events/batch"""

    async def test_batch_update_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(
                UPDATE_PATCH,
                new_callable=AsyncMock,
                return_value=GoogleCalendarEventResource(id="ev-001", summary="Updated"),
            ) as mock_update,
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            resp = await client.put(
                f"{API}/calendar/events/batch",
                json={"events": [{"event_id": "ev-001", "summary": "Updated"}]},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["successful"]) == 1
        mock_capture.assert_called_once_with(
            AnalyticsEvents.CALENDAR_EVENT_UPDATED,
            {"batch_size": 1, "success_count": 1, "failure_count": 0},
        )
        assert all(
            len(call.args) == 2 and all(arg is not None for arg in call.args)
            for call in mock_update.await_args_list
        )

    async def test_batch_update_partial_failure(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(
                UPDATE_PATCH,
                new_callable=AsyncMock,
                side_effect=[
                    GoogleCalendarEventResource(id="ev-001", summary="Updated"),
                    Exception("Not found"),
                ],
            ),
        ):
            resp = await client.put(
                f"{API}/calendar/events/batch",
                json={
                    "events": [
                        {"event_id": "ev-001", "summary": "Updated"},
                        {"event_id": "ev-002", "summary": "Nope"},
                    ]
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["successful"]) == 1
        assert len(data["failed"]) == 1

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.put(
            f"{API}/calendar/events/batch",
            json={"events": [{"event_id": "ev-001", "summary": "Updated"}]},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/v1/calendar/events/batch (delete)
# ---------------------------------------------------------------------------


class TestBatchDeleteEvents:
    """DELETE /api/v1/calendar/events/batch"""

    async def test_batch_delete_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(DELETE_PATCH, new_callable=AsyncMock, return_value=None) as mock_delete,
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            resp = await client.request(
                "DELETE",
                f"{API}/calendar/events/batch",
                json={"events": [{"event_id": "ev-001", "calendar_id": "primary"}]},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["successful"]) == 1
        assert data["successful"][0]["event_id"] == "ev-001"
        mock_capture.assert_called_once_with(
            AnalyticsEvents.CALENDAR_EVENT_DELETED,
            {"batch_size": 1, "success_count": 1, "failure_count": 0},
        )
        assert all(
            len(call.args) == 2 and all(arg is not None for arg in call.args)
            for call in mock_delete.await_args_list
        )

    async def test_batch_delete_partial_failure(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            # token patch removed (composio proxy migration)
            patch(DELETE_PATCH, new_callable=AsyncMock, side_effect=[None, Exception("Not found")]),
        ):
            resp = await client.request(
                "DELETE",
                f"{API}/calendar/events/batch",
                json={
                    "events": [
                        {"event_id": "ev-001", "calendar_id": "primary"},
                        {"event_id": "ev-002", "calendar_id": "primary"},
                    ]
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["successful"]) == 1
        assert len(data["failed"]) == 1

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.request(
            "DELETE",
            f"{API}/calendar/events/batch",
            json={"events": [{"event_id": "ev-001", "calendar_id": "primary"}]},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Integration not connected (403)
# ---------------------------------------------------------------------------


class TestIntegrationNotConnected:
    """Verify endpoints return 403 when calendar integration is not connected."""

    async def test_list_calendars_returns_403(self, client: AsyncClient) -> None:
        with patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=False):
            resp = await client.get(f"{API}/calendar/list")
        assert resp.status_code == 403

    async def test_get_events_returns_403(self, client: AsyncClient) -> None:
        with patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=False):
            resp = await client.get(f"{API}/calendar/events")
        assert resp.status_code == 403

    async def test_create_event_returns_403(self, client: AsyncClient) -> None:
        with patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=False):
            resp = await client.post(
                f"{API}/calendar/event",
                json={
                    "summary": "Test",
                    "start": "2026-03-20T12:00:00+00:00",
                    "end": "2026-03-20T13:00:00+00:00",
                },
            )
        assert resp.status_code == 403


class TestCalendarAnalytics:
    """Analytics captures on calendar event mutation endpoints."""

    _EVENT_JSON: ClassVar[dict[str, str]] = {
        "summary": "Lunch",
        "start": "2026-03-20T12:00:00+00:00",
        "end": "2026-03-20T13:00:00+00:00",
    }

    async def test_create_event_captures_event_created(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
            patch(ANALYTICS_PATCH) as mock_capture,
            patch("app.api.v1.endpoints.calendar.log") as mock_log,
        ):
            mock_svc.create_calendar_event.return_value = GoogleCalendarEventResource(
                id="ev-new", summary="Lunch"
            )
            resp = await client.post(f"{API}/calendar/event", json=self._EVENT_JSON)

        assert resp.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.CALENDAR_EVENT_CREATED,
            {
                "is_all_day": False,
                "has_description": False,
                "has_recurrence": False,
                "recurrence_frequency": None,
            },
        )
        assert len(mock_svc.create_calendar_event.await_args.args) == 2
        assert all(arg is not None for arg in mock_svc.create_calendar_event.await_args.args)
        mock_log.set.assert_any_call(
            user={"id": USER_ID},
            calendar={"operation": "create_event", "calendar_id": None},
        )

    async def test_create_event_captures_description_and_recurrence(
        self, client: AsyncClient
    ) -> None:
        """The create capture reports the shape of the event, not its content."""
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            mock_svc.create_calendar_event.return_value = GoogleCalendarEventResource(
                id="ev-new", summary="Standup"
            )
            resp = await client.post(
                f"{API}/calendar/event",
                json={
                    **self._EVENT_JSON,
                    "is_all_day": True,
                    "description": "daily sync",
                    "recurrence": {"rrule": {"frequency": "WEEKLY", "by_day": ["MO", "WE"]}},
                },
            )

        assert resp.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.CALENDAR_EVENT_CREATED,
            {
                "is_all_day": True,
                "has_description": True,
                "has_recurrence": True,
                "recurrence_frequency": "WEEKLY",
            },
        )

    async def test_create_event_logs_calendar_id(self, client: AsyncClient) -> None:
        """A calendar_id on the request is reported in the create log.set."""
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
            patch(ANALYTICS_PATCH),
            patch("app.api.v1.endpoints.calendar.log") as mock_log,
        ):
            mock_svc.create_calendar_event.return_value = GoogleCalendarEventResource(
                id="ev-new", summary="Lunch"
            )
            resp = await client.post(
                f"{API}/calendar/event",
                json={**self._EVENT_JSON, "calendar_id": "primary"},
            )

        assert resp.status_code == 200
        mock_log.set.assert_any_call(
            user={"id": USER_ID},
            calendar={"operation": "create_event", "calendar_id": "primary"},
        )

    async def test_update_event_captures_event_updated(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(UPDATE_PATCH, new_callable=AsyncMock) as mock_update,
            patch(ANALYTICS_PATCH) as mock_capture,
            patch("app.api.v1.endpoints.calendar.log") as mock_log,
        ):
            mock_update.return_value = GoogleCalendarEventResource(id="ev-1", summary="Lunch")
            resp = await client.put(
                f"{API}/calendar/event",
                json={"event_id": "ev-1", "summary": "Lunch"},
            )

        assert resp.status_code == 200
        mock_capture.assert_called_once_with(AnalyticsEvents.CALENDAR_EVENT_UPDATED)
        assert len(mock_update.await_args.args) == 2
        assert all(arg is not None for arg in mock_update.await_args.args)
        mock_log.set.assert_any_call(user={"id": USER_ID}, calendar={"operation": "update_event"})

    async def test_delete_event_captures_event_deleted(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(DELETE_PATCH, new_callable=AsyncMock) as mock_delete,
            patch(ANALYTICS_PATCH) as mock_capture,
            patch("app.api.v1.endpoints.calendar.log") as mock_log,
        ):
            mock_delete.return_value = EventDeleteResponse(success=True, message="Event deleted")
            resp = await client.request(
                "DELETE", f"{API}/calendar/event", json={"event_id": "ev-1"}
            )

        assert resp.status_code == 200
        mock_capture.assert_called_once_with(AnalyticsEvents.CALENDAR_EVENT_DELETED)
        assert len(mock_delete.await_args.args) == 2
        assert all(arg is not None for arg in mock_delete.await_args.args)
        mock_log.set.assert_any_call(user={"id": USER_ID}, calendar={"operation": "delete_event"})

    async def test_batch_create_captures_counts(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH, new_callable=AsyncMock) as mock_svc,
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            mock_svc.create_calendar_event.return_value = GoogleCalendarEventResource(
                id="ev-new", summary="Lunch"
            )
            resp = await client.post(
                f"{API}/calendar/events/batch",
                json={"events": [self._EVENT_JSON, self._EVENT_JSON]},
            )

        assert resp.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.CALENDAR_EVENT_CREATED,
            {"batch_size": 2, "success_count": 2, "failure_count": 0},
        )
        assert mock_svc.create_calendar_event.await_count == 2
        assert all(
            arg is not None
            for call in mock_svc.create_calendar_event.await_args_list
            for arg in call.args
        )
