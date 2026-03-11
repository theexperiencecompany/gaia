"""Calendar tools using Composio custom tool infrastructure.

These tools provide calendar functionality using the access_token from Composio's
auth_credentials. Uses shared calendar_service functions for all operations.

Note: Errors are raised as exceptions, not returned as dicts - Composio wraps
responses in {successful: bool, data: Any, error: str} format automatically.
"""

import asyncio
import concurrent.futures
import zoneinfo
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any, Dict, List

import httpx
from shared.py.wide_events import log
from app.decorators import with_doc
from app.models.calendar_models import (
    AddRecurrenceInput,
    CreateEventInput,
    DeleteEventInput,
    FetchEventsInput,
    FindEventInput,
    GetDaySummaryInput,
    GetEventInput,
    ListCalendarsInput,
    PatchEventInput,
)
from app.models.common_models import GatherContextInput
from app.services import calendar_service, user_service
from app.templates.docstrings.calendar_tool_docs import (
    CUSTOM_ADD_RECURRENCE as CUSTOM_ADD_RECURRENCE_DOC,
)
from app.templates.docstrings.calendar_tool_docs import (
    CUSTOM_CREATE_EVENT as CUSTOM_CREATE_EVENT_DOC,
)
from app.templates.docstrings.calendar_tool_docs import (
    CUSTOM_DELETE_EVENT as CUSTOM_DELETE_EVENT_DOC,
)
from app.templates.docstrings.calendar_tool_docs import (
    CUSTOM_FETCH_EVENTS as CUSTOM_FETCH_EVENTS_DOC,
)
from app.templates.docstrings.calendar_tool_docs import (
    CUSTOM_FIND_EVENT as CUSTOM_FIND_EVENT_DOC,
)
from app.templates.docstrings.calendar_tool_docs import (
    CUSTOM_GET_DAY_SUMMARY as CUSTOM_GET_DAY_SUMMARY_DOC,
)
from app.templates.docstrings.calendar_tool_docs import (
    CUSTOM_GET_EVENT as CUSTOM_GET_EVENT_DOC,
)
from app.templates.docstrings.calendar_tool_docs import (
    CUSTOM_LIST_CALENDARS as CUSTOM_LIST_CALENDARS_DOC,
)
from app.templates.docstrings.calendar_tool_docs import (
    CUSTOM_PATCH_EVENT as CUSTOM_PATCH_EVENT_DOC,
)
from app.utils.context_utils import execute_tool
from composio import Composio
from langgraph.config import get_config, get_stream_writer

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"

# Reusable sync HTTP client for direct API calls
_http_client = httpx.Client(timeout=30)


def _extract_datetime(dt: Any) -> str:
    """Extract a datetime string from a Google Calendar date/dateTime dict or string."""
    if not dt:
        return ""
    if isinstance(dt, str):
        return dt
    if isinstance(dt, dict):
        return dt.get("dateTime") or dt.get("date", "")
    return ""


def _format_event_for_stream(event: Dict[str, Any]) -> Dict[str, Any]:
    """Format a calendar event into the CalendarFetchData schema for frontend streaming."""
    return {
        "summary": event.get("summary", event.get("title", "")),
        "start_time": _extract_datetime(event.get("start")),
        "end_time": _extract_datetime(event.get("end")),
        "calendar_name": event.get("calendarTitle", event.get("calendar_name", "")),
        "background_color": event.get("backgroundColor", "#4285f4"),
    }


def _format_calendar_option_for_stream(opt: Dict[str, Any]) -> Dict[str, Any]:
    """Format a calendar draft option into CalendarOptions schema for frontend streaming."""
    formatted: Dict[str, Any] = {
        "summary": opt.get("summary", ""),
        "description": opt.get("description", ""),
        "is_all_day": opt.get("is_all_day", False),
        "calendar_id": opt.get("calendar_id", ""),
        "calendar_name": opt.get("calendar_name", ""),
        "background_color": opt.get("color", "#4285f4"),
        "start": _extract_datetime(opt.get("start")),
        "end": _extract_datetime(opt.get("end")),
    }
    if opt.get("location"):
        formatted["location"] = opt["location"]
    if opt.get("attendees"):
        formatted["attendees"] = opt["attendees"]
    if opt.get("create_meeting_room"):
        formatted["create_meeting_room"] = True
    return formatted


