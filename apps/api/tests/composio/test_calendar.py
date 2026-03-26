"""Unit tests for calendar_tool.py custom tool handler functions.

These tests exercise every inner function registered by
``register_calendar_custom_tools`` by calling those functions directly after
extracting them from a mock Composio client.  They do **not** require real
API credentials; all network I/O and service-layer calls are replaced with
``unittest.mock`` objects.

What is being tested
--------------------
All nine handler functions defined inside
``app.agents.tools.integrations.calendar_tool.register_calendar_custom_tools``:

* CUSTOM_LIST_CALENDARS
* CUSTOM_GET_DAY_SUMMARY
* CUSTOM_FETCH_EVENTS
* CUSTOM_FIND_EVENT
* CUSTOM_GET_EVENT
* CUSTOM_DELETE_EVENT
* CUSTOM_PATCH_EVENT
* CUSTOM_ADD_RECURRENCE
* CUSTOM_CREATE_EVENT

For each handler the test suite covers:

* Happy path – service / HTTP returns success; verify the return value
  structure matches the documented contract.
* Error path – service / HTTP raises an error (HTTPStatusError, ValueError,
  RuntimeError); verify the handler propagates the exception or raises the
  expected exception type.

Markers
-------
All tests are tagged ``@pytest.mark.composio`` because they live in the
``tests/composio/`` directory (auto-marked by the conftest) and we add the
marker explicitly at class level for clarity.

Import coupling
---------------
The import at the top of this file::

    from app.agents.tools.integrations.calendar_tool import register_calendar_custom_tools

means that if ``calendar_tool.py`` is deleted or the function is renamed,
**every test in this module will fail**, which is the intended behaviour.
"""

from __future__ import annotations

import httpx
import pytest
from unittest.mock import MagicMock, patch

from app.agents.tools.integrations.calendar_tool import (
    _get_access_token,
    _get_user_id,
    _auth_headers,
    register_calendar_custom_tools,
)
from app.models.calendar_models import (
    AddRecurrenceInput,
    CreateEventInput,
    DeleteEventInput,
    EventReference,
    FetchEventsInput,
    FindEventInput,
    GetDaySummaryInput,
    GetEventInput,
    ListCalendarsInput,
    PatchEventInput,
    SingleEventInput,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_composio_mock() -> tuple[MagicMock, dict[str, MagicMock]]:
    """Return a (composio_mock, handlers) pair.

    Calling ``register_calendar_custom_tools(composio_mock)`` causes the
    decorator ``composio.tools.custom_tool(toolkit=...)`` to be invoked for
    each handler.  We capture every decorated function so the tests can call
    them directly.
    """
    captured: dict[str, MagicMock] = {}

    def _fake_custom_tool(toolkit: str):
        """Mimic @composio.tools.custom_tool(toolkit=...) decorator."""

        def _decorator(fn):
            captured[fn.__name__] = fn
            return fn

        return _decorator

    composio = MagicMock()
    composio.tools.custom_tool.side_effect = _fake_custom_tool

    register_calendar_custom_tools(composio)
    return composio, captured


def _http_status_error(
    status_code: int, method: str = "GET", url: str = "https://example.com"
) -> httpx.HTTPStatusError:
    """Build a minimal httpx.HTTPStatusError for testing."""
    request = httpx.Request(method, url)
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=request,
        response=response,
    )


AUTH_CREDS_BASIC = {"access_token": "test-token-abc", "user_id": "user-42"}
EXECUTE_REQUEST_STUB = None  # handlers never use this arg; keep it None


# ===========================================================================
# Tests for pure helper functions
# ===========================================================================


@pytest.mark.composio
class TestHelpers:
    """Tests for the module-level helper functions in calendar_tool.py."""

    def test_get_access_token_success(self):
        token = _get_access_token({"access_token": "tok123"})
        assert token == "tok123"

    def test_get_access_token_missing_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            _get_access_token({})

    def test_get_access_token_none_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            _get_access_token({"access_token": None})

    def test_get_user_id_present(self):
        uid = _get_user_id({"user_id": "u99"})
        assert uid == "u99"

    def test_get_user_id_absent_returns_empty(self):
        uid = _get_user_id({})
        assert uid == ""

    def test_auth_headers_format(self):
        headers = _auth_headers("mytoken")
        assert headers == {"Authorization": "Bearer mytoken"}


# ===========================================================================
# Tests for CUSTOM_LIST_CALENDARS
# ===========================================================================


