import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from app.agents.templates.calendar_template import (
    CALENDAR_LIST_TEMPLATE,
    CALENDAR_PROMPT_TEMPLATE,
)
from app.config.loggers import chat_logger as logger
from app.decorators import require_integration, with_doc, with_rate_limiting
from app.models.calendar_models import (
    CalendarEventToolRequest,
    CalendarEventUpdateToolRequest,
    EventLookupRequest,
)
from app.services.calendar_service import (
    find_event_for_action,
    get_calendar_events,
    list_calendars,
    search_calendar_events_native,
)
from app.templates.docstrings.calendar_tool_docs import (
    CALENDAR_EVENT,
    DELETE_CALENDAR_EVENT,
    EDIT_CALENDAR_EVENT,
    FETCH_CALENDAR_EVENTS,
    FETCH_CALENDAR_LIST,
    SEARCH_CALENDAR_EVENTS,
    VIEW_CALENDAR_EVENT,
)
from app.utils.oauth_utils import get_tokens_by_user_id
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer


async def process_single_event(
    event: CalendarEventToolRequest,
    user_time_str: str,
    user_id: str,
) -> tuple[Dict[str, Any] | None, str | None]:
    """
    Process a single calendar event with validation and timezone handling.

    Returns:
        tuple: (event_dict or None, error_message or None)
    """
    try:
        processed_event = event.process_times(user_time_str)

        event_dict = {
            "summary": processed_event.summary,
            "description": processed_event.description or "",
            "is_all_day": processed_event.is_all_day,
            "start": processed_event.start,
            "end": processed_event.end,
        }

        if processed_event.calendar_id:
            event_dict["calendar_id"] = processed_event.calendar_id
            try:
                # Get access token for fetching calendar details
                access_token, _, token_success = await get_tokens_by_user_id(user_id)
                if token_success and access_token:
                    calendar_list: Dict[str, Any] = await list_calendars(access_token)
                    if calendar_list and "items" in calendar_list:
                        for cal in calendar_list.get("items", []):
                            if cal.get("id") == processed_event.calendar_id:
                                event_dict["calendar_name"] = cal.get(
                                    "summary", "Calendar"
                                )
                                event_dict["background_color"] = cal.get(
                                    "backgroundColor", "#00bbff"
                                )
                                break
                else:
                    event_dict["background_color"] = "#00bbff"
                    event_dict["calendar_name"] = "Calendar"
            except Exception as e:
                logger.warning(f"Could not fetch calendar color: {e}")
                event_dict["background_color"] = "#00bbff"
                event_dict["calendar_name"] = "Calendar"
        else:
            # Default values when no calendar_id is specified
            event_dict["background_color"] = "#00bbff"
            event_dict["calendar_name"] = "Calendar"

        if processed_event.recurrence:
            event_dict["recurrence"] = processed_event.recurrence.model_dump()

        logger.info(f"Added calendar event: {processed_event.summary}")
        return event_dict, None

    except Exception as e:
        error_msg = f"Error processing calendar event: {e}"
        logger.error(error_msg)
        return None, error_msg


