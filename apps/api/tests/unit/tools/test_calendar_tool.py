"""Unit tests for app.agents.tools.integrations.calendar_tool.

The pure helpers are exercised with no mocking at all; the Composio-registered
tool bodies are exercised for real with only the true I/O boundaries faked
(`proxy_request_sync`, the async `calendar_service` / `user_service` functions,
the LangGraph stream writer and config).

Five production bugs were found while writing these tests and fixed at the root
in `calendar_tool.py` / `calendar_models.py`; the tests that pin them down are
marked with a "BUG:" comment.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.agents.tools.integrations.calendar_tool import (
    _extract_datetime,
    _format_calendar_for_stream,
    _format_calendar_option_for_stream,
    _get_user_id,
    _get_user_timezone,
    _run_sync,
    register_calendar_custom_tools,
)
from app.constants.calendar import DEFAULT_CALENDAR_COLOR
from app.models.calendar_models import (
    AddRecurrenceInput,
    CalendarEventsResponse,
    CalendarListResponse,
    CalendarSearchResult,
    CalendarSummary,
    CreateEventInput,
    DeleteEventInput,
    EventReference,
    FetchEventsInput,
    FindEventInput,
    GetDaySummaryInput,
    GetEventInput,
    GoogleCalendarEventResource,
    ListCalendarsInput,
    PatchEventInput,
    SingleEventInput,
)
from app.models.common_models import GatherContextInput
from app.utils.calendar_utils import CALENDAR_API_BASE
from app.utils.concurrency import reset_captured_loop
from app.utils.errors import AppError

MODULE = "app.agents.tools.integrations.calendar_tool"
AUTH: dict[str, Any] = {"user_id": "user-42"}
EXECUTE_REQUEST = MagicMock()


def _tools() -> dict[str, Any]:
    """Register the calendar custom tools against a fake Composio and capture them."""
    captured: dict[str, Any] = {}
    composio = MagicMock()

    def custom_tool(**_kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            captured[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    register_calendar_custom_tools(composio)
    return captured


@pytest.fixture
def tools() -> dict[str, Any]:
    return _tools()


@pytest.fixture(autouse=True)
def _no_captured_server_loop() -> Iterator[None]:
    """Run the tool bodies in a loop-less sync context, like the e2e graph harness.

    With no captured server loop, `_run_sync` runs the (mocked, loop-agnostic)
    services on a fresh loop. Clearing the global guards against a captured loop
    leaking in from another test, which would make `_run_sync` dispatch onto a
    closed loop.
    """
    reset_captured_loop()
    yield
    reset_captured_loop()


@pytest.fixture
def writer():
    """Capture everything the tool pushes to the LangGraph stream."""
    sink = MagicMock()
    with patch(f"{MODULE}.get_stream_writer", return_value=sink):
        yield sink


def _event(payload: dict[str, Any]) -> GoogleCalendarEventResource:
    return GoogleCalendarEventResource.model_validate(payload)


def _timed_event(
    start: str, end: str, summary: str = "Event", calendar_id: str = "primary"
) -> GoogleCalendarEventResource:
    return _event(
        {
            "summary": summary,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
            "calendarId": calendar_id,
        }
    )


def _events_response(
    events: list[GoogleCalendarEventResource], *, has_more: bool = False
) -> CalendarEventsResponse:
    return CalendarEventsResponse(
        events=events, selected_calendars=[], has_more=has_more, calendars_truncated=[]
    )


# ---------------------------------------------------------------------------
# _extract_datetime
# ---------------------------------------------------------------------------


class TestExtractDatetime:
    def test_none_yields_empty_string(self) -> None:
        assert _extract_datetime(None) == ""

    def test_empty_dict_yields_empty_string(self) -> None:
        assert _extract_datetime({}) == ""

    def test_plain_string_passes_through(self) -> None:
        assert _extract_datetime("2026-01-15T10:00:00Z") == "2026-01-15T10:00:00Z"

    def test_datetime_key_wins_over_date(self) -> None:
        assert (
            _extract_datetime({"dateTime": "2026-01-15T10:00:00Z", "date": "2026-01-15"})
            == "2026-01-15T10:00:00Z"
        )

    def test_falls_back_to_date_for_all_day(self) -> None:
        assert _extract_datetime({"date": "2026-01-15"}) == "2026-01-15"

    def test_blank_datetime_falls_back_to_date(self) -> None:
        assert _extract_datetime({"dateTime": "", "date": "2026-01-15"}) == "2026-01-15"

    def test_dict_without_time_keys_yields_empty_string(self) -> None:
        assert _extract_datetime({"timeZone": "UTC"}) == ""

    def test_non_string_value_is_rejected(self) -> None:
        # Google never returns this, but a malformed payload must not leak an int
        # into a schema the frontend types as a string.
        assert _extract_datetime({"dateTime": 1737000000}) == ""


# ---------------------------------------------------------------------------
# _format_calendar_option_for_stream
# ---------------------------------------------------------------------------


class TestFormatCalendarOptionForStream:
    def test_minimal_option_uses_shared_default_color(self) -> None:
        out = _format_calendar_option_for_stream({})
        assert out == {
            "summary": "",
            "description": "",
            "is_all_day": False,
            "calendar_id": "",
            "calendar_name": "",
            "background_color": DEFAULT_CALENDAR_COLOR,
            "start": "",
            "end": "",
        }

    def test_start_end_dicts_are_flattened(self) -> None:
        out = _format_calendar_option_for_stream(
            {
                "summary": "Standup",
                "start": {"dateTime": "2026-01-15T10:00:00+00:00"},
                "end": {"dateTime": "2026-01-15T10:30:00+00:00"},
                "color": "#123456",
            }
        )
        assert out["start"] == "2026-01-15T10:00:00+00:00"
        assert out["end"] == "2026-01-15T10:30:00+00:00"
        assert out["background_color"] == "#123456"

    def test_optional_keys_are_omitted_when_absent(self) -> None:
        out = _format_calendar_option_for_stream({"summary": "X"})
        assert "location" not in out
        assert "attendees" not in out
        assert "create_meeting_room" not in out

    def test_optional_keys_are_included_when_present(self) -> None:
        out = _format_calendar_option_for_stream(
            {
                "location": "Room 3",
                "attendees": ["a@b.com"],
                "create_meeting_room": True,
            }
        )
        assert out["location"] == "Room 3"
        assert out["attendees"] == ["a@b.com"]
        assert out["create_meeting_room"] is True

    def test_empty_attendee_list_is_not_streamed(self) -> None:
        assert "attendees" not in _format_calendar_option_for_stream({"attendees": []})


# ---------------------------------------------------------------------------
# _format_calendar_for_stream
# ---------------------------------------------------------------------------


class TestFormatCalendarForStream:
    def test_google_shape(self) -> None:
        assert _format_calendar_for_stream(
            CalendarSummary(
                summary="Work",
                id="work@group.calendar.google.com",
                description="team",
                backgroundColor="#ff0000",
            )
        ) == {
            "name": "Work",
            "id": "work@group.calendar.google.com",
            "description": "team",
            "backgroundColor": "#ff0000",
        }

    def test_missing_fields_do_not_raise(self) -> None:
        out = _format_calendar_for_stream(CalendarSummary())
        assert out["name"] is None
        assert out["id"] is None
        assert out["backgroundColor"] is None


# ---------------------------------------------------------------------------
# _get_user_id
# ---------------------------------------------------------------------------


class TestGetUserId:
    def test_returns_user_id(self) -> None:
        assert _get_user_id({"user_id": "abc"}) == "abc"

    @pytest.mark.parametrize(
        "creds",
        [{}, {"user_id": ""}, {"user_id": None}, {"user_id": 123}, {"userId": "abc"}],
        ids=["missing", "blank", "none", "int", "wrong-key"],
    )
    def test_rejects_unusable_credentials(self, creds: dict[str, Any]) -> None:
        with pytest.raises(ValueError, match="Missing user_id"):
            _get_user_id(creds)


# ---------------------------------------------------------------------------
# _get_user_timezone
# ---------------------------------------------------------------------------


class TestGetUserTimezone:
    def test_returns_tzinfo_from_config(self) -> None:
        cfg = {"configurable": {"user_timezone": "+05:30"}}
        with patch(f"{MODULE}.get_config", return_value=cfg):
            tz = _get_user_timezone()
        assert tz is not None
        assert tz.utcoffset(None) == timedelta(hours=5, minutes=30)

    def test_returns_none_when_config_has_no_timezone(self) -> None:
        with patch(f"{MODULE}.get_config", return_value={"configurable": {}}):
            assert _get_user_timezone() is None

    def test_returns_none_when_configurable_is_none(self) -> None:
        with patch(f"{MODULE}.get_config", return_value={"configurable": None}):
            assert _get_user_timezone() is None

    def test_returns_none_outside_runnable_context(self) -> None:
        with patch(f"{MODULE}.get_config", side_effect=RuntimeError("no context")):
            assert _get_user_timezone() is None


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_every_registered_function_is_returned_as_a_tool_name(self) -> None:
        composio = MagicMock()
        captured: dict[str, Any] = {}

        def custom_tool(**kwargs: Any) -> Any:
            assert kwargs == {"toolkit": "GOOGLECALENDAR"}

            def decorator(fn: Any) -> Any:
                captured[fn.__name__] = fn
                return fn

            return decorator

        composio.tools.custom_tool = custom_tool
        names = register_calendar_custom_tools(composio)

        assert sorted(names) == sorted(f"GOOGLECALENDAR_{fn}" for fn in captured)

    def test_docstrings_are_attached_for_llm_tool_selection(self, tools: dict[str, Any]) -> None:
        for name, fn in tools.items():
            assert fn.__doc__, f"{name} has no docstring"


# ---------------------------------------------------------------------------
# CUSTOM_LIST_CALENDARS
# ---------------------------------------------------------------------------


_CALENDAR_LIST = CalendarListResponse.model_validate(
    {
        "kind": "calendar#calendarList",
        "items": [
            {"id": "primary", "summary": "Work", "backgroundColor": "#abc", "etag": "e1"},
        ],
    }
)


class TestListCalendars:
    def test_short_returns_the_trimmed_projection_and_streams_it(self, tools, writer) -> None:
        with patch(
            "app.services.calendar_service.list_calendars",
            new=AsyncMock(return_value=_CALENDAR_LIST),
        ) as mock_list:
            out = tools["CUSTOM_LIST_CALENDARS"](ListCalendarsInput(), EXECUTE_REQUEST, AUTH)

        assert out == {
            "calendars": [
                {
                    "id": "primary",
                    "summary": "Work",
                    "description": None,
                    "backgroundColor": "#abc",
                }
            ]
        }
        assert mock_list.await_args.args == ("user-42",)
        assert writer.call_args[0][0] == {
            "calendar_list_fetch_data": [
                {
                    "name": "Work",
                    "id": "primary",
                    "description": None,
                    "backgroundColor": "#abc",
                }
            ]
        }

    def test_short_false_returns_googles_full_entries_verbatim(self, tools, writer) -> None:
        with patch(
            "app.services.calendar_service.list_calendars",
            new=AsyncMock(return_value=_CALENDAR_LIST),
        ):
            out = tools["CUSTOM_LIST_CALENDARS"](
                ListCalendarsInput(short=False), EXECUTE_REQUEST, AUTH
            )
        # Every key Google sent survives, including the ones the short view drops.
        assert out["calendars"] == [
            {"id": "primary", "summary": "Work", "backgroundColor": "#abc", "etag": "e1"}
        ]

    def test_nothing_is_streamed_when_there_are_no_calendars(self, tools, writer) -> None:
        with patch(
            "app.services.calendar_service.list_calendars",
            new=AsyncMock(return_value=CalendarListResponse()),
        ):
            out = tools["CUSTOM_LIST_CALENDARS"](ListCalendarsInput(), EXECUTE_REQUEST, AUTH)
        assert out == {"calendars": []}
        writer.assert_not_called()

    def test_missing_user_id_fails_before_any_service_call(self, tools) -> None:
        with patch("app.services.calendar_service.list_calendars", new=AsyncMock()) as mock_list:
            with pytest.raises(ValueError, match="Missing user_id"):
                tools["CUSTOM_LIST_CALENDARS"](ListCalendarsInput(), EXECUTE_REQUEST, {})
        mock_list.assert_not_awaited()


# ---------------------------------------------------------------------------
# CUSTOM_GET_DAY_SUMMARY
# ---------------------------------------------------------------------------


class _FrozenDatetime(datetime):
    """`datetime` with a pinned `now()` — everything else is the real thing."""

    _instant = datetime(2026, 3, 14, 20, 30, tzinfo=UTC)

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> "_FrozenDatetime":
        # Rebuilt through cls so the pinned instant comes back as this subclass:
        # datetime.now() is declared to return Self, and handing back a plain
        # datetime would break that contract for every caller under patch.
        inst = cls._instant.astimezone(tz) if tz is not None else cls._instant.replace(tzinfo=None)
        return cls.fromisoformat(inst.isoformat())


class TestRunSync:
    async def _coro(self) -> str:
        return "unused"

    def test_forwards_the_timeout_to_the_captured_loop_dispatch(self) -> None:
        # With no running loop on this thread, _run_sync dispatches onto the
        # captured server loop and must forward the caller's timeout unchanged —
        # that is the timeout=5 guard CUSTOM_GET_DAY_SUMMARY relies on.
        sentinel = object()
        coro = self._coro()
        with patch(f"{MODULE}.run_on_captured_loop", return_value=sentinel) as dispatch:
            assert _run_sync(coro, timeout=3.0) is sentinel
        assert dispatch.call_args.args[0] is coro
        assert dispatch.call_args.kwargs == {"timeout": 3.0}
        coro.close()


class TestGetDaySummary:
    def _run(self, tools, request, *, events, user=None, metadata=None, raises_metadata=False):
        metadata_mock = (
            AsyncMock(side_effect=RuntimeError("calendar list down"))
            if raises_metadata
            else AsyncMock(return_value=metadata or ({}, {}))
        )
        with (
            patch("app.services.user_service.get_user_by_id", new=AsyncMock(return_value=user)),
            patch(
                "app.services.calendar_service.get_calendar_events",
                new=AsyncMock(return_value=_events_response(events)),
            ) as mock_events,
            patch("app.services.calendar_service.get_calendar_metadata_map", new=metadata_mock),
        ):
            out = tools["CUSTOM_GET_DAY_SUMMARY"](request, EXECUTE_REQUEST, AUTH)
        return out, mock_events

    def test_window_is_the_whole_day_in_the_users_timezone(self, tools, writer) -> None:
        out, mock_events = self._run(
            tools,
            GetDaySummaryInput(date="2026-03-15"),
            events=[],
            user={"timezone": "Asia/Kolkata"},
        )
        kwargs = mock_events.await_args.kwargs
        assert kwargs["time_min"] == "2026-03-15T00:00:00+05:30"
        assert kwargs["time_max"] == "2026-03-16T00:00:00+05:30"
        assert kwargs["max_results"] == 100
        assert kwargs["selected_calendars"] is None
        assert out["date"] == "2026-03-15"
        assert out["timezone"] == "Asia/Kolkata"

    def test_fixed_offset_timezone_is_supported(self, tools, writer) -> None:
        # A stored "+05:30" home zone makes zoneinfo.ZoneInfo raise; Timezone.parse
        # must absorb it rather than blowing up the whole tool.
        out, mock_events = self._run(
            tools,
            GetDaySummaryInput(date="2026-03-15"),
            events=[],
            user={"timezone": "+05:30"},
        )
        assert out["timezone"] == "+05:30"
        assert mock_events.await_args.kwargs["time_min"] == "2026-03-15T00:00:00+05:30"

    def test_missing_user_falls_back_to_utc(self, tools, writer) -> None:
        out, mock_events = self._run(
            tools, GetDaySummaryInput(date="2026-03-15"), events=[], user=None
        )
        assert out["timezone"] == "UTC"
        assert mock_events.await_args.kwargs["time_min"] == "2026-03-15T00:00:00+00:00"

    def test_user_lookup_failure_falls_back_to_utc(self, tools, writer) -> None:
        with (
            patch(
                "app.services.user_service.get_user_by_id",
                new=AsyncMock(side_effect=RuntimeError("mongo down")),
            ),
            patch(
                "app.services.calendar_service.get_calendar_events",
                new=AsyncMock(return_value=_events_response([])),
            ),
            patch(
                "app.services.calendar_service.get_calendar_metadata_map",
                new=AsyncMock(return_value=({}, {})),
            ),
        ):
            out = tools["CUSTOM_GET_DAY_SUMMARY"](
                GetDaySummaryInput(date="2026-03-15"), EXECUTE_REQUEST, AUTH
            )
        assert out["timezone"] == "UTC"

    @pytest.mark.parametrize("bad", ["15-03-2026", "2026/03/15", "tomorrow", "2026-13-45"])
    def test_malformed_date_is_rejected(self, tools, bad: str) -> None:
        with pytest.raises(ValueError, match="Invalid date format"):
            self._run(tools, GetDaySummaryInput(date=bad), events=[])

    def test_blank_date_is_treated_as_today(self, tools, writer) -> None:
        with patch(f"{MODULE}.datetime", _FrozenDatetime):
            out, _ = self._run(
                tools, GetDaySummaryInput(date=""), events=[], user={"timezone": "Asia/Kolkata"}
            )
        assert out["date"] == "2026-03-15"

    def test_busy_hours_sums_only_timed_events(self, tools, writer) -> None:
        events = [
            _timed_event("2026-03-15T09:00:00+00:00", "2026-03-15T10:30:00+00:00"),
            _timed_event("2026-03-15T13:00:00Z", "2026-03-15T14:00:00Z"),
            _event(
                {
                    "summary": "Holiday",
                    "start": {"date": "2026-03-15"},
                    "end": {"date": "2026-03-16"},
                }
            ),
            _event(
                {"summary": "Broken", "start": {"dateTime": "not-a-time"}, "end": {"dateTime": "x"}}
            ),
            _event(
                {
                    "summary": "Half-typed",
                    "start": {"dateTime": "2026-03-15T15:00:00Z"},
                    "end": {"date": "2026-03-16"},
                }
            ),
        ]
        out, _ = self._run(tools, GetDaySummaryInput(date="2026-03-15"), events=events)
        assert out["busy_hours"] == 2.5

    def test_next_event_is_the_first_future_event_today(self, tools, writer) -> None:
        events = [
            _timed_event("2026-03-14T18:00:00+00:00", "2026-03-14T19:00:00+00:00", "past"),
            _timed_event("2026-03-14T21:00:00+00:00", "2026-03-14T22:00:00+00:00", "next"),
            _timed_event("2026-03-14T23:00:00+00:00", "2026-03-14T23:30:00+00:00", "later"),
        ]
        with patch(f"{MODULE}.datetime", _FrozenDatetime):
            out, _ = self._run(tools, GetDaySummaryInput(date="2026-03-14"), events=events)
        assert out["next_event"]["summary"] == "next"

    def test_next_event_is_none_for_a_day_that_is_not_today(self, tools, writer) -> None:
        events = [_timed_event("2026-03-20T21:00:00+00:00", "2026-03-20T22:00:00+00:00")]
        with patch(f"{MODULE}.datetime", _FrozenDatetime):
            out, _ = self._run(tools, GetDaySummaryInput(date="2026-03-20"), events=events)
        assert out["next_event"] is None

    def test_an_event_starting_exactly_now_is_not_the_next_event(self, tools, writer) -> None:
        events = [
            _timed_event("2026-03-14T20:30:00+00:00", "2026-03-14T21:00:00+00:00", "starting now"),
            _timed_event("2026-03-14T21:00:00+00:00", "2026-03-14T22:00:00+00:00", "next"),
        ]
        with patch(f"{MODULE}.datetime", _FrozenDatetime):
            out, _ = self._run(tools, GetDaySummaryInput(date="2026-03-14"), events=events)
        assert out["next_event"]["summary"] == "next"

    def test_unparseable_event_does_not_shadow_the_real_next_event(self, tools, writer) -> None:
        events = [
            _event(
                {"summary": "corrupt", "start": {"dateTime": "23:00"}, "end": {"dateTime": "23:30"}}
            ),
            _timed_event("2026-03-14T21:00:00+00:00", "2026-03-14T22:00:00+00:00", "next"),
        ]
        with patch(f"{MODULE}.datetime", _FrozenDatetime):
            out, _ = self._run(tools, GetDaySummaryInput(date="2026-03-14"), events=events)
        assert out["next_event"]["summary"] == "next"

    def test_next_event_is_none_when_every_event_has_passed(self, tools, writer) -> None:
        events = [_timed_event("2026-03-14T08:00:00+00:00", "2026-03-14T09:00:00+00:00")]
        with patch(f"{MODULE}.datetime", _FrozenDatetime):
            out, _ = self._run(tools, GetDaySummaryInput(date="2026-03-14"), events=events)
        assert out["next_event"] is None

    def test_events_are_formatted_and_streamed(self, tools, writer) -> None:
        events = [_timed_event("2026-03-15T09:00:00Z", "2026-03-15T10:00:00Z", "Standup", "cal-1")]
        out, _ = self._run(
            tools,
            GetDaySummaryInput(date="2026-03-15"),
            events=events,
            metadata=({"cal-1": "#ff0000"}, {"cal-1": "Team"}),
        )
        assert out["events"] == [
            {
                "summary": "Standup",
                "start_time": "2026-03-15T09:00:00Z",
                "end_time": "2026-03-15T10:00:00Z",
                "calendar_name": "Team",
                "background_color": "#ff0000",
            }
        ]
        assert writer.call_args[0][0] == {"calendar_fetch_data": out["events"]}

    def test_metadata_failure_falls_back_to_raw_events(self, tools, writer) -> None:
        events = [_timed_event("2026-03-15T09:00:00Z", "2026-03-15T10:00:00Z")]
        out, _ = self._run(
            tools, GetDaySummaryInput(date="2026-03-15"), events=events, raises_metadata=True
        )
        assert out["events"] == [event.model_dump() for event in events]

    def test_nothing_is_streamed_for_an_empty_day(self, tools, writer) -> None:
        self._run(tools, GetDaySummaryInput(date="2026-03-15"), events=[])
        writer.assert_not_called()

    def test_today_is_resolved_in_the_users_timezone(self, tools, writer) -> None:
        # BUG: GetDaySummaryInput.date defaulted to the *server's* local date via
        # default_factory, so a user in Asia/Kolkata asking "what's on today?"
        # between 00:00 and 05:30 local got yesterday's schedule from a UTC
        # server. The date must be resolved from the user's own zone, which is
        # only known inside the tool.
        with patch(f"{MODULE}.datetime", _FrozenDatetime):
            out, mock_events = self._run(
                tools, GetDaySummaryInput(), events=[], user={"timezone": "Asia/Kolkata"}
            )
        assert out["date"] == "2026-03-15"
        assert mock_events.await_args.kwargs["time_min"] == "2026-03-15T00:00:00+05:30"


# ---------------------------------------------------------------------------
# CUSTOM_FETCH_EVENTS
# ---------------------------------------------------------------------------


class TestFetchEvents:
    def _run(self, tools, request, *, events, has_more=False, metadata=None, raises_metadata=False):
        metadata_mock = (
            AsyncMock(side_effect=RuntimeError("down"))
            if raises_metadata
            else AsyncMock(return_value=metadata or ({}, {}))
        )
        with (
            patch(
                "app.services.calendar_service.get_calendar_events",
                new=AsyncMock(return_value=_events_response(events, has_more=has_more)),
            ) as mock_events,
            patch("app.services.calendar_service.get_calendar_metadata_map", new=metadata_mock),
        ):
            out = tools["CUSTOM_FETCH_EVENTS"](request, EXECUTE_REQUEST, AUTH)
        return out, mock_events

    def test_time_min_defaults_to_now_in_utc(self, tools, writer) -> None:
        with patch(f"{MODULE}.datetime", _FrozenDatetime):
            _, mock_events = self._run(tools, FetchEventsInput(), events=[])
        assert mock_events.await_args.kwargs["time_min"] == "2026-03-14T20:30:00+00:00"

    def test_explicit_filters_are_forwarded(self, tools, writer) -> None:
        _, mock_events = self._run(
            tools,
            FetchEventsInput(
                calendar_ids=["a", "b"],
                time_min="2026-01-01T00:00:00Z",
                time_max="2026-01-02T00:00:00Z",
                max_results=7,
            ),
            events=[],
        )
        assert mock_events.await_args.kwargs == {
            "user_id": "user-42",
            "selected_calendars": ["a", "b"],
            "time_min": "2026-01-01T00:00:00Z",
            "time_max": "2026-01-02T00:00:00Z",
            "max_results": 7,
        }

    def test_empty_calendar_ids_means_all_selected_calendars(self, tools, writer) -> None:
        _, mock_events = self._run(tools, FetchEventsInput(calendar_ids=[]), events=[])
        assert mock_events.await_args.kwargs["selected_calendars"] is None

    def test_none_calendar_ids_means_all_selected_calendars(self, tools, writer) -> None:
        # The tool docstring tells the model to pass calendar_ids=None for "all
        # calendars", but the field was typed list[str] and rejected None with a
        # Pydantic list_type error, breaking every no-ids fetch. It must accept None.
        _, mock_events = self._run(tools, FetchEventsInput(calendar_ids=None), events=[])
        assert mock_events.await_args.kwargs["selected_calendars"] is None

    def test_events_are_formatted_and_has_more_is_propagated(self, tools, writer) -> None:
        events = [_timed_event("2026-01-01T09:00:00Z", "2026-01-01T10:00:00Z", "Sync", "cal-1")]
        out, _ = self._run(
            tools,
            FetchEventsInput(),
            events=events,
            has_more=True,
            metadata=({"cal-1": "#0f0"}, {"cal-1": "Team"}),
        )
        assert out["has_more"] is True
        assert out["calendar_fetch_data"][0]["calendar_name"] == "Team"
        assert out["calendar_fetch_data"][0]["background_color"] == "#0f0"
        assert writer.call_args[0][0] == {"calendar_fetch_data": out["calendar_fetch_data"]}

    def test_has_more_defaults_to_false(self, tools, writer) -> None:
        out, _ = self._run(tools, FetchEventsInput(), events=[])
        assert out["has_more"] is False

    def test_metadata_failure_falls_back_to_raw_events(self, tools, writer) -> None:
        events = [_timed_event("2026-01-01T09:00:00Z", "2026-01-01T10:00:00Z")]
        out, _ = self._run(tools, FetchEventsInput(), events=events, raises_metadata=True)
        assert out["calendar_fetch_data"] == [event.model_dump() for event in events]

    def test_nothing_is_streamed_when_there_are_no_events(self, tools, writer) -> None:
        self._run(tools, FetchEventsInput(), events=[])
        writer.assert_not_called()


# ---------------------------------------------------------------------------
# CUSTOM_FIND_EVENT
# ---------------------------------------------------------------------------


class TestFindEvent:
    def _run(self, tools, request, *, matching_events, metadata=None, raises_metadata=False):
        metadata_mock = (
            AsyncMock(side_effect=RuntimeError("down"))
            if raises_metadata
            else AsyncMock(return_value=metadata or ({}, {}))
        )
        with (
            patch(
                "app.services.calendar_service.search_calendar_events_native",
                new=AsyncMock(
                    return_value=CalendarSearchResult(
                        query=request.query,
                        matching_events=matching_events,
                        total_matches=len(matching_events),
                        total_events_searched=len(matching_events),
                        searched_calendars=[],
                    )
                ),
            ) as mock_search,
            patch("app.services.calendar_service.get_calendar_metadata_map", new=metadata_mock),
        ):
            out = tools["CUSTOM_FIND_EVENT"](request, EXECUTE_REQUEST, AUTH)
        return out, mock_search

    def test_query_and_bounds_are_forwarded(self, tools, writer) -> None:
        _, mock_search = self._run(
            tools,
            FindEventInput(query="dentist", time_min="2026-01-01T00:00:00Z", time_max=None),
            matching_events=[],
        )
        assert mock_search.await_args.kwargs == {
            "query": "dentist",
            "user_id": "user-42",
            "time_min": "2026-01-01T00:00:00Z",
            "time_max": None,
        }

    def test_returns_raw_events_and_formatted_search_data(self, tools, writer) -> None:
        events = [_timed_event("2026-01-01T09:00:00Z", "2026-01-01T10:00:00Z", "Dentist", "cal-1")]
        out, _ = self._run(
            tools,
            FindEventInput(query="dentist"),
            matching_events=events,
            metadata=({"cal-1": "#00f"}, {"cal-1": "Personal"}),
        )
        assert out["events"] == [event.model_dump() for event in events]
        assert out["calendar_search_data"][0]["summary"] == "Dentist"
        assert out["calendar_search_data"][0]["calendar_name"] == "Personal"
        assert writer.call_args[0][0] == {"calendar_fetch_data": out["calendar_search_data"]}

    def test_no_matches_streams_nothing(self, tools, writer) -> None:
        out, _ = self._run(tools, FindEventInput(query="nope"), matching_events=[])
        assert out == {"events": [], "calendar_search_data": []}
        writer.assert_not_called()

    def test_metadata_failure_falls_back_to_raw_events(self, tools, writer) -> None:
        events = [_timed_event("2026-01-01T09:00:00Z", "2026-01-01T10:00:00Z")]
        out, _ = self._run(
            tools,
            FindEventInput(query="x"),
            matching_events=events,
            raises_metadata=True,
        )
        assert out["calendar_search_data"] == [event.model_dump() for event in events]


# ---------------------------------------------------------------------------
# CUSTOM_GET_EVENT
# ---------------------------------------------------------------------------


class TestGetEvent:
    def test_fetches_each_event_from_the_right_endpoint(self, tools) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value={"id": "e1"}) as proxy:
            out = tools["CUSTOM_GET_EVENT"](
                GetEventInput(events=[EventReference(event_id="e1", calendar_id="cal-1")]),
                EXECUTE_REQUEST,
                AUTH,
            )
        assert proxy.call_args.kwargs == {
            "user_id": "user-42",
            "toolkit": "GOOGLECALENDAR",
            "endpoint": f"{CALENDAR_API_BASE}/calendars/cal-1/events/e1",
            "method": "GET",
        }
        assert out["events"] == [{"event_id": "e1", "calendar_id": "cal-1", "event": {"id": "e1"}}]

    def test_partial_failure_reports_the_failed_events(self, tools) -> None:
        # BUG: the `errors` list was built with full detail and then dropped from
        # the response whenever at least one event succeeded, so the agent told
        # the user every event was fetched.
        def side_effect(**kwargs: Any) -> dict[str, Any]:
            if kwargs["endpoint"].endswith("missing"):
                raise AppError(message="Not Found", why="deleted", status_code=404)
            return {"id": "ok"}

        with patch(f"{MODULE}.proxy_request_sync", side_effect=side_effect):
            out = tools["CUSTOM_GET_EVENT"](
                GetEventInput(
                    events=[EventReference(event_id="ok"), EventReference(event_id="missing")]
                ),
                EXECUTE_REQUEST,
                AUTH,
            )

        assert len(out["events"]) == 1
        assert out["errors"] == [
            {
                "event_id": "missing",
                "calendar_id": "primary",
                "error": "Event not found: Not Found",
            }
        ]

    def test_no_errors_key_noise_on_full_success(self, tools) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value={"id": "e1"}):
            out = tools["CUSTOM_GET_EVENT"](
                GetEventInput(events=[EventReference(event_id="e1")]), EXECUTE_REQUEST, AUTH
            )
        assert out["errors"] == []

    def test_total_failure_raises(self, tools) -> None:
        with patch(
            f"{MODULE}.proxy_request_sync",
            side_effect=AppError(message="Not Found", why="gone", status_code=404),
        ):
            with pytest.raises(RuntimeError, match="Failed to get events"):
                tools["CUSTOM_GET_EVENT"](
                    GetEventInput(events=[EventReference(event_id="e1")]), EXECUTE_REQUEST, AUTH
                )

    def test_non_apperror_failures_are_not_swallowed(self, tools) -> None:
        with patch(f"{MODULE}.proxy_request_sync", side_effect=ConnectionError("socket closed")):
            with pytest.raises(ConnectionError):
                tools["CUSTOM_GET_EVENT"](
                    GetEventInput(events=[EventReference(event_id="e1")]), EXECUTE_REQUEST, AUTH
                )

    def test_empty_request_is_a_no_op(self, tools) -> None:
        with patch(f"{MODULE}.proxy_request_sync") as proxy:
            out = tools["CUSTOM_GET_EVENT"](GetEventInput(events=[]), EXECUTE_REQUEST, AUTH)
        proxy.assert_not_called()
        assert out["events"] == []

    def test_percent_encodes_calendar_id_with_reserved_chars(self, tools) -> None:
        # Google calendar IDs like "user@group.calendar.google.com" or
        # "#contacts@group.v.calendar.google.com" contain '@'/'#'. Unencoded,
        # those characters break the URL path (same bug as calendar_service.py,
        # fixed at the root by routing every endpoint through
        # calendar_events_endpoint()).
        with patch(f"{MODULE}.proxy_request_sync", return_value={"id": "e1"}) as proxy:
            tools["CUSTOM_GET_EVENT"](
                GetEventInput(
                    events=[
                        EventReference(
                            event_id="e1",
                            calendar_id="user@group.calendar.google.com",
                        )
                    ]
                ),
                EXECUTE_REQUEST,
                AUTH,
            )
        endpoint = proxy.call_args.kwargs["endpoint"]
        assert "user@group.calendar.google.com" not in endpoint
        assert endpoint.endswith("/calendars/user%40group.calendar.google.com/events/e1")


# ---------------------------------------------------------------------------
# CUSTOM_DELETE_EVENT
# ---------------------------------------------------------------------------


class TestDeleteEvent:
    def test_deletes_each_event(self, tools) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value=None) as proxy:
            out = tools["CUSTOM_DELETE_EVENT"](
                DeleteEventInput(events=[EventReference(event_id="e1", calendar_id="cal-1")]),
                EXECUTE_REQUEST,
                AUTH,
            )
        assert proxy.call_args.kwargs["method"] == "DELETE"
        assert (
            proxy.call_args.kwargs["endpoint"] == f"{CALENDAR_API_BASE}/calendars/cal-1/events/e1"
        )
        assert out["deleted"] == [{"event_id": "e1", "calendar_id": "cal-1"}]

    @pytest.mark.parametrize("send_updates", ["all", "externalOnly", "none"])
    def test_attendees_are_notified_of_the_cancellation(self, tools, send_updates: str) -> None:
        # BUG: DeleteEventInput.send_updates is advertised to the model in the
        # tool docstring but was never forwarded, so Google defaulted to
        # sendUpdates=none — cancelling a meeting never told the attendees.
        with patch(f"{MODULE}.proxy_request_sync", return_value=None) as proxy:
            tools["CUSTOM_DELETE_EVENT"](
                DeleteEventInput(events=[EventReference(event_id="e1")], send_updates=send_updates),
                EXECUTE_REQUEST,
                AUTH,
            )
        assert proxy.call_args.kwargs["query"] == {"sendUpdates": send_updates}

    def test_partial_failure_reports_the_failed_deletes(self, tools) -> None:
        # BUG: same swallowed-`errors` defect as CUSTOM_GET_EVENT. Reporting a
        # delete as successful when it failed is the worse half of the bug: the
        # user believes the event is gone.
        def side_effect(**kwargs: Any) -> None:
            if kwargs["endpoint"].endswith("locked"):
                raise AppError(message="Forbidden", why="read-only calendar", status_code=403)

        with patch(f"{MODULE}.proxy_request_sync", side_effect=side_effect):
            out = tools["CUSTOM_DELETE_EVENT"](
                DeleteEventInput(
                    events=[EventReference(event_id="ok"), EventReference(event_id="locked")]
                ),
                EXECUTE_REQUEST,
                AUTH,
            )

        assert out["deleted"] == [{"event_id": "ok", "calendar_id": "primary"}]
        assert out["errors"] == [
            {
                "event_id": "locked",
                "calendar_id": "primary",
                "error": "Failed to delete: Forbidden",
            }
        ]

    def test_total_failure_raises(self, tools) -> None:
        with patch(
            f"{MODULE}.proxy_request_sync",
            side_effect=AppError(message="Forbidden", why="nope", status_code=403),
        ):
            with pytest.raises(RuntimeError, match="Failed to delete events"):
                tools["CUSTOM_DELETE_EVENT"](
                    DeleteEventInput(events=[EventReference(event_id="e1")]), EXECUTE_REQUEST, AUTH
                )

    def test_percent_encodes_calendar_id_with_reserved_chars(self, tools) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value=None) as proxy:
            tools["CUSTOM_DELETE_EVENT"](
                DeleteEventInput(
                    events=[
                        EventReference(
                            event_id="e1",
                            calendar_id="#contacts@group.v.calendar.google.com",
                        )
                    ]
                ),
                EXECUTE_REQUEST,
                AUTH,
            )
        endpoint = proxy.call_args.kwargs["endpoint"]
        assert "#contacts@group.v.calendar.google.com" not in endpoint
        assert endpoint.endswith("/calendars/%23contacts%40group.v.calendar.google.com/events/e1")


# ---------------------------------------------------------------------------
# CUSTOM_PATCH_EVENT
# ---------------------------------------------------------------------------


class TestPatchEvent:
    def test_only_supplied_fields_are_patched(self, tools) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value={"id": "e1"}) as proxy:
            out = tools["CUSTOM_PATCH_EVENT"](
                PatchEventInput(event_id="e1", calendar_id="cal-1", summary="New title"),
                EXECUTE_REQUEST,
                AUTH,
            )
        assert proxy.call_args.kwargs["body"] == {"summary": "New title"}
        assert proxy.call_args.kwargs["method"] == "PATCH"
        assert (
            proxy.call_args.kwargs["endpoint"] == f"{CALENDAR_API_BASE}/calendars/cal-1/events/e1"
        )
        assert proxy.call_args.kwargs["query"] == {"sendUpdates": "all"}
        assert out == {"event": {"id": "e1"}}

    def test_all_fields_are_mapped_to_the_google_shape(self, tools) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value={}) as proxy:
            tools["CUSTOM_PATCH_EVENT"](
                PatchEventInput(
                    event_id="e1",
                    summary="S",
                    description="D",
                    location="L",
                    start_datetime="2026-01-15T10:00:00Z",
                    end_datetime="2026-01-15T11:00:00Z",
                    attendees=["a@b.com", "c@d.com"],
                    send_updates="none",
                ),
                EXECUTE_REQUEST,
                AUTH,
            )
        assert proxy.call_args.kwargs["body"] == {
            "summary": "S",
            "description": "D",
            "location": "L",
            "start": {"dateTime": "2026-01-15T10:00:00Z"},
            "end": {"dateTime": "2026-01-15T11:00:00Z"},
            "attendees": [{"email": "a@b.com"}, {"email": "c@d.com"}],
        }
        assert proxy.call_args.kwargs["query"] == {"sendUpdates": "none"}

    def test_explicit_empty_values_are_still_patched(self, tools) -> None:
        # "" is a deliberate clear, not "unset" — only None means "leave alone".
        with patch(f"{MODULE}.proxy_request_sync", return_value={}) as proxy:
            tools["CUSTOM_PATCH_EVENT"](
                PatchEventInput(event_id="e1", description="", location="", attendees=[]),
                EXECUTE_REQUEST,
                AUTH,
            )
        assert proxy.call_args.kwargs["body"] == {
            "description": "",
            "location": "",
            "attendees": [],
        }

    def test_proxy_errors_propagate(self, tools) -> None:
        with patch(
            f"{MODULE}.proxy_request_sync",
            side_effect=AppError(message="Not Found", why="gone", status_code=404),
        ):
            with pytest.raises(AppError):
                tools["CUSTOM_PATCH_EVENT"](
                    PatchEventInput(event_id="e1", summary="x"), EXECUTE_REQUEST, AUTH
                )

    def test_percent_encodes_calendar_id_with_reserved_chars(self, tools) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value={"id": "e1"}) as proxy:
            tools["CUSTOM_PATCH_EVENT"](
                PatchEventInput(
                    event_id="e1",
                    calendar_id="user@group.calendar.google.com",
                    summary="New title",
                ),
                EXECUTE_REQUEST,
                AUTH,
            )
        endpoint = proxy.call_args.kwargs["endpoint"]
        assert "user@group.calendar.google.com" not in endpoint
        assert endpoint.endswith("/calendars/user%40group.calendar.google.com/events/e1")


# ---------------------------------------------------------------------------
# CUSTOM_ADD_RECURRENCE
# ---------------------------------------------------------------------------


class TestAddRecurrence:
    def _run(self, tools, request):
        existing = {"id": "e1", "summary": "Standup"}
        with patch(
            f"{MODULE}.proxy_request_sync", side_effect=[existing, {"id": "e1", "updated": True}]
        ) as proxy:
            out = tools["CUSTOM_ADD_RECURRENCE"](request, EXECUTE_REQUEST, AUTH)
        return out, proxy

    def test_reads_then_writes_the_same_event(self, tools) -> None:
        out, proxy = self._run(
            tools, AddRecurrenceInput(event_id="e1", calendar_id="cal-1", frequency="DAILY")
        )
        endpoint = f"{CALENDAR_API_BASE}/calendars/cal-1/events/e1"
        assert [c.kwargs["method"] for c in proxy.call_args_list] == ["GET", "PUT"]
        assert {c.kwargs["endpoint"] for c in proxy.call_args_list} == {endpoint}
        assert proxy.call_args_list[1].kwargs["body"]["recurrence"] == ["RRULE:FREQ=DAILY"]
        assert proxy.call_args_list[1].kwargs["body"]["summary"] == "Standup"
        assert out["event"] == {"id": "e1", "updated": True}
        assert out["recurrence_rule"] == "RRULE:FREQ=DAILY"

    @pytest.mark.parametrize(
        "kwargs,expected",
        [
            ({"frequency": "WEEKLY"}, "RRULE:FREQ=WEEKLY"),
            ({"frequency": "DAILY", "interval": 1}, "RRULE:FREQ=DAILY"),
            ({"frequency": "DAILY", "interval": 3}, "RRULE:FREQ=DAILY;INTERVAL=3"),
            ({"frequency": "DAILY", "count": 5}, "RRULE:FREQ=DAILY;COUNT=5"),
            (
                {"frequency": "DAILY", "until_date": "2026-12-31"},
                "RRULE:FREQ=DAILY;UNTIL=20261231",
            ),
            (
                {"frequency": "WEEKLY", "by_day": ["MO", "WE", "FR"]},
                "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR",
            ),
            (
                {"frequency": "WEEKLY", "interval": 2, "count": 4, "by_day": ["TU"]},
                "RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=4;BYDAY=TU",
            ),
        ],
    )
    def test_rrule_assembly(self, tools, kwargs: dict[str, Any], expected: str) -> None:
        out, _ = self._run(tools, AddRecurrenceInput(event_id="e1", **kwargs))
        assert out["recurrence_rule"] == expected

    def test_count_zero_is_omitted_not_emitted(self, tools) -> None:
        out, _ = self._run(tools, AddRecurrenceInput(event_id="e1", frequency="DAILY", count=0))
        assert "COUNT" not in out["recurrence_rule"]

    def test_failure_to_read_the_event_aborts_before_writing(self, tools) -> None:
        with patch(
            f"{MODULE}.proxy_request_sync",
            side_effect=AppError(message="Not Found", why="gone", status_code=404),
        ) as proxy:
            with pytest.raises(AppError):
                tools["CUSTOM_ADD_RECURRENCE"](
                    AddRecurrenceInput(event_id="e1", frequency="DAILY"), EXECUTE_REQUEST, AUTH
                )
        assert proxy.call_count == 1

    def test_percent_encodes_calendar_id_with_reserved_chars(self, tools) -> None:
        out, proxy = self._run(
            tools,
            AddRecurrenceInput(
                event_id="e1",
                calendar_id="#contacts@group.v.calendar.google.com",
                frequency="DAILY",
            ),
        )
        endpoint = proxy.call_args_list[0].kwargs["endpoint"]
        assert "#contacts@group.v.calendar.google.com" not in endpoint
        assert endpoint.endswith("/calendars/%23contacts%40group.v.calendar.google.com/events/e1")
        assert out["event"] == {"id": "e1", "updated": True}


# ---------------------------------------------------------------------------
# CUSTOM_CREATE_EVENT
# ---------------------------------------------------------------------------


class TestCreateEvent:
    def _run(self, tools, request, *, metadata=None, raises_metadata=False, created=None):
        metadata_mock = (
            AsyncMock(side_effect=RuntimeError("down"))
            if raises_metadata
            else AsyncMock(return_value=metadata or ({}, {}))
        )
        with (
            patch("app.services.calendar_service.get_calendar_metadata_map", new=metadata_mock),
            patch(
                f"{MODULE}.proxy_request_sync",
                return_value=created or {"id": "evt-1", "htmlLink": "https://cal/evt-1"},
            ) as proxy,
        ):
            out = tools["CUSTOM_CREATE_EVENT"](request, EXECUTE_REQUEST, AUTH)
        return out, proxy

    # -- all-day ----------------------------------------------------------

    def test_all_day_end_date_is_exclusive(self, tools, writer) -> None:
        # BUG: `end.date` was the same day as `start.date`. Google Calendar
        # treats all-day `end.date` as exclusive and rejects an empty range with
        # HTTP 400, so every all-day event the agent created failed. The rest of
        # the codebase (calendar_service.create_calendar_event) already uses
        # start + 1 day.
        _, proxy = self._run(
            tools,
            CreateEventInput(
                events=[
                    SingleEventInput(
                        summary="Holiday", start_datetime="2026-01-15T00:00:00", is_all_day=True
                    )
                ],
                confirm_immediately=True,
            ),
        )
        body = proxy.call_args.kwargs["body"]
        assert body["start"] == {"date": "2026-01-15"}
        assert body["end"] == {"date": "2026-01-16"}

    def test_all_day_end_date_crosses_month_and_year_boundaries(self, tools, writer) -> None:
        _, proxy = self._run(
            tools,
            CreateEventInput(
                events=[
                    SingleEventInput(
                        summary="NYE", start_datetime="2026-12-31T00:00:00", is_all_day=True
                    )
                ],
                confirm_immediately=True,
            ),
        )
        assert proxy.call_args.kwargs["body"]["end"] == {"date": "2027-01-01"}

    # -- timezone handling -------------------------------------------------

    def test_aware_start_is_preserved_verbatim(self, tools, writer) -> None:
        with patch(
            f"{MODULE}.get_config", return_value={"configurable": {"user_timezone": "+09:00"}}
        ):
            _, proxy = self._run(
                tools,
                CreateEventInput(
                    events=[
                        SingleEventInput(
                            summary="Call",
                            start_datetime="2026-01-15T10:00:00+05:30",
                            duration_hours=1,
                            duration_minutes=0,
                        )
                    ],
                    confirm_immediately=True,
                ),
            )
        body = proxy.call_args.kwargs["body"]
        assert body["start"] == {"dateTime": "2026-01-15T10:00:00+05:30"}
        assert body["end"] == {"dateTime": "2026-01-15T11:00:00+05:30"}

    def test_naive_start_is_stamped_with_the_users_timezone(self, tools, writer) -> None:
        with patch(
            f"{MODULE}.get_config", return_value={"configurable": {"user_timezone": "+05:30"}}
        ):
            _, proxy = self._run(
                tools,
                CreateEventInput(
                    events=[SingleEventInput(summary="Call", start_datetime="2026-01-15T10:00:00")],
                    confirm_immediately=True,
                ),
            )
        body = proxy.call_args.kwargs["body"]
        assert body["start"] == {"dateTime": "2026-01-15T10:00:00+05:30"}
        assert body["end"] == {"dateTime": "2026-01-15T10:30:00+05:30"}

    def test_naive_start_stays_naive_without_a_configured_timezone(self, tools, writer) -> None:
        # Deliberate: Google then interprets the wall time in the calendar's own
        # zone, which beats silently forcing UTC.
        with patch(f"{MODULE}.get_config", return_value={"configurable": {}}):
            _, proxy = self._run(
                tools,
                CreateEventInput(
                    events=[SingleEventInput(summary="Call", start_datetime="2026-01-15T10:00:00")],
                    confirm_immediately=True,
                ),
            )
        assert proxy.call_args.kwargs["body"]["start"] == {"dateTime": "2026-01-15T10:00:00"}

    def test_duration_is_added_to_the_start(self, tools, writer) -> None:
        with patch(f"{MODULE}.get_config", return_value={"configurable": {}}):
            _, proxy = self._run(
                tools,
                CreateEventInput(
                    events=[
                        SingleEventInput(
                            summary="Workshop",
                            start_datetime="2026-01-15T23:00:00",
                            duration_hours=2,
                            duration_minutes=30,
                        )
                    ],
                    confirm_immediately=True,
                ),
            )
        assert proxy.call_args.kwargs["body"]["end"] == {"dateTime": "2026-01-16T01:30:00"}

    # -- optional fields ---------------------------------------------------

    def test_optional_fields_are_only_sent_when_set(self, tools, writer) -> None:
        with patch(f"{MODULE}.get_config", return_value={"configurable": {}}):
            _, proxy = self._run(
                tools,
                CreateEventInput(
                    events=[SingleEventInput(summary="Bare", start_datetime="2026-01-15T10:00:00")],
                    confirm_immediately=True,
                ),
            )
        assert set(proxy.call_args.kwargs["body"]) == {"summary", "start", "end"}

    def test_meeting_room_requests_a_conference(self, tools, writer) -> None:
        with (
            patch(f"{MODULE}.get_config", return_value={"configurable": {}}),
            patch(f"{MODULE}.datetime", _FrozenDatetime),
        ):
            _, proxy = self._run(
                tools,
                CreateEventInput(
                    events=[
                        SingleEventInput(
                            summary="Sync",
                            start_datetime="2026-01-15T10:00:00",
                            description="notes",
                            location="Room 3",
                            attendees=["a@b.com"],
                            create_meeting_room=True,
                        )
                    ],
                    confirm_immediately=True,
                ),
            )
        body = proxy.call_args.kwargs["body"]
        assert body["description"] == "notes"
        assert body["location"] == "Room 3"
        assert body["attendees"] == [{"email": "a@b.com"}]
        assert body["conferenceData"]["createRequest"]["conferenceSolutionKey"] == {
            "type": "hangoutsMeet"
        }
        assert proxy.call_args.kwargs["query"] == {
            "sendUpdates": "all",
            "conferenceDataVersion": "1",
        }

    def test_no_conference_version_without_a_meeting_room(self, tools, writer) -> None:
        with patch(f"{MODULE}.get_config", return_value={"configurable": {}}):
            _, proxy = self._run(
                tools,
                CreateEventInput(
                    events=[SingleEventInput(summary="X", start_datetime="2026-01-15T10:00:00")],
                    confirm_immediately=True,
                ),
            )
        assert proxy.call_args.kwargs["query"] == {"sendUpdates": "all"}

    # -- confirm_immediately path ------------------------------------------

    def test_created_events_are_summarised_and_streamed(self, tools, writer) -> None:
        with patch(f"{MODULE}.get_config", return_value={"configurable": {}}):
            out, proxy = self._run(
                tools,
                CreateEventInput(
                    events=[
                        SingleEventInput(
                            summary="Sync",
                            start_datetime="2026-01-15T10:00:00",
                            calendar_id="cal-1",
                        )
                    ],
                    confirm_immediately=True,
                ),
                metadata=({"cal-1": "#ff0000"}, {"cal-1": "Team"}),
            )
        assert proxy.call_args.kwargs["endpoint"] == f"{CALENDAR_API_BASE}/calendars/cal-1/events"
        assert out["created"] is True
        assert out["created_events"] == [
            {
                "index": 0,
                "summary": "Sync",
                "event_id": "evt-1",
                "calendar_id": "cal-1",
                "link": "https://cal/evt-1",
                "start": {"dateTime": "2026-01-15T10:00:00"},
                "end": {"dateTime": "2026-01-15T10:30:00"},
            }
        ]
        assert writer.call_args[0][0] == {
            "calendar_fetch_data": [
                {
                    "summary": "Sync",
                    "start_time": "2026-01-15T10:00:00",
                    "end_time": "2026-01-15T10:30:00",
                    "calendar_name": "Team",
                    "background_color": "#ff0000",
                }
            ]
        }

    def test_percent_encodes_calendar_id_with_reserved_chars(self, tools, writer) -> None:
        with patch(f"{MODULE}.get_config", return_value={"configurable": {}}):
            _, proxy = self._run(
                tools,
                CreateEventInput(
                    events=[
                        SingleEventInput(
                            summary="Sync",
                            start_datetime="2026-01-15T10:00:00",
                            calendar_id="user@group.calendar.google.com",
                        )
                    ],
                    confirm_immediately=True,
                ),
                metadata=({"user@group.calendar.google.com": "#ff0000"}, {}),
            )
        endpoint = proxy.call_args.kwargs["endpoint"]
        assert "user@group.calendar.google.com" not in endpoint
        assert endpoint.endswith("/calendars/user%40group.calendar.google.com/events")

    # -- draft path --------------------------------------------------------

    def test_draft_path_does_not_touch_google(self, tools, writer) -> None:
        with patch(f"{MODULE}.get_config", return_value={"configurable": {}}):
            out, proxy = self._run(
                tools,
                CreateEventInput(
                    events=[SingleEventInput(summary="Draft", start_datetime="2026-01-15T10:00:00")]
                ),
            )
        proxy.assert_not_called()
        assert out["created"] is False
        assert "NOT been added" in out["message"]
        assert out["message"].startswith("1 event(s)")

    def test_draft_falls_back_to_the_shared_default_color(self, tools, writer) -> None:
        # BUG: this path hardcoded "#4285f4", disagreeing with
        # DEFAULT_CALENDAR_COLOR, which calendar_service and the frontend both
        # use — an unmapped calendar drafted a card in a different colour than
        # the same event shown after confirmation.
        with patch(f"{MODULE}.get_config", return_value={"configurable": {}}):
            out, _ = self._run(
                tools,
                CreateEventInput(
                    events=[
                        SingleEventInput(
                            summary="Draft",
                            start_datetime="2026-01-15T10:00:00",
                            calendar_id="unmapped",
                        )
                    ]
                ),
            )
        # A minimal event drafts with defaults and no optional keys — pinned whole
        # so the fallback color/name and the "omit when falsy" guards are all caught.
        assert out["calendar_options"][0] == {
            "index": 0,
            "summary": "Draft",
            "description": "",
            "is_all_day": False,
            "start": {"dateTime": "2026-01-15T10:00:00"},
            "end": {"dateTime": "2026-01-15T10:30:00"},
            "calendar_id": "unmapped",
            "color": DEFAULT_CALENDAR_COLOR,
            "calendar_name": "Calendar",
        }
        assert writer.call_args[0][0]["calendar_options"][0]["background_color"] == (
            DEFAULT_CALENDAR_COLOR
        )

    def test_immediate_path_falls_back_to_the_shared_default_color(self, tools, writer) -> None:
        with patch(f"{MODULE}.get_config", return_value={"configurable": {}}):
            self._run(
                tools,
                CreateEventInput(
                    events=[
                        SingleEventInput(
                            summary="Sync",
                            start_datetime="2026-01-15T10:00:00",
                            calendar_id="unmapped",
                        )
                    ],
                    confirm_immediately=True,
                ),
            )
        streamed = writer.call_args[0][0]["calendar_fetch_data"][0]
        assert streamed["background_color"] == DEFAULT_CALENDAR_COLOR

    def test_draft_uses_calendar_metadata_when_available(self, tools, writer) -> None:
        with patch(f"{MODULE}.get_config", return_value={"configurable": {}}):
            out, _ = self._run(
                tools,
                CreateEventInput(
                    events=[
                        SingleEventInput(
                            summary="Draft",
                            start_datetime="2026-01-15T10:00:00",
                            calendar_id="cal-1",
                            location="Room 3",
                            attendees=["a@b.com"],
                            create_meeting_room=True,
                        )
                    ]
                ),
                metadata=({"cal-1": "#abcdef"}, {"cal-1": "Team"}),
            )
        # Pin the whole draft option so a wrong key, default, or dropped field is caught.
        assert out["calendar_options"][0] == {
            "index": 0,
            "summary": "Draft",
            "description": "",
            "is_all_day": False,
            "start": {"dateTime": "2026-01-15T10:00:00"},
            "end": {"dateTime": "2026-01-15T10:30:00"},
            "calendar_id": "cal-1",
            "color": "#abcdef",
            "calendar_name": "Team",
            "location": "Room 3",
            "attendees": ["a@b.com"],
            "create_meeting_room": True,
        }

    def test_metadata_failure_still_drafts(self, tools, writer) -> None:
        with patch(f"{MODULE}.get_config", return_value={"configurable": {}}):
            out, _ = self._run(
                tools,
                CreateEventInput(
                    events=[SingleEventInput(summary="Draft", start_datetime="2026-01-15T10:00:00")]
                ),
                raises_metadata=True,
            )
        assert out["calendar_options"][0]["color"] == DEFAULT_CALENDAR_COLOR

    # -- validation --------------------------------------------------------

    def test_every_event_invalid_raises(self, tools, writer) -> None:
        with pytest.raises(ValueError, match="All events failed validation"):
            self._run(
                tools,
                CreateEventInput(
                    events=[SingleEventInput(summary="Bad", start_datetime="next tuesday")]
                ),
            )

    def test_partial_validation_failure_reports_the_rejected_events(self, tools, writer) -> None:
        # BUG: `errors` was discarded whenever at least one event survived, so a
        # batch where 1 of 2 events had an unparseable start time was reported to
        # the user as a clean success.
        with patch(f"{MODULE}.get_config", return_value={"configurable": {}}):
            out, _ = self._run(
                tools,
                CreateEventInput(
                    events=[
                        SingleEventInput(summary="Good", start_datetime="2026-01-15T10:00:00"),
                        SingleEventInput(summary="Bad", start_datetime="next tuesday"),
                    ]
                ),
            )
        assert len(out["calendar_options"]) == 1
        assert len(out["errors"]) == 1
        assert out["errors"][0]["index"] == 1
        assert out["errors"][0]["summary"] == "Bad"
        assert "Invalid start_datetime" in out["errors"][0]["error"]

    def test_partial_failure_is_reported_on_the_immediate_path_too(self, tools, writer) -> None:
        with patch(f"{MODULE}.get_config", return_value={"configurable": {}}):
            out, _ = self._run(
                tools,
                CreateEventInput(
                    events=[
                        SingleEventInput(summary="Good", start_datetime="2026-01-15T10:00:00"),
                        SingleEventInput(summary="Bad", start_datetime="whenever"),
                    ],
                    confirm_immediately=True,
                ),
            )
        assert out["created"] is True
        assert [e["summary"] for e in out["errors"]] == ["Bad"]

    def test_no_events_is_not_reported_as_created(self, tools, writer) -> None:
        out, _ = self._run(tools, CreateEventInput(events=[]))
        assert out["created"] is False
        assert out["calendar_options"] == []
        assert out["errors"] == []


# ---------------------------------------------------------------------------
# CUSTOM_GATHER_CONTEXT
# ---------------------------------------------------------------------------


class TestGatherContext:
    def test_delegates_to_the_day_summary_tool(self, tools) -> None:
        # BUG: this passed date.today() — the *server's* date — which defeated the
        # per-user timezone resolution inside CUSTOM_GET_DAY_SUMMARY. Omitting it
        # lets the day summary resolve "today" in the user's own zone.
        with patch(f"{MODULE}.execute_tool", return_value={"busy_hours": 3.0}) as execute:
            out = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH)
        assert out == {"busy_hours": 3.0}
        assert execute.call_args.args == ("GOOGLECALENDAR_CUSTOM_GET_DAY_SUMMARY", {}, "user-42")

    def test_missing_user_id_fails_before_dispatch(self, tools) -> None:
        with patch(f"{MODULE}.execute_tool") as execute:
            with pytest.raises(ValueError, match="Missing user_id"):
                tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, {})
        execute.assert_not_called()

    def test_downstream_failures_propagate(self, tools) -> None:
        with patch(f"{MODULE}.execute_tool", side_effect=RuntimeError("composio down")):
            with pytest.raises(RuntimeError, match="composio down"):
                tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH)


# ---------------------------------------------------------------------------
# GetDaySummaryInput default
# ---------------------------------------------------------------------------


def test_day_summary_input_leaves_today_to_the_tool() -> None:
    # BUG (root): a default_factory of datetime.now() froze "today" in the
    # server's local zone at validation time, so the tool could no longer tell
    # "the model omitted a date" from "the model asked for this date".
    assert GetDaySummaryInput().date is None
    assert GetDaySummaryInput(date="2026-03-15").date == "2026-03-15"


def test_zoneinfo_offset_guard_is_still_needed() -> None:
    # Pins the reason CUSTOM_GET_DAY_SUMMARY must go through Timezone.parse.
    with pytest.raises(Exception):
        ZoneInfo("+05:30")