@pytest.mark.composio
class TestCustomListCalendars:
    """Tests for the CUSTOM_LIST_CALENDARS handler."""

    def setup_method(self):
        _, self.handlers = _make_composio_mock()
        self.handler = self.handlers["CUSTOM_LIST_CALENDARS"]

    def test_happy_path_short(self):
        fake_calendars = [{"id": "cal1", "summary": "Work"}]
        with patch(
            "app.agents.tools.integrations.calendar_tool.calendar_service.list_calendars",
            return_value=fake_calendars,
        ) as mock_list:
            result = self.handler(
                request=ListCalendarsInput(short=True),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDS_BASIC,
            )

        assert result == {"calendars": fake_calendars}
        mock_list.assert_called_once_with("test-token-abc", short=True)

    def test_happy_path_full(self):
        fake_calendars = [{"id": "cal1"}, {"id": "cal2"}]
        with patch(
            "app.agents.tools.integrations.calendar_tool.calendar_service.list_calendars",
            return_value=fake_calendars,
        ):
            result = self.handler(
                request=ListCalendarsInput(short=False),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials=AUTH_CREDS_BASIC,
            )

        assert result["calendars"] == fake_calendars

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self.handler(
                request=ListCalendarsInput(),
                execute_request=EXECUTE_REQUEST_STUB,
                auth_credentials={},
            )

    def test_service_raises_propagates(self):
        with patch(
            "app.agents.tools.integrations.calendar_tool.calendar_service.list_calendars",
            side_effect=RuntimeError("Google API down"),
        ):
            with pytest.raises(RuntimeError, match="Google API down"):
                self.handler(
                    request=ListCalendarsInput(),
                    execute_request=EXECUTE_REQUEST_STUB,
                    auth_credentials=AUTH_CREDS_BASIC,
                )


# ===========================================================================
# Tests for CUSTOM_GET_DAY_SUMMARY
# ===========================================================================


@pytest.mark.composio
class TestCustomGetDaySummary:
    """Tests for the CUSTOM_GET_DAY_SUMMARY handler."""

    def setup_method(self):
        _, self.handlers = _make_composio_mock()
        self.handler = self.handlers["CUSTOM_GET_DAY_SUMMARY"]

    def _run(self, request: GetDaySummaryInput, creds=None):
        creds = AUTH_CREDS_BASIC if creds is None else creds
        return self.handler(
            request=request,
            execute_request=EXECUTE_REQUEST_STUB,
            auth_credentials=creds,
        )

    def _patch_services(self, events=None):
        """Context-manager helper that patches calendar_service calls."""
        events = events or []
        get_events_patch = patch(
            "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_events",
            return_value={"events": events},
        )
        metadata_patch = patch(
            "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
            return_value=({}, {}),
        )
        format_patch = patch(
            "app.agents.tools.integrations.calendar_tool.calendar_service.format_event_for_frontend",
            side_effect=lambda ev, cm, nm: ev,
        )
        user_patch = patch(
            "app.agents.tools.integrations.calendar_tool.user_service.get_user_by_id",
            return_value={"timezone": "UTC"},
        )
        return get_events_patch, metadata_patch, format_patch, user_patch

    def test_happy_path_today_no_events(self):
        p1, p2, p3, p4 = self._patch_services(events=[])
        with p1, p2, p3, p4:
            result = self._run(GetDaySummaryInput(date=None))

        assert "date" in result
        assert "timezone" in result
        assert result["events"] == []
        assert result["busy_hours"] == pytest.approx(0.0)
        assert result["next_event"] is None

    def test_happy_path_specific_date(self):
        p1, p2, p3, p4 = self._patch_services(events=[])
        with p1, p2, p3, p4:
            result = self._run(GetDaySummaryInput(date="2026-03-03"))

        assert result["date"] == "2026-03-03"

    def test_busy_hours_calculated_correctly(self):
        """One 60-minute event should produce busy_hours == 1.0."""
        events = [
            {
                "start": {"dateTime": "2026-03-03T09:00:00+00:00"},
                "end": {"dateTime": "2026-03-03T10:00:00+00:00"},
            }
        ]
        p1, p2, p3, p4 = self._patch_services(events=events)
        with p1, p2, p3, p4:
            result = self._run(GetDaySummaryInput(date="2026-03-03"))

        assert result["busy_hours"] == pytest.approx(1.0)

    def test_busy_hours_multiple_events(self):
        """30 + 90 minutes → 2.0 hours."""
        events = [
            {
                "start": {"dateTime": "2026-03-03T08:00:00+00:00"},
                "end": {"dateTime": "2026-03-03T08:30:00+00:00"},
            },
            {
                "start": {"dateTime": "2026-03-03T10:00:00+00:00"},
                "end": {"dateTime": "2026-03-03T11:30:00+00:00"},
            },
        ]
        p1, p2, p3, p4 = self._patch_services(events=events)
        with p1, p2, p3, p4:
            result = self._run(GetDaySummaryInput(date="2026-03-03"))

        assert result["busy_hours"] == pytest.approx(2.0)

    def test_invalid_date_format_raises(self):
        p1, p2, p3, p4 = self._patch_services()
        with p1, p2, p3, p4:
            with pytest.raises(ValueError, match="Invalid date format"):
                self._run(GetDaySummaryInput(date="not-a-date"))

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self._run(GetDaySummaryInput(), creds={})

    def test_all_day_events_do_not_contribute_busy_hours(self):
        """Events with only 'date' keys (all-day) should not affect busy_hours."""
        events = [{"start": {"date": "2026-03-03"}, "end": {"date": "2026-03-04"}}]
        p1, p2, p3, p4 = self._patch_services(events=events)
        with p1, p2, p3, p4:
            result = self._run(GetDaySummaryInput(date="2026-03-03"))

        assert result["busy_hours"] == pytest.approx(0.0)

    def test_metadata_failure_falls_back_to_raw_events(self):
        """If get_calendar_metadata_map raises, handler falls back to raw events."""
        events = [{"start": {"date": "2026-03-03"}, "end": {"date": "2026-03-04"}}]
        with (
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_events",
                return_value={"events": events},
            ),
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
                side_effect=RuntimeError("metadata unavailable"),
            ),
            patch(
                "app.agents.tools.integrations.calendar_tool.user_service.get_user_by_id",
                return_value={"timezone": "UTC"},
            ),
        ):
            result = self._run(GetDaySummaryInput(date="2026-03-03"))

        # Falls back to raw events (no format applied)
        assert result["events"] == events