@tool()
@with_rate_limiting("calendar_management")
@with_doc(CALENDAR_EVENT)
@require_integration("calendar")
async def create_calendar_event(
    events_data: List[CalendarEventToolRequest],
    config: RunnableConfig,
) -> str:
    try:
        if not events_data:
            logger.error("Empty event list provided")
            return json.dumps(
                {
                    "error": "At least one calendar event must be provided",
                    "calendar_options": [],
                    "prompt": str(CALENDAR_PROMPT_TEMPLATE.invoke({})),
                }
            )

        configurable = config.get("configurable", {})
        if not configurable:
            logger.error("Missing 'configurable' section in config")
            return json.dumps(
                {
                    "error": "Configuration data is missing",
                    "calendar_options": [],
                    "prompt": str(CALENDAR_PROMPT_TEMPLATE.invoke({})),
                }
            )

        user_time_str: str = configurable.get("user_time", "")
        user_id = configurable.get("user_id")

        if not user_time_str:
            logger.error("User time is required for calendar event processing")
            return json.dumps(
                {
                    "error": "User time is required to process calendar events",
                    "calendar_options": [],
                    "prompt": str(CALENDAR_PROMPT_TEMPLATE.invoke({})),
                }
            )

        if not user_id:
            logger.error("User ID is required for calendar event processing")
            return json.dumps(
                {
                    "error": "User ID is required to process calendar events",
                    "calendar_options": [],
                    "prompt": str(CALENDAR_PROMPT_TEMPLATE.invoke({})),
                }
            )

        logger.info(f"Processing {len(events_data)} calendar events")

        # Process all events in parallel
        results = await asyncio.gather(
            *[
                process_single_event(event, user_time_str, user_id)
                for event in events_data
            ]
        )

        calendar_options = []
        validation_errors = []

        for event_dict, error_msg in results:
            if event_dict:
                calendar_options.append(event_dict)
            if error_msg:
                validation_errors.append(error_msg)

        if validation_errors and not calendar_options:
            logger.error(f"Calendar event validation failed: {validation_errors}")
            return json.dumps(
                {
                    "error": "Calendar event validation failed",
                    "details": validation_errors,
                    "calendar_options": [],
                    "prompt": str(CALENDAR_PROMPT_TEMPLATE.invoke({})),
                }
            )

        writer = get_stream_writer()

        # Fetch same-day events for context
        try:
            access_token, _, token_success = await get_tokens_by_user_id(user_id)
            if not token_success or not access_token:
                raise Exception("Failed to get valid access token")

            # Fetch calendar list to map colors and names
            calendar_list = await list_calendars(access_token)
            calendar_color_map = {}
            calendar_name_map = {}

            if calendar_list and "items" in calendar_list:
                for cal in calendar_list.get("items", []):
                    cal_id = cal.get("id")
                    if cal_id:
                        calendar_color_map[cal_id] = cal.get(
                            "backgroundColor", "#00bbff"
                        )
                        calendar_name_map[cal_id] = cal.get("summary", "Calendar")

            # Add background_color and calendar_name to calendar_options
            for option in calendar_options:
                calendar_id = option.get("calendar_id", "primary")
                if calendar_id in calendar_color_map:
                    option["background_color"] = calendar_color_map[calendar_id]
                    option["calendar_name"] = calendar_name_map[calendar_id]
                else:
                    option["background_color"] = "#00bbff"
                    option["calendar_name"] = "Calendar"

            # Extract unique dates from events with proper timezone handling
            event_dates_info = {}  # date_str -> timezone_str
            for event_option in calendar_options:
                start_time = event_option.get("start", "")
                if start_time:
                    try:
                        # Parse the ISO format datetime with timezone
                        # Format: "2025-10-25T22:00:00+05:30"
                        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                        # Get the date in the event's local timezone
                        date_str = dt.strftime("%Y-%m-%d")

                        # Extract timezone offset from the original string
                        # We want to query the same date in the user's timezone
                        if "+" in start_time or "-" in start_time.split("T")[-1]:
                            # Has explicit timezone offset
                            tz_part = start_time.split("T")[-1]
                            # Find the timezone part (after last occurrence of + or -)
                            for sep in ["+", "-"]:
                                if sep in tz_part:
                                    tz_offset = sep + tz_part.split(sep)[-1]
                                    event_dates_info[date_str] = tz_offset
                                    break
                        elif start_time.endswith("Z"):
                            event_dates_info[date_str] = "+00:00"
                        else:
                            # No timezone info, assume UTC
                            event_dates_info[date_str] = "+00:00"
                    except Exception as e:
                        logger.warning(f"Error parsing date {start_time}: {e}")
                        # Fallback to simple string split
                        event_date = (
                            start_time.split("T")[0]
                            if "T" in start_time
                            else start_time
                        )
                        event_dates_info[event_date] = "+00:00"

            # Fetch events for each date in parallel with proper timezone
            same_day_events = []
            fetch_tasks = []
            for event_date, tz_offset in event_dates_info.items():
                # Create time boundaries in the user's timezone
                time_min = f"{event_date}T00:00:00{tz_offset}"
                time_max = f"{event_date}T23:59:59{tz_offset}"
                fetch_tasks.append(
                    get_calendar_events(
                        access_token=access_token,
                        user_id=user_id,
                        time_min=time_min,
                        time_max=time_max,
                    )
                )

            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, dict) and "events" in result:
                    same_day_events.extend(result["events"])

            # Add background_color to each same_day_event
            for event in same_day_events:
                calendar_id = event.get("calendarId")
                if calendar_id and calendar_id in calendar_color_map:
                    event["background_color"] = calendar_color_map[calendar_id]
                else:
                    event["background_color"] = "#00bbff"

            # Nest same_day_events in each calendar_option for frontend context
            for option in calendar_options:
                option["same_day_events"] = same_day_events

            writer(
                {
                    "calendar_options": calendar_options,
                    "intent": "calendar",
                }
            )
        except Exception as e:
            logger.warning(f"Error fetching same-day events: {str(e)}")
            # Still send calendar options even if we can't get same-day events
            writer({"calendar_options": calendar_options, "intent": "calendar"})

        logger.info("Calendar event processing successful")
        logger.info(f"Sent {len(calendar_options)} calendar options to frontend")
        return "Calendar options sent to frontend"

    except Exception as e:
        error_msg = f"Error processing calendar event: {e}"
        logger.error(error_msg)
        return json.dumps(
            {
                "error": "Unable to process calendar event",
                "details": str(e),
                "calendar_options": [],
                "prompt": str(CALENDAR_PROMPT_TEMPLATE.invoke({})),
            }
        )


