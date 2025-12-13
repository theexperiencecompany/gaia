"""Reminder LangChain tools."""

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Optional

from app.config.loggers import reminders_logger as logger
from app.decorators import with_doc, with_rate_limiting
from app.templates.docstrings.reminder_tool_docs import (
    CREATE_REMINDER,
    DELETE_REMINDER,
    GET_REMINDER,
    LIST_USER_REMINDERS,
    SEARCH_REMINDERS,
    UPDATE_REMINDER,
)
from app.models.reminder_models import (
    AgentType,
    CreateReminderToolRequest,
    ReminderStatus,
    StaticReminderPayload,
)
from app.services.reminder_service import reminder_scheduler
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool


def _apply_timezone_offset(dt: datetime, offset_str: str) -> datetime:
    """Apply timezone offset to datetime object."""
    # Parse offset string (+|-)HH:MM
    sign = 1 if offset_str.startswith("+") else -1
    hours, minutes = map(int, offset_str[1:].split(":"))
    offset_seconds = sign * (hours * 3600 + minutes * 60)
    tz = timezone(timedelta(seconds=offset_seconds))
    return dt.replace(tzinfo=tz)


@tool()
@with_rate_limiting("reminder_operations")
@with_doc(CREATE_REMINDER)
async def create_reminder_tool(
    config: RunnableConfig,
    payload: Annotated[
        StaticReminderPayload,
        "Static reminder data with title and body",
    ],
    agent: Annotated[
        AgentType, "The agent type creating the reminder (static only)"
    ] = AgentType.STATIC,
    repeat: Annotated[Optional[str], "Cron expression for recurring reminders"] = None,
    scheduled_at: Annotated[
        Optional[str],
        "Date/time for when the reminder should run (YYYY-MM-DD HH:MM:SS format)",
    ] = None,
    timezone_offset: Annotated[
        Optional[str],
        "Timezone offset in (+|-)HH:MM format. Only use if user explicitly mentions a timezone.",
    ] = None,
    max_occurrences: Annotated[
        Optional[int],
        "Maximum number of times to run the reminder. Use this when user explicitly sets a limit on how many times the reminder should run.",
    ] = None,
    stop_after: Annotated[
        Optional[str],
        "Date/time after which no more runs (YYYY-MM-DD HH:MM:SS format)",
    ] = None,
    stop_after_timezone_offset: Annotated[
        Optional[str],
        "Timezone offset for stop_after in (+|-)HH:MM format. Only use if user explicitly mentions a timezone.",
    ] = None,
) -> Any:
    """Create a new reminder tool function."""
    try:
        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            return {"error": "User ID is required to create a reminder"}

        user_time_str: str = config.get("configurable", {}).get("user_time", "")
        if not user_time_str:
            return {"error": "User time is required to create a reminder"}

        # Create the tool request model which handles all validation and conversion
        tool_request = CreateReminderToolRequest(
            agent=agent,
            payload=payload,
            repeat=repeat,
            scheduled_at=scheduled_at,
            timezone_offset=timezone_offset,
            max_occurrences=max_occurrences,
            stop_after=stop_after,
            stop_after_timezone_offset=stop_after_timezone_offset,
            user_time=user_time_str,
        )

        # Convert to the service request model
        request_model = tool_request.to_create_reminder_request()

        # Create the reminder
        await reminder_scheduler.create_reminder(request_model, user_id=user_id)

        return "Reminder created successfully"

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return {"error": str(e)}
    except Exception as e:
        logger.exception("Exception occurred while creating reminder")
        return {"error": str(e)}


@tool(parse_docstring=True)
@with_rate_limiting("reminder_operations")
@with_doc(LIST_USER_REMINDERS)
async def list_user_reminders_tool(
    config: RunnableConfig,
    status: Annotated[
        Optional[ReminderStatus],
        "Filter by reminder status (scheduled, completed, cancelled, paused)",
    ] = None,
) -> Any:
    """List user reminders tool function."""
    try:
        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            return {"error": "User ID is required to list reminders"}

        reminders = await reminder_scheduler.list_user_reminders(
            user_id=user_id, status=status, limit=100, skip=0
        )
        return [r.model_dump() for r in reminders]
    except Exception as e:
        logger.exception("Exception occurred while listing reminders")
        return {"error": str(e)}


