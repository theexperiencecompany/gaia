"""
Google Calendar custom tool tests using pytest.

Tests 9 calendar tools with proper assertions:
- CUSTOM_LIST_CALENDARS
- CUSTOM_GET_DAY_SUMMARY
- CUSTOM_FETCH_EVENTS
- CUSTOM_FIND_EVENT
- CUSTOM_CREATE_EVENT
- CUSTOM_GET_EVENT
- CUSTOM_PATCH_EVENT
- CUSTOM_ADD_RECURRENCE
- CUSTOM_DELETE_EVENT

Usage:
    pytest tests/composio_tools/test_calendar_pytest.py -v --user-id USER_ID
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Generator

import pytest
from pytest_check import check

from tests.composio_tools.conftest import execute_tool


@pytest.fixture(scope="session")
def calendar_id(composio_client, user_id: str) -> str:
    """Get the primary calendar ID for the user."""
    result = execute_tool(
        composio_client,
        "GOOGLECALENDAR_CUSTOM_LIST_CALENDARS",
        {"short": True},
        user_id,
    )

    if not result.get("successful"):
        pytest.fail(f"Failed to list calendars: {result.get('error')}")

    calendars = result.get("data", {}).get("calendars", [])
    if not calendars:
        pytest.fail("No calendars found for user")

    # Prefer primary calendar, otherwise use first available
    for cal in calendars:
        if cal.get("primary"):
            return cal["id"]
    return calendars[0]["id"]


@pytest.fixture(scope="session")
def test_event(
    composio_client, user_id: str, calendar_id: str
) -> Generator[Dict[str, Any], None, None]:
    """Create a test event for the session and clean up after.

    Yields:
        Dict with event_id and calendar_id
    """
    # Create event for 2 hours from now
    now = datetime.now()
    start_time = (now + timedelta(hours=2)).replace(second=0, microsecond=0)

    result = execute_tool(
        composio_client,
        "GOOGLECALENDAR_CUSTOM_CREATE_EVENT",
        {
            "events": [
                {
                    "summary": "[PYTEST] Session Test Event",
                    "description": "Auto-created by pytest suite. Will be auto-deleted.",
                    "calendar_id": calendar_id,
                    "start_datetime": start_time.isoformat(),
                    "duration_hours": 1.0,
                    "duration_minutes": 0.0,
                    "is_all_day": False,
                }
            ],
            "confirm_immediately": True,
        },
        user_id,
    )

    if not result.get("successful"):
        pytest.fail(f"Failed to create test event: {result.get('error')}")

    created = result.get("data", {})
    if not isinstance(created, dict):
        # Fallback if data is not parsed correctly (e.g. error string)
        if isinstance(result.get("data"), str):
            pytest.fail(
                f"Failed to create event (Validation Error): {result.get('data')}"
            )
        created = {}

    created_events = (
        created.get("created_events", []) if isinstance(created, dict) else []
    )
    if not created_events:
        pytest.fail(f"No event created in response: {result}")

    event_info = {
        "event_id": created_events[0].get("event_id"),
        "calendar_id": created_events[0].get("calendar_id") or calendar_id,
    }

    yield event_info

    # Cleanup: delete the test event
    execute_tool(
        composio_client,
        "GOOGLECALENDAR_CUSTOM_DELETE_EVENT",
        {
            "events": [
                {
                    "event_id": event_info["event_id"],
                    "calendar_id": event_info["calendar_id"],
                }
            ],
            "send_updates": "none",
        },
        user_id,
    )


class TestCalendarReadOperations:
    """Tests for read-only calendar operations."""

    def test_list_calendars(self, composio_client, user_id):
        """Test CUSTOM_LIST_CALENDARS returns at least one calendar."""
        result = execute_tool(
            composio_client,
            "GOOGLECALENDAR_CUSTOM_LIST_CALENDARS",
            {"short": True},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

        data = result.get("data", {})
        calendars = data.get("calendars", [])

        # Validate calendars list
        assert len(calendars) > 0, "Expected at least 1 calendar"

        # Validate calendar structure
        first_cal = calendars[0]
        assert "id" in first_cal, "Calendar should have 'id' field"
        assert "summary" in first_cal, "Calendar should have 'summary' (name) field"
        assert first_cal["id"], "Calendar id should not be empty"

    def test_get_day_summary(self, composio_client, user_id, test_event):
        """Test CUSTOM_GET_DAY_SUMMARY returns proper structure."""
        today = datetime.now().strftime("%Y-%m-%d")

        result = execute_tool(
            composio_client,
            "GOOGLECALENDAR_CUSTOM_GET_DAY_SUMMARY",
            {"date": today},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

        data = result.get("data", {})
        with check:
            assert "date" in data, "Response should have 'date' field"
            assert "timezone" in data, "Response should have 'timezone' field"
            assert "events" in data, "Response should have 'events' field"
            assert isinstance(data.get("events"), list), "'events' should be a list"
            assert "busy_hours" in data, "Response should have 'busy_hours' field"
            assert isinstance(data.get("busy_hours"), (int, float)), (
                "busy_hours should be numeric"
            )

    def test_fetch_events(self, composio_client, user_id, calendar_id, test_event):
        """Test CUSTOM_FETCH_EVENTS returns events from specified calendar."""
        now = datetime.now()
        time_min = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max = (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

        result = execute_tool(
            composio_client,
            "GOOGLECALENDAR_CUSTOM_FETCH_EVENTS",
            {
                "time_min": time_min,
                "time_max": time_max,
                "max_results": 10,
                "calendar_ids": [calendar_id],
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

        data = result.get("data", {})
        events = data.get("calendar_fetch_data", [])

        assert isinstance(events, list), "'calendar_fetch_data' should be a list"
        assert len(events) > 0, "Expected at least 1 event (test event should exist)"

        # Validate event structure
        first_event = events[0]
        assert "summary" in first_event, "Event should have 'summary' field"
        assert "start_time" in first_event, "Event should have 'start_time' field"

    def test_find_event(self, composio_client, user_id, test_event):
        """Test CUSTOM_FIND_EVENT finds our test event."""
        result = execute_tool(
            composio_client,
            "GOOGLECALENDAR_CUSTOM_FIND_EVENT",
            {"query": "PYTEST"},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

        data = result.get("data", {})
        events = data.get("events", [])

        assert isinstance(events, list), "'events' should be a list"
        assert len(events) > 0, "Expected to find at least 1 matching event"

        # Validate found event contains PYTEST in summary
        found_pytest = any("PYTEST" in e.get("summary", "") for e in events)
        assert found_pytest, "Should find event with 'PYTEST' in summary"


class TestCalendarWriteOperations:
    """Tests for calendar create/update/delete operations."""

    @pytest.fixture
    def created_event(
        self, composio_client, user_id, calendar_id
    ) -> Generator[Dict[str, Any], None, None]:
        """Create a test event for write operation tests."""
        tomorrow = datetime.now() + timedelta(days=1)
        start_time = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)

        result = execute_tool(
            composio_client,
            "GOOGLECALENDAR_CUSTOM_CREATE_EVENT",
            {
                "events": [
                    {
                        "summary": "[PYTEST] Write Test Event",
                        "description": "Test event for write operations",
                        "calendar_id": calendar_id,
                        "start_datetime": start_time.isoformat(),
                        "duration_hours": 1.0,
                        "duration_minutes": 0.0,
                        "is_all_day": False,
                    }
                ],
                "confirm_immediately": True,
            },
            user_id,
        )

        assert result.get("successful"), (
            f"Failed to create event: {result.get('error')}"
        )

        created = result.get("data", {})
        if not isinstance(created, dict):
            pytest.fail(f"Event creation failed, data not dict: {result.get('data')}")

        created_list = created.get("created_events", [])
        assert len(created_list) > 0, "No event created in response"

        event_info = {
            "event_id": created_list[0].get("event_id"),
            "calendar_id": created_list[0].get("calendar_id") or calendar_id,
        }

        yield event_info

        # Cleanup
        execute_tool(
            composio_client,
            "GOOGLECALENDAR_CUSTOM_DELETE_EVENT",
            {
                "events": [event_info],
                "send_updates": "none",
            },
            user_id,
        )

    def test_create_event(self, composio_client, user_id, calendar_id):
        """Test CUSTOM_CREATE_EVENT creates an event successfully."""
        tomorrow = datetime.now() + timedelta(days=2)
        start_time = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)

        result = execute_tool(
            composio_client,
            "GOOGLECALENDAR_CUSTOM_CREATE_EVENT",
            {
                "events": [
                    {
                        "summary": "[PYTEST] Create Test",
                        "description": "Testing event creation",
                        "calendar_id": calendar_id,
                        "start_datetime": start_time.isoformat(),
                        "duration_hours": 1,
                        "duration_minutes": 30,
                        "is_all_day": False,
                    }
                ],
                "confirm_immediately": True,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

        data = result.get("data", {})
        assert isinstance(data, dict), f"Data is not a dict: {type(data)} - {data}"
        created = data.get("created_events", [])

        assert len(created) > 0, "Expected at least 1 created event"
        assert "event_id" in created[0], "Created event should have 'event_id'"
        assert created[0]["event_id"], "event_id should not be empty"
        assert "calendar_id" in created[0], "Created event should have 'calendar_id'"
        assert "summary" in created[0], "Created event should have 'summary'"

        # Cleanup
        execute_tool(
            composio_client,
            "GOOGLECALENDAR_CUSTOM_DELETE_EVENT",
            {
                "events": [
                    {
                        "event_id": created[0]["event_id"],
                        "calendar_id": created[0].get("calendar_id") or calendar_id,
                    }
                ],
                "send_updates": "none",
            },
            user_id,
        )

    def test_get_event(self, composio_client, user_id, created_event):
        """Test CUSTOM_GET_EVENT retrieves a specific event."""
        result = execute_tool(
            composio_client,
            "GOOGLECALENDAR_CUSTOM_GET_EVENT",
            {
                "events": [created_event],
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

        data = result.get("data", {})
        events = data.get("events", [])

        assert len(events) > 0, "Expected to retrieve at least 1 event"
        retrieved = events[0]
        assert retrieved.get("event_id") == created_event["event_id"], (
            "event_id should match"
        )
        # The actual event data is nested under 'event' key
        event_data = retrieved.get("event", {})
        assert event_data, "Retrieved response should have 'event' data"
        assert "summary" in event_data, "Event should have 'summary'"

    def test_patch_event(self, composio_client, user_id, created_event):
        """Test CUSTOM_PATCH_EVENT updates an event."""
        result = execute_tool(
            composio_client,
            "GOOGLECALENDAR_CUSTOM_PATCH_EVENT",
            {
                "event_id": created_event["event_id"],
                "calendar_id": created_event["calendar_id"],
                "summary": "[PYTEST] Updated Event Title",
                "description": "This event was updated by pytest",
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

        # Response contains the updated event under 'event' key
        data = result.get("data", {})
        event_data = data.get("event", {})
        assert event_data, "Expected 'event' in response from PATCH"

        # Verify the update was applied (summary should now contain "Updated")
        updated_summary = event_data.get("summary", "")
        assert "Updated" in updated_summary, (
            f"Summary should be updated, got: {updated_summary}"
        )

    def test_add_recurrence(self, composio_client, user_id, created_event):
        """Test CUSTOM_ADD_RECURRENCE adds recurrence to an event."""
        result = execute_tool(
            composio_client,
            "GOOGLECALENDAR_CUSTOM_ADD_RECURRENCE",
            {
                "event_id": created_event["event_id"],
                "calendar_id": created_event["calendar_id"],
                "frequency": "WEEKLY",
                "count": 4,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

        # ADD_RECURRENCE returns the updated event + recurrence_rule
        data = result.get("data", {})
        assert data, "Expected response data from ADD_RECURRENCE"

        # Check for recurrence_rule string (the tool's actual return format)
        recurrence_rule = data.get("recurrence_rule", "")
        assert recurrence_rule, "Expected 'recurrence_rule' in response"
        assert "WEEKLY" in recurrence_rule, (
            f"Should contain WEEKLY, got: {recurrence_rule}"
        )

        # Also verify event was returned
        event_data = data.get("event", {})
        assert event_data, "Expected 'event' in response"


class TestCalendarErrorHandling:
    """Tests for error handling scenarios."""

    def test_get_nonexistent_event(self, composio_client, user_id, calendar_id):
        """Test CUSTOM_GET_EVENT with non-existent event ID returns error."""
        result = execute_tool(
            composio_client,
            "GOOGLECALENDAR_CUSTOM_GET_EVENT",
            {
                "events": [
                    {
                        "event_id": "nonexistent_event_id_12345",
                        "calendar_id": calendar_id,
                    }
                ]
            },
            user_id,
        )
        assert not result.get("successful"), "Should fail for nonexistent event"

    def test_delete_nonexistent_event(self, composio_client, user_id, calendar_id):
        """Test CUSTOM_DELETE_EVENT with non-existent event ID returns error."""
        result = execute_tool(
            composio_client,
            "GOOGLECALENDAR_CUSTOM_DELETE_EVENT",
            {
                "events": [
                    {
                        "event_id": "nonexistent_delete_id_67890",
                        "calendar_id": calendar_id,
                    }
                ],
                "send_updates": "none",
            },
            user_id,
        )
        assert not result.get("successful"), "Should fail for nonexistent event"

    def test_create_event_invalid_calendar(self, composio_client, user_id):
        """Test CUSTOM_CREATE_EVENT with invalid calendar ID returns error."""
        start_time = (datetime.now() + timedelta(hours=1)).isoformat()

        result = execute_tool(
            composio_client,
            "GOOGLECALENDAR_CUSTOM_CREATE_EVENT",
            {
                "events": [
                    {
                        "summary": "[PYTEST-ERROR] Invalid Calendar Event",
                        "start_datetime": start_time,
                        "duration_hours": 1.0,
                        "duration_minutes": 0.0,
                        "calendar_id": "invalid_calendar_does_not_exist@group.calendar.google.com",
                    }
                ],
                "confirm_immediately": True,
            },
            user_id,
        )
        assert (
            not result.get("successful")
            or result.get("data") == "Tool input validation error"
        ), "Should fail for invalid calendar"