def _format_calendar_for_stream(cal: Dict[str, Any]) -> Dict[str, Any]:
    """Format a calendar entry into CalendarListFetchData schema for frontend streaming."""
    return {
        "name": cal.get("summary", cal.get("name", "")),
        "id": cal.get("id", ""),
        "description": cal.get("description", ""),
        "backgroundColor": cal.get("backgroundColor", cal.get("background_color")),
    }


def _get_access_token(auth_credentials: Dict[str, Any]) -> str:
    """Extract access token from auth_credentials."""
    token = auth_credentials.get("access_token")
    if not token:
        raise ValueError("Missing access_token in auth_credentials")
    return token


def _get_user_id(auth_credentials: Dict[str, Any]) -> str:
    """Extract user_id from auth_credentials."""
    return auth_credentials.get("user_id", "")


def _auth_headers(access_token: str) -> Dict[str, str]:
    """Return Bearer token header for Google Calendar API."""
    return {"Authorization": f"Bearer {access_token}"}


def _get_user_timezone() -> tzinfo | None:
    """Retrieve the user's timezone offset from the LangGraph RunnableConfig."""
    try:
        config = get_config()
        configurable = config.get("configurable", {})

        # Try user_timezone format like "+05:30"
        user_timezone_str = configurable.get("user_timezone")
        if user_timezone_str and len(user_timezone_str) >= 6:
            sign = 1 if user_timezone_str.startswith("+") else -1
            hours, minutes = map(int, user_timezone_str[1:].split(":"))
            return timezone(timedelta(seconds=sign * (hours * 3600 + minutes * 60)))

        # Fallback to user_time full ISO string
        user_time_str = configurable.get("user_time")
        if user_time_str:
            dt = datetime.fromisoformat(user_time_str)
            return dt.tzinfo
    except Exception:
        log.error("Error getting user timezone")
    return None