# ===========================================================================
# Tests for CUSTOM_FETCH_EVENTS
# ===========================================================================


@pytest.mark.composio
class TestCustomFetchEvents:
    """Tests for the CUSTOM_FETCH_EVENTS handler."""

    def setup_method(self):
        _, self.handlers = _make_composio_mock()
        self.handler = self.handlers["CUSTOM_FETCH_EVENTS"]

    def _run(self, request: FetchEventsInput, creds=None):
        creds = AUTH_CREDS_BASIC if creds is None else creds
        return self.handler(
            request=request,
            execute_request=EXECUTE_REQUEST_STUB,
            auth_credentials=creds,
        )

    def test_happy_path_with_events(self):
        events = [{"id": "ev1", "summary": "Team meeting"}]
        with (
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_events",
                return_value={"events": events, "has_more": False},
            ),
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
                return_value=({}, {}),
            ),
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.format_event_for_frontend",
                side_effect=lambda ev, cm, nm: ev,
            ),
        ):
            result = self._run(FetchEventsInput())

        assert "calendar_fetch_data" in result
        assert result["has_more"] is False
        assert len(result["calendar_fetch_data"]) == 1

    def test_happy_path_empty_events(self):
        with (
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_events",
                return_value={"events": [], "has_more": False},
            ),
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
                return_value=({}, {}),
            ),
        ):
            result = self._run(FetchEventsInput())

        assert result["calendar_fetch_data"] == []
        assert result["has_more"] is False

    def test_calendar_ids_passed_through(self):
        """Specific calendar IDs should be forwarded to get_calendar_events."""
        with (
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_events",
                return_value={"events": [], "has_more": False},
            ) as mock_get,
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
                return_value=({}, {}),
            ),
        ):
            self._run(FetchEventsInput(calendar_ids=["cal-work", "cal-personal"]))

        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["selected_calendars"] == ["cal-work", "cal-personal"]

    def test_empty_calendar_ids_passes_none(self):
        """Empty calendar_ids list should pass None (fetch from all)."""
        with (
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_events",
                return_value={"events": [], "has_more": False},
            ) as mock_get,
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
                return_value=({}, {}),
            ),
        ):
            self._run(FetchEventsInput(calendar_ids=[]))

        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["selected_calendars"] is None

    def test_metadata_failure_falls_back_to_raw_events(self):
        events = [{"id": "ev1"}]
        with (
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_events",
                return_value={"events": events, "has_more": False},
            ),
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
                side_effect=RuntimeError("metadata unavailable"),
            ),
        ):
            result = self._run(FetchEventsInput())

        # Raw events used as fallback
        assert result["calendar_fetch_data"] == events

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self._run(FetchEventsInput(), creds={})


# ===========================================================================
# Tests for CUSTOM_FIND_EVENT
# ===========================================================================


@pytest.mark.composio
class TestCustomFindEvent:
    """Tests for the CUSTOM_FIND_EVENT handler."""

    def setup_method(self):
        _, self.handlers = _make_composio_mock()
        self.handler = self.handlers["CUSTOM_FIND_EVENT"]

    def _run(self, request: FindEventInput, creds=None):
        creds = AUTH_CREDS_BASIC if creds is None else creds
        return self.handler(
            request=request,
            execute_request=EXECUTE_REQUEST_STUB,
            auth_credentials=creds,
        )

    def test_happy_path_finds_events(self):
        matching = [{"id": "ev42", "summary": "Sprint review"}]
        with (
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.search_calendar_events_native",
                return_value={"matching_events": matching},
            ),
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
                return_value=({}, {}),
            ),
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.format_event_for_frontend",
                side_effect=lambda ev, cm, nm: ev,
            ),
        ):
            result = self._run(FindEventInput(query="sprint"))

        assert "events" in result
        assert "calendar_search_data" in result
        assert result["events"] == matching
        assert result["calendar_search_data"] == matching

    def test_happy_path_no_matches(self):
        with (
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.search_calendar_events_native",
                return_value={"matching_events": []},
            ),
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
                return_value=({}, {}),
            ),
        ):
            result = self._run(FindEventInput(query="nothing"))

        assert result["events"] == []
        assert result["calendar_search_data"] == []

    def test_query_forwarded_to_service(self):
        with (
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.search_calendar_events_native",
                return_value={"matching_events": []},
            ) as mock_search,
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
                return_value=({}, {}),
            ),
        ):
            self._run(FindEventInput(query="dentist appointment"))

        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs["query"] == "dentist appointment"

    def test_metadata_failure_falls_back_to_raw(self):
        matching = [{"id": "ev1"}]
        with (
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.search_calendar_events_native",
                return_value={"matching_events": matching},
            ),
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
                side_effect=RuntimeError("oops"),
            ),
        ):
            result = self._run(FindEventInput(query="test"))

        assert result["calendar_search_data"] == matching

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self._run(FindEventInput(query="test"), creds={})


