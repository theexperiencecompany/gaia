from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from app.constants.calendar import DEFAULT_CALENDAR_COLOR
from app.constants.error_codes import INTEGRATION_NOT_CONNECTED
from app.db.repositories.calendar import calendar_repository
from app.models.calendar_models import (
    CalendarEventDisplay,
    CalendarEventFetchResult,
    CalendarEventPageResponse,
    CalendarEventsResponse,
    CalendarListResponse,
    CalendarPreferencesResponse,
    CalendarPreferencesUpdateResponse,
    CalendarSearchResult,
    CalendarSummary,
    EventCreateRequest,
    EventDeleteRequest,
    EventDeleteResponse,
    EventUpdateRequest,
    GoogleCalendarAttendee,
    GoogleCalendarEventDateTime,
    GoogleCalendarEventResource,
    GoogleCalendarEventsPage,
    GoogleCalendarEventWrite,
    GoogleCalendarListEntry,
    GoogleConferenceCreateRequest,
    GoogleConferenceData,
    GoogleConferenceSolutionKey,
)
from app.services.composio.proxy_client import ProxyMethod, proxy_request
from app.utils.calendar_utils import CALENDAR_API_BASE, calendar_events_endpoint
from app.utils.errors import AppError
from shared.py.wide_events import log

CALENDAR_TOOLKIT = "GOOGLECALENDAR"
_DATE_FORMAT = "%Y-%m-%d"
_EVENT_NOT_FOUND_DETAIL = "Event not found or access denied"

QueryParams = dict[str, str | int]


async def _proxy(
    user_id: str,
    *,
    endpoint: str,
    method: ProxyMethod,
    body: GoogleCalendarEventWrite | None = None,
    query: QueryParams | None = None,
) -> object:
    """Wrapper that converts Composio proxy errors to FastAPI HTTPException.

    Returns Google's raw JSON as ``object`` — this is the provider boundary and
    the shape varies per endpoint, so the type stays opaque and every caller
    feeds it straight into a ``model_validate`` rather than reading fields off it.

    Calendar callers (FastAPI endpoints, custom tools) historically expect
    HTTPException-shaped failures, so we normalize AppError here.
    """
    try:
        return await proxy_request(
            user_id=user_id,
            toolkit=CALENDAR_TOOLKIT,
            endpoint=endpoint,
            method=method,
            body=body.model_dump(exclude_none=True) if body is not None else None,
            query=query,
        )
    except AppError as exc:
        # Integration not connected → emit the structured "integration" detail
        # the web client already understands (same shape as require_integration),
        # so it shows an actionable reconnect toast instead of the login modal.
        if exc.meta.get("error_code") == INTEGRATION_NOT_CONNECTED:
            raise HTTPException(
                status_code=exc.status_code,
                detail={
                    "type": "integration",
                    "error_code": INTEGRATION_NOT_CONNECTED,
                    "toolkit": exc.meta.get("toolkit"),
                    "message": "Reconnect Google Calendar to load your events.",
                },
            ) from exc
        provider_response = exc.meta.get("provider_response")
        detail: object = exc.message
        if isinstance(provider_response, dict):
            error_message = provider_response.get("error", {})
            if isinstance(error_message, dict) and error_message.get("message"):
                detail = error_message["message"]
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


async def list_calendars(user_id: str) -> CalendarListResponse:
    """Retrieve the user's calendar list."""
    return CalendarListResponse.model_validate(
        await _proxy(
            user_id,
            endpoint=f"{CALENDAR_API_BASE}/users/me/calendarList",
            method="GET",
        )
    )


def to_calendar_summaries(calendar_list: CalendarListResponse) -> list[CalendarSummary]:
    """Trim Google's calendar-list entries to the fields GAIA surfaces."""
    return [CalendarSummary.model_validate(entry.model_dump()) for entry in calendar_list.items]


def filter_events(
    events: list[GoogleCalendarEventResource],
) -> list[GoogleCalendarEventResource]:
    """Filter out birthdays and events missing a valid start time."""
    return [
        event
        for event in events
        if event.eventType != "birthday"
        and event.start is not None
        and (event.start.dateTime is not None or event.start.date is not None)
    ]


