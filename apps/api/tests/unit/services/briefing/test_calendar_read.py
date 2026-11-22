"""Reading the user's calendar for the brief: their day, the week ahead, and a calendar that cannot answer.

The connected-integrations read and the calendar fetch are the faked seams.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from tests.factories import make_user_id
from tests.helpers import captured_wide_event, local_timezone, user_clock

from app.models.brief_payload_models import BriefingEvent
from app.models.calendar_models import (
    CalendarEventsResponse,
    CalendarResponse,
    GoogleCalendarEventResource,
    GoogleCalendarListEntry,
)
from app.services import calendar_service
from app.services.briefing import calendar_read
from app.services.briefing.calendar_read import CalendarGap, CalendarRead, read_calendar
from app.services.briefing.work import CompletedWork, count_week
from app.utils.errors import AppError, IntegrationNotConnectedError

USER_ID = make_user_id()
CLOCK = user_clock("Asia/Kolkata", date(2026, 10, 14), 7)


async def _calendar(days: int, starts_in: int = 0) -> CalendarRead:
    span = CLOCK.days(CLOCK.today + timedelta(days=starts_in), days)
    return await read_calendar(USER_ID, span, span)


def _event(
    summary: str, start: dict[str, str], location: str | None = None
) -> GoogleCalendarEventResource:
    data: dict[str, object] = {"summary": summary, "start": start}
    if location:
        data["location"] = location
    return GoogleCalendarEventResource.model_validate(data)


def _response(
    events: list[GoogleCalendarEventResource], failed: list[str] | None = None
) -> CalendarEventsResponse:
    return CalendarEventsResponse(
        events=events,
        selected_calendars=["primary"],
        has_more=False,
        calendars_truncated=[],
        calendars_failed=failed or [],
    )


class TestReadCalendar:
    @pytest.fixture
    def connected(self, monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        ids = AsyncMock(return_value={"googlecalendar"})
        monkeypatch.setattr(calendar_read, "get_connected_integration_ids", ids)
        return ids

    async def test_no_calendar_connected_reads_nothing(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        connected.return_value = {"gmail"}
        fetch = AsyncMock()
        monkeypatch.setattr(calendar_read, "get_calendar_events", fetch)

        assert (await _calendar(1)).gap is CalendarGap.NOT_CONNECTED
        fetch.assert_not_awaited()

    async def test_events_land_on_the_users_clock_in_start_order(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        fetch = AsyncMock(
            return_value=_response(
                events=[
                    _event(
                        "Sequoia partner meeting",
                        {"dateTime": "2026-10-14T05:30:00Z"},
                        "Menlo Park",
                    ),
                    _event("Offsite", {"date": "2026-10-14"}),
                    _event("Standup", {"dateTime": "2026-10-14T03:30:00Z"}),
                ]
            )
        )
        monkeypatch.setattr(calendar_read, "get_calendar_events", fetch)

        events = (await _calendar(1)).events

        assert [(e.date, e.start, e.title, e.location) for e in events] == [
            ("2026-10-14", None, "Offsite", None),
            ("2026-10-14", "09:00", "Standup", None),
            ("2026-10-14", "11:00", "Sequoia partner meeting", "Menlo Park"),
        ]
        window = fetch.await_args.kwargs
        assert window["time_min"] == "2026-10-13T18:30:00+00:00"
        assert window["time_max"] == "2026-10-14T18:30:00+00:00"

    async def test_a_timed_event_carries_its_end_calendar_answer_organizer_and_guests(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        meeting = GoogleCalendarEventResource.model_validate(
            {
                "summary": "Board review",
                "start": {"dateTime": "2026-10-14T05:30:00Z"},
                "end": {"dateTime": "2026-10-14T06:45:00Z"},
                "calendarTitle": "Work",
                "organizer": {"displayName": "Ada Lovelace", "email": "ada@example.com"},
                "attendees": [
                    {"self": True, "responseStatus": "tentative"},
                    {"email": "bob@example.com"},
                    {"email": "carol@example.com"},
                    {"email": "room@example.com", "resource": True},
                ],
            }
        )
        late = GoogleCalendarEventResource.model_validate(
            {
                "summary": "Launch watch",
                "start": {"dateTime": "2026-10-14T17:00:00Z"},
                "end": {"dateTime": "2026-10-14T19:00:00Z"},
            }
        )
        monkeypatch.setattr(
            calendar_read, "get_calendar_events", AsyncMock(return_value=_response([meeting, late]))
        )

        with local_timezone("UTC"):
            events = (await _calendar(1)).events

        assert events == [
            BriefingEvent(
                date="2026-10-14",
                start="11:00",
                end="12:15",
                title="Board review",
                calendar="Work",
                response=CalendarResponse.TENTATIVE,
                organizer="Ada Lovelace",
                guests=2,
            ),
            BriefingEvent(date="2026-10-14", start="22:30", title="Launch watch"),
        ]

    async def test_untitled_and_all_day_events_keep_their_place(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        untitled = GoogleCalendarEventResource.model_validate(
            {"start": {"dateTime": "2026-10-14T03:30:00Z"}}
        )
        fetch = AsyncMock(
            return_value=_response(events=[untitled, _event("   ", {"date": "2026-10-14"}, "Goa")])
        )
        monkeypatch.setattr(calendar_read, "get_calendar_events", fetch)

        events = (await _calendar(1)).events

        assert events == [
            BriefingEvent(date="2026-10-14", title="Untitled event", location="Goa"),
            BriefingEvent(date="2026-10-14", start="09:00", title="Untitled event"),
        ]
        connected.assert_awaited_once_with(USER_ID)
        assert fetch.await_args.args == (USER_ID,)
        assert fetch.await_args.kwargs["fetch_all"] is True

    async def test_a_calendar_failure_the_read_cannot_name_still_fails_it(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        monkeypatch.setattr(
            calendar_read, "get_calendar_events", AsyncMock(side_effect=RuntimeError("proxy down"))
        )

        with pytest.raises(RuntimeError, match="proxy down"):
            await _calendar(1)

    @pytest.mark.parametrize(
        "failure",
        [
            IntegrationNotConnectedError(
                integration_id="googlecalendar",
                integration_name="Google Calendar",
                why="the token expired",
                grant_died=True,
            ),
            AppError(message="Invalid Credentials", status_code=401),
        ],
    )
    async def test_an_expired_calendar_is_unavailable_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock, failure: AppError
    ) -> None:
        """Regression: an expired token on the calendar list failed the whole daily brief."""
        monkeypatch.setattr(calendar_service, "proxy_request", AsyncMock(side_effect=failure))

        assert (await _calendar(1)).gap is CalendarGap.UNAVAILABLE

    async def test_a_calendar_that_failed_to_answer_is_unavailable_not_empty(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        """Regression: a calendar whose events failed to load read as a free day."""
        listing = {"items": [{"id": "primary", "summary": "Ada"}]}
        monkeypatch.setattr(
            calendar_service,
            "proxy_request",
            AsyncMock(side_effect=[listing, AppError(message="Backend Error", status_code=503)]),
        )
        monkeypatch.setattr(
            calendar_service,
            "_resolve_selected_calendars",
            AsyncMock(return_value=[GoogleCalendarListEntry.model_validate(listing["items"][0])]),
        )

        assert (await _calendar(1)).gap is CalendarGap.UNAVAILABLE

    async def test_an_unavailable_calendar_is_a_warning_on_the_runs_event(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        monkeypatch.setattr(
            calendar_read,
            "get_calendar_events",
            AsyncMock(return_value=_response([], failed=["primary"])),
        )

        async with captured_wide_event() as event:
            await _calendar(1)

        assert [w["msg"] for w in event["warnings"]] == ["briefing.calendar_unavailable"]
        assert event["warnings"][0]["calendars_failed"] == 1

    async def test_a_failed_calendar_list_is_a_warning_naming_the_error(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        failure = AppError(message="Invalid Credentials", status_code=401)
        monkeypatch.setattr(calendar_service, "proxy_request", AsyncMock(side_effect=failure))

        async with captured_wide_event() as event:
            await _calendar(1)

        warning = event["warnings"][0]
        assert (warning["msg"], warning["error_type"], warning["error"]) == (
            "briefing.calendar_unavailable",
            "HTTPException",
            "401: Invalid Credentials",
        )

    async def test_days_ahead_shifts_the_window_forward(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        fetch = AsyncMock(return_value=_response(events=[]))
        monkeypatch.setattr(calendar_read, "get_calendar_events", fetch)

        await _calendar(7, starts_in=1)

        window = fetch.await_args.kwargs
        assert window["time_min"] == "2026-10-14T18:30:00+00:00"
        assert window["time_max"] == "2026-10-21T18:30:00+00:00"

    async def test_the_week_ahead_holds_only_its_own_days(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        """Google answers for any event overlapping the window; the days are the brief's."""
        events = [
            _event("Today", {"date": "2026-10-14"}),
            _event("Tomorrow", {"date": "2026-10-15"}),
            _event("Last day", {"date": "2026-10-21"}),
            _event("Past the week", {"date": "2026-10-22"}),
            GoogleCalendarEventResource.model_validate({"summary": "No start"}),
        ]
        monkeypatch.setattr(
            calendar_read, "get_calendar_events", AsyncMock(return_value=_response(events))
        )

        ahead = (await _calendar(7, starts_in=1)).events

        assert [e.title for e in ahead] == ["Tomorrow", "Last day"]

    async def test_the_days_read_holds_today_and_keeps_the_whole_window(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        raw = [
            _event("Standup", {"dateTime": "2026-10-14T03:30:00Z"}),
            _event("Offsite", {"date": "2026-10-15"}),
        ]
        monkeypatch.setattr(
            calendar_read, "get_calendar_events", AsyncMock(return_value=_response(raw))
        )

        day = await read_calendar(USER_ID, CLOCK.days(CLOCK.today, 7), CLOCK.days(CLOCK.today, 1))

        assert day.events == [BriefingEvent(date="2026-10-14", start="09:00", title="Standup")]
        assert day.raw == raw

    async def test_an_event_the_user_declined_is_not_on_their_day(
        self, monkeypatch: pytest.MonkeyPatch, connected: AsyncMock
    ) -> None:
        declined = GoogleCalendarEventResource.model_validate(
            {
                "summary": "Vendor pitch",
                "start": {"dateTime": "2026-10-14T05:30:00Z"},
                "attendees": [
                    {"email": "ada@x.test", "self": True, "responseStatus": "declined"},
                    {"email": "vendor@y.test", "responseStatus": "accepted"},
                ],
            }
        )
        kept = _event("Standup", {"dateTime": "2026-10-14T03:30:00Z"})
        monkeypatch.setattr(
            calendar_read,
            "get_calendar_events",
            AsyncMock(return_value=_response([declined, kept])),
        )

        events = (await _calendar(1)).events

        assert [e.title for e in events] == ["Standup"]

    def test_an_unread_calendar_holds_no_events_and_names_itself_unread(self) -> None:
        unread = CalendarRead(gap=CalendarGap.UNAVAILABLE)

        assert count_week(CLOCK, CompletedWork(), unread.events).ahead == []
        assert [s.app for s in unread.unread] == ["Google Calendar"]
