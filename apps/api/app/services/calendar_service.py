from datetime import datetime, timedelta

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
from app.utils.errors import AppError
from shared.py.wide_events import log

CALENDAR_TOOLKIT = "GOOGLECALENDAR"
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
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
            endpoint=f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events",
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
                f"Calendar {calendar_id} has many events - fetched {len(all_items)} so far, page {page_count}"
            )

    truncated = page_count >= max_pages and next_page_token is not None
    if truncated:
        log.warning(
            f"Calendar {calendar_id} truncated at {len(all_items)} events (hit max pages limit)"
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
        log.info(f"Fetching ALL events for {len(selected_cal_objs)} calendars in date range")

    for cal in selected_cal_objs:
        try:
            if fetch_every_page:
                result = await fetch_all_calendar_events(cal.id, user_id, time_min, time_max)
                events = result.items
                if result.truncated:
                    calendars_truncated.append(cal.id)
                    log.warning(f"Calendar {cal.id} ({cal.summary or 'Unknown'}) was truncated")
            else:
                events = (
                    await fetch_calendar_events(
                        cal.id, user_id, None, time_min, time_max, max_results
                    )
                ).items

            all_events.extend(_tag_with_source_calendar(events, cal, seen_event_ids))
        except Exception as e:
            log.error(f"Error fetching events for calendar {cal.id}: {e}")

    all_events.sort(key=_event_sort_key)

    log.set(
        calendar={
            "user_id": user_id,
            "calendars_queried": len(selected_cal_objs),
            "events_fetched": len(all_events),
            "calendars_truncated": len(calendars_truncated),
        }
    )
    log.info(f"Fetched {len(all_events)} total events from {len(selected_cal_objs)} calendars")

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
        start_dt = datetime.strptime(start_date, _DATE_FORMAT)
        end_date = (start_dt + timedelta(days=1)).strftime(_DATE_FORMAT)
    else:
        today = datetime.now()
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
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {e!s}")


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
        raise HTTPException(status_code=400, detail=f"Invalid recurrence rule format: {e!s}")


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
                requestId=f"meet_{int(datetime.now().timestamp())}",
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
            endpoint=f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events",
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


async def search_calendar_events_native(
    query: str,
    user_id: str,
    time_min: str | None = None,
    time_max: str | None = None,
) -> CalendarSearchResult:
    """Search calendar events using Google Calendar API's native search."""
    calendars = (await list_calendars(user_id)).items

    user_selected_calendars: list[str] = []
    preferences = await calendar_repository.get_for_user(user_id)
    if preferences is not None and preferences.selected_calendars:
        user_selected_calendars = preferences.selected_calendars
        log.info(f"User has calendar preferences: {user_selected_calendars}")
    else:
        user_selected_calendars = [cal.id for cal in calendars]
        log.info(
            f"No preferences found, defaulting to all calendars: {len(user_selected_calendars)} calendars"
        )

    selected_cal_objs = [cal for cal in calendars if cal.id in user_selected_calendars]

    log.info(
        f"Searching in {len(selected_cal_objs)} calendars: {[cal.summary for cal in selected_cal_objs]}"
    )

    if not selected_cal_objs:
        log.info("No selected calendars found, searching all available calendars")
        selected_cal_objs = calendars

    all_matching_events: list[GoogleCalendarEventResource] = []
    total_events_searched = 0

    for cal in selected_cal_objs:
        try:
            result = await search_events_in_calendar(cal.id, query, user_id, time_min, time_max)
            events = result.items
            log.info(f"Found {len(events)} events in calendar '{cal.summary or cal.id}'")

            for event in events:
                event.calendarId = cal.id
                event.calendarTitle = cal.summary or ""

            filtered_events = filter_events(events)
            log.info(
                f"After filtering: {len(filtered_events)} events in calendar '{cal.summary or cal.id}'"
            )

            all_matching_events.extend(filtered_events)
            total_events_searched += len(filtered_events)
        except Exception as e:
            log.error(f"Error searching events in calendar {cal.id}: {e}")

    log.info(f"Total matching events across all calendars: {len(all_matching_events)}")

    if not all_matching_events and selected_cal_objs != calendars:
        log.info("No events found in selected calendars, searching all calendars...")

        for cal in calendars:
            try:
                result = await search_events_in_calendar(cal.id, query, user_id, time_min, time_max)
                events = result.items

                if events:
                    log.info(f"Found {len(events)} events in calendar '{cal.summary or cal.id}'")

                    for event in events:
                        event.calendarId = cal.id
                        event.calendarTitle = cal.summary or ""

                    filtered_events = filter_events(events)
                    all_matching_events.extend(filtered_events)
                    total_events_searched += len(filtered_events)
            except Exception as e:
                log.error(f"Error searching events in calendar {cal.id}: {e}")

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

    log.info(f"Searching calendar {calendar_id} with query '{query}' and params: {params}")
    result = GoogleCalendarEventsPage.model_validate(
        await _proxy(
            user_id,
            endpoint=f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events",
            method="GET",
            query=params,
        )
    )
    log.info(f"Calendar {calendar_id} search returned {len(result.items)} events")
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
            endpoint=f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event.event_id}",
            method="DELETE",
        )
        return EventDeleteResponse(success=True, message="Event deleted successfully")
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="Event not found or already deleted")
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
        log.error(f"Error processing recurrence rules: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid recurrence rule format: {e!s}")


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
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {e!s}")


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
    endpoint = f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event.event_id}"

    try:
        existing_event = GoogleCalendarEventResource.model_validate(
            await _proxy(user_id, endpoint=endpoint, method="GET")
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail=_EVENT_NOT_FOUND_DETAIL)
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
            raise HTTPException(status_code=404, detail=_EVENT_NOT_FOUND_DETAIL)
        raise

    updated_event.calendarId = calendar_id
    return updated_event