def register_calendar_custom_tools(composio: Composio) -> List[str]:
    """Register calendar tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_LIST_CALENDARS_DOC)
    def CUSTOM_LIST_CALENDARS(
        request: ListCalendarsInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        log.set(tool={"integration": "google_calendar", "action": "list_calendars"})
        access_token = _get_access_token(auth_credentials)
        calendars = calendar_service.list_calendars(access_token, short=request.short)

        # Stream calendar list to frontend
        writer = get_stream_writer()
        if calendars:
            writer(
                {
                    "calendar_list_fetch_data": [
                        _format_calendar_for_stream(cal)
                        for cal in calendars
                        if isinstance(cal, dict)
                    ]
                }
            )

        return {"calendars": calendars}

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_GET_DAY_SUMMARY_DOC)
    def CUSTOM_GET_DAY_SUMMARY(
        request: GetDaySummaryInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        log.set(tool={"integration": "google_calendar", "action": "get_day_summary"})
        access_token = _get_access_token(auth_credentials)
        user_id = _get_user_id(auth_credentials)

        # Get user's timezone from their preferences
        try:
            try:
                asyncio.get_running_loop()
                # Inside a running loop — offload to a new thread
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    user = pool.submit(
                        lambda: asyncio.run(user_service.get_user_by_id(user_id))
                    ).result(timeout=5)
                user_timezone = user.get("timezone") if user else None
            except RuntimeError:
                # No running loop — safe to use asyncio.run directly
                user = asyncio.run(user_service.get_user_by_id(user_id))
                user_timezone = user.get("timezone") if user else None
        except Exception:
            user_timezone = None

        # Use user's timezone or fallback to UTC
        tz: zoneinfo.ZoneInfo | timezone = timezone.utc
        try:
            if user_timezone:
                tz = zoneinfo.ZoneInfo(user_timezone)
            else:
                user_timezone = "UTC"
        except Exception:
            user_timezone = "UTC"

        # Determine target date
        now = datetime.now(tz)
        if request.date:
            try:
                target_date = datetime.strptime(request.date, "%Y-%m-%d").replace(
                    tzinfo=tz
                )
            except ValueError as e:
                raise ValueError(
                    f"Invalid date format: {request.date}. Use YYYY-MM-DD."
                ) from e
        else:
            target_date = now

        day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        result = calendar_service.get_calendar_events(
            user_id=user_id,
            access_token=access_token,
            selected_calendars=None,
            time_min=day_start.isoformat(),
            time_max=day_end.isoformat(),
            max_results=100,
        )

        events = result.get("events", [])

        try:
            color_map, name_map = calendar_service.get_calendar_metadata_map(
                access_token
            )
            formatted_events = [
                calendar_service.format_event_for_frontend(event, color_map, name_map)
                for event in events
            ]
        except Exception:
            formatted_events = events

        # Calculate busy hours
        busy_minutes: float = 0.0
        for event in events:
            start = event.get("start", {})
            end = event.get("end", {})
            if "dateTime" in start and "dateTime" in end:
                try:
                    start_dt = datetime.fromisoformat(
                        start["dateTime"].replace("Z", "+00:00")
                    )
                    end_dt = datetime.fromisoformat(
                        end["dateTime"].replace("Z", "+00:00")
                    )
                    duration = (end_dt - start_dt).total_seconds() / 60
                    busy_minutes += duration
                except Exception:  # nosec B110
                    pass

        next_event = None
        if day_start.date() == now.date():
            for event in events:
                start = event.get("start", {})
                if "dateTime" in start:
                    try:
                        event_start = datetime.fromisoformat(
                            start["dateTime"].replace("Z", "+00:00")
                        )
                        if event_start > now:
                            next_event = event
                            break
                    except Exception:  # nosec B110
                        pass

        result_data = {
            "date": day_start.strftime("%Y-%m-%d"),
            "timezone": user_timezone,
            "events": formatted_events,
            "next_event": next_event,
            "busy_hours": round(busy_minutes / 60, 1),
        }

        # Stream events to frontend
        writer = get_stream_writer()
        if formatted_events:
            writer(
                {
                    "calendar_fetch_data": [
                        _format_event_for_stream(e)
                        for e in formatted_events
                        if isinstance(e, dict)
                    ]
                }
            )

        return result_data

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_FETCH_EVENTS_DOC)
    def CUSTOM_FETCH_EVENTS(
        request: FetchEventsInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        log.set(tool={"integration": "google_calendar", "action": "fetch_events"})
        access_token = _get_access_token(auth_credentials)
        user_id = _get_user_id(auth_credentials)

        time_min = request.time_min or datetime.now(timezone.utc).isoformat()

        result = calendar_service.get_calendar_events(
            user_id=user_id,
            access_token=access_token,
            selected_calendars=request.calendar_ids if request.calendar_ids else None,
            time_min=time_min,
            time_max=request.time_max,
            max_results=request.max_results,
        )

        events = result.get("events", [])

        # Format events for frontend
        try:
            color_map, name_map = calendar_service.get_calendar_metadata_map(
                access_token
            )
            calendar_fetch_data = [
                calendar_service.format_event_for_frontend(event, color_map, name_map)
                for event in events
            ]
        except Exception:
            calendar_fetch_data = events

        # Stream fetched events to frontend
        writer = get_stream_writer()
        if calendar_fetch_data:
            writer(
                {
                    "calendar_fetch_data": [
                        _format_event_for_stream(e)
                        for e in calendar_fetch_data
                        if isinstance(e, dict)
                    ]
                }
            )

        return {
            "calendar_fetch_data": calendar_fetch_data,
            "has_more": result.get("has_more", False),
        }

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_FIND_EVENT_DOC)
    def CUSTOM_FIND_EVENT(
        request: FindEventInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        log.set(tool={"integration": "google_calendar", "action": "find_event"})
        access_token = _get_access_token(auth_credentials)
        user_id = _get_user_id(auth_credentials)

        result = calendar_service.search_calendar_events_native(
            query=request.query,
            user_id=user_id,
            access_token=access_token,
            time_min=request.time_min,
            time_max=request.time_max,
        )

        events = result.get("matching_events", [])

        # Format events for frontend
        try:
            color_map, name_map = calendar_service.get_calendar_metadata_map(
                access_token
            )
            calendar_search_data = [
                calendar_service.format_event_for_frontend(event, color_map, name_map)
                for event in events
            ]
        except Exception:
            calendar_search_data = events

        # Stream search results to frontend
        writer = get_stream_writer()
        if calendar_search_data:
            writer(
                {
                    "calendar_fetch_data": [
                        _format_event_for_stream(e)
                        for e in calendar_search_data
                        if isinstance(e, dict)
                    ]
                }
            )

        return {
            "events": events,
            "calendar_search_data": calendar_search_data,
        }

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_GET_EVENT_DOC)
    def CUSTOM_GET_EVENT(
        request: GetEventInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        log.set(tool={"integration": "google_calendar", "action": "get_event"})
        access_token = _get_access_token(auth_credentials)
        headers = _auth_headers(access_token)

        results = []
        errors = []

        for event_ref in request.events:
            url = f"{CALENDAR_API_BASE}/calendars/{event_ref.calendar_id}/events/{event_ref.event_id}"
            try:
                resp = _http_client.get(url, headers=headers)
                resp.raise_for_status()
                results.append(
                    {
                        "event_id": event_ref.event_id,
                        "calendar_id": event_ref.calendar_id,
                        "event": resp.json(),
                    }
                )
            except httpx.HTTPStatusError as e:
                log.error(f"Error getting event {event_ref.event_id}: {e}")
                errors.append(
                    {
                        "event_id": event_ref.event_id,
                        "calendar_id": event_ref.calendar_id,
                        "error": f"Event not found: {e}",
                    }
                )

        # If all events failed, raise an exception
        if errors and not results:
            raise RuntimeError(f"Failed to get events: {errors}")

        return {"events": results}

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_DELETE_EVENT_DOC)
    def CUSTOM_DELETE_EVENT(
        request: DeleteEventInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        log.set(tool={"integration": "google_calendar", "action": "delete_event"})
        access_token = _get_access_token(auth_credentials)
        headers = _auth_headers(access_token)

        deleted = []
        errors = []

        for event_ref in request.events:
            url = f"{CALENDAR_API_BASE}/calendars/{event_ref.calendar_id}/events/{event_ref.event_id}"
            try:
                resp = _http_client.delete(url, headers=headers)
                resp.raise_for_status()
                deleted.append(
                    {
                        "event_id": event_ref.event_id,
                        "calendar_id": event_ref.calendar_id,
                    }
                )
            except httpx.HTTPStatusError as e:
                log.error(f"Error deleting event {event_ref.event_id}: {e}")
                errors.append(
                    {
                        "event_id": event_ref.event_id,
                        "calendar_id": event_ref.calendar_id,
                        "error": f"Failed to delete: {e}",
                    }
                )

        # If all deletions failed, raise an exception
        if errors and not deleted:
            raise RuntimeError(f"Failed to delete events: {errors}")

        return {"deleted": deleted}

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_PATCH_EVENT_DOC)
    def CUSTOM_PATCH_EVENT(
        request: PatchEventInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        log.set(tool={"integration": "google_calendar", "action": "patch_event"})
        access_token = _get_access_token(auth_credentials)

        url = f"{CALENDAR_API_BASE}/calendars/{request.calendar_id}/events/{request.event_id}"
        headers = _auth_headers(access_token)
        headers["Content-Type"] = "application/json"
        params = {"sendUpdates": request.send_updates}

        body: Dict[str, Any] = {}
        if request.summary is not None:
            body["summary"] = request.summary
        if request.description is not None:
            body["description"] = request.description
        if request.location is not None:
            body["location"] = request.location
        if request.start_datetime is not None:
            body["start"] = {"dateTime": request.start_datetime}
        if request.end_datetime is not None:
            body["end"] = {"dateTime": request.end_datetime}
        if request.attendees is not None:
            body["attendees"] = [{"email": email} for email in request.attendees]

        resp = _http_client.patch(url, headers=headers, json=body, params=params)
        resp.raise_for_status()
        event = resp.json()

        return {"event": event}

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_ADD_RECURRENCE_DOC)
    def CUSTOM_ADD_RECURRENCE(
        request: AddRecurrenceInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        log.set(tool={"integration": "google_calendar", "action": "add_recurrence"})
        access_token = _get_access_token(auth_credentials)

        url = f"{CALENDAR_API_BASE}/calendars/{request.calendar_id}/events/{request.event_id}"
        headers = _auth_headers(access_token)

        get_resp = _http_client.get(url, headers=headers)
        get_resp.raise_for_status()
        event = get_resp.json()

        # Build RRULE string
        rrule_parts = [f"FREQ={request.frequency}"]
        if request.interval != 1:
            rrule_parts.append(f"INTERVAL={request.interval}")
        if request.count > 0:
            rrule_parts.append(f"COUNT={request.count}")
        if request.until_date:
            until_formatted = request.until_date.replace("-", "")
            rrule_parts.append(f"UNTIL={until_formatted}")
        if request.by_day:
            rrule_parts.append(f"BYDAY={','.join(request.by_day)}")

        rrule = "RRULE:" + ";".join(rrule_parts)
        event["recurrence"] = [rrule]

        headers["Content-Type"] = "application/json"
        put_resp = _http_client.put(url, headers=headers, json=event)
        put_resp.raise_for_status()

        return {
            "event": put_resp.json(),
            "recurrence_rule": rrule,
        }

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_CREATE_EVENT_DOC)
    def CUSTOM_CREATE_EVENT(
        request: CreateEventInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        log.set(tool={"integration": "google_calendar", "action": "create_event"})
        access_token = _get_access_token(auth_credentials)
        headers = _auth_headers(access_token)
        headers["Content-Type"] = "application/json"

        # Get calendar metadata for enrichment
        try:
            color_map, name_map = calendar_service.get_calendar_metadata_map(
                access_token
            )
        except Exception:
            color_map, name_map = {}, {}

        created_events = []
        calendar_options = []
        errors = []

        for index, event in enumerate(request.events):
            try:
                start_dt = datetime.fromisoformat(event.start_datetime)
            except ValueError as e:
                errors.append(
                    {
                        "index": index,
                        "summary": event.summary,
                        "error": f"Invalid start_datetime format: {e}",
                    }
                )
                continue

            duration = timedelta(
                hours=event.duration_hours, minutes=event.duration_minutes
            )
            end_dt = start_dt + duration

            body: Dict[str, Any] = {"summary": event.summary}

            if event.is_all_day:
                body["start"] = {"date": start_dt.strftime("%Y-%m-%d")}
                body["end"] = {"date": end_dt.strftime("%Y-%m-%d")}
            elif start_dt.tzinfo is not None:
                body["start"] = {"dateTime": start_dt.isoformat()}
                body["end"] = {"dateTime": end_dt.isoformat()}
            else:
                # Naive datetime — apply the user's timezone offset from config
                user_tz = _get_user_timezone()
                if user_tz is not None:
                    start_dt = start_dt.replace(tzinfo=user_tz)
                    end_dt = end_dt.replace(tzinfo=user_tz)
                body["start"] = {"dateTime": start_dt.isoformat()}
                body["end"] = {"dateTime": end_dt.isoformat()}
            if event.description:
                body["description"] = event.description
            if event.location:
                body["location"] = event.location
            if event.attendees:
                body["attendees"] = [{"email": email} for email in event.attendees]
            if event.create_meeting_room:
                body["conferenceData"] = {
                    "createRequest": {
                        "requestId": f"meet_{index}_{int(datetime.now().timestamp())}",
                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    }
                }

            if request.confirm_immediately:
                # Create immediately
                url = f"{CALENDAR_API_BASE}/calendars/{event.calendar_id}/events"
                params = {"sendUpdates": "all"}
                if event.create_meeting_room:
                    params["conferenceDataVersion"] = "1"

                resp = _http_client.post(
                    url,
                    headers=headers,
                    json=body,
                    params=params,
                )
                resp.raise_for_status()
                created_event = resp.json()
                created_events.append(
                    {
                        "index": index,
                        "summary": event.summary,
                        "event_id": created_event.get("id"),
                        "calendar_id": event.calendar_id,
                        "link": created_event.get("htmlLink"),
                        "start": body["start"],
                        "end": body["end"],
                    }
                )
            else:
                # Prepare for frontend confirmation
                calendar_option = {
                    "index": index,
                    "summary": event.summary,
                    "description": event.description or "",
                    "is_all_day": event.is_all_day,
                    "start": body["start"],
                    "end": body["end"],
                    "calendar_id": event.calendar_id,
                    "color": color_map.get(event.calendar_id, "#4285f4"),
                    "calendar_name": name_map.get(event.calendar_id, "Calendar"),
                }
                if event.location:
                    calendar_option["location"] = event.location
                if event.attendees:
                    calendar_option["attendees"] = event.attendees
                if event.create_meeting_room:
                    calendar_option["create_meeting_room"] = True
                calendar_options.append(calendar_option)

        # If all events failed with validation errors, raise
        if errors and not created_events and not calendar_options:
            raise ValueError(f"All events failed validation: {errors}")

        if request.confirm_immediately:
            # Stream created events to frontend
            writer = get_stream_writer()
            if created_events:
                writer(
                    {
                        "calendar_fetch_data": [
                            {
                                "summary": e.get("summary", ""),
                                "start_time": _extract_datetime(e.get("start")),
                                "end_time": _extract_datetime(e.get("end")),
                                "calendar_name": name_map.get(
                                    e.get("calendar_id", ""), ""
                                ),
                                "background_color": color_map.get(
                                    e.get("calendar_id", ""), "#4285f4"
                                ),
                            }
                            for e in created_events
                            if isinstance(e, dict)
                        ]
                    }
                )

            return {
                "created": len(created_events) > 0,
                "created_events": created_events,
            }
        else:
            # Stream draft options to frontend for user confirmation
            writer = get_stream_writer()
            writer(
                {
                    "calendar_options": [
                        _format_calendar_option_for_stream(opt)
                        for opt in calendar_options
                        if isinstance(opt, dict)
                    ]
                }
            )

            return {
                "created": False,
                "calendar_options": calendar_options,
                "message": (
                    f"{len(calendar_options)} event(s) have been drafted for review. "
                    "They have NOT been added to your calendar yet. "
                    "Inform the user to confirm or cancel using the event card."
                ),
            }

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Google Calendar context snapshot: today's events, busy hours, free slots.

        Zero required parameters. Returns today's schedule for situational awareness.
        """
        log.set(tool={"integration": "google_calendar", "action": "gather_context"})
        user_id = _get_user_id(auth_credentials)
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")
        date_str = date.today().strftime("%Y-%m-%d")
        return execute_tool(
            "GOOGLECALENDAR_CUSTOM_GET_DAY_SUMMARY", {"date": date_str}, user_id
        )

    return [
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
    ]