@tool
@with_rate_limiting("calendar_management")
@with_doc(FETCH_CALENDAR_LIST)
@require_integration("calendar")
async def fetch_calendar_list(
    config: RunnableConfig,
) -> str | dict:
    try:
        if not config:
            logger.error("Missing configuration data")
            return "Unable to access calendar configuration. Please try again."

        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            logger.error("Missing user_id in config")
            return "Unable to access your calendar. Please ensure you're logged in with calendar permissions."

        # Get tokens from token registry
        access_token, _, token_success = await get_tokens_by_user_id(user_id)
        if not token_success or not access_token:
            logger.error("Failed to get valid tokens from token registry")
            return "Unable to access your calendar. Please ensure you're logged in with calendar permissions."

        calendars = await list_calendars(access_token=access_token, short=True)
        if calendars is None:
            logger.error("Unable to fetch calendars - no data returned")
            return "Unable to fetch your calendars. Please ensure your calendar is connected."

        logger.info(f"Fetched {len(calendars)} calendars")

        # Build array of {name, id, description} for all calendars
        calendar_list_fetch_data: List[Dict[str, Any]] = []
        if calendars and isinstance(calendars, list):
            for calendar in calendars:
                if isinstance(calendar, dict):
                    calendar_list_fetch_data.append(
                        {
                            "name": calendar.get("summary", "Unknown Calendar"),
                            "id": calendar.get("id", ""),
                            "description": calendar.get("description", ""),
                            "backgroundColor": calendar.get("backgroundColor"),
                        }
                    )

        writer = get_stream_writer()
        writer({"calendar_list_fetch_data": calendar_list_fetch_data})

        formatted_response = CALENDAR_LIST_TEMPLATE.format(
            calendars=json.dumps(calendars)
        )

        return formatted_response
    except Exception as e:
        error_msg = f"Error fetching calendars: {str(e)}"
        logger.error(error_msg)
        return f"Error fetching calendars: {str(e)}"


