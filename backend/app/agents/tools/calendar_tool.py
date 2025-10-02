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


def transform_calendar_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transform calendar events to essential fields for LLM consumption.
    Reduces token usage by removing unnecessary metadata.

    Args:
        events: List of full event objects from Google Calendar API.

    Returns:
        List of events with only essential fields.
    """
    transformed = []
    for event in events:
        transformed_event = {
            "id": event.get("id"),
            "summary": event.get("summary"),
            "start": event.get("start"),
            "end": event.get("end"),
        }

        # Add optional fields only if they exist and are non-empty
        if event.get("description"):
            transformed_event["description"] = event["description"]
        if event.get("location"):
            transformed_event["location"] = event["location"]
        if event.get("attendees"):
            # Simplify attendees to only essential info: email, response status, and organizer flag
            transformed_event["attendees"] = [
                {
                    "email": attendee.get("email"),
                    "responseStatus": attendee.get("responseStatus"),
                    "organizer": attendee.get("organizer", False),
                }
                for attendee in event["attendees"]
            ]
        if event.get("recurrence"):
            transformed_event["recurrence"] = event["recurrence"]
        if event.get("status"):
            transformed_event["status"] = event["status"]
        if event.get("calendarId"):
            transformed_event["calendarId"] = event["calendarId"]
        if event.get("calendarTitle"):
            transformed_event["calendarTitle"] = event["calendarTitle"]

        transformed.append(transformed_event)

    return transformed


@tool()
@with_rate_limiting("calendar_management")
@with_doc(CALENDAR_EVENT)
@require_integration("calendar")
async def create_calendar_event(
    events_data: List[CalendarEventToolRequest],
    config: RunnableConfig,
) -> str:
    try:
        # Validate non-empty
        if not events_data:
            logger.error("Empty event list provided")
            return json.dumps(
                {
                    "error": "At least one calendar event must be provided",
                    "calendar_options": [],
                    "prompt": str(CALENDAR_PROMPT_TEMPLATE.invoke({})),
                }
            )

        # Get user time from config for timezone processing
        configurable = config.get("configurable", {})
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

        calendar_options = []
        validation_errors = []

        logger.info(f"Processing {len(events_data)} calendar events")

        # Process each event with validation
        for event in events_data:
            try:
                # Process the event times with timezone handling to convert to service format
                processed_event = event.process_times(user_time_str)

                # Add the validated and processed event as a proper dict with all required fields
                event_dict = {
                    "summary": processed_event.summary,
                    "description": processed_event.description or "",
                    "is_all_day": processed_event.is_all_day,
                    "start": processed_event.start,
                    "end": processed_event.end,
                }

                # Add optional fields only if they exist
                if processed_event.calendar_id:
                    event_dict["calendar_id"] = processed_event.calendar_id
                if processed_event.recurrence:
                    event_dict["recurrence"] = processed_event.recurrence.model_dump()

                calendar_options.append(event_dict)
                logger.info(f"Added calendar event: {processed_event.summary}")

            except Exception as e:
                error_msg = f"Error processing calendar event: {e}"
                logger.error(error_msg)
                validation_errors.append(error_msg)

        # Return validation errors if any
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

        # Validate configurable section exists
        if not configurable:
            logger.error("Missing 'configurable' section in config")
            return json.dumps(
                {
                    "error": "Configuration data is missing",
                    "calendar_options": [],
                    "prompt": str(CALENDAR_PROMPT_TEMPLATE.invoke({})),
                }
            )

        # # If initiated by backend then create notification
        # if configurable.get("initiator") == "backend":
        #     user_id = configurable.get("user_id")
        #     if not user_id:
        #         logger.error("Missing user_id in configuration")
        #         return json.dumps(
        #             {
        #                 "error": "User ID is required to create calendar notification",
        #                 "calendar_options": [],
        #                 "prompt": str(CALENDAR_PROMPT_TEMPLATE.invoke({})),
        #             }
        #         )

        #     # Create a notification for the user
        #     notifications = (
        #         AIProactiveNotificationSource.create_calendar_event_notification(
        #             user_id=user_id,
        #             notification_data=event_list,
        #         )
        #     )
        #     await asyncio.gather(
        #         *[
        #             notification_service.create_notification(notification)
        #             for notification in notifications
        #         ]
        #     )

        #     return "Calendar notification created successfully."

        # Return the successfully processed events
        writer = get_stream_writer()

        # Send calendar options to frontend via writer
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

        events_data = await get_calendar_events(
            user_id=user_id,
            access_token=access_token,
            selected_calendars=selected_calendars,
            time_min=time_min,
            time_max=time_max,
            max_results=limit,
        )

        # Transform events to reduce token usage
        events = transform_calendar_events(events_data.get("events", []))
        logger.info(f"Fetched and transformed {len(events)} events")

        # Build array of {summary, start_time} for all events
        calendar_fetch_data = []
        for event in events:
            start_time = ""
            if event.get("start"):
                start_obj = event["start"]
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

        # Build array of {summary, start_time} for search results
        calendar_search_data = []
        for event in search_results.get("matching_events", []):
            start_time = ""
            if event.get("start"):
                start_obj = event["start"]
                if start_obj.get("dateTime"):
                    start_time = start_obj["dateTime"]
                elif start_obj.get("date"):
                    start_time = start_obj["date"]

            calendar_search_data.append(
                {
                    "summary": event.get("summary", "No Title"),
                    "start_time": start_time,
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
    # delete_calendar_event,
    edit_calendar_event,
    fetch_calendar_events,
    search_calendar_events,
    view_calendar_event,
]
