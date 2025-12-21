"""Calendar tools using Composio custom tool infrastructure.

These tools provide calendar functionality using the access_token from Composio's
auth_credentials. Uses shared calendar_service functions for all operations.
"""

import zoneinfo
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
    GetDaySummaryInput,
    GetEventInput,
    ListCalendarsInput,
    PatchEventInput,
)
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
    @with_doc(CUSTOM_GET_DAY_SUMMARY_DOC)
    def CUSTOM_GET_DAY_SUMMARY(
        request: GetDaySummaryInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get a day's schedule summary with events, busy hours, and next event."""
        import asyncio

        access_token = _get_access_token(auth_credentials)
        user_id = _get_user_id(auth_credentials)

        # Get user's timezone from their preferences
        try:
            loop = asyncio.get_event_loop()
            user = loop.run_until_complete(user_service.get_user_by_id(user_id))
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
            except ValueError:
                return {
                    "success": False,
                    "error": f"Invalid date format: {request.date}. Use YYYY-MM-DD.",
                }
        else:
            target_date = now

        day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        try:
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
                    calendar_service.format_event_for_frontend(
                        event, color_map, name_map
                    )
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

            return {
                "success": True,
                "date": day_start.strftime("%Y-%m-%d"),
                "timezone": user_timezone,
                "events": formatted_events,
                "total_events": len(events),
                "next_event": next_event,
                "busy_hours": round(busy_minutes / 60, 1),
            }
        except Exception as e:
            logger.error(f"Error getting day summary: {e}")
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
            # calendar_ids=None means fetch from all user's selected calendars
            result = calendar_service.get_calendar_events(
                user_id=user_id,
                access_token=access_token,
                selected_calendars=request.calendar_ids,
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
                "has_more": result.get("has_more", False),
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
        """Get one or more calendar events by ID."""
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
                logger.error(f"Error getting event {event_ref.event_id}: {e}")
                errors.append(
                    {
                        "event_id": event_ref.event_id,
                        "calendar_id": event_ref.calendar_id,
                        "error": f"Event not found: {e}",
                    }
                )
            except Exception as e:
                logger.error(f"Error getting event {event_ref.event_id}: {e}")
                errors.append(
                    {
                        "event_id": event_ref.event_id,
                        "calendar_id": event_ref.calendar_id,
                        "error": str(e),
                    }
                )

        return {
            "success": len(errors) == 0,
            "events": results,
            "errors": errors if errors else None,
            "total_retrieved": len(results),
        }

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_DELETE_EVENT_DOC)
    def CUSTOM_DELETE_EVENT(
        request: DeleteEventInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Delete one or more calendar events."""
        access_token = _get_access_token(auth_credentials)
        headers = _auth_headers(access_token)
        params = {"sendUpdates": request.send_updates}

        deleted = []
        errors = []

        for event_ref in request.events:
            url = f"{CALENDAR_API_BASE}/calendars/{event_ref.calendar_id}/events/{event_ref.event_id}"
            try:
                resp = _http_client.delete(url, headers=headers, params=params)
                resp.raise_for_status()
                deleted.append(
                    {
                        "event_id": event_ref.event_id,
                        "calendar_id": event_ref.calendar_id,
                    }
                )
            except httpx.HTTPStatusError as e:
                logger.error(f"Error deleting event {event_ref.event_id}: {e}")
                errors.append(
                    {
                        "event_id": event_ref.event_id,
                        "calendar_id": event_ref.calendar_id,
                        "error": f"Failed to delete: {e}",
                    }
                )
            except Exception as e:
                logger.error(f"Error deleting event {event_ref.event_id}: {e}")
                errors.append(
                    {
                        "event_id": event_ref.event_id,
                        "calendar_id": event_ref.calendar_id,
                        "error": str(e),
                    }
                )

        return {
            "success": len(errors) == 0,
            "deleted": deleted,
            "errors": errors if errors else None,
            "total_deleted": len(deleted),
        }

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
        """Create one or more calendar events with ID mapping for recurrence."""
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
            else:
                body["start"] = {"dateTime": start_dt.isoformat()}
                body["end"] = {"dateTime": end_dt.isoformat()}

            if event.description:
                body["description"] = event.description
            if event.location:
                body["location"] = event.location
            if event.attendees:
                body["attendees"] = [{"email": email} for email in event.attendees]

            if request.confirm_immediately:
                # Create immediately
                url = f"{CALENDAR_API_BASE}/calendars/{event.calendar_id}/events"
                try:
                    resp = _http_client.post(
                        url,
                        headers=headers,
                        json=body,
                        params={"sendUpdates": "all"},
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
                except httpx.HTTPStatusError as e:
                    logger.error(f"Error creating event {event.summary}: {e}")
                    errors.append(
                        {
                            "index": index,
                            "summary": event.summary,
                            "error": f"Failed to create: {e}",
                        }
                    )
                except Exception as e:
                    logger.error(f"Error creating event {event.summary}: {e}")
                    errors.append(
                        {
                            "index": index,
                            "summary": event.summary,
                            "error": str(e),
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
                calendar_options.append(calendar_option)

        if request.confirm_immediately:
            return {
                "success": len(errors) == 0,
                "created": True,
                "created_events": created_events,
                "errors": errors if errors else None,
                "total_created": len(created_events),
            }
        else:
            return {
                "success": True,
                "created": False,
                "calendar_options": calendar_options,
                "intent": "calendar",
                "message": f"{len(calendar_options)} event(s) prepared for confirmation.",
            }

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
    ]