@tool(parse_docstring=True)
@with_rate_limiting("calendar_management")
@with_doc(FETCH_CALENDAR_EVENTS)
@require_integration("calendar")
async def fetch_calendar_events(
    config: RunnableConfig,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    selected_calendars: Optional[List[str]] = None,
    limit: int = 20,
) -> str:
    try:
        if not config:
            logger.error("Missing configuration data")
            return "Unable to access calendar configuration. Please try again."

        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            logger.error("Missing user_id in config")
            return "Unable to access your calendar. Please ensure you're logged in with calendar permissions."

        # Get tokens from token registry
        access_token, _, token_success = await get_tokens_by_user_id(user_id)
        if not token_success or not access_token:
            logger.error("Failed to get valid tokens from token registry")
            return "Unable to access your calendar. Please ensure you're logged in with calendar permissions."

        logger.info(f"Fetching calendar events for user {user_id} with limit {limit}")

        # Set default time_min to current time for future events only
        if time_min is None:
            time_min = datetime.now(timezone.utc).isoformat()

        # Fetch calendar list to get backgroundColor mapping
        calendars = await list_calendars(access_token=access_token, short=True)
        calendar_color_map = {}
        if calendars and isinstance(calendars, list):
            for cal in calendars:
                if isinstance(cal, dict):
                    calendar_color_map[cal.get("id")] = {
                        "name": cal.get("summary", "Unknown Calendar"),
                        "backgroundColor": cal.get("backgroundColor", "#00bbff"),
                    }

        events_data = await get_calendar_events(
            user_id=user_id,
            access_token=access_token,
            selected_calendars=selected_calendars,
            time_min=time_min,
            time_max=time_max,
            max_results=limit,
        )

        events = events_data.get("events", [])
        logger.info(f"Fetched {len(events)} events")

        # Build array with all necessary fields for frontend
        calendar_fetch_data = []
        for event in events:
            start_time = ""
            end_time = ""

            if event.get("start"):
                start_obj = event["start"]
                if start_obj.get("dateTime"):
                    start_time = start_obj["dateTime"]
                elif start_obj.get("date"):
                    start_time = start_obj["date"]

            if event.get("end"):
                end_obj = event["end"]
                if end_obj.get("dateTime"):
                    end_time = end_obj["dateTime"]
                elif end_obj.get("date"):
                    end_time = end_obj["date"]

            calendar_id = event.get("calendarId", "")
            calendar_info = calendar_color_map.get(
                calendar_id,
                {
                    "name": event.get("calendarTitle", "Unknown Calendar"),
                    "backgroundColor": "#00bbff",
                },
            )

            calendar_fetch_data.append(
                {
                    "summary": event.get("summary", "No Title"),
                    "start_time": start_time,
                    "end_time": end_time,
                    "calendar_name": calendar_info.get("name", "Unknown Calendar"),
                    "background_color": calendar_info.get("backgroundColor", "#00bbff"),
                }
            )

        writer = get_stream_writer()
        writer({"calendar_fetch_data": calendar_fetch_data})

        return json.dumps(
            {
                "events": events,
                "total_events": len(events),
                "selected_calendars": events_data.get("selectedCalendars", []),
                "next_page_token": events_data.get("nextPageToken"),
            }
        )

    except Exception as e:
        error_msg = f"Error fetching calendar events: {str(e)}"
        logger.error(error_msg)
        return error_msg