# Define get_reminder_tool
@tool(parse_docstring=True)
@with_rate_limiting("reminder_operations")
@with_doc(GET_REMINDER)
async def get_reminder_tool(
    config: RunnableConfig,
    reminder_id: Annotated[str, "The unique identifier of the reminder"],
) -> Any:
    """Get full details of a specific reminder by ID"""
    try:
        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            return {"error": "User ID is required to get reminder"}

        reminder = await reminder_scheduler.get_reminder(reminder_id, user_id)
        if reminder:
            return reminder.model_dump()
        else:
            return {"error": "Reminder not found"}
    except Exception as e:
        logger.exception("Exception occurred while getting reminder")
        return {"error": str(e)}


# Define delete_reminder_tool
@tool(parse_docstring=True)
@with_rate_limiting("reminder_operations")
@with_doc(DELETE_REMINDER)
async def delete_reminder_tool(
    config: RunnableConfig,
    reminder_id: Annotated[str, "The unique identifier of the reminder to cancel"],
) -> Any:
    """Cancel a scheduled reminder by ID"""
    try:
        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            logger.error("Missing user_id in config")
            return {"error": "User ID is required to delete reminder"}

        success = await reminder_scheduler.cancel_task(reminder_id, user_id)
        if success:
            return {"status": "cancelled"}
        else:
            return {"error": "Failed to cancel reminder"}
    except Exception as e:
        logger.exception("Exception occurred while deleting reminder")
        return {"error": str(e)}


# Define update_reminder_tool
@tool(parse_docstring=True)
@with_rate_limiting("reminder_operations")
@with_doc(UPDATE_REMINDER)
async def update_reminder_tool(
    config: RunnableConfig,
    reminder_id: Annotated[str, "The unique identifier of the reminder to update"],
    repeat: Annotated[
        Optional[str], "Cron expression for recurring reminders (optional)"
    ] = None,
    max_occurrences: Annotated[
        Optional[int], "Maximum number of times to run the reminder (optional)"
    ] = None,
    stop_after: Annotated[
        Optional[str],
        "Date/time after which no more runs (YYYY-MM-DD HH:MM:SS format, optional)",
    ] = None,
    stop_after_timezone_offset: Annotated[
        Optional[str],
        "Timezone offset for stop_after in (+|-)HH:MM format. Only use if user explicitly mentions a timezone.",
    ] = None,
    payload: Annotated[
        Optional[dict], "Additional data for the reminder task (optional)"
    ] = None,
) -> Any:
    """Update attributes of an existing reminder"""
    try:
        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            return {"error": "User ID is required to update reminder"}

        update_data: dict[str, Any] = {}
        if repeat is not None:
            update_data["repeat"] = repeat
        if max_occurrences is not None:
            update_data["max_occurrences"] = max_occurrences
        if stop_after:
            try:
                # Parse the datetime string
                dt = datetime.fromisoformat(stop_after.replace(" ", "T"))

                # Handle timezone based on the rules
                if stop_after_timezone_offset:
                    # User explicitly provided timezone - create timezone from offset
                    processed_stop_after = _apply_timezone_offset(
                        dt, stop_after_timezone_offset
                    )
                else:
                    # Absolute time with no timezone - no timezone info
                    processed_stop_after = dt

                update_data["stop_after"] = processed_stop_after
            except ValueError as e:
                logger.error(f"Invalid stop_after format: {stop_after}, error: {e}")
                return {
                    "error": f"Invalid stop_after format: {stop_after}. Use YYYY-MM-DD HH:MM:SS format."
                }
        if payload is not None:
            update_data["payload"] = payload

        success = await reminder_scheduler.update_reminder(
            reminder_id, update_data, user_id
        )
        if success:
            return {"status": "updated"}
        else:
            logger.error("Failed to update reminder")
            return {"error": "Failed to update reminder"}
    except Exception as e:
        logger.exception("Exception occurred while updating reminder")
        return {"error": str(e)}


# Define search_reminders_tool
@tool(parse_docstring=True)
@with_rate_limiting("reminder_operations")
@with_doc(SEARCH_REMINDERS)
async def search_reminders_tool(
    config: RunnableConfig,
    query: Annotated[str, "Search keyword(s) to match against reminders"],
) -> Any:
    """Search reminders by keyword or content"""
    try:
        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            logger.error("Missing user_id in config")
            return {"error": "User ID is required to search reminders"}

        reminders = await reminder_scheduler.list_user_reminders(
            user_id=user_id, limit=100, skip=0
        )

        results = []
        for r in reminders:
            rd = r.model_dump()
            if query.lower() in json.dumps(rd).lower():
                results.append(rd)

        return results
    except Exception as e:
        logger.exception("Exception occurred while searching reminders")
        return {"error": str(e)}


tools = [
    create_reminder_tool,
    list_user_reminders_tool,
    get_reminder_tool,
    delete_reminder_tool,
    update_reminder_tool,
    search_reminders_tool,
]
