from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from shared.py.wide_events import log
from app.db.mongodb.collections import get_sync_collection
from app.models.calendar_models import (
    EventCreateRequest,
    EventDeleteRequest,
    EventLookupRequest,
    EventUpdateRequest,
)
from app.services.composio.proxy_client import proxy_request_sync
from app.utils.errors import AppError
from fastapi import HTTPException

CALENDAR_TOOLKIT = "GOOGLECALENDAR"
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"

# Sync MongoDB collection for calendar preferences
calendars_collection = get_sync_collection("calendar")


def _proxy(
    user_id: str,
    *,
    endpoint: str,
    method: str,
    body: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, Any]] = None,
) -> Any:
    """Wrapper that converts Composio proxy errors to FastAPI HTTPException.

    Calendar callers (FastAPI endpoints, custom tools) historically expect
    HTTPException-shaped failures, so we normalize AppError here.
    """
    try:
        return proxy_request_sync(
            user_id=user_id,
            toolkit=CALENDAR_TOOLKIT,
            endpoint=endpoint,
            method=method,  # type: ignore[arg-type]
            body=body,
            query=query,
        )
    except AppError as exc:
        provider_response = exc.meta.get("provider_response")
        detail: Any = exc.message
        if isinstance(provider_response, dict):
            error_message = provider_response.get("error", {})
            if isinstance(error_message, dict) and error_message.get("message"):
                detail = error_message["message"]
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


