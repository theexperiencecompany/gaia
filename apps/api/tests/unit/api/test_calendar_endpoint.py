"""Unit tests for calendar API endpoints.

Tests the calendar endpoints with mocked service layer and integration
dependency to verify routing, status codes, response bodies, and validation.

All calendar endpoints use ``require_integration("calendar")`` which calls
``check_integration_status`` under the hood.  We patch that function to
return ``True`` so the authenticated ``client`` fixture from conftest.py
can reach the endpoint logic.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.conftest import FAKE_USER

API = "/api/v1"
USER_ID = FAKE_USER["user_id"]

# All calendar endpoints go through require_integration("calendar") which
# calls check_integration_status.  We patch it globally for this module so
# every request reaches the actual endpoint handler.
INTEGRATION_PATCH = (
    "app.api.v1.dependencies.google_scope_dependencies.check_integration_status"
)
TOKEN_PATCH = "app.api.v1.endpoints.calendar.get_google_calendar_token"
SVC_PATCH = "app.api.v1.endpoints.calendar.calendar_service"
DELETE_PATCH = "app.api.v1.endpoints.calendar.delete_calendar_event"
UPDATE_PATCH = "app.api.v1.endpoints.calendar.update_calendar_event"


# ---------------------------------------------------------------------------
# GET /api/v1/calendar/list
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetCalendarList:
    """GET /api/v1/calendar/list"""

    async def test_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(SVC_PATCH) as mock_svc,
        ):
            mock_svc.list_calendars.return_value = [
                {"id": "primary", "summary": "Main Calendar"}
            ]
            resp = await client.get(f"{API}/calendar/list")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["id"] == "primary"

    async def test_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, side_effect=Exception("Token error")),
            patch(SVC_PATCH),
        ):
            resp = await client.get(f"{API}/calendar/list")
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/calendar/list")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/calendar/events/query
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQueryEvents:
    """POST /api/v1/calendar/events/query"""

    async def test_query_events_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(SVC_PATCH) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = {
                "events": [{"id": "ev1", "summary": "Meeting"}],
                "has_more": False,
                "calendars_truncated": [],
            }
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
            patch(TOKEN_PATCH, return_value="tok"),
            patch(SVC_PATCH) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = {
                "events": [],
                "has_more": False,
                "calendars_truncated": [],
            }
            resp = await client.post(
                f"{API}/calendar/events/query",
                json={"selected_calendars": ["primary"]},
            )
        assert resp.status_code == 200

    async def test_query_events_service_error_returns_500(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(SVC_PATCH) as mock_svc,
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


@pytest.mark.unit
class TestGetEvents:
    """GET /api/v1/calendar/events"""

    async def test_get_events_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(SVC_PATCH) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = {
                "events": [],
                "has_more": False,
            }
            resp = await client.get(f"{API}/calendar/events")
        assert resp.status_code == 200

    async def test_get_events_with_date_range(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(SVC_PATCH) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = {"events": []}
            resp = await client.get(
                f"{API}/calendar/events",
                params={"start_date": "2026-03-01", "end_date": "2026-03-31"},
            )
        assert resp.status_code == 200

    async def test_get_events_with_selected_calendars(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(SVC_PATCH) as mock_svc,
        ):
            mock_svc.get_calendar_events.return_value = {"events": []}
            resp = await client.get(
                f"{API}/calendar/events",
                params={"selected_calendars": ["primary", "work"]},
            )
        assert resp.status_code == 200

    async def test_get_events_service_error_returns_500(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(SVC_PATCH) as mock_svc,
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


@pytest.mark.unit
class TestGetEventsByCalendar:
    """GET /api/v1/calendar/{calendar_id}/events"""

    async def test_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(SVC_PATCH) as mock_svc,
        ):
            mock_svc.get_calendar_events_by_id.return_value = {
                "events": [{"id": "ev2"}],
            }
            resp = await client.get(f"{API}/calendar/my-cal-id/events")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1

    async def test_with_date_filters(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(SVC_PATCH) as mock_svc,
        ):
            mock_svc.get_calendar_events_by_id.return_value = {"events": []}
            resp = await client.get(
                f"{API}/calendar/primary/events",
                params={"start_date": "2026-01-01", "end_date": "2026-12-31"},
            )
        assert resp.status_code == 200

    async def test_service_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(SVC_PATCH) as mock_svc,
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


@pytest.mark.unit
class TestCreateEvent:
    """POST /api/v1/calendar/event"""

    async def test_create_event_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(SVC_PATCH) as mock_svc,
        ):
            mock_svc.create_calendar_event.return_value = {
                "id": "ev-new",
                "summary": "Lunch",
            }
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

    async def test_create_event_service_error_returns_500(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(SVC_PATCH) as mock_svc,
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


@pytest.mark.unit
class TestDeleteEvent:
    """DELETE /api/v1/calendar/event"""

    async def test_delete_event_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(DELETE_PATCH, return_value={"status": "deleted"}),
        ):
            resp = await client.request(
                "DELETE",
                f"{API}/calendar/event",
                json={"event_id": "ev-001", "calendar_id": "primary"},
            )
        assert resp.status_code == 200

    async def test_delete_event_service_error_returns_500(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(DELETE_PATCH, side_effect=Exception("Not found")),
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


@pytest.mark.unit
class TestUpdateEvent:
    """PUT /api/v1/calendar/event"""

    async def test_update_event_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(UPDATE_PATCH, return_value={"id": "ev-001", "summary": "Updated"}),
        ):
            resp = await client.put(
                f"{API}/calendar/event",
                json={"event_id": "ev-001", "summary": "Updated"},
            )
        assert resp.status_code == 200
        assert resp.json()["summary"] == "Updated"

    async def test_update_event_service_error_returns_500(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(UPDATE_PATCH, side_effect=Exception("Update failed")),
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


@pytest.mark.unit
class TestGetCalendarPreferences:
    """GET /api/v1/calendar/preferences"""

    async def test_get_preferences_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH) as mock_svc,
        ):
            mock_svc.get_user_calendar_preferences.return_value = {
                "selected_calendars": ["primary"]
            }
            resp = await client.get(f"{API}/calendar/preferences")
        assert resp.status_code == 200
        assert resp.json()["selected_calendars"] == ["primary"]

    async def test_get_preferences_service_error_returns_500(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH) as mock_svc,
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


@pytest.mark.unit
class TestUpdateCalendarPreferences:
    """PUT /api/v1/calendar/preferences"""

    async def test_update_preferences_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH) as mock_svc,
        ):
            mock_svc.update_user_calendar_preferences.return_value = {
                "message": "Preferences updated"
            }
            resp = await client.put(
                f"{API}/calendar/preferences",
                json={"selected_calendars": ["primary", "work"]},
            )
        assert resp.status_code == 200

    async def test_update_preferences_service_error_returns_500(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(SVC_PATCH) as mock_svc,
        ):
            mock_svc.update_user_calendar_preferences.side_effect = Exception(
                "DB error"
            )
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


@pytest.mark.unit
class TestBatchCreateEvents:
    """POST /api/v1/calendar/events/batch"""

    async def test_batch_create_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(SVC_PATCH) as mock_svc,
        ):
            mock_svc.create_calendar_event.return_value = {"id": "ev-batch-1"}
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
            patch(TOKEN_PATCH, return_value="tok"),
            patch(SVC_PATCH) as mock_svc,
        ):
            mock_svc.create_calendar_event.side_effect = [
                {"id": "ev-ok"},
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

    async def test_batch_create_service_error_returns_500(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, side_effect=Exception("Token error")),
            patch(SVC_PATCH),
        ):
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
        assert resp.status_code == 500

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


@pytest.mark.unit
class TestBatchUpdateEvents:
    """PUT /api/v1/calendar/events/batch"""

    async def test_batch_update_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(UPDATE_PATCH, return_value={"id": "ev-001", "summary": "Updated"}),
        ):
            resp = await client.put(
                f"{API}/calendar/events/batch",
                json={"events": [{"event_id": "ev-001", "summary": "Updated"}]},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["successful"]) == 1

    async def test_batch_update_partial_failure(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(
                UPDATE_PATCH,
                side_effect=[
                    {"id": "ev-001", "summary": "Updated"},
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


@pytest.mark.unit
class TestBatchDeleteEvents:
    """DELETE /api/v1/calendar/events/batch"""

    async def test_batch_delete_returns_200(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(DELETE_PATCH, return_value=None),
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

    async def test_batch_delete_partial_failure(self, client: AsyncClient) -> None:
        with (
            patch(INTEGRATION_PATCH, new_callable=AsyncMock, return_value=True),
            patch(TOKEN_PATCH, return_value="tok"),
            patch(DELETE_PATCH, side_effect=[None, Exception("Not found")]),
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


@pytest.mark.unit
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