# ===========================================================================
# Tests for CUSTOM_GET_EVENT
# ===========================================================================


@pytest.mark.composio
class TestCustomGetEvent:
    """Tests for the CUSTOM_GET_EVENT handler."""

    def setup_method(self):
        _, self.handlers = _make_composio_mock()
        self.handler = self.handlers["CUSTOM_GET_EVENT"]

    def _run(self, request: GetEventInput, creds=None):
        creds = AUTH_CREDS_BASIC if creds is None else creds
        return self.handler(
            request=request,
            execute_request=EXECUTE_REQUEST_STUB,
            auth_credentials=creds,
        )

    def _make_request(self, event_id="ev1", calendar_id="primary") -> GetEventInput:
        return GetEventInput(
            events=[EventReference(event_id=event_id, calendar_id=calendar_id)]
        )

    def test_happy_path_single_event(self):
        fake_event = {"id": "ev1", "summary": "Standup"}
        mock_response = MagicMock()
        mock_response.json.return_value = fake_event
        mock_response.raise_for_status.return_value = None

        with patch(
            "app.agents.tools.integrations.calendar_tool._http_client.get",
            return_value=mock_response,
        ):
            result = self._run(self._make_request("ev1"))

        assert "events" in result
        assert len(result["events"]) == 1
        assert result["events"][0]["event_id"] == "ev1"
        assert result["events"][0]["event"] == fake_event

    def test_happy_path_multiple_events(self):
        fake_event = {"id": "evX", "summary": "Meeting"}
        mock_response = MagicMock()
        mock_response.json.return_value = fake_event
        mock_response.raise_for_status.return_value = None

        request = GetEventInput(
            events=[
                EventReference(event_id="evA", calendar_id="primary"),
                EventReference(event_id="evB", calendar_id="work@group.calendar"),
            ]
        )

        with patch(
            "app.agents.tools.integrations.calendar_tool._http_client.get",
            return_value=mock_response,
        ):
            result = self._run(request)

        assert len(result["events"]) == 2

    def test_http_404_all_events_fail_raises_runtime_error(self):
        """When all requests fail, the handler must raise RuntimeError."""
        with patch(
            "app.agents.tools.integrations.calendar_tool._http_client.get",
            side_effect=_http_status_error(404),
        ):
            with pytest.raises(RuntimeError, match="Failed to get events"):
                self._run(self._make_request("missing-ev"))

    def test_partial_failure_returns_successful_events(self):
        """If at least one event succeeds the call should NOT raise."""
        fake_event = {"id": "evGood", "summary": "OK"}
        good_resp = MagicMock()
        good_resp.json.return_value = fake_event
        good_resp.raise_for_status.return_value = None

        def _side_effect(url, headers):
            if "evBad" in url:
                raise _http_status_error(404)
            return good_resp

        request = GetEventInput(
            events=[
                EventReference(event_id="evGood", calendar_id="primary"),
                EventReference(event_id="evBad", calendar_id="primary"),
            ]
        )

        with patch(
            "app.agents.tools.integrations.calendar_tool._http_client.get",
            side_effect=_side_effect,
        ):
            result = self._run(request)

        assert len(result["events"]) == 1
        assert result["events"][0]["event_id"] == "evGood"

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self._run(self._make_request(), creds={})


# ===========================================================================
# Tests for CUSTOM_DELETE_EVENT
# ===========================================================================


