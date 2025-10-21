"""
Google Calendar-specific hooks using the enhanced decorator system.

These hooks implement writer functionality for frontend streaming
and response processing for Composio Google Calendar tools.
"""

from typing import Any

from app.config.loggers import app_logger as logger
from composio.types import ToolExecuteParams, ToolExecutionResponse
from langgraph.config import get_stream_writer

from .registry import register_after_hook, register_before_hook


# ====================== BEFORE EXECUTE HOOKS ======================
# These hooks send progress/streaming data to frontend before tool execution


@register_before_hook(tools=["GOOGLECALENDAR_CREATE_EVENT"])
def calendar_create_event_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle event creation and send calendar_options to frontend."""
    try:
        writer = get_stream_writer()
        arguments = params.get("arguments", {})

        # Build calendar_options data for frontend
        calendar_options = [
            {
                "summary": arguments.get("summary", ""),
                "description": arguments.get("description", ""),
                "start": arguments.get("start", ""),
                "end": arguments.get("end", ""),
                "is_all_day": arguments.get("is_all_day", False),
                "calendar_id": arguments.get("calendar_id", "primary"),
                "location": arguments.get("location"),
                "attendees": arguments.get("attendees"),
                "recurrence": arguments.get("recurrence"),
            }
        ]

        if writer:
            payload = {"calendar_options": calendar_options}
            writer(payload)

        return params

    except Exception as e:
        logger.error(f"Error in calendar_create_event_before_hook: {e}")
        return params


@register_before_hook(tools=["GOOGLECALENDAR_EVENTS_LIST"])
def calendar_events_list_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle event listing with default parameters."""
    try:
        arguments = params.get("arguments", {})

        # Set default calendar_id if not specified
        if "calendar_id" not in arguments or not arguments["calendar_id"]:
            arguments["calendar_id"] = "primary"

        # Set default max_results if not specified
        if "max_results" not in arguments or not arguments["max_results"]:
            arguments["max_results"] = 20

        params["arguments"] = arguments

        writer = get_stream_writer()
        if writer:
            payload = {"progress": "Fetching calendar events..."}
            writer(payload)

    except Exception as e:
        logger.error(f"Error in calendar_events_list_before_hook: {e}")

    return params


@register_before_hook(tools=["GOOGLECALENDAR_LIST_CALENDARS"])
def calendar_list_calendars_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle calendar list fetching."""
    try:
        writer = get_stream_writer()
        if writer:
            payload = {"progress": "Fetching your calendars..."}
            writer(payload)

    except Exception as e:
        logger.error(f"Error in calendar_list_calendars_before_hook: {e}")

    return params


@register_before_hook(
    tools=[
        "GOOGLECALENDAR_UPDATE_EVENT",
        "GOOGLECALENDAR_PATCH_EVENT",
    ]
)
def calendar_update_event_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle event update and send calendar_edit_options to frontend."""
    try:
        writer = get_stream_writer()
        arguments = params.get("arguments", {})

        # Build calendar_edit_options data for frontend
        edit_options = [
            {
                "action": "edit",
                "event_id": arguments.get("event_id", ""),
                "calendar_id": arguments.get("calendar_id", "primary"),
                "summary": arguments.get("summary"),
                "description": arguments.get("description"),
                "start": arguments.get("start"),
                "end": arguments.get("end"),
                "is_all_day": arguments.get("is_all_day"),
                "location": arguments.get("location"),
                "attendees": arguments.get("attendees"),
                "recurrence": arguments.get("recurrence"),
            }
        ]

        if writer:
            payload = {"calendar_edit_options": edit_options}
            writer(payload)

        return params

    except Exception as e:
        logger.error(f"Error in calendar_update_event_before_hook: {e}")
        return params


@register_before_hook(tools=["GOOGLECALENDAR_DELETE_EVENT"])
def calendar_delete_event_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle event deletion and send calendar_delete_options to frontend."""
    try:
        writer = get_stream_writer()
        arguments = params.get("arguments", {})

        # Build calendar_delete_options data for frontend
        delete_options = [
            {
                "action": "delete",
                "event_id": arguments.get("event_id", ""),
                "calendar_id": arguments.get("calendar_id", "primary"),
            }
        ]

        if writer:
            payload = {"calendar_delete_options": delete_options}
            writer(payload)

        return params

    except Exception as e:
        logger.error(f"Error in calendar_delete_event_before_hook: {e}")
        return params


@register_before_hook(
    tools=[
        "GOOGLECALENDAR_FIND_EVENT",
        "GOOGLECALENDAR_FIND_FREE_SLOTS",
    ]
)
def calendar_search_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle calendar search operations."""
    try:
        writer = get_stream_writer()
        arguments = params.get("arguments", {})

        if tool == "GOOGLECALENDAR_FIND_EVENT":
            query = arguments.get("query", "")
            payload = {"progress": f"Searching for events matching '{query}'..."}
        elif tool == "GOOGLECALENDAR_FIND_FREE_SLOTS":
            payload = {"progress": "Finding free time slots..."}
        else:
            payload = {"progress": "Searching calendar..."}

        if writer:
            writer(payload)

    except Exception as e:
        logger.error(f"Error in calendar_search_before_hook for {tool}: {e}")

    return params