@tool(parse_docstring=True)
@with_doc(SEARCH_CALENDAR_EVENTS)
@with_rate_limiting("calendar_management")
@require_integration("calendar")
async def search_calendar_events(
    query: str,
    config: RunnableConfig,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
) -> str:
    try:
        if not config:
            logger.error("Missing configuration data")
            return "Unable to access calendar configuration. Please try again."

        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            logger.error("Missing user_id in config")
            return "Unable to access your calendar. Please ensure you're logged in with calendar permissions."

        # Get tokens from token registry
        access_token, _, token_success = await get_tokens_by_user_id(user_id)
        if not token_success or not access_token:
            logger.error("Failed to get valid tokens from token registry")
            return "Unable to access your calendar. Please ensure you're logged in with calendar permissions."

        logger.info(f"Searching calendar events for query: {query}")

        # Send progress update
        writer = get_stream_writer()
        writer({"progress": f"Searching calendar events for '{query}'..."})

        # Use the new search function with Google Calendar API's native search
        search_results = await search_calendar_events_native(
            query=query,
            access_token=access_token,
            time_min=time_min,
            time_max=time_max,
            user_id=user_id,
        )

        logger.info(
            f"Found {len(search_results.get('matching_events', []))} matching events for query: {query}"
        )

        # Fetch calendar list to get backgroundColor mapping
        calendars = await list_calendars(access_token=access_token, short=True)
        calendar_color_map = {}
        if calendars and isinstance(calendars, list):
            for cal in calendars:
                if isinstance(cal, dict):
                    calendar_color_map[cal.get("id")] = {
                        "name": cal.get("summary", "Unknown Calendar"),
                        "backgroundColor": cal.get("backgroundColor", "#00bbff"),
                    }

        # Build array with all necessary fields for frontend
        calendar_search_data = []
        for event in search_results.get("matching_events", []):
            start_time = ""
            end_time = ""

            if event.get("start"):
                start_obj = event["start"]
                if start_obj.get("dateTime"):
                    start_time = start_obj["dateTime"]
                elif start_obj.get("date"):
                    start_time = start_obj["date"]

            if event.get("end"):
                end_obj = event["end"]
                if end_obj.get("dateTime"):
                    end_time = end_obj["dateTime"]
                elif end_obj.get("date"):
                    end_time = end_obj["date"]

            calendar_id = event.get("calendarId", "")
            calendar_info = calendar_color_map.get(
                calendar_id,
                {
                    "name": event.get("calendarTitle", "Unknown Calendar"),
                    "backgroundColor": "#00bbff",
                },
            )

            calendar_search_data.append(
                {
                    "summary": event.get("summary", "No Title"),
                    "start_time": start_time,
                    "end_time": end_time,
                    "calendar_name": calendar_info.get("name", "Unknown Calendar"),
                    "background_color": calendar_info.get("backgroundColor", "#00bbff"),
                }
            )

        # Send search results to frontend via writer using grouped structure
        writer(
            {
                "calendar_data": {"calendar_search_results": search_results},
                "calendar_fetch_data": calendar_search_data,
            }
        )

        return "Calendar search results sent to frontend"

    except Exception as e:
        error_msg = f"Error searching calendar events: {str(e)}"
        logger.error(error_msg)
        return error_msg


@tool(parse_docstring=True)
@with_doc(VIEW_CALENDAR_EVENT)
@with_rate_limiting("calendar_management")
@require_integration("calendar")
async def view_calendar_event(
    event_id: str,
    config: RunnableConfig,
    calendar_id: str = "primary",
) -> str:
    try:
        if not config:
            logger.error("Missing configuration data")
            return "Unable to access calendar configuration. Please try again."

        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            logger.error("Missing user_id in config")
            return "Unable to access your calendar. Please ensure you're logged in with calendar permissions."

        # Get tokens from token registry
        access_token, _, token_success = await get_tokens_by_user_id(user_id)
        if not token_success or not access_token:
            logger.error("Failed to get valid tokens from token registry")
            return "Unable to access your calendar. Please ensure you're logged in with calendar permissions."

        # Fetch specific event using Google Calendar API
        url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}"
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)

        if response.status_code == 200:
            event = response.json()
            logger.info(f"Retrieved event: {event.get('summary', 'Unknown')}")

            return json.dumps(
                {
                    "event": event,
                    "event_id": event_id,
                    "calendar_id": calendar_id,
                }
            )
        else:
            error_msg = (
                f"Event not found or access denied (Status: {response.status_code})"
            )
            logger.error(error_msg)
            return error_msg

    except Exception as e:
        error_msg = f"Error viewing calendar event: {str(e)}"
        logger.error(error_msg)
        return error_msg