def fetch_calendar_list(user_id: str, short: bool = False) -> Any:
    """Fetch the list of calendars for the authenticated user."""
    data = _proxy(
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


def filter_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter out birthdays and events missing a valid start time."""
    return [
        event
        for event in events
        if event.get("eventType") != "birthday"
        and "start" in event
        and ("dateTime" in event["start"] or "date" in event["start"])
    ]


def fetch_calendar_events(
    calendar_id: str,
    user_id: str,
    page_token: Optional[str] = None,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: int = 20,
) -> Dict[str, Any]:
    """Fetch events for a specific calendar."""
    query: Dict[str, Any] = {
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

    return _proxy(
        user_id,
        endpoint=f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events",
        method="GET",
        query=query,
    )


def fetch_all_calendar_events(
    calendar_id: str,
    user_id: str,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_per_page: int = 250,
) -> Dict[str, Any]:
    """Fetch all events from a calendar within a date range, handling pagination."""
    all_items: List[Dict[str, Any]] = []
    next_page_token: Optional[str] = None
    page_count = 0
    max_pages = 20

    while page_count < max_pages:
        page_data = fetch_calendar_events(
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


def list_calendars(
    user_id: str, short: bool = False
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """Retrieve the user's calendar list."""
    return fetch_calendar_list(user_id, short)


def initialize_calendar_preferences(user_id: str) -> None:
    """Initialize calendar preferences for a newly-connected user."""
    try:
        existing_preferences = calendars_collection.find_one({"user_id": user_id})
        if existing_preferences and existing_preferences.get("selected_calendars"):
            log.info(
                f"User {user_id} already has calendar preferences, skipping initialization"
            )
            return

        calendar_data = fetch_calendar_list(user_id)
        calendars = calendar_data.get("items", [])

        if not calendars:
            log.warning(f"No calendars found for user {user_id}")
            return

        all_calendar_ids = [cal["id"] for cal in calendars]

        calendars_collection.update_one(
            {"user_id": user_id},
            {"$set": {"selected_calendars": all_calendar_ids}},
            upsert=True,
        )

        log.info(
            f"Initialized calendar preferences for user {user_id}: "
            f"selected {len(all_calendar_ids)} calendars"
        )

    except Exception as e:
        log.error(
            f"Failed to initialize calendar preferences for user {user_id}: {e}",
            exc_info=True,
        )


def get_calendar_metadata_map(
    user_id: str,
) -> tuple[Dict[str, str], Dict[str, str]]:
    """Fetch calendar list and return color/name mappings."""
    calendars = list_calendars(user_id=user_id, short=True)

    color_map: Dict[str, str] = {}
    name_map: Dict[str, str] = {}

    if calendars and isinstance(calendars, list):
        for cal in calendars:
            if isinstance(cal, dict):
                cal_id = cal.get("id")
                if cal_id:
                    color_map[cal_id] = cal.get("backgroundColor", "#00bbff")
                    name_map[cal_id] = cal.get("summary", "Calendar")

    return color_map, name_map


def format_event_for_frontend(
    event: Dict[str, Any],
    calendar_color_map: Dict[str, str],
    calendar_name_map: Dict[str, str],
) -> Dict[str, Any]:
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
    background_color = calendar_color_map.get(calendar_id, "#00bbff")

    return {
        "summary": event.get("summary", "No Title"),
        "start_time": start_time,
        "end_time": end_time,
        "calendar_name": calendar_name,
        "background_color": background_color,
    }


def extract_unique_dates(calendar_options: List[Dict[str, Any]]) -> Dict[str, str]:
    """Extract unique dates with timezone offsets from calendar options."""
    event_dates_info: Dict[str, str] = {}
    for option in calendar_options:
        start_time = option.get("start", "")
        if start_time:
            try:
                dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
                tz_offset = dt.strftime("%z")
                if tz_offset:
                    tz_offset = f"{tz_offset[:3]}:{tz_offset[3:]}"
                else:
                    tz_offset = "+00:00"
                event_dates_info[date_str] = tz_offset
            except Exception as e:
                log.warning(f"Could not parse start time: {start_time}, {e}")
    return event_dates_info


def fetch_same_day_events(
    event_dates_info: Dict[str, str],
    user_id: str,
) -> List[Dict[str, Any]]:
    """Fetch events for each unique date."""
    same_day_events: List[Dict[str, Any]] = []
    for event_date, tz_offset in event_dates_info.items():
        time_min = f"{event_date}T00:00:00{tz_offset}"
        time_max = f"{event_date}T23:59:59{tz_offset}"
        try:
            result = get_calendar_events(
                user_id=user_id,
                time_min=time_min,
                time_max=time_max,
            )
            if isinstance(result, dict) and "events" in result:
                same_day_events.extend(result["events"])
        except Exception as e:
            log.error(f"Error fetching events for {event_date}: {e}")

    return same_day_events


def enrich_calendar_options_with_metadata(
    calendar_options: List[Dict[str, Any]],
    user_id: str,
) -> List[Dict[str, Any]]:
    """Add calendar colors, names, and same-day events to calendar options."""
    color_map, name_map = get_calendar_metadata_map(user_id)

    for option in calendar_options:
        calendar_id = option.get("calendar_id", "primary")
        option["background_color"] = color_map.get(calendar_id, "#00bbff")
        option["calendar_name"] = name_map.get(calendar_id, "Calendar")

    event_dates_info = extract_unique_dates(calendar_options)
    same_day_events = fetch_same_day_events(event_dates_info, user_id)

    for event in same_day_events:
        calendar_id = event.get("calendarId") or ""
        event["background_color"] = color_map.get(calendar_id, "#00bbff")

    for option in calendar_options:
        option["same_day_events"] = same_day_events

    return calendar_options


def get_calendar_events(
    user_id: str,
    page_token: Optional[str] = None,
    selected_calendars: Optional[List[str]] = None,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: Optional[int] = 20,
    fetch_all: bool = False,
) -> Dict[str, Any]:
    """Get events from the user's selected calendars with date-based pagination."""
    calendar_data = fetch_calendar_list(user_id)
    calendars = calendar_data.get("items", [])

    user_selected_calendars: List[str] = []
    if selected_calendars is not None:
        user_selected_calendars = selected_calendars
        calendars_collection.update_one(
            {"user_id": user_id},
            {"$set": {"selected_calendars": user_selected_calendars}},
            upsert=True,
        )
    else:
        preferences = calendars_collection.find_one({"user_id": user_id})
        if preferences and preferences.get("selected_calendars"):
            user_selected_calendars = preferences["selected_calendars"]
        else:
            user_selected_calendars = [cal["id"] for cal in calendars]
            calendars_collection.update_one(
                {"user_id": user_id},
                {"$set": {"selected_calendars": user_selected_calendars}},
                upsert=True,
            )

    selected_cal_objs = [
        cal for cal in calendars if cal["id"] in user_selected_calendars
    ]

    all_events: List[Dict[str, Any]] = []
    seen_event_ids: set = set()
    calendars_truncated: List[str] = []

    if fetch_all or not max_results:
        log.info(
            f"Fetching ALL events for {len(selected_cal_objs)} calendars in date range"
        )
        for cal in selected_cal_objs:
            try:
                result = fetch_all_calendar_events(
                    cal["id"], user_id, time_min, time_max
                )
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
                result = fetch_calendar_events(
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
        key=lambda e: (
            e.get("start", {}).get("dateTime") or e.get("start", {}).get("date") or ""
        )
    )

    log.set(
        calendar={
            "user_id": user_id,
            "calendars_queried": len(selected_cal_objs),
            "events_fetched": len(all_events),
            "calendars_truncated": len(calendars_truncated),
        }
    )
    log.info(
        f"Fetched {len(all_events)} total events from {len(selected_cal_objs)} calendars"
    )

    return {
        "events": all_events,
        "selectedCalendars": user_selected_calendars,
        "has_more": len(calendars_truncated) > 0,
        "calendars_truncated": calendars_truncated,
    }


def get_calendar_events_by_id(
    calendar_id: str,
    user_id: str,
    page_token: Optional[str] = None,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch events for a specific calendar by its ID."""
    events_data = fetch_calendar_events(
        calendar_id, user_id, page_token, time_min, time_max
    )

    events = filter_events(events_data.get("items", []))
    return {
        "events": events,
        "nextPageToken": events_data.get("nextPageToken"),
    }


def find_event_for_action(
    user_id: str,
    event_lookup_data: EventLookupRequest,
) -> Optional[dict]:
    """Find a specific event by query or by (calendar_id, event_id)."""
    if event_lookup_data.query:
        search_results = search_calendar_events_native(
            query=event_lookup_data.query,
            user_id=user_id,
        )
        matching_events = search_results.get("matching_events", [])
        if not matching_events:
            return None
        return matching_events[0]

    try:
        return _proxy(
            user_id,
            endpoint=(
                f"{CALENDAR_API_BASE}/calendars/"
                f"{event_lookup_data.calendar_id}/events/{event_lookup_data.event_id}"
            ),
            method="GET",
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise


def create_calendar_event(
    event: EventCreateRequest,
    user_id: str,
) -> Dict[str, Any]:
    """Create a new calendar event using the Google Calendar API."""
    calendar_id = event.calendar_id or "primary"

    event_payload: Dict[str, Any] = {
        "summary": event.summary,
        "description": event.description,
    }

    if event.is_all_day:
        if event.start and event.end:
            start_date = (
                event.start.split("T")[0] if "T" in event.start else event.start
            )
            end_date = event.end.split("T")[0] if "T" in event.end else event.end
        elif event.start:
            start_date = (
                event.start.split("T")[0] if "T" in event.start else event.start
            )
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
            raise HTTPException(
                status_code=400, detail=f"Invalid datetime format: {str(e)}"
            )

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
            raise HTTPException(
                status_code=400, detail=f"Invalid recurrence rule format: {str(e)}"
            )

    if event.attendees:
        event_payload["attendees"] = [{"email": e} for e in event.attendees]

    query_params: Dict[str, Any] = {"sendUpdates": "all"} if event.attendees else {}
    if event.create_meeting_room:
        event_payload["conferenceData"] = {
            "createRequest": {
                "requestId": f"meet_{int(datetime.now().timestamp())}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
        query_params["conferenceDataVersion"] = "1"

    response_data = _proxy(
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


def get_user_calendar_preferences(user_id: str) -> Dict[str, List[str]]:
    """Retrieve the user's selected calendar preferences from the database."""
    preferences = calendars_collection.find_one({"user_id": user_id})
    if preferences and "selected_calendars" in preferences:
        return {"selectedCalendars": preferences["selected_calendars"]}
    raise HTTPException(status_code=404, detail="Calendar preferences not found")


def update_user_calendar_preferences(
    user_id: str, selected_calendars: List[str]
) -> Dict[str, str]:
    """Update the user's selected calendar preferences in the database."""
    result = calendars_collection.update_one(
        {"user_id": user_id},
        {"$set": {"selected_calendars": selected_calendars}},
        upsert=True,
    )
    if result.modified_count or result.upserted_id:
        return {"message": "Calendar preferences updated successfully"}
    return {"message": "No changes made to calendar preferences"}


def search_calendar_events_native(
    query: str,
    user_id: str,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
) -> Dict[str, Any]:
    """Search calendar events using Google Calendar API's native search."""
    calendar_list_data = fetch_calendar_list(user_id)
    calendars = calendar_list_data.get("items", [])

    user_selected_calendars: List[str] = []
    preferences = calendars_collection.find_one({"user_id": user_id})
    if preferences and preferences.get("selected_calendars"):
        user_selected_calendars = preferences["selected_calendars"]
        log.info(f"User has calendar preferences: {user_selected_calendars}")
    else:
        user_selected_calendars = [cal["id"] for cal in calendars]
        log.info(
            f"No preferences found, defaulting to all calendars: {len(user_selected_calendars)} calendars"
        )

    selected_cal_objs = [
        cal for cal in calendars if cal["id"] in user_selected_calendars
    ]

    log.info(
        f"Searching in {len(selected_cal_objs)} calendars: {[cal['summary'] for cal in selected_cal_objs]}"
    )

    if not selected_cal_objs:
        log.info("No selected calendars found, searching all available calendars")
        selected_cal_objs = calendars

    all_matching_events: List[Dict[str, Any]] = []
    total_events_searched = 0

    for cal in selected_cal_objs:
        try:
            result = search_events_in_calendar(
                cal["id"], query, user_id, time_min, time_max
            )
            events = result.get("items", [])
            log.info(
                f"Found {len(events)} events in calendar '{cal.get('summary', cal['id'])}'"
            )

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
                result = search_events_in_calendar(
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


def search_events_in_calendar(
    calendar_id: str,
    query: str,
    user_id: str,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
) -> Dict[str, Any]:
    """Search events in a specific calendar using Google Calendar API's native search."""
    params: Dict[str, Any] = {
        "q": query,
        "maxResults": 50,
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    if time_min:
        params["timeMin"] = time_min
    if time_max:
        params["timeMax"] = time_max

    log.info(
        f"Searching calendar {calendar_id} with query '{query}' and params: {params}"
    )
    result = _proxy(
        user_id,
        endpoint=f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events",
        method="GET",
        query=params,
    )
    event_count = len(result.get("items", []))
    log.info(f"Calendar {calendar_id} search returned {event_count} events")
    return result


def delete_calendar_event(
    event: EventDeleteRequest,
    user_id: str,
) -> Dict[str, Any]:
    """Delete a calendar event using the Google Calendar API."""
    calendar_id = event.calendar_id or "primary"

    try:
        _proxy(
            user_id,
            endpoint=f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event.event_id}",
            method="DELETE",
        )
        return {"success": True, "message": "Event deleted successfully"}
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404, detail="Event not found or already deleted"
            )
        raise


def update_calendar_event(
    event: EventUpdateRequest,
    user_id: str,
) -> Dict[str, Any]:
    """Update a calendar event using the Google Calendar API."""
    calendar_id = event.calendar_id or "primary"
    endpoint = f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event.event_id}"

    try:
        existing_event = _proxy(user_id, endpoint=endpoint, method="GET")
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404, detail="Event not found or access denied"
            )
        raise

    event_payload: Dict[str, Any] = {
        "summary": (
            event.summary
            if event.summary is not None
            else existing_event.get("summary", "")
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
            raise HTTPException(
                status_code=400, detail=f"Invalid recurrence rule format: {str(e)}"
            )
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
                start_date = (
                    event.start.split("T")[0] if "T" in event.start else event.start
                )
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

                timezone: Optional[str] = None
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

                start_payload: Dict[str, str] = {"dateTime": start_time}
                end_payload: Dict[str, str] = {"dateTime": end_time}

                if timezone:
                    start_payload["timeZone"] = timezone
                    end_payload["timeZone"] = timezone

                event_payload["start"] = start_payload
                event_payload["end"] = end_payload
            except Exception as e:
                raise HTTPException(
                    status_code=400, detail=f"Invalid datetime format: {str(e)}"
                )
    else:
        event_payload["start"] = existing_event.get("start", {})
        event_payload["end"] = existing_event.get("end", {})

    try:
        updated_event = _proxy(
            user_id, endpoint=endpoint, method="PUT", body=event_payload
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404, detail="Event not found or access denied"
            )
        raise

    if isinstance(updated_event, dict):
        updated_event["calendarId"] = calendar_id
    return updated_event
