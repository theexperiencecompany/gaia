"""Calendar tools using Composio custom tool infrastructure.

These tools provide calendar functionality using the access_token from Composio's
auth_credentials. Uses shared calendar_service functions for all operations.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx
from app.config.loggers import chat_logger as logger
from app.decorators import with_doc
from app.models.calendar_models import (
    AddRecurrenceInput,
    CreateEventInput,
    DeleteEventInput,
    FetchEventsInput,
    FindEventInput,
    GetEventInput,
    ListCalendarsInput,
    PatchEventInput,
)
from app.services import calendar_service
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
    CUSTOM_GET_EVENT as CUSTOM_GET_EVENT_DOC,
)
from app.templates.docstrings.calendar_tool_docs import (
    CUSTOM_LIST_CALENDARS as CUSTOM_LIST_CALENDARS_DOC,
)
from app.templates.docstrings.calendar_tool_docs import (
    CUSTOM_PATCH_EVENT as CUSTOM_PATCH_EVENT_DOC,
)
from composio import Composio

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"

# Reusable sync HTTP client for direct API calls
_http_client = httpx.Client(timeout=30)


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


def register_calendar_custom_tools(composio: Composio) -> List[str]:
    """Register calendar tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_LIST_CALENDARS_DOC)
    def CUSTOM_LIST_CALENDARS(
        request: ListCalendarsInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        access_token = _get_access_token(auth_credentials)

        try:
            calendars = calendar_service.list_calendars(
                access_token, short=request.short
            )
            return {"success": True, "calendars": calendars}
        except Exception as e:
            logger.error(f"Error listing calendars: {e}")
            return {"success": False, "error": str(e)}

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_FETCH_EVENTS_DOC)
    def CUSTOM_FETCH_EVENTS(
        request: FetchEventsInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        access_token = _get_access_token(auth_credentials)
        user_id = _get_user_id(auth_credentials)

        time_min = request.time_min or datetime.now(timezone.utc).isoformat()

        try:
            # Use calendar_service.get_calendar_events for consistency
            result = calendar_service.get_calendar_events(
                user_id=user_id,
                access_token=access_token,
                selected_calendars=[request.calendar_id]
                if request.calendar_id != "primary"
                else None,
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
                    calendar_service.format_event_for_frontend(
                        event, color_map, name_map
                    )
                    for event in events
                ]
            except Exception:
                calendar_fetch_data = events

            return {
                "success": True,
                "events": events,
                "calendar_fetch_data": calendar_fetch_data,
                "total_events": len(events),
            }
        except Exception as e:
            logger.error(f"Error fetching events: {e}")
            return {"success": False, "error": str(e)}

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_FIND_EVENT_DOC)
    def CUSTOM_FIND_EVENT(
        request: FindEventInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        access_token = _get_access_token(auth_credentials)
        user_id = _get_user_id(auth_credentials)

        try:
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
                    calendar_service.format_event_for_frontend(
                        event, color_map, name_map
                    )
                    for event in events
                ]
            except Exception:
                calendar_search_data = events

            return {
                "success": True,
                "events": events,
                "calendar_search_data": calendar_search_data,
                "count": len(events),
                "query": request.query,
            }
        except Exception as e:
            logger.error(f"Error searching events: {e}")
            return {"success": False, "error": str(e)}

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_GET_EVENT_DOC)
    def CUSTOM_GET_EVENT(
        request: GetEventInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        access_token = _get_access_token(auth_credentials)

        url = f"{CALENDAR_API_BASE}/calendars/{request.calendar_id}/events/{request.event_id}"
        headers = _auth_headers(access_token)

        try:
            resp = _http_client.get(url, headers=headers)
            resp.raise_for_status()
            return {"success": True, "event": resp.json()}
        except httpx.HTTPStatusError as e:
            logger.error(f"Error getting event: {e}")
            return {"success": False, "error": f"Event not found: {e}"}
        except Exception as e:
            logger.error(f"Error getting event: {e}")
            return {"success": False, "error": str(e)}

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_DELETE_EVENT_DOC)
    def CUSTOM_DELETE_EVENT(
        request: DeleteEventInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        access_token = _get_access_token(auth_credentials)

        url = f"{CALENDAR_API_BASE}/calendars/{request.calendar_id}/events/{request.event_id}"
        headers = _auth_headers(access_token)
        params = {"sendUpdates": request.send_updates}

        try:
            resp = _http_client.delete(url, headers=headers, params=params)
            resp.raise_for_status()
            return {"success": True, "message": f"Event {request.event_id} deleted"}
        except httpx.HTTPStatusError as e:
            logger.error(f"Error deleting event: {e}")
            return {"success": False, "error": f"Failed to delete event: {e}"}
        except Exception as e:
            logger.error(f"Error deleting event: {e}")
            return {"success": False, "error": str(e)}

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_PATCH_EVENT_DOC)
    def CUSTOM_PATCH_EVENT(
        request: PatchEventInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
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

        try:
            resp = _http_client.patch(url, headers=headers, json=body, params=params)
            resp.raise_for_status()
            return {"success": True, "event": resp.json()}
        except httpx.HTTPStatusError as e:
            logger.error(f"Error patching event: {e}")
            return {"success": False, "error": f"Failed to update event: {e}"}
        except Exception as e:
            logger.error(f"Error patching event: {e}")
            return {"success": False, "error": str(e)}

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_ADD_RECURRENCE_DOC)
    def CUSTOM_ADD_RECURRENCE(
        request: AddRecurrenceInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        access_token = _get_access_token(auth_credentials)

        url = f"{CALENDAR_API_BASE}/calendars/{request.calendar_id}/events/{request.event_id}"
        headers = _auth_headers(access_token)

        try:
            get_resp = _http_client.get(url, headers=headers)
            get_resp.raise_for_status()
            event = get_resp.json()

            # Build RRULE string
            rrule_parts = [f"FREQ={request.frequency}"]
            if request.interval != 1:
                rrule_parts.append(f"INTERVAL={request.interval}")
            if request.count is not None:
                rrule_parts.append(f"COUNT={request.count}")
            if request.until_date is not None:
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
                "success": True,
                "event": put_resp.json(),
                "recurrence_rule": rrule,
            }
        except httpx.HTTPStatusError as e:
            logger.error(f"Error adding recurrence: {e}")
            return {"success": False, "error": f"Failed to add recurrence: {e}"}
        except Exception as e:
            logger.error(f"Error adding recurrence: {e}")
            return {"success": False, "error": str(e)}

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_CREATE_EVENT_DOC)
    def CUSTOM_CREATE_EVENT(
        request: CreateEventInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        access_token = _get_access_token(auth_credentials)

        try:
            start_dt = datetime.fromisoformat(request.start_datetime)
        except ValueError as e:
            return {"success": False, "error": f"Invalid start_datetime format: {e}"}

        duration = timedelta(
            hours=request.duration_hours, minutes=request.duration_minutes
        )
        end_dt = start_dt + duration

        body: Dict[str, Any] = {"summary": request.summary}

        if request.is_all_day:
            body["start"] = {"date": start_dt.strftime("%Y-%m-%d")}
            body["end"] = {"date": end_dt.strftime("%Y-%m-%d")}
        else:
            body["start"] = {"dateTime": start_dt.isoformat()}
            body["end"] = {"dateTime": end_dt.isoformat()}

        if request.description:
            body["description"] = request.description
        if request.location:
            body["location"] = request.location
        if request.attendees:
            body["attendees"] = [{"email": email} for email in request.attendees]

        if request.confirm_immediately:
            url = f"{CALENDAR_API_BASE}/calendars/{request.calendar_id}/events"
            headers = _auth_headers(access_token)
            headers["Content-Type"] = "application/json"

            try:
                resp = _http_client.post(
                    url,
                    headers=headers,
                    json=body,
                    params={"sendUpdates": "all"},
                )
                resp.raise_for_status()
                return {"success": True, "event": resp.json(), "created": True}
            except httpx.HTTPStatusError as e:
                logger.error(f"Error creating event: {e}")
                return {"success": False, "error": f"Failed to create event: {e}"}
            except Exception as e:
                logger.error(f"Error creating event: {e}")
                return {"success": False, "error": str(e)}

        # Send to frontend for confirmation
        calendar_option = {
            "summary": request.summary,
            "description": request.description or "",
            "is_all_day": request.is_all_day,
            "start": body["start"],
            "end": body["end"],
            "calendar_id": request.calendar_id,
        }

        if request.location:
            calendar_option["location"] = request.location
        if request.attendees:
            calendar_option["attendees"] = request.attendees

        # Enrich with calendar metadata
        try:
            color_map, name_map = calendar_service.get_calendar_metadata_map(
                access_token
            )
            calendar_option["color"] = color_map.get(request.calendar_id, "#4285f4")
            calendar_option["calendar_name"] = name_map.get(
                request.calendar_id, "Calendar"
            )
        except Exception as e:
            logger.warning(f"Could not enrich calendar options: {e}")

        return {
            "success": True,
            "created": False,
            "calendar_options": [calendar_option],
            "intent": "calendar",
            "message": "Event prepared for confirmation. Please confirm to create.",
        }

    return [
        "GOOGLECALENDAR_CUSTOM_CREATE_EVENT",
        "GOOGLECALENDAR_CUSTOM_LIST_CALENDARS",
        "GOOGLECALENDAR_CUSTOM_FETCH_EVENTS",
        "GOOGLECALENDAR_CUSTOM_FIND_EVENT",
        "GOOGLECALENDAR_CUSTOM_GET_EVENT",
        "GOOGLECALENDAR_CUSTOM_DELETE_EVENT",
        "GOOGLECALENDAR_CUSTOM_PATCH_EVENT",
        "GOOGLECALENDAR_CUSTOM_ADD_RECURRENCE",
    ]
