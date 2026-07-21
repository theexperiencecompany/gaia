from datetime import datetime, timedelta
from typing import Any, Union

from fastapi import HTTPException

from app.constants.calendar import DEFAULT_CALENDAR_COLOR
from app.constants.error_codes import INTEGRATION_NOT_CONNECTED
from app.db.repositories.calendar import calendar_repository
from app.models.calendar_models import (
    EventCreateRequest,
    EventDeleteRequest,
    EventUpdateRequest,
)
from app.services.composio.proxy_client import proxy_request
from app.utils.errors import AppError
from shared.py.wide_events import log

CALENDAR_TOOLKIT = "GOOGLECALENDAR"
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


async def _proxy(
    user_id: str,
    *,
    endpoint: str,
    method: str,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> Any:
    """Wrapper that converts Composio proxy errors to FastAPI HTTPException.

    Calendar callers (FastAPI endpoints, custom tools) historically expect
    HTTPException-shaped failures, so we normalize AppError here.
    """
    try:
        return await proxy_request(
            user_id=user_id,
            toolkit=CALENDAR_TOOLKIT,
            endpoint=endpoint,
            method=method,  # type: ignore[arg-type]
            body=body,
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
        detail: Any = exc.message
        if isinstance(provider_response, dict):
            error_message = provider_response.get("error", {})
            if isinstance(error_message, dict) and error_message.get("message"):
                detail = error_message["message"]
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


async def fetch_calendar_list(user_id: str, short: bool = False) -> Any:
    """Fetch the list of calendars for the authenticated user."""
    data = await _proxy(
        user_id,
        endpoint=f"{CALENDAR_API_BASE}/users/me/calendarList",
        method="GET",
    )

    if short:
        return [
            {
                "id": c.get("id"),
                "summary": c.get("summary"),
                "description": c.get("description"),
                "backgroundColor": c.get("backgroundColor"),
            }
            for c in (data or {}).get("items", [])
        ]

    return data


def filter_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter out birthdays and events missing a valid start time."""
    return [
        event
        for event in events
        if event.get("eventType") != "birthday"
        and "start" in event
        and ("dateTime" in event["start"] or "date" in event["start"])
    ]


async def fetch_calendar_events(
    calendar_id: str,
    user_id: str,
    page_token: str | None = None,
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 20,
) -> dict[str, Any]:
    """Fetch events for a specific calendar."""
    query: dict[str, Any] = {
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

    return await _proxy(
        user_id,
        endpoint=f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events",
        method="GET",
        query=query,
    )


async def fetch_all_calendar_events(
    calendar_id: str,
    user_id: str,
    time_min: str | None = None,
    time_max: str | None = None,
    max_per_page: int = 250,
) -> dict[str, Any]:
    """Fetch all events from a calendar within a date range, handling pagination."""
    all_items: list[dict[str, Any]] = []
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

        items = page_data.get("items", [])
        all_items.extend(items)

        next_page_token = page_data.get("nextPageToken")
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

    return {
        "items": all_items,
        "truncated": truncated,
        "total_fetched": len(all_items),
    }


async def list_calendars(
    user_id: str, short: bool = False
) -> Union[list[dict[str, Any]], dict[str, Any]]:
    """Retrieve the user's calendar list."""
    return await fetch_calendar_list(user_id, short)


async def get_calendar_metadata_map(
    user_id: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Fetch calendar list and return color/name mappings."""
    calendars = await list_calendars(user_id=user_id, short=True)

    color_map: dict[str, str] = {}
    name_map: dict[str, str] = {}

    if calendars and isinstance(calendars, list):
        for cal in calendars:
            if isinstance(cal, dict):
                cal_id = cal.get("id")
                if cal_id:
                    color_map[cal_id] = cal.get("backgroundColor", DEFAULT_CALENDAR_COLOR)
                    name_map[cal_id] = cal.get("summary", "Calendar")

    return color_map, name_map


def format_event_for_frontend(
    event: dict[str, Any],
    calendar_color_map: dict[str, str],
    calendar_name_map: dict[str, str],
) -> dict[str, Any]:
    """Format a calendar event for frontend display."""
    start_time = ""
    end_time = ""

    if event.get("start"):
        start_obj = event["start"]
        start_time = start_obj.get("dateTime") or start_obj.get("date", "")

    if event.get("end"):
        end_obj = event["end"]
        end_time = end_obj.get("dateTime") or end_obj.get("date", "")

    calendar_id = event.get("calendarId", "")
    calendar_name = calendar_name_map.get(
        calendar_id, event.get("calendarTitle", "Unknown Calendar")
    )
    background_color = calendar_color_map.get(calendar_id, DEFAULT_CALENDAR_COLOR)

    return {
        "summary": event.get("summary", "No Title"),
        "start_time": start_time,
        "end_time": end_time,
        "calendar_name": calendar_name,
        "background_color": background_color,
    }


async def get_calendar_events(
    user_id: str,
    page_token: str | None = None,
    selected_calendars: list[str] | None = None,
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int | None = 20,
    fetch_all: bool = False,
) -> dict[str, Any]:
    """Get events from the user's selected calendars with date-based pagination."""
    calendar_data = await fetch_calendar_list(user_id)
    calendars = calendar_data.get("items", [])

    user_selected_calendars: list[str] = []
    if selected_calendars is not None:
        user_selected_calendars = selected_calendars
        await calendar_repository.set_selected_calendars(user_id, user_selected_calendars)
    else:
        preferences = await calendar_repository.get_for_user(user_id)
        if preferences is not None and preferences.selected_calendars:
            user_selected_calendars = preferences.selected_calendars
        else:
            user_selected_calendars = [cal["id"] for cal in calendars]
            await calendar_repository.set_selected_calendars(user_id, user_selected_calendars)

    selected_cal_objs = [cal for cal in calendars if cal["id"] in user_selected_calendars]

    all_events: list[dict[str, Any]] = []
    seen_event_ids: set = set()
    calendars_truncated: list[str] = []

    if fetch_all or not max_results:
        log.info(f"Fetching ALL events for {len(selected_cal_objs)} calendars in date range")
        for cal in selected_cal_objs:
            try:
                result = await fetch_all_calendar_events(cal["id"], user_id, time_min, time_max)
                events = result.get("items", [])

                if result.get("truncated", False):
                    calendars_truncated.append(cal["id"])
                    log.warning(
                        f"Calendar {cal['id']} ({cal.get('summary', 'Unknown')}) was truncated"
                    )

                for event in events:
                    event_id = event.get("id")
                    if event_id and event_id in seen_event_ids:
                        continue
                    if event_id:
                        seen_event_ids.add(event_id)
                    event["calendarId"] = cal["id"]
                    event["calendarTitle"] = cal.get("summary", "")
                all_events.extend(filter_events(events))
            except Exception as e:
                log.error(f"Error fetching events for calendar {cal['id']}: {e}")
    else:
        for cal in selected_cal_objs:
            try:
                result = await fetch_calendar_events(
                    cal["id"], user_id, None, time_min, time_max, max_results
                )
                events = result.get("items", [])

                for event in events:
                    event_id = event.get("id")
                    if event_id and event_id in seen_event_ids:
                        continue
                    if event_id:
                        seen_event_ids.add(event_id)
                    event["calendarId"] = cal["id"]
                    event["calendarTitle"] = cal.get("summary", "")
                all_events.extend(filter_events(events))
            except Exception as e:
                log.error(f"Error fetching events for calendar {cal['id']}: {e}")

    all_events.sort(
        key=lambda e: e.get("start", {}).get("dateTime") or e.get("start", {}).get("date") or ""
    )

    log.set(
        calendar={
            "user_id": user_id,
            "calendars_queried": len(selected_cal_objs),
            "events_fetched": len(all_events),
            "calendars_truncated": len(calendars_truncated),
        }
    )
    log.info(f"Fetched {len(all_events)} total events from {len(selected_cal_objs)} calendars")

    return {
        "events": all_events,
        "selectedCalendars": user_selected_calendars,
        "has_more": len(calendars_truncated) > 0,
        "calendars_truncated": calendars_truncated,
    }


async def get_calendar_events_by_id(
    calendar_id: str,
    user_id: str,
    page_token: str | None = None,
    time_min: str | None = None,
    time_max: str | None = None,
) -> dict[str, Any]:
    """Fetch events for a specific calendar by its ID."""
    events_data = await fetch_calendar_events(calendar_id, user_id, page_token, time_min, time_max)

    events = filter_events(events_data.get("items", []))
    return {
        "events": events,
        "nextPageToken": events_data.get("nextPageToken"),
    }


async def create_calendar_event(
    event: EventCreateRequest,
    user_id: str,
) -> dict[str, Any]:
    """Create a new calendar event using the Google Calendar API."""
    calendar_id = event.calendar_id or "primary"

    event_payload: dict[str, Any] = {
        "summary": event.summary,
        "description": event.description,
    }

    if event.is_all_day:
        if event.start and event.end:
            start_date = event.start.split("T")[0] if "T" in event.start else event.start
            end_date = event.end.split("T")[0] if "T" in event.end else event.end
        elif event.start:
            start_date = event.start.split("T")[0] if "T" in event.start else event.start
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_date = (start_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            today = datetime.now()
            start_date = today.strftime("%Y-%m-%d")
            end_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")

        event_payload["start"] = {"date": start_date}
        event_payload["end"] = {"date": end_date}
    else:
        try:
            if not event.start or not event.end:
                raise HTTPException(
                    status_code=400,
                    detail="Start and end times are required for time-specific events",
                )

            timezone = getattr(event, "timezone", None) or "UTC"
            start_time = event.start
            end_time = event.end

            if (
                start_time
                and not start_time.endswith("Z")
                and "+" not in start_time
                and "-" not in start_time[-6:]
            ):
                start_time = start_time + "Z"
            if (
                end_time
                and not end_time.endswith("Z")
                and "+" not in end_time
                and "-" not in end_time[-6:]
            ):
                end_time = end_time + "Z"

            event_payload["start"] = {"dateTime": start_time, "timeZone": timezone}
            event_payload["end"] = {"dateTime": end_time, "timeZone": timezone}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid datetime format: {e!s}")

    if event.recurrence:
        try:
            recurrence_rules = event.recurrence.to_google_calendar_format()
            event_payload["recurrence"] = recurrence_rules

            if not event.is_all_day:
                timezone = getattr(event, "timezone", None) or "UTC"
                if "timeZone" in event_payload.get("start", {}):
                    event_payload["start"]["timeZone"] = timezone
                if "timeZone" in event_payload.get("end", {}):
                    event_payload["end"]["timeZone"] = timezone

        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid recurrence rule format: {e!s}")

    if event.attendees:
        event_payload["attendees"] = [{"email": e} for e in event.attendees]

    query_params: dict[str, Any] = {"sendUpdates": "all"} if event.attendees else {}
    if event.create_meeting_room:
        event_payload["conferenceData"] = {
            "createRequest": {
                "requestId": f"meet_{int(datetime.now().timestamp())}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
        query_params["conferenceDataVersion"] = "1"

    response_data = await _proxy(
        user_id,
        endpoint=f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events",
        method="POST",
        body=event_payload,
        query=query_params or None,
    )

    log.set(
        calendar={
            "action": "create_event",
            "calendar_id": calendar_id,
            "summary": event.summary,
            "event_id": response_data.get("id") if isinstance(response_data, dict) else None,
        }
    )
    return response_data


async def get_user_calendar_preferences(user_id: str) -> dict[str, list[str]]:
    """Retrieve the user's selected calendar preferences from the database."""
    preferences = await calendar_repository.get_for_user(user_id)
    if preferences is not None:
        return {"selectedCalendars": preferences.selected_calendars}
    raise HTTPException(status_code=404, detail="Calendar preferences not found")


async def update_user_calendar_preferences(
    user_id: str, selected_calendars: list[str]
) -> dict[str, str]:
    """Update the user's selected calendar preferences in the database."""
    changed = await calendar_repository.set_selected_calendars(user_id, selected_calendars)
    if changed:
        return {"message": "Calendar preferences updated successfully"}
    return {"message": "No changes made to calendar preferences"}


async def search_calendar_events_native(
    query: str,
    user_id: str,
    time_min: str | None = None,
    time_max: str | None = None,
) -> dict[str, Any]:
    """Search calendar events using Google Calendar API's native search."""
    calendar_list_data = await fetch_calendar_list(user_id)
    calendars = calendar_list_data.get("items", [])

    user_selected_calendars: list[str] = []
    preferences = await calendar_repository.get_for_user(user_id)
    if preferences is not None and preferences.selected_calendars:
        user_selected_calendars = preferences.selected_calendars
        log.info(f"User has calendar preferences: {user_selected_calendars}")
    else:
        user_selected_calendars = [cal["id"] for cal in calendars]
        log.info(
            f"No preferences found, defaulting to all calendars: {len(user_selected_calendars)} calendars"
        )

    selected_cal_objs = [cal for cal in calendars if cal["id"] in user_selected_calendars]

    log.info(
        f"Searching in {len(selected_cal_objs)} calendars: {[cal['summary'] for cal in selected_cal_objs]}"
    )

    if not selected_cal_objs:
        log.info("No selected calendars found, searching all available calendars")
        selected_cal_objs = calendars

    all_matching_events: list[dict[str, Any]] = []
    total_events_searched = 0

    for cal in selected_cal_objs:
        try:
            result = await search_events_in_calendar(cal["id"], query, user_id, time_min, time_max)
            events = result.get("items", [])
            log.info(f"Found {len(events)} events in calendar '{cal.get('summary', cal['id'])}'")

            for event in events:
                event["calendarId"] = cal["id"]
                event["calendarTitle"] = cal.get("summary", "")

            filtered_events = filter_events(events)
            log.info(
                f"After filtering: {len(filtered_events)} events in calendar '{cal.get('summary', cal['id'])}'"
            )

            all_matching_events.extend(filtered_events)
            total_events_searched += len(filtered_events)
        except Exception as e:
            log.error(f"Error searching events in calendar {cal['id']}: {e}")

    log.info(f"Total matching events across all calendars: {len(all_matching_events)}")

    if not all_matching_events and selected_cal_objs != calendars:
        log.info("No events found in selected calendars, searching all calendars...")

        for cal in calendars:
            try:
                result = await search_events_in_calendar(
                    cal["id"], query, user_id, time_min, time_max
                )
                events = result.get("items", [])

                if events:
                    log.info(
                        f"Found {len(events)} events in calendar '{cal.get('summary', cal['id'])}'"
                    )

                    for event in events:
                        event["calendarId"] = cal["id"]
                        event["calendarTitle"] = cal.get("summary", "")

                    filtered_events = filter_events(events)
                    all_matching_events.extend(filtered_events)
                    total_events_searched += len(filtered_events)
            except Exception as e:
                log.error(f"Error searching events in calendar {cal['id']}: {e}")

    return {
        "query": query,
        "matching_events": all_matching_events,
        "total_matches": len(all_matching_events),
        "total_events_searched": total_events_searched,
        "searched_calendars": [cal["summary"] for cal in selected_cal_objs],
    }


async def search_events_in_calendar(
    calendar_id: str,
    query: str,
    user_id: str,
    time_min: str | None = None,
    time_max: str | None = None,
) -> dict[str, Any]:
    """Search events in a specific calendar using Google Calendar API's native search."""
    params: dict[str, Any] = {
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
    result = await _proxy(
        user_id,
        endpoint=f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events",
        method="GET",
        query=params,
    )
    event_count = len(result.get("items", []))
    log.info(f"Calendar {calendar_id} search returned {event_count} events")
    return result


async def delete_calendar_event(
    event: EventDeleteRequest,
    user_id: str,
) -> dict[str, Any]:
    """Delete a calendar event using the Google Calendar API."""
    calendar_id = event.calendar_id or "primary"

    try:
        await _proxy(
            user_id,
            endpoint=f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event.event_id}",
            method="DELETE",
        )
        return {"success": True, "message": "Event deleted successfully"}
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="Event not found or already deleted")
        raise


async def update_calendar_event(
    event: EventUpdateRequest,
    user_id: str,
) -> dict[str, Any]:
    """Update a calendar event using the Google Calendar API."""
    calendar_id = event.calendar_id or "primary"
    endpoint = f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event.event_id}"

    try:
        existing_event = await _proxy(user_id, endpoint=endpoint, method="GET")
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="Event not found or access denied")
        raise

    event_payload: dict[str, Any] = {
        "summary": (
            event.summary if event.summary is not None else existing_event.get("summary", "")
        ),
        "description": (
            event.description
            if event.description is not None
            else existing_event.get("description", "")
        ),
    }

    if event.recurrence is not None:
        try:
            recurrence_rules = event.recurrence.to_google_calendar_format()
            event_payload["recurrence"] = recurrence_rules
        except Exception as e:
            log.error(f"Error processing recurrence rules: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid recurrence rule format: {e!s}")
    elif "recurrence" in existing_event:
        event_payload["recurrence"] = existing_event.get("recurrence", [])

    if event.start is not None or event.end is not None or event.is_all_day is not None:
        is_all_day = (
            event.is_all_day
            if event.is_all_day is not None
            else existing_event.get("start", {}).get("date") is not None
        )

        if is_all_day:
            if event.start is not None:
                start_date = event.start.split("T")[0] if "T" in event.start else event.start
            else:
                start_date = existing_event.get("start", {}).get("date", "")

            if event.end is not None:
                end_date = event.end.split("T")[0] if "T" in event.end else event.end
            else:
                end_date = existing_event.get("end", {}).get("date", "")

            event_payload["start"] = {"date": start_date}
            event_payload["end"] = {"date": end_date}
        else:
            try:
                if event.start is not None:
                    start_time = event.start
                else:
                    start_time = existing_event.get("start", {}).get("dateTime", "")

                if event.end is not None:
                    end_time = event.end
                else:
                    end_time = existing_event.get("end", {}).get("dateTime", "")

                timezone: str | None = None
                if event.timezone:
                    timezone = event.timezone
                elif hasattr(event, "timezone_offset") and event.timezone_offset:
                    timezone = event.timezone_offset
                elif existing_event.get("start", {}).get("timeZone"):
                    timezone = existing_event.get("start", {}).get("timeZone")

                if (
                    start_time
                    and not start_time.endswith("Z")
                    and "+" not in start_time
                    and "-" not in start_time[-6:]
                ):
                    start_time = start_time + "Z"
                if (
                    end_time
                    and not end_time.endswith("Z")
                    and "+" not in end_time
                    and "-" not in end_time[-6:]
                ):
                    end_time = end_time + "Z"

                start_payload: dict[str, str] = {"dateTime": start_time}
                end_payload: dict[str, str] = {"dateTime": end_time}

                if timezone:
                    start_payload["timeZone"] = timezone
                    end_payload["timeZone"] = timezone

                event_payload["start"] = start_payload
                event_payload["end"] = end_payload
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid datetime format: {e!s}")
    else:
        event_payload["start"] = existing_event.get("start", {})
        event_payload["end"] = existing_event.get("end", {})

    try:
        updated_event = await _proxy(user_id, endpoint=endpoint, method="PUT", body=event_payload)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="Event not found or access denied")
        raise

    if isinstance(updated_event, dict):
        updated_event["calendarId"] = calendar_id
    return updated_event