@pytest.mark.composio
class TestCustomDeleteEvent:
    """Tests for the CUSTOM_DELETE_EVENT handler."""

    def setup_method(self):
        _, self.handlers = _make_composio_mock()
        self.handler = self.handlers["CUSTOM_DELETE_EVENT"]

    def _run(self, request: DeleteEventInput, creds=None):
        creds = AUTH_CREDS_BASIC if creds is None else creds
        return self.handler(
            request=request,
            execute_request=EXECUTE_REQUEST_STUB,
            auth_credentials=creds,
        )

    def _make_request(self, event_id="ev1", calendar_id="primary") -> DeleteEventInput:
        return DeleteEventInput(
            events=[EventReference(event_id=event_id, calendar_id=calendar_id)],
            send_updates="all",
        )

    def test_happy_path_single_delete(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None

        with patch(
            "app.agents.tools.integrations.calendar_tool._http_client.delete",
            return_value=mock_response,
        ):
            result = self._run(self._make_request("ev1"))

        assert "deleted" in result
        assert len(result["deleted"]) == 1
        assert result["deleted"][0]["event_id"] == "ev1"
        assert result["deleted"][0]["calendar_id"] == "primary"

    def test_happy_path_multiple_deletes(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None

        request = DeleteEventInput(
            events=[
                EventReference(event_id="ev1", calendar_id="primary"),
                EventReference(event_id="ev2", calendar_id="primary"),
            ],
            send_updates="none",
        )

        with patch(
            "app.agents.tools.integrations.calendar_tool._http_client.delete",
            return_value=mock_response,
        ):
            result = self._run(request)

        assert len(result["deleted"]) == 2

    def test_http_404_all_fail_raises_runtime_error(self):
        with patch(
            "app.agents.tools.integrations.calendar_tool._http_client.delete",
            side_effect=_http_status_error(404),
        ):
            with pytest.raises(RuntimeError, match="Failed to delete events"):
                self._run(self._make_request("non-existent"))

    def test_http_401_all_fail_raises_runtime_error(self):
        with patch(
            "app.agents.tools.integrations.calendar_tool._http_client.delete",
            side_effect=_http_status_error(401),
        ):
            with pytest.raises(RuntimeError, match="Failed to delete events"):
                self._run(self._make_request())

    def test_partial_failure_returns_successful_deletions(self):
        good_resp = MagicMock()
        good_resp.raise_for_status.return_value = None

        def _side_effect(url, headers, params):
            if "evBad" in url:
                raise _http_status_error(404)
            return good_resp

        request = DeleteEventInput(
            events=[
                EventReference(event_id="evGood", calendar_id="primary"),
                EventReference(event_id="evBad", calendar_id="primary"),
            ],
        )

        with patch(
            "app.agents.tools.integrations.calendar_tool._http_client.delete",
            side_effect=_side_effect,
        ):
            result = self._run(request)

        assert len(result["deleted"]) == 1
        assert result["deleted"][0]["event_id"] == "evGood"

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self._run(self._make_request(), creds={})


# ===========================================================================
# Tests for CUSTOM_PATCH_EVENT
# ===========================================================================


@pytest.mark.composio
class TestCustomPatchEvent:
    """Tests for the CUSTOM_PATCH_EVENT handler."""

    def setup_method(self):
        _, self.handlers = _make_composio_mock()
        self.handler = self.handlers["CUSTOM_PATCH_EVENT"]

    def _run(self, request: PatchEventInput, creds=None):
        creds = AUTH_CREDS_BASIC if creds is None else creds
        return self.handler(
            request=request,
            execute_request=EXECUTE_REQUEST_STUB,
            auth_credentials=creds,
        )

    def test_happy_path_patch_summary(self):
        updated_event = {"id": "ev1", "summary": "New Title"}
        mock_response = MagicMock()
        mock_response.json.return_value = updated_event
        mock_response.raise_for_status.return_value = None

        with patch(
            "app.agents.tools.integrations.calendar_tool._http_client.patch",
            return_value=mock_response,
        ) as mock_patch:
            result = self._run(
                PatchEventInput(
                    event_id="ev1", calendar_id="primary", summary="New Title"
                )
            )

        assert result == {"event": updated_event}
        _, kwargs = mock_patch.call_args
        assert kwargs["json"]["summary"] == "New Title"

    def test_happy_path_patch_times(self):
        updated_event = {"id": "ev1"}
        mock_response = MagicMock()
        mock_response.json.return_value = updated_event
        mock_response.raise_for_status.return_value = None

        with patch(
            "app.agents.tools.integrations.calendar_tool._http_client.patch",
            return_value=mock_response,
        ) as mock_patch:
            self._run(
                PatchEventInput(
                    event_id="ev1",
                    calendar_id="primary",
                    start_datetime="2026-03-04T10:00:00+00:00",
                    end_datetime="2026-03-04T11:00:00+00:00",
                )
            )

        _, kwargs = mock_patch.call_args
        assert "start" in kwargs["json"]
        assert "end" in kwargs["json"]

    def test_happy_path_patch_attendees(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": "ev1"}
        mock_response.raise_for_status.return_value = None

        with patch(
            "app.agents.tools.integrations.calendar_tool._http_client.patch",
            return_value=mock_response,
        ) as mock_patch:
            self._run(
                PatchEventInput(
                    event_id="ev1",
                    attendees=["alice@example.com", "bob@example.com"],
                )
            )

        _, kwargs = mock_patch.call_args
        attendees = kwargs["json"]["attendees"]
        assert {"email": "alice@example.com"} in attendees
        assert {"email": "bob@example.com"} in attendees

    def test_none_fields_not_included_in_body(self):
        """Fields left as None must not appear in the PATCH body."""
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status.return_value = None

        with patch(
            "app.agents.tools.integrations.calendar_tool._http_client.patch",
            return_value=mock_response,
        ) as mock_patch:
            self._run(PatchEventInput(event_id="ev1"))

        _, kwargs = mock_patch.call_args
        body = kwargs["json"]
        assert "summary" not in body
        assert "description" not in body
        assert "location" not in body
        assert "start" not in body
        assert "end" not in body
        assert "attendees" not in body

    def test_http_error_propagates(self):
        with patch(
            "app.agents.tools.integrations.calendar_tool._http_client.patch",
            side_effect=_http_status_error(403),
        ):
            with pytest.raises(httpx.HTTPStatusError):
                self._run(PatchEventInput(event_id="ev1", summary="Updated"))

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self._run(PatchEventInput(event_id="ev1"), creds={})


# ===========================================================================
# Tests for CUSTOM_ADD_RECURRENCE
# ===========================================================================


@pytest.mark.composio
class TestCustomAddRecurrence:
    """Tests for the CUSTOM_ADD_RECURRENCE handler."""

    def setup_method(self):
        _, self.handlers = _make_composio_mock()
        self.handler = self.handlers["CUSTOM_ADD_RECURRENCE"]

    def _run(self, request: AddRecurrenceInput, creds=None):
        creds = AUTH_CREDS_BASIC if creds is None else creds
        return self.handler(
            request=request,
            execute_request=EXECUTE_REQUEST_STUB,
            auth_credentials=creds,
        )

    def _make_mock_client(self, existing_event: dict | None = None):
        """Return a mock _http_client with GET returning existing_event."""
        existing_event = existing_event or {"id": "ev1", "summary": "Standup"}

        get_resp = MagicMock()
        get_resp.json.return_value = existing_event
        get_resp.raise_for_status.return_value = None

        put_resp = MagicMock()
        put_resp.json.return_value = {
            **existing_event,
            "recurrence": ["RRULE:FREQ=DAILY"],
        }
        put_resp.raise_for_status.return_value = None

        client = MagicMock()
        client.get.return_value = get_resp
        client.put.return_value = put_resp
        return client, get_resp, put_resp

    def test_happy_path_daily_recurrence(self):
        client, _, _ = self._make_mock_client()
        with patch("app.agents.tools.integrations.calendar_tool._http_client", client):
            result = self._run(
                AddRecurrenceInput(
                    event_id="ev1",
                    calendar_id="primary",
                    frequency="DAILY",
                )
            )

        assert "event" in result
        assert "recurrence_rule" in result
        assert result["recurrence_rule"].startswith("RRULE:FREQ=DAILY")

    def test_happy_path_weekly_with_byday(self):
        client, _, put_resp = self._make_mock_client()
        put_resp.json.return_value = {
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"]
        }

        with patch("app.agents.tools.integrations.calendar_tool._http_client", client):
            result = self._run(
                AddRecurrenceInput(
                    event_id="ev1",
                    frequency="WEEKLY",
                    by_day=["MO", "WE", "FR"],
                )
            )

        assert "BYDAY=MO,WE,FR" in result["recurrence_rule"]

    def test_happy_path_with_count(self):
        client, _, _ = self._make_mock_client()
        with patch("app.agents.tools.integrations.calendar_tool._http_client", client):
            result = self._run(
                AddRecurrenceInput(
                    event_id="ev1",
                    frequency="DAILY",
                    count=10,
                )
            )

        assert "COUNT=10" in result["recurrence_rule"]

    def test_happy_path_with_until_date(self):
        client, _, _ = self._make_mock_client()
        with patch("app.agents.tools.integrations.calendar_tool._http_client", client):
            result = self._run(
                AddRecurrenceInput(
                    event_id="ev1",
                    frequency="MONTHLY",
                    until_date="2026-12-31",
                )
            )

        assert "UNTIL=20261231" in result["recurrence_rule"]

    def test_interval_included_when_not_one(self):
        client, _, _ = self._make_mock_client()
        with patch("app.agents.tools.integrations.calendar_tool._http_client", client):
            result = self._run(
                AddRecurrenceInput(
                    event_id="ev1",
                    frequency="WEEKLY",
                    interval=2,
                )
            )

        assert "INTERVAL=2" in result["recurrence_rule"]

    def test_interval_not_included_when_one(self):
        client, _, _ = self._make_mock_client()
        with patch("app.agents.tools.integrations.calendar_tool._http_client", client):
            result = self._run(
                AddRecurrenceInput(event_id="ev1", frequency="DAILY", interval=1)
            )

        assert "INTERVAL" not in result["recurrence_rule"]

    def test_get_fails_propagates(self):
        with patch(
            "app.agents.tools.integrations.calendar_tool._http_client.get",
            side_effect=_http_status_error(404),
        ):
            with pytest.raises(httpx.HTTPStatusError):
                self._run(AddRecurrenceInput(event_id="missing", frequency="DAILY"))

    def test_put_fails_propagates(self):
        existing_event = {"id": "ev1"}
        get_resp = MagicMock()
        get_resp.json.return_value = existing_event
        get_resp.raise_for_status.return_value = None

        client = MagicMock()
        client.get.return_value = get_resp
        client.put.side_effect = _http_status_error(500)

        with patch("app.agents.tools.integrations.calendar_tool._http_client", client):
            with pytest.raises(httpx.HTTPStatusError):
                self._run(AddRecurrenceInput(event_id="ev1", frequency="DAILY"))

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self._run(
                AddRecurrenceInput(event_id="ev1", frequency="DAILY"),
                creds={},
            )


# ===========================================================================
# Tests for CUSTOM_CREATE_EVENT
# ===========================================================================


@pytest.mark.composio
class TestCustomCreateEvent:
    """Tests for the CUSTOM_CREATE_EVENT handler."""

    def setup_method(self):
        _, self.handlers = _make_composio_mock()
        self.handler = self.handlers["CUSTOM_CREATE_EVENT"]

    def _run(self, request: CreateEventInput, creds=None):
        creds = AUTH_CREDS_BASIC if creds is None else creds
        return self.handler(
            request=request,
            execute_request=EXECUTE_REQUEST_STUB,
            auth_credentials=creds,
        )

    def _single_event_input(self, **kwargs) -> SingleEventInput:
        defaults = {
            "summary": "Test Event",
            "start_datetime": "2026-03-10T10:00:00+00:00",
            "duration_hours": 1,
            "duration_minutes": 0,
            "calendar_id": "primary",
        }
        defaults.update(kwargs)
        return SingleEventInput(**defaults)

    # ---- confirm_immediately=True (immediate creation) ----

    def test_confirm_immediately_creates_event(self):
        created = {"id": "new-ev1", "htmlLink": "https://cal.google.com/ev1"}
        mock_response = MagicMock()
        mock_response.json.return_value = created
        mock_response.raise_for_status.return_value = None

        with (
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
                return_value=({}, {}),
            ),
            patch(
                "app.agents.tools.integrations.calendar_tool._http_client.post",
                return_value=mock_response,
            ),
        ):
            result = self._run(
                CreateEventInput(
                    events=[self._single_event_input()],
                    confirm_immediately=True,
                )
            )

        assert result["created"] is True
        assert len(result["created_events"]) == 1
        ev = result["created_events"][0]
        assert ev["event_id"] == "new-ev1"
        assert ev["summary"] == "Test Event"
        assert ev["calendar_id"] == "primary"

    def test_confirm_immediately_multiple_events(self):
        created_ev = {"id": "evX", "htmlLink": "https://cal.google.com/evX"}
        mock_response = MagicMock()
        mock_response.json.return_value = created_ev
        mock_response.raise_for_status.return_value = None

        events = [
            self._single_event_input(summary="Event A"),
            self._single_event_input(summary="Event B"),
        ]

        with (
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
                return_value=({}, {}),
            ),
            patch(
                "app.agents.tools.integrations.calendar_tool._http_client.post",
                return_value=mock_response,
            ),
        ):
            result = self._run(
                CreateEventInput(events=events, confirm_immediately=True)
            )

        assert len(result["created_events"]) == 2

    def test_confirm_immediately_http_error_propagates(self):
        with (
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
                return_value=({}, {}),
            ),
            patch(
                "app.agents.tools.integrations.calendar_tool._http_client.post",
                side_effect=_http_status_error(500, method="POST"),
            ),
        ):
            with pytest.raises(httpx.HTTPStatusError):
                self._run(
                    CreateEventInput(
                        events=[self._single_event_input()],
                        confirm_immediately=True,
                    )
                )

    # ---- confirm_immediately=False (prepare for frontend confirmation) ----

    def test_prepare_for_confirmation_returns_calendar_options(self):
        color_map = {"primary": "#4285f4"}
        name_map = {"primary": "My Calendar"}
        with patch(
            "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
            return_value=(color_map, name_map),
        ):
            result = self._run(
                CreateEventInput(
                    events=[self._single_event_input()],
                    confirm_immediately=False,
                )
            )

        assert result["created"] is False
        assert "calendar_options" in result
        assert len(result["calendar_options"]) == 1
        opt = result["calendar_options"][0]
        assert opt["summary"] == "Test Event"
        assert opt["calendar_id"] == "primary"
        assert opt["color"] == "#4285f4"
        assert opt["calendar_name"] == "My Calendar"

    def test_prepare_for_confirmation_message_present(self):
        with patch(
            "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
            return_value=({}, {}),
        ):
            result = self._run(
                CreateEventInput(
                    events=[self._single_event_input()],
                    confirm_immediately=False,
                )
            )

        assert "message" in result
        assert "1 event(s) prepared" in result["message"]

    def test_unknown_calendar_uses_default_color(self):
        """Calendar not in color_map should fall back to #4285f4."""
        with patch(
            "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
            return_value=({}, {}),
        ):
            result = self._run(
                CreateEventInput(
                    events=[self._single_event_input(calendar_id="unknown-cal")],
                    confirm_immediately=False,
                )
            )

        opt = result["calendar_options"][0]
        assert opt["color"] == "#4285f4"

    # ---- timezone handling ----

    def test_naive_datetime_defaults_to_utc(self):
        """A start_datetime without timezone info should be treated as UTC."""
        created = {"id": "evUTC", "htmlLink": "https://cal.google.com/evUTC"}
        mock_response = MagicMock()
        mock_response.json.return_value = created
        mock_response.raise_for_status.return_value = None

        with (
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
                return_value=({}, {}),
            ),
            patch(
                "app.agents.tools.integrations.calendar_tool._http_client.post",
                return_value=mock_response,
            ) as mock_post,
        ):
            self._run(
                CreateEventInput(
                    events=[
                        self._single_event_input(start_datetime="2026-05-01T09:00:00")
                    ],
                    confirm_immediately=True,
                )
            )

        _, kwargs = mock_post.call_args
        start_dt_str = kwargs["json"]["start"]["dateTime"]
        # Should contain UTC offset info
        assert "+00:00" in start_dt_str or "Z" in start_dt_str

    # ---- all-day events ----

    def test_all_day_event_uses_date_format(self):
        with patch(
            "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
            return_value=({}, {}),
        ):
            result = self._run(
                CreateEventInput(
                    events=[self._single_event_input(is_all_day=True)],
                    confirm_immediately=False,
                )
            )

        opt = result["calendar_options"][0]
        assert "date" in opt["start"]
        assert "dateTime" not in opt["start"]

    # ---- validation errors ----

    def test_invalid_start_datetime_skips_event(self):
        """An unparseable start_datetime causes the event to be skipped (error collected)."""
        with (
            patch(
                "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
                return_value=({}, {}),
            ),
        ):
            with pytest.raises(ValueError, match="All events failed validation"):
                self._run(
                    CreateEventInput(
                        events=[self._single_event_input(start_datetime="NOT-A-DATE")],
                        confirm_immediately=False,
                    )
                )

    def test_metadata_failure_falls_back_to_empty_maps(self):
        """If get_calendar_metadata_map raises, handler should fall back to empty maps."""
        with patch(
            "app.agents.tools.integrations.calendar_tool.calendar_service.get_calendar_metadata_map",
            side_effect=RuntimeError("service unavailable"),
        ):
            result = self._run(
                CreateEventInput(
                    events=[self._single_event_input()],
                    confirm_immediately=False,
                )
            )

        # Should still produce calendar_options with default color
        assert len(result["calendar_options"]) == 1
        assert result["calendar_options"][0]["color"] == "#4285f4"

    def test_missing_access_token_raises(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            self._run(
                CreateEventInput(events=[self._single_event_input()]),
                creds={},
            )


# ===========================================================================
# Tests for register_calendar_custom_tools return value
# ===========================================================================


@pytest.mark.composio
class TestRegisterCalendarCustomTools:
    """Verify that register_calendar_custom_tools registers the expected tool names."""

    def test_returns_expected_tool_slugs(self):
        _, _ = _make_composio_mock()

        # Invoke with a fresh mock to get the return value
        composio_mock2 = MagicMock()

        def _fake_custom_tool2(toolkit: str):
            def _decorator(fn):
                return fn

            return _decorator

        composio_mock2.tools.custom_tool.side_effect = _fake_custom_tool2
        result = register_calendar_custom_tools(composio_mock2)

        expected_slugs = {
            "GOOGLECALENDAR_CUSTOM_CREATE_EVENT",
            "GOOGLECALENDAR_CUSTOM_LIST_CALENDARS",
            "GOOGLECALENDAR_CUSTOM_GET_DAY_SUMMARY",
            "GOOGLECALENDAR_CUSTOM_FETCH_EVENTS",
            "GOOGLECALENDAR_CUSTOM_FIND_EVENT",
            "GOOGLECALENDAR_CUSTOM_GET_EVENT",
            "GOOGLECALENDAR_CUSTOM_DELETE_EVENT",
            "GOOGLECALENDAR_CUSTOM_PATCH_EVENT",
            "GOOGLECALENDAR_CUSTOM_ADD_RECURRENCE",
            "GOOGLECALENDAR_CUSTOM_GATHER_CONTEXT",
        }

        assert set(result) == expected_slugs

    def test_returns_ten_tools(self):
        composio_mock = MagicMock()

        def _fake(toolkit):
            def _d(fn):
                return fn

            return _d

        composio_mock.tools.custom_tool.side_effect = _fake
        result = register_calendar_custom_tools(composio_mock)
        assert len(result) == 10

    def test_all_ten_handlers_are_captured(self):
        """Ensure all ten inner functions are decorated and captured."""
        _, handlers = _make_composio_mock()
        expected_names = {
            "CUSTOM_LIST_CALENDARS",
            "CUSTOM_GET_DAY_SUMMARY",
            "CUSTOM_FETCH_EVENTS",
            "CUSTOM_FIND_EVENT",
            "CUSTOM_GET_EVENT",
            "CUSTOM_DELETE_EVENT",
            "CUSTOM_PATCH_EVENT",
            "CUSTOM_ADD_RECURRENCE",
            "CUSTOM_CREATE_EVENT",
            "CUSTOM_GATHER_CONTEXT",
        }
        assert set(handlers.keys()) == expected_names