@tool()
@with_rate_limiting("calendar_management")
@with_doc(DELETE_CALENDAR_EVENT)
async def delete_calendar_event(
    config: RunnableConfig,
    event_lookup_data: EventLookupRequest,
) -> str:
    try:
        if not config:
            logger.error("Missing configuration data")
            return "Unable to access calendar configuration. Please try again."

        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            logger.error("Missing user_id in config")
            return "Unable to access your calendar. Please ensure you're logged in with calendar permissions."

        # Get tokens from token registry
        access_token, _, token_success = await get_tokens_by_user_id(user_id)
        if not token_success or not access_token:
            logger.error("Failed to get valid tokens from token registry")
            return "Unable to access your calendar. Please ensure you're logged in with calendar permissions."

        writer = get_stream_writer()
        # Use service method to find the event for action (delete)
        try:
            target_event = await find_event_for_action(
                access_token=access_token,
                user_id=user_id,
                event_lookup_data=event_lookup_data,
            )
        except Exception as e:
            logger.error(f"Error finding event for deletion: {str(e)}")
            return f"Error finding event for deletion: {str(e)}"

        if not target_event:
            return "No matching event found to delete."

        # Prepare deletion confirmation data
        delete_option = {
            "action": "delete",
            "event_id": target_event.get("id"),
            "calendar_id": target_event.get("calendarId", "primary"),
            "summary": target_event.get("summary", ""),
            "description": target_event.get("description", ""),
            "start": target_event.get("start", {}),
            "end": target_event.get("end", {}),
            "original_query": event_lookup_data.query,
        }

        # Send deletion options to frontend via writer
        writer(
            {
                "calendar_delete_options": [delete_option],
            }
        )

        logger.info("Calendar event deletion options sent to frontend")
        return f"Found event '{target_event.get('summary', 'Unknown')}' matching your search. Please confirm the deletion."

    except Exception as e:
        error_msg = f"Error searching for calendar event to delete: {str(e)}"
        logger.error(error_msg)
        return error_msg