@register_before_hook(
    tools=[
        "GOOGLECALENDAR_QUICK_ADD",
        "GOOGLECALENDAR_EVENTS_MOVE",
        "GOOGLECALENDAR_CLEAR_CALENDAR",
        "GOOGLECALENDAR_DUPLICATE_CALENDAR",
    ]
)
def calendar_operations_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle various calendar operations with progress updates."""
    try:
        writer = get_stream_writer()
        if not writer:
            return params

        if tool == "GOOGLECALENDAR_QUICK_ADD":
            payload = {"progress": "Creating quick event..."}
        elif tool == "GOOGLECALENDAR_EVENTS_MOVE":
            payload = {"progress": "Moving event to another calendar..."}
        elif tool == "GOOGLECALENDAR_CLEAR_CALENDAR":
            payload = {"progress": "Clearing calendar events..."}
        elif tool == "GOOGLECALENDAR_DUPLICATE_CALENDAR":
            payload = {"progress": "Duplicating calendar..."}
        else:
            return params

        writer(payload)

    except Exception as e:
        logger.error(f"Error in calendar_operations_before_hook for {tool}: {e}")

    return params


# ====================== AFTER EXECUTE HOOKS ======================
# These hooks process responses and send data to frontend after tool execution


@register_after_hook(tools=["GOOGLECALENDAR_EVENTS_LIST"])
def calendar_events_list_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process event list response and send data to frontend."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response.get("data", {}):
            return response.get("data", response)

        response_data = response.get("data", {})
        items = response_data.get("items", [])

        # Transform to calendar_fetch_data format for frontend
        calendar_fetch_data = []
        for event in items:
            start_time = ""
            start_obj = event.get("start", {})
            if start_obj.get("dateTime"):
                start_time = start_obj["dateTime"]
            elif start_obj.get("date"):
                start_time = start_obj["date"]

            calendar_fetch_data.append(
                {
                    "summary": event.get("summary", "No Title"),
                    "start_time": start_time,
                }
            )

        # Send to frontend
        if writer and calendar_fetch_data:
            payload = {"calendar_fetch_data": calendar_fetch_data}
            writer(payload)

        # Return minimal data for LLM
        minimal_events = []
        for event in items:
            minimal_event = {
                "id": event.get("id"),
                "summary": event.get("summary"),
                "start": event.get("start"),
                "end": event.get("end"),
            }

            # Add optional fields only if present
            if event.get("description"):
                minimal_event["description"] = event["description"]
            if event.get("location"):
                minimal_event["location"] = event["location"]
            if event.get("attendees"):
                minimal_event["attendees"] = [
                    {
                        "email": a.get("email"),
                        "responseStatus": a.get("responseStatus"),
                    }
                    for a in event["attendees"]
                ]

            minimal_events.append(minimal_event)

        return {
            "events": minimal_events,
            "total_events": len(minimal_events),
            "next_page_token": response_data.get("nextPageToken"),
        }

    except Exception as e:
        logger.error(f"Error in calendar_events_list_after_hook: {e}")
        return response.get("data", response)


@register_after_hook(tools=["GOOGLECALENDAR_LIST_CALENDARS"])
def calendar_list_calendars_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process calendar list response and send data to frontend."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response.get("data", {}):
            return response.get("data", response)

        response_data = response.get("data", {})
        items = response_data.get("items", [])

        # Transform to calendar_list_fetch_data format for frontend
        calendar_list_fetch_data = []
        for calendar in items:
            calendar_list_fetch_data.append(
                {
                    "name": calendar.get("summary", "Unknown Calendar"),
                    "id": calendar.get("id", ""),
                    "description": calendar.get("description", ""),
                    "backgroundColor": calendar.get("backgroundColor"),
                }
            )

        # Send to frontend
        if writer and calendar_list_fetch_data:
            payload = {"calendar_list_fetch_data": calendar_list_fetch_data}
            writer(payload)

        # Return minimal data for LLM
        minimal_calendars = [
            {
                "id": cal.get("id"),
                "summary": cal.get("summary"),
                "primary": cal.get("primary", False),
            }
            for cal in items
        ]

        return {"calendars": minimal_calendars, "total": len(minimal_calendars)}

    except Exception as e:
        logger.error(f"Error in calendar_list_calendars_after_hook: {e}")
        return response.get("data", response)


@register_after_hook(tools=["GOOGLECALENDAR_FIND_EVENT"])
def calendar_find_event_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process event search response and send data to frontend."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response.get("data", {}):
            return response.get("data", response)

        response_data = response.get("data", {})
        items = response_data.get("items", [])

        # Transform to calendar_fetch_data format for frontend (search results)
        calendar_fetch_data = []
        for event in items:
            start_time = ""
            start_obj = event.get("start", {})
            if start_obj.get("dateTime"):
                start_time = start_obj["dateTime"]
            elif start_obj.get("date"):
                start_time = start_obj["date"]

            calendar_fetch_data.append(
                {
                    "summary": event.get("summary", "No Title"),
                    "start_time": start_time,
                }
            )

        # Send to frontend
        if writer and calendar_fetch_data:
            payload = {"calendar_fetch_data": calendar_fetch_data}
            writer(payload)

        # Return minimal data for LLM
        minimal_events = [
            {
                "id": event.get("id"),
                "summary": event.get("summary"),
                "start": event.get("start"),
                "end": event.get("end"),
                "description": event.get("description"),
            }
            for event in items
        ]

        return {
            "matching_events": minimal_events,
            "total_found": len(minimal_events),
        }

    except Exception as e:
        logger.error(f"Error in calendar_find_event_after_hook: {e}")
        return response.get("data", response)


@register_after_hook(tools=["GOOGLECALENDAR_CREATE_EVENT"])
def calendar_create_event_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process event creation response."""
    try:
        if not response or "error" in response.get("data", {}):
            return response.get("data", response)

        response_data = response.get("data", {})

        # Return minimal confirmation for LLM
        return {
            "id": response_data.get("id"),
            "summary": response_data.get("summary"),
            "start": response_data.get("start"),
            "end": response_data.get("end"),
            "status": "created",
        }

    except Exception as e:
        logger.error(f"Error in calendar_create_event_after_hook: {e}")
        return response.get("data", response)