async def fetch_calendar_events(
    calendar_id: str,
    user_id: str,
    page_token: str | None = None,
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 20,
) -> GoogleCalendarEventsPage:
    """Fetch events for a specific calendar."""
    query: QueryParams = {
        "maxResults": max_results,
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    if time_min:
        query["timeMin"] = time_min
    if time_max:
        query["timeMax"] = time_max
    if page_token:
        query["pageToken"] = page_token

    return GoogleCalendarEventsPage.model_validate(
        await _proxy(
            user_id,
            endpoint=calendar_events_endpoint(calendar_id),
            method="GET",
            query=query,
        )
    )


async def fetch_all_calendar_events(
    calendar_id: str,
    user_id: str,
    time_min: str | None = None,
    time_max: str | None = None,
    max_per_page: int = 250,
) -> CalendarEventFetchResult:
    """Fetch all events from a calendar within a date range, handling pagination."""
    all_items: list[GoogleCalendarEventResource] = []
    next_page_token: str | None = None
    page_count = 0
    max_pages = 20

    while page_count < max_pages:
        page_data = await fetch_calendar_events(
            calendar_id=calendar_id,
            user_id=user_id,
            page_token=next_page_token,
            time_min=time_min,
            time_max=time_max,
            max_results=max_per_page,
        )

        all_items.extend(page_data.items)

        next_page_token = page_data.nextPageToken
        page_count += 1

        if not next_page_token:
            break

        if page_count > 5:
            log.info(
                "Calendar has many events - fetched so far, page",
                calendar_id=calendar_id,
                all_items_count=len(all_items),
                page_count=page_count,
            )

    truncated = page_count >= max_pages and next_page_token is not None
    if truncated:
        log.warning(
            "Calendar truncated at events (hit max pages limit)",
            calendar_id=calendar_id,
            all_items_count=len(all_items),
            user_id=user_id,
        )

    return CalendarEventFetchResult(
        items=all_items,
        truncated=truncated,
        total_fetched=len(all_items),
    )


async def get_calendar_metadata_map(
    user_id: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Fetch calendar list and return color/name mappings."""
    calendars = to_calendar_summaries(await list_calendars(user_id))

    color_map: dict[str, str] = {}
    name_map: dict[str, str] = {}

    for cal in calendars:
        if cal.id:
            color_map[cal.id] = cal.backgroundColor or DEFAULT_CALENDAR_COLOR
            name_map[cal.id] = cal.summary or "Calendar"

    return color_map, name_map


def format_event_for_frontend(
    event: GoogleCalendarEventResource,
    calendar_color_map: dict[str, str],
    calendar_name_map: dict[str, str],
) -> CalendarEventDisplay:
    """Format a calendar event for frontend display."""
    start_time = ""
    end_time = ""

    if event.start:
        start_time = event.start.dateTime or event.start.date or ""

    if event.end:
        end_time = event.end.dateTime or event.end.date or ""

    calendar_id = event.calendarId or ""
    fallback_name = event.calendarTitle if event.calendarTitle is not None else "Unknown Calendar"

    return CalendarEventDisplay(
        summary=event.summary if event.summary is not None else "No Title",
        start_time=start_time,
        end_time=end_time,
        calendar_name=calendar_name_map.get(calendar_id, fallback_name),
        background_color=calendar_color_map.get(calendar_id, DEFAULT_CALENDAR_COLOR),
    )


def _event_sort_key(event: GoogleCalendarEventResource) -> str:
    if event.start is None:
        return ""
    return event.start.dateTime or event.start.date or ""


async def _resolve_selected_calendars(
    user_id: str,
    calendars: list[GoogleCalendarListEntry],
    selected_calendars: list[str] | None,
) -> list[str]:
    """The calendar ids to read from. An explicit selection is persisted; absent
    one, stored preferences win, and a user with neither gets all their calendars."""
    if selected_calendars is not None:
        await calendar_repository.set_selected_calendars(user_id, selected_calendars)
        return selected_calendars

    preferences = await calendar_repository.get_for_user(user_id)
    if preferences is not None and preferences.selected_calendars:
        return preferences.selected_calendars

    all_calendar_ids = [cal.id for cal in calendars]
    await calendar_repository.set_selected_calendars(user_id, all_calendar_ids)
    return all_calendar_ids


def _tag_with_source_calendar(
    events: list[GoogleCalendarEventResource],
    cal: GoogleCalendarListEntry,
    seen_event_ids: set[str],
) -> list[GoogleCalendarEventResource]:
    """Stamp each event with the calendar it came from, skipping ids already
    stamped by an earlier calendar (the same event can be on several)."""
    for event in events:
        if event.id and event.id in seen_event_ids:
            continue
        if event.id:
            seen_event_ids.add(event.id)
        event.calendarId = cal.id
        event.calendarTitle = cal.summary or ""
    return filter_events(events)


async def get_calendar_events(
    user_id: str,
    selected_calendars: list[str] | None = None,
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int | None = 20,
    fetch_all: bool = False,
) -> CalendarEventsResponse:
    """Get events from the user's selected calendars with date-based pagination."""
    calendars = (await list_calendars(user_id)).items
    user_selected_calendars = await _resolve_selected_calendars(
        user_id, calendars, selected_calendars
    )
    selected_cal_objs = [cal for cal in calendars if cal.id in user_selected_calendars]

    all_events: list[GoogleCalendarEventResource] = []
    seen_event_ids: set[str] = set()
    calendars_truncated: list[str] = []
    fetch_every_page = fetch_all or not max_results

    if fetch_every_page:
        log.info(
            "Fetching ALL events for calendars in date range",
            selected_cal_objs_count=len(selected_cal_objs),
        )

    for cal in selected_cal_objs:
        try:
            if fetch_every_page:
                result = await fetch_all_calendar_events(cal.id, user_id, time_min, time_max)
                events = result.items
                if result.truncated:
                    calendars_truncated.append(cal.id)
                    log.warning("Calendar was truncated", calendar_id=cal.id, user_id=user_id)
            else:
                events = (
                    await fetch_calendar_events(
                        cal.id, user_id, None, time_min, time_max, max_results
                    )
                ).items

            all_events.extend(_tag_with_source_calendar(events, cal, seen_event_ids))
        except Exception as e:
            log.error(
                "Error fetching events for calendar",
                cal_id=cal.id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )

    all_events.sort(key=_event_sort_key)

    log.set(
        calendar={
            "user_id": user_id,
            "calendars_queried": len(selected_cal_objs),
            "events_fetched": len(all_events),
            "calendars_truncated": len(calendars_truncated),
        }
    )
    log.info(
        "Fetched total events from calendars",
        all_events_count=len(all_events),
        selected_cal_objs_count=len(selected_cal_objs),
    )

    return CalendarEventsResponse(
        events=all_events,
        selected_calendars=user_selected_calendars,
        has_more=len(calendars_truncated) > 0,
        calendars_truncated=calendars_truncated,
    )


async def get_calendar_events_by_id(
    calendar_id: str,
    user_id: str,
    page_token: str | None = None,
    time_min: str | None = None,
    time_max: str | None = None,
) -> CalendarEventPageResponse:
    """Fetch events for a specific calendar by its ID."""
    events_data = await fetch_calendar_events(calendar_id, user_id, page_token, time_min, time_max)

    return CalendarEventPageResponse(
        events=filter_events(events_data.items),
        next_page_token=events_data.nextPageToken,
    )


def _date_part(timestamp: str) -> str:
    """The date half of an ISO timestamp — Google's all-day events carry no time."""
    return timestamp.split("T", maxsplit=1)[0]


def _with_utc_suffix(timestamp: str) -> str:
    """Google rejects a naive timestamp; a value with no offset is taken as UTC."""
    if not timestamp or timestamp.endswith("Z") or "+" in timestamp or "-" in timestamp[-6:]:
        return timestamp
    return timestamp + "Z"


def _all_day_bounds(
    event: EventCreateRequest,
) -> tuple[GoogleCalendarEventDateTime, GoogleCalendarEventDateTime]:
    """All-day bounds, defaulting a missing end to the next day and a missing
    start to today (Google's end date is exclusive)."""
    if event.start and event.end:
        start_date = _date_part(event.start)
        end_date = _date_part(event.end)
    elif event.start:
        start_date = _date_part(event.start)
        # The bounds are date-only strings, so the +1 day is plain calendar
        # arithmetic on the parsed wall date — no tz attachment needed (and a
        # tz here would be invisible to the output, which is exactly the kind
        # of dead surface mutation-equivalent mutants survive on).
        end_date = (datetime.strptime(start_date, _DATE_FORMAT) + timedelta(days=1)).strftime(
            _DATE_FORMAT
        )
    else:
        today = datetime.now(UTC)
        start_date = today.strftime(_DATE_FORMAT)
        end_date = (today + timedelta(days=1)).strftime(_DATE_FORMAT)

    return (
        GoogleCalendarEventDateTime(date=start_date),
        GoogleCalendarEventDateTime(date=end_date),
    )


def _timed_bounds(
    event: EventCreateRequest,
) -> tuple[GoogleCalendarEventDateTime, GoogleCalendarEventDateTime]:
    try:
        if not event.start or not event.end:
            raise HTTPException(
                status_code=400,
                detail="Start and end times are required for time-specific events",
            )

        timezone = event.timezone or "UTC"
        return (
            GoogleCalendarEventDateTime(dateTime=_with_utc_suffix(event.start), timeZone=timezone),
            GoogleCalendarEventDateTime(dateTime=_with_utc_suffix(event.end), timeZone=timezone),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {e!s}") from e


def _create_recurrence_rules(
    event: EventCreateRequest,
    start_obj: GoogleCalendarEventDateTime,
    end_obj: GoogleCalendarEventDateTime,
) -> list[str] | None:
    """Google's RRULE list, re-stamping the timezone onto both bounds — a
    recurring series expands against it, so it has to be explicit."""
    if not event.recurrence:
        return None
    try:
        rules = event.recurrence.to_google_calendar_format()

        if not event.is_all_day:
            timezone = event.timezone or "UTC"
            if start_obj.timeZone is not None:
                start_obj.timeZone = timezone
            if end_obj.timeZone is not None:
                end_obj.timeZone = timezone

        return rules
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid recurrence rule format: {e!s}") from e


async def create_calendar_event(
    event: EventCreateRequest,
    user_id: str,
) -> GoogleCalendarEventResource:
    """Create a new calendar event using the Google Calendar API."""
    calendar_id = event.calendar_id or "primary"

    start_obj, end_obj = _all_day_bounds(event) if event.is_all_day else _timed_bounds(event)
    recurrence_rules = _create_recurrence_rules(event, start_obj, end_obj)

    query_params: QueryParams = {"sendUpdates": "all"} if event.attendees else {}
    conference_data: GoogleConferenceData | None = None
    if event.create_meeting_room:
        conference_data = GoogleConferenceData(
            createRequest=GoogleConferenceCreateRequest(
                requestId=f"meet_{int(datetime.now(UTC).timestamp())}",
                conferenceSolutionKey=GoogleConferenceSolutionKey(type="hangoutsMeet"),
            )
        )
        query_params["conferenceDataVersion"] = "1"

    payload = GoogleCalendarEventWrite(
        summary=event.summary,
        description=event.description,
        start=start_obj,
        end=end_obj,
        recurrence=recurrence_rules,
        attendees=(
            [GoogleCalendarAttendee(email=e) for e in event.attendees] if event.attendees else None
        ),
        conferenceData=conference_data,
    )

    created_event = GoogleCalendarEventResource.model_validate(
        await _proxy(
            user_id,
            endpoint=calendar_events_endpoint(calendar_id),
            method="POST",
            body=payload,
            query=query_params or None,
        )
    )

    log.set(
        calendar={
            "action": "create_event",
            "calendar_id": calendar_id,
            "summary": event.summary,
            "event_id": created_event.id,
        }
    )
    return created_event


async def get_user_calendar_preferences(user_id: str) -> CalendarPreferencesResponse:
    """Retrieve the user's selected calendar preferences from the database."""
    preferences = await calendar_repository.get_for_user(user_id)
    if preferences is not None:
        return CalendarPreferencesResponse(selected_calendars=preferences.selected_calendars)
    raise HTTPException(status_code=404, detail="Calendar preferences not found")


async def update_user_calendar_preferences(
    user_id: str, selected_calendars: list[str]
) -> CalendarPreferencesUpdateResponse:
    """Update the user's selected calendar preferences in the database."""
    changed = await calendar_repository.set_selected_calendars(user_id, selected_calendars)
    if changed:
        return CalendarPreferencesUpdateResponse(
            message="Calendar preferences updated successfully"
        )
    return CalendarPreferencesUpdateResponse(message="No changes made to calendar preferences")


async def _selected_search_calendars(
    user_id: str,
    calendars: list[GoogleCalendarListEntry],
) -> list[GoogleCalendarListEntry]:
    """The calendars a native search covers: stored preferences when present,
    otherwise every calendar the user has."""
    preferences = await calendar_repository.get_for_user(user_id)
    if preferences is not None and preferences.selected_calendars:
        user_selected_calendars = preferences.selected_calendars
        log.info("User has calendar preferences", user_selected_calendars=user_selected_calendars)
    else:
        user_selected_calendars = [cal.id for cal in calendars]
        log.info(
            "No preferences found, defaulting to all calendars: calendars",
            user_selected_calendars_count=len(user_selected_calendars),
        )

    selected_cal_objs = [cal for cal in calendars if cal.id in user_selected_calendars]

    log.info("Searching selected calendars", calendar_count=len(selected_cal_objs))

    if not selected_cal_objs:
        log.info("No selected calendars found, searching all available calendars")
        return calendars
    return selected_cal_objs


async def _search_calendars(
    calendars: list[GoogleCalendarListEntry],
    query: str,
    user_id: str,
    time_min: str | None,
    time_max: str | None,
) -> tuple[list[GoogleCalendarEventResource], int]:
    """Run the native search across each calendar, tagging hits with their
    source; a failing calendar is logged and skipped, not fatal to the search."""
    all_matching_events: list[GoogleCalendarEventResource] = []
    total_events_searched = 0

    for cal in calendars:
        try:
            result = await search_events_in_calendar(
                cal.id, query, user_id, time_min=time_min, time_max=time_max
            )
            events = result.items
            log.info("Found events in calendar", event_count=len(events), calendar_id=cal.id)

            for event in events:
                event.calendarId = cal.id
                event.calendarTitle = cal.summary or ""

            filtered_events = filter_events(events)
            log.info(
                "Events remaining after filtering",
                filtered_event_count=len(filtered_events),
                calendar_id=cal.id,
            )

            all_matching_events.extend(filtered_events)
            total_events_searched += len(filtered_events)
        except Exception as e:
            log.error(
                "Error searching events in calendar",
                cal_id=cal.id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )

    return all_matching_events, total_events_searched


async def search_calendar_events_native(
    query: str,
    user_id: str,
    time_min: str | None = None,
    time_max: str | None = None,
) -> CalendarSearchResult:
    """Search calendar events using Google Calendar API's native search."""
    calendars = (await list_calendars(user_id)).items
    selected_cal_objs = await _selected_search_calendars(user_id, calendars)

    all_matching_events, total_events_searched = await _search_calendars(
        selected_cal_objs, query, user_id, time_min, time_max
    )

    log.info(
        "Total matching events across all calendars",
        all_matching_events_count=len(all_matching_events),
    )

    if not all_matching_events and selected_cal_objs != calendars:
        # Fallback covers only the calendars the selected pass did NOT already
        # search — re-hitting them would double the API cost per empty result.
        searched_ids = {cal.id for cal in selected_cal_objs}
        remaining = [cal for cal in calendars if cal.id not in searched_ids]
        log.info("No events found in selected calendars, searching remaining calendars...")
        all_matching_events, total_events_searched = await _search_calendars(
            remaining, query, user_id, time_min, time_max
        )

    return CalendarSearchResult(
        query=query,
        matching_events=all_matching_events,
        total_matches=len(all_matching_events),
        total_events_searched=total_events_searched,
        searched_calendars=[cal.summary or "" for cal in selected_cal_objs],
    )


async def search_events_in_calendar(
    calendar_id: str,
    query: str,
    user_id: str,
    time_min: str | None = None,
    time_max: str | None = None,
) -> GoogleCalendarEventsPage:
    """Search events in a specific calendar using Google Calendar API's native search."""
    params: QueryParams = {
        "q": query,
        "maxResults": 50,
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    if time_min:
        params["timeMin"] = time_min
    if time_max:
        params["timeMax"] = time_max

    log.info("Searching calendar", calendar_id=calendar_id, time_min=time_min, time_max=time_max)
    result = GoogleCalendarEventsPage.model_validate(
        await _proxy(
            user_id,
            endpoint=calendar_events_endpoint(calendar_id),
            method="GET",
            query=params,
        )
    )
    log.info(
        "Calendar search returned events", calendar_id=calendar_id, event_count=len(result.items)
    )
    return result


async def delete_calendar_event(
    event: EventDeleteRequest,
    user_id: str,
) -> EventDeleteResponse:
    """Delete a calendar event using the Google Calendar API."""
    calendar_id = event.calendar_id or "primary"

    try:
        await _proxy(
            user_id,
            endpoint=calendar_events_endpoint(calendar_id, event.event_id),
            method="DELETE",
        )
        return EventDeleteResponse(success=True, message="Event deleted successfully")
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404, detail="Event not found or already deleted"
            ) from exc
        raise


def _update_recurrence_rules(
    event: EventUpdateRequest, existing_event: GoogleCalendarEventResource
) -> list[str] | None:
    """The requested RRULE list, or the stored one when the update omits it."""
    if event.recurrence is None:
        return existing_event.recurrence
    try:
        return event.recurrence.to_google_calendar_format()
    except Exception as e:
        log.error("Error processing recurrence rules", error=str(e), error_type=type(e).__name__)
        raise HTTPException(status_code=400, detail=f"Invalid recurrence rule format: {e!s}") from e


def _merged_all_day_bounds(
    event: EventUpdateRequest,
    existing_start: GoogleCalendarEventDateTime,
    existing_end: GoogleCalendarEventDateTime,
) -> tuple[GoogleCalendarEventDateTime, GoogleCalendarEventDateTime]:
    start_date = _date_part(event.start) if event.start is not None else (existing_start.date or "")
    end_date = _date_part(event.end) if event.end is not None else (existing_end.date or "")
    return (
        GoogleCalendarEventDateTime(date=start_date),
        GoogleCalendarEventDateTime(date=end_date),
    )


def _merged_timed_bounds(
    event: EventUpdateRequest,
    existing_start: GoogleCalendarEventDateTime,
    existing_end: GoogleCalendarEventDateTime,
) -> tuple[GoogleCalendarEventDateTime, GoogleCalendarEventDateTime]:
    try:
        start_time = event.start if event.start is not None else (existing_start.dateTime or "")
        end_time = event.end if event.end is not None else (existing_end.dateTime or "")
        timezone = event.timezone or event.timezone_offset or existing_start.timeZone or None

        return (
            GoogleCalendarEventDateTime(dateTime=_with_utc_suffix(start_time), timeZone=timezone),
            GoogleCalendarEventDateTime(dateTime=_with_utc_suffix(end_time), timeZone=timezone),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {e!s}") from e


def _merge_event_bounds(
    event: EventUpdateRequest,
    existing_start: GoogleCalendarEventDateTime,
    existing_end: GoogleCalendarEventDateTime,
) -> tuple[GoogleCalendarEventDateTime, GoogleCalendarEventDateTime]:
    """Overlay the requested start/end onto the stored ones. An update that
    touches neither (nor all-day-ness) leaves the existing bounds alone."""
    if event.start is None and event.end is None and event.is_all_day is None:
        return existing_start, existing_end

    is_all_day = (
        event.is_all_day if event.is_all_day is not None else existing_start.date is not None
    )
    if is_all_day:
        return _merged_all_day_bounds(event, existing_start, existing_end)
    return _merged_timed_bounds(event, existing_start, existing_end)


async def update_calendar_event(
    event: EventUpdateRequest,
    user_id: str,
) -> GoogleCalendarEventResource:
    """Update a calendar event using the Google Calendar API."""
    calendar_id = event.calendar_id or "primary"
    endpoint = calendar_events_endpoint(calendar_id, event.event_id)

    try:
        existing_event = GoogleCalendarEventResource.model_validate(
            await _proxy(user_id, endpoint=endpoint, method="GET")
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail=_EVENT_NOT_FOUND_DETAIL) from exc
        raise

    recurrence_rules = _update_recurrence_rules(event, existing_event)
    start_obj, end_obj = _merge_event_bounds(
        event,
        existing_event.start or GoogleCalendarEventDateTime(),
        existing_event.end or GoogleCalendarEventDateTime(),
    )

    payload = GoogleCalendarEventWrite(
        summary=(event.summary if event.summary is not None else (existing_event.summary or "")),
        description=(
            event.description
            if event.description is not None
            else (existing_event.description or "")
        ),
        start=start_obj,
        end=end_obj,
        recurrence=recurrence_rules,
    )

    try:
        updated_event = GoogleCalendarEventResource.model_validate(
            await _proxy(user_id, endpoint=endpoint, method="PUT", body=payload)
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail=_EVENT_NOT_FOUND_DETAIL) from exc
        raise

    updated_event.calendarId = calendar_id
    return updated_event