@tool()
@with_rate_limiting("calendar_management")
@with_doc(docstring=EDIT_CALENDAR_EVENT)
async def edit_calendar_event(
    config: RunnableConfig,
    event_lookup_data: EventLookupRequest,
    summary: Optional[str] = None,
    description: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    is_all_day: Optional[bool] = None,
    timezone_offset: Optional[str] = None,
    recurrence: Optional[dict] = None,
    location: Optional[str] = None,
    attendees: Optional[list] = None,
    reminders: Optional[dict] = None,
    visibility: Optional[str] = None,
    color_id: Optional[str] = None,
) -> str:
    try:
        if not config:
            logger.error("Missing configuration data")
            return "Unable to access calendar configuration. Please try again."

        user_id = config.get("configurable", {}).get("user_id")
        user_time_str = config.get("configurable", {}).get("user_time", "")

        # Ensure user_id and user_time are available
        if not user_id:
            logger.error("Missing user_id in config")
            return "Unable to access your calendar. Please ensure you're logged in with calendar permissions."
        if not user_time_str:
            logger.error("Missing user_time in config")
            return "User time is required for calendar event processing."

        # Get tokens from token registry
        access_token, _, token_success = await get_tokens_by_user_id(user_id)
        if not token_success or not access_token:
            logger.error("Failed to get valid tokens from token registry")
            return "Unable to access your calendar. Please ensure you're logged in with calendar permissions."

        # Process timezone for start/end times if provided
        processed_start = start
        processed_end = end

        if start is not None or end is not None:
            try:
                # Convert recurrence dict to RecurrenceData if provided
                recurrence_data = None
                if recurrence is not None:
                    from app.models.calendar_models import RecurrenceData

                    recurrence_data = (
                        RecurrenceData(**recurrence)
                        if isinstance(recurrence, dict)
                        else recurrence
                    )

                tool_request = CalendarEventUpdateToolRequest(
                    event_lookup=event_lookup_data,
                    user_time=user_time_str,
                    start=start,
                    end=end,
                    timezone_offset=timezone_offset,
                    summary=summary,
                    description=description,
                    is_all_day=is_all_day,
                    recurrence=recurrence_data,
                )

                update_request = tool_request.to_update_request()
                processed_start = update_request.start
                processed_end = update_request.end

            except Exception as e:
                logger.error(f"Error processing timezone for calendar update: {e}")
                return f"Error processing timezone: {e}"

        writer = get_stream_writer()
        # Use service method to find the event for action (edit)
        try:
            target_event = await find_event_for_action(
                access_token=access_token,
                user_id=user_id,
                event_lookup_data=event_lookup_data,
            )
        except Exception as e:
            logger.error(f"Error finding event for edit: {str(e)}")
            return f"Error finding event for edit: {str(e)}"
        if not target_event:
            return "No matching event found to edit."

        # Prepare the updated event data
        edit_option = {
            "action": "edit",
            "event_id": target_event.get("id"),
            "calendar_id": target_event.get("calendarId", "primary"),
            "original_summary": target_event.get("summary", ""),
            "original_description": target_event.get("description", ""),
            "original_start": target_event.get("start", {}),
            "original_end": target_event.get("end", {}),
            "original_query": event_lookup_data.query,
        }

        # Add updated fields only if they are provided (compatible with create event parameters)
        if summary is not None:
            edit_option["summary"] = summary
        if description is not None:
            edit_option["description"] = description
        if start is not None:
            edit_option["start"] = processed_start
        if end is not None:
            edit_option["end"] = processed_end
        if is_all_day is not None:
            edit_option["is_all_day"] = is_all_day
        if recurrence is not None:
            # Pass recurrence data as is - it will be validated and converted by the service layer
            edit_option["recurrence"] = recurrence
        if location is not None:
            edit_option["location"] = location
        if attendees is not None:
            edit_option["attendees"] = attendees
        if reminders is not None:
            edit_option["reminders"] = reminders
        if visibility is not None:
            edit_option["visibility"] = visibility
        if color_id is not None:
            edit_option["color_id"] = color_id

        # Send edit options to frontend via writer
        writer(
            {
                "calendar_edit_options": [edit_option],
            }
        )

        logger.info("Calendar event edit options sent to frontend")

        # Build changes summary
        changes_summary = []
        if summary is not None:
            changes_summary.append(f"title to '{summary}'")
        if description is not None:
            changes_summary.append(f"description to '{description}'")
        if start is not None or end is not None:
            changes_summary.append("time/date")
        if location is not None:
            changes_summary.append(f"location to '{location}'")
        if attendees is not None:
            changes_summary.append("attendees")
        if recurrence is not None:
            changes_summary.append("recurrence pattern")
        if is_all_day is not None:
            changes_summary.append(f"all-day status to {is_all_day}")
        if reminders is not None:
            changes_summary.append("reminders")
        if visibility is not None:
            changes_summary.append(f"visibility to '{visibility}'")
        if color_id is not None:
            changes_summary.append("color")

        changes_text = (
            ", ".join(changes_summary) if changes_summary else "the specified fields"
        )
        return f"Found event '{target_event.get('summary', 'Unknown')}' matching your search. Ready to update {changes_text}. Please confirm the changes."

    except Exception as e:
        error_msg = f"Error searching for calendar event to edit: {str(e)}"
        logger.error(error_msg)
        return error_msg


tools = [
    fetch_calendar_list,
    create_calendar_event,
    delete_calendar_event,
    edit_calendar_event,
    fetch_calendar_events,
    search_calendar_events,
    view_calendar_event,
]