@register_after_hook(
    tools=[
        "GOOGLECALENDAR_UPDATE_EVENT",
        "GOOGLECALENDAR_PATCH_EVENT",
    ]
)
def calendar_update_event_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process event update response."""
    try:
        if not response or "error" in response.get("data", {}):
            return response.get("data", response)

        response_data = response.get("data", {})

        # Return minimal confirmation for LLM
        return {
            "id": response_data.get("id"),
            "summary": response_data.get("summary"),
            "start": response_data.get("start"),
            "end": response_data.get("end"),
            "status": "updated",
        }

    except Exception as e:
        logger.error(f"Error in calendar_update_event_after_hook: {e}")
        return response.get("data", response)


@register_after_hook(tools=["GOOGLECALENDAR_DELETE_EVENT"])
def calendar_delete_event_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process event deletion response."""
    try:
        if not response or "error" in response.get("data", {}):
            return response.get("data", response)

        # Return minimal confirmation for LLM
        return {
            "status": "deleted",
            "message": "Event deleted successfully",
        }

    except Exception as e:
        logger.error(f"Error in calendar_delete_event_after_hook: {e}")
        return response.get("data", response)


@register_after_hook(tools=["GOOGLECALENDAR_FIND_FREE_SLOTS"])
def calendar_find_free_slots_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process free slots search response."""
    try:
        if not response or "error" in response.get("data", {}):
            return response.get("data", response)

        response_data = response.get("data", {})

        # Return minimal data for LLM
        return {
            "free_slots": response_data.get("calendars", {}),
            "message": "Free time slots found",
        }

    except Exception as e:
        logger.error(f"Error in calendar_find_free_slots_after_hook: {e}")
        return response.get("data", response)


@register_after_hook(tools=["GOOGLECALENDAR_GET_CALENDAR"])
def calendar_get_calendar_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process get calendar response."""
    try:
        if not response or "error" in response.get("data", {}):
            return response.get("data", response)

        response_data = response.get("data", {})

        # Return minimal data for LLM
        return {
            "id": response_data.get("id"),
            "summary": response_data.get("summary"),
            "description": response_data.get("description"),
            "timeZone": response_data.get("timeZone"),
        }

    except Exception as e:
        logger.error(f"Error in calendar_get_calendar_after_hook: {e}")
        return response.get("data", response)


@register_after_hook(tools=["GOOGLECALENDAR_QUICK_ADD"])
def calendar_quick_add_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process quick add response."""
    try:
        if not response or "error" in response.get("data", {}):
            return response.get("data", response)

        response_data = response.get("data", {})

        # Return minimal confirmation for LLM
        return {
            "id": response_data.get("id"),
            "summary": response_data.get("summary"),
            "start": response_data.get("start"),
            "end": response_data.get("end"),
            "status": "created",
        }

    except Exception as e:
        logger.error(f"Error in calendar_quick_add_after_hook: {e}")
        return response.get("data", response)
