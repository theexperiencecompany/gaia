import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union, cast

import httpx
from app.config.loggers import calendar_logger as logger
from app.config.token_repository import token_repository
from app.db.mongodb.collections import calendars_collection
from app.models.calendar_models import (
    EventCreateRequest,
    EventDeleteRequest,
    EventLookupRequest,
    EventUpdateRequest,
)
from fastapi import HTTPException

http_async_client = httpx.AsyncClient()


async def fetch_calendar_list(access_token: str, short: bool = False) -> Any:
    """
    Fetch the list of calendars for the authenticated user.

    Args:
        access_token (str): The access token.
        short (bool): If True, returns only key fields per calendar.

    Returns:
        Any: Full or filtered calendar data.
    """
    url = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = await httpx.AsyncClient().get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        if short:
            return [
                {
                    "id": c.get("id"),
                    "summary": c.get("summary"),
                    "description": c.get("description"),
                    "backgroundColor": c.get("backgroundColor"),
                }
                for c in data.get("items", [])
            ]

        return data

    except httpx.HTTPStatusError as exc:
        error_detail = "Unknown error"
        error_json = exc.response.json()
        if isinstance(error_json, dict):
            error_message = error_json.get("error", {})
            if isinstance(error_message, dict):
                error_detail = error_message.get("message", "Unknown error")

        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Error fetching list of calendars: {error_detail}",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while requesting the calendar list: {exc}",
        )


def filter_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter out unwanted events from the provided list.

    Args:
        events (list): List of events.

    Returns:
        list: Filtered events excluding birthdays and events missing a valid start time.
    """
    return [
        event
        for event in events
        if event.get("eventType") != "birthday"
        and "start" in event
        and ("dateTime" in event["start"] or "date" in event["start"])
    ]


async def fetch_calendar_events(
    calendar_id: str,
    access_token: str,
    page_token: Optional[str] = None,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: int = 20,
) -> Dict[str, Any]:
    """
    Fetch events for a specific calendar.

    Args:
        calendar_id (str): Calendar identifier.
        access_token (str): Access token.
        page_token (Optional[str]): Pagination token.
        time_min (Optional[str]): Start time filter.
        time_max (Optional[str]): End time filter.
        max_results (int): Maximum number of events to return (default: 20).

    Returns:
        dict: The events data.
    """
    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    headers = {"Authorization": f"Bearer {access_token}"}

    params: Dict[str, Union[str, int, bool]] = {
        "maxResults": max_results,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    if time_min:
        params["timeMin"] = time_min
    if time_max:
        params["timeMax"] = time_max
    if page_token:
        params["pageToken"] = page_token

    try:
        response = await http_async_client.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json()
        else:
            error_detail = (
                response.json().get("error", {}).get("message", "Unknown error")
            )
            raise HTTPException(status_code=response.status_code, detail=error_detail)
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"HTTP request failed: {e}")


async def list_calendars(access_token: str, short=False) -> Optional[Dict[str, Any]]:
    """
    Retrieve the user's calendar list. If the access token is invalid,
    it will get a new token from the token repository.

    Args:
        user_id (str): User ID to get tokens from repository.
        access_token (Optional[str]): Optional access token (if not provided, will fetch from repository).
        short (bool): If True, returns only key fields per calendar.

    Returns:
        Optional[Dict[str, Any]]: Calendar list data or None if retrieval fails.
    """
    # Token refresh will be handled by the decorator if needed
    return await fetch_calendar_list(access_token, short)


async def get_calendar_metadata_map(
    access_token: str,
) -> tuple[Dict[str, str], Dict[str, str]]:
    """
    Fetch calendar list and return color/name mappings.

    Args:
        access_token (str): The access token.

    Returns:
        tuple: (calendar_color_map, calendar_name_map)
    """
    calendars = await list_calendars(access_token=access_token, short=True)

    color_map = {}
    name_map = {}

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
    """
    Format a calendar event for frontend display.

    Args:
        event: Raw calendar event from Google API
        calendar_color_map: Mapping of calendar_id to backgroundColor
        calendar_name_map: Mapping of calendar_id to calendar name

    Returns:
        Formatted event dict with essential frontend fields
    """
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
    """
    Extract unique dates with timezone offsets from calendar options.

    Args:
        calendar_options: List of calendar event options

    Returns:
        Dict mapping date strings to timezone offsets (e.g., {"2025-10-25": "+05:30"})
    """
    event_dates_info = {}
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
                logger.warning(f"Could not parse start time: {start_time}, {e}")
    return event_dates_info


async def fetch_same_day_events(
    event_dates_info: Dict[str, str],
    access_token: str,
    user_id: str,
) -> List[Dict[str, Any]]:
    """
    Fetch events for each unique date in parallel.

    Args:
        event_dates_info: Dict mapping date strings to timezone offsets
        access_token: Access token for calendar API
        user_id: User identifier

    Returns:
        List of events across all specified dates
    """
    fetch_tasks = []
    for event_date, tz_offset in event_dates_info.items():
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
    same_day_events = []
    for result in results:
        if isinstance(result, dict) and "events" in result:
            same_day_events.extend(result["events"])

    return same_day_events


async def enrich_calendar_options_with_metadata(
    calendar_options: List[Dict[str, Any]],
    access_token: str,
    user_id: str,
) -> List[Dict[str, Any]]:
    """
    Add calendar colors, names, and same-day events to calendar options.

    Args:
        calendar_options: List of calendar event options to enrich
        access_token: Access token for calendar API
        user_id: User identifier

    Returns:
        Enriched calendar options with metadata
    """
    color_map, name_map = await get_calendar_metadata_map(access_token)

    for option in calendar_options:
        calendar_id = option.get("calendar_id", "primary")
        option["background_color"] = color_map.get(calendar_id, "#00bbff")
        option["calendar_name"] = name_map.get(calendar_id, "Calendar")

    event_dates_info = extract_unique_dates(calendar_options)
    same_day_events = await fetch_same_day_events(
        event_dates_info, access_token, user_id
    )

    for event in same_day_events:
        calendar_id = event.get("calendarId")
        event["background_color"] = color_map.get(calendar_id, "#00bbff")

    for option in calendar_options:
        option["same_day_events"] = same_day_events

    return calendar_options


async def get_calendar_events(
    user_id: str,
    access_token: Optional[str] = None,
    page_token: Optional[str] = None,
    selected_calendars: Optional[List[str]] = None,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: int = 20,
) -> Dict[str, Any]:
    """
    Get events from the user's selected calendars with pagination and preferences.
    Uses token repository to manage access tokens.

    Args:
        user_id (str): User identifier.
        access_token (Optional[str]): Optional access token (if not provided, will fetch from repository).
        page_token (Optional[str]): Pagination token.
        selected_calendars (Optional[List[str]]): List of selected calendar IDs.
        time_min (Optional[str]): Start time filter.
        time_max (Optional[str]): End time filter.
        max_results (int): Maximum number of events to return per calendar (default: 20).

    Returns:
        dict: A dictionary containing events, nextPageToken, and the selected calendar IDs.
    """
    # Get valid access token if not provided
    if not access_token:
        token = await token_repository.get_token(
            user_id, "google", renew_if_expired=True
        )

        access_token = str(token.get("access_token", ""))

        if not access_token:
            raise HTTPException(
                status_code=401, detail="No valid access token available"
            )

    # Fetch the calendar list - token refresh will be handled by the decorator if needed
    calendar_data = await fetch_calendar_list(access_token)

    calendars = calendar_data.get("items", [])

    # Determine selected calendars: update preferences if provided,
    # otherwise load from the database or default to the primary calendar.
    user_selected_calendars: List[str] = []
    if selected_calendars is not None:
        user_selected_calendars = selected_calendars
        await calendars_collection.update_one(
            {"user_id": user_id},
            {"$set": {"selected_calendars": user_selected_calendars}},
            upsert=True,
        )
    else:
        preferences = await calendars_collection.find_one({"user_id": user_id})
        if preferences and preferences.get("selected_calendars"):
            user_selected_calendars = preferences["selected_calendars"]
        else:
            primary_calendar = next(
                (cal for cal in calendars if cal.get("primary")), None
            )
            if primary_calendar:
                user_selected_calendars = [primary_calendar["id"]]
            await calendars_collection.update_one(
                {"user_id": user_id},
                {"$set": {"selected_calendars": user_selected_calendars}},
                upsert=True,
            )

    # Filter the calendars to only those that are selected.
    selected_cal_objs = [
        cal for cal in calendars if cal["id"] in user_selected_calendars
    ]

    # Create tasks for fetching events concurrently.
    token_str = access_token
    tasks = [
        fetch_calendar_events(
            cal["id"], token_str, page_token, time_min, time_max, max_results
        )
        for cal in selected_cal_objs
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_events = []
    next_page_token = None

    # Process results from all tasks.
    for cal, result in zip(selected_cal_objs, results):
        if isinstance(result, Exception):
            logger.error(f"Error fetching events for calendar {cal['id']}: {result}")
            continue

        # Cast result to a dictionary explicitly
        result_dict = cast(Dict[str, Any], result)

        events = result_dict.get("items", [])
        for event in events:
            event["calendarId"] = cal["id"]
            event["calendarTitle"] = cal.get("summary", "")
        all_events.extend(filter_events(events))

        # Use the first encountered nextPageToken (or handle it as needed)
        if not next_page_token and result_dict.get("nextPageToken"):
            next_page_token = result_dict["nextPageToken"]

    return {
        "events": all_events,
        "nextPageToken": next_page_token,
        "selectedCalendars": user_selected_calendars,
    }


async def get_calendar_events_by_id(
    calendar_id: str,
    access_token: str,
    page_token: Optional[str] = None,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fetch events for a specific calendar by its ID.

    Args:
        calendar_id (str): The calendar identifier.
        access_token (str): The access token.
        user_id (Optional[str]): User ID for token refresh if needed.
        page_token (Optional[str]): Pagination token.
        time_min (Optional[str]): Start time filter.
        time_max (Optional[str]): End time filter.

    Returns:
        dict: A dictionary containing the events and a nextPageToken if available.
    """
    events_data = await fetch_calendar_events(
        calendar_id, access_token, page_token, time_min, time_max
    )

    events = filter_events(events_data.get("items", []))
    return {
        "events": events,
        "nextPageToken": events_data.get("nextPageToken"),
    }


async def find_event_for_action(
    access_token: str,
    event_lookup_data: EventLookupRequest,
    user_id: str,
) -> Optional[dict]:
    """
    Find a specific event given either:
    - query (searches for the first matching event)
    - both calendar_id and event_id (fetches by ID)
    Returns the event dict or None if not found.
    Raises HTTPException for invalid input.
    """
    if event_lookup_data.query:
        search_results = await search_calendar_events_native(
            query=event_lookup_data.query,
            user_id=user_id,
            access_token=access_token,
        )
        matching_events = search_results.get("matching_events", [])
        if not matching_events:
            return None
        return matching_events[0]
    else:
        url = f"https://www.googleapis.com/calendar/v3/calendars/{event_lookup_data.calendar_id}/events/{event_lookup_data.event_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        return None


async def get_all_calendar_events(
    access_token: str,
    user_id: Optional[str] = None,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fetch events from all calendars associated with the user concurrently.

    Args:
        access_token (str): Access token.
        user_id (Optional[str]): User ID for token refresh if needed.
        time_min (Optional[str]): Start time filter.
        time_max (Optional[str]): End time filter.

    Returns:
        dict: A mapping of calendar IDs to their respective events.
    """
    calendar_list_data = await fetch_calendar_list(access_token)
    valid_token = access_token

    calendars = calendar_list_data.get("items", [])
    if not calendars:
        return {"calendars": {}}
    if not time_min:
        time_min = datetime.now(timezone.utc).isoformat()

    # Create tasks for each calendar - use coroutines directly rather than decorated functions
    async def get_events_for_calendar(cal_id: str):
        return await get_calendar_events_by_id(
            calendar_id=cal_id,
            access_token=str(valid_token),
            time_min=time_min,
            time_max=time_max,
        )

    tasks = {
        cal["id"]: asyncio.create_task(get_events_for_calendar(cal["id"]))
        for cal in calendars
        if "id" in cal
    }

    events_by_calendar = {}
    for cal_id, task in tasks.items():
        try:
            result = await task
            events_by_calendar[cal_id] = result
        except Exception as e:
            events_by_calendar[cal_id] = {"error": str(e)}

    return {"calendars": events_by_calendar}


async def create_calendar_event(
    event: EventCreateRequest,
    access_token: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new calendar event using the Google Calendar API.
    The function normalizes the provided timezone and ensures the event datetimes are timezone-aware.
    Supports full-day events, recurring events, and custom calendar selection.

    Args:
        event (EventCreateRequest): The event details, including optional recurrence rules.
        access_token (str): The access token.
        user_id (Optional[str]): User ID for token refresh.

    Returns:
        dict: The newly created event details.

    Raises:
        HTTPException: If event creation fails.
    """
    # Determine which calendar to use (default to primary if not specified)
    calendar_id = event.calendar_id or "primary"
    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # Create the basic event payload
    event_payload: dict[str, Any] = {
        "summary": event.summary,
        "description": event.description,
    }

    # Handle different event types (all-day vs. time-specific)
    if event.is_all_day:
        # For all-day events, use date format without time component
        if event.start and event.end:
            # If start and end dates are provided, extract the date parts
            start_date = (
                event.start.split("T")[0] if "T" in event.start else event.start
            )
            end_date = event.end.split("T")[0] if "T" in event.end else event.end
        elif event.start:
            # If only start date is provided, end date is the next day
            start_date = (
                event.start.split("T")[0] if "T" in event.start else event.start
            )
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_date = (start_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            # If no dates provided, default to today for start and tomorrow for end
            today = datetime.now()
            start_date = today.strftime("%Y-%m-%d")
            end_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")

        event_payload["start"] = {"date": start_date}
        event_payload["end"] = {"date": end_date}
    else:
        # For time-specific events, use datetime with timezone
        try:
            # Both start and end times are required for time-specific events
            if not event.start or not event.end:
                raise HTTPException(
                    status_code=400,
                    detail="Start and end times are required for time-specific events",
                )

            # Get timezone from event or use default
            timezone = getattr(event, "timezone", None) or "UTC"

            # Ensure times have timezone indicator if they don't
            start_time = event.start
            end_time = event.end

            if (
                start_time
                and not start_time.endswith("Z")
                and "+" not in start_time
                and "-" not in start_time[-6:]
            ):
                # No timezone info, add Z for UTC
                start_time = start_time + "Z"
            if (
                end_time
                and not end_time.endswith("Z")
                and "+" not in end_time
                and "-" not in end_time[-6:]
            ):
                end_time = end_time + "Z"

            # The calendar tool has already processed times - use them directly
            event_payload["start"] = {
                "dateTime": start_time,
                "timeZone": timezone,
            }
            event_payload["end"] = {
                "dateTime": end_time,
                "timeZone": timezone,
            }
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid datetime format: {str(e)}"
            )

    # Handle recurrence rules if provided
    if event.recurrence:
        try:
            # Convert recurrence data to Google Calendar format
            recurrence_rules = event.recurrence.to_google_calendar_format()
            event_payload["recurrence"] = recurrence_rules

            # For recurring events, times are already processed by calendar tool
            # Just ensure timezone is consistent
            if not event.is_all_day:
                if "timeZone" in event_payload.get("start", {}):
                    event_payload["start"]["timeZone"] = "UTC"
                if "timeZone" in event_payload.get("end", {}):
                    event_payload["end"]["timeZone"] = "UTC"

        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid recurrence rule format: {str(e)}"
            )  # Send request to create the event
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=event_payload)

        # Handle response
        if response.status_code in (200, 201):
            response_data = response.json()
            return response_data
        elif response.status_code == 403:
            raise HTTPException(
                status_code=403,
                detail="Insufficient authentication scopes. Please ensure your token includes the required scopes.",
            )
        elif response.status_code == 401:
            # The decorator will handle token refresh, but we need to raise a 401 to trigger it
            raise HTTPException(status_code=401, detail="Authentication failed")
        else:
            try:
                response_json = response.json()
                if isinstance(response_json, dict):
                    error_detail = response_json.get("error", {}).get(
                        "message", "Unknown error"
                    )
                else:
                    error_detail = "Unknown error"
            except Exception:
                error_detail = "Unknown error, could not parse response"

            raise HTTPException(status_code=response.status_code, detail=error_detail)
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Failed to create event: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


async def get_user_calendar_preferences(user_id: str) -> Dict[str, List[str]]:
    """
    Retrieve the user's selected calendar preferences from the database.

    Args:
        user_id (str): The ID of the user whose preferences are being retrieved.

    Returns:
        Dict[str, List[str]]: A dictionary with the user's selected calendar IDs.

    Raises:
        HTTPException: If preferences are not found for the user.
    """
    preferences = await calendars_collection.find_one({"user_id": user_id})
    if preferences and "selected_calendars" in preferences:
        return {"selectedCalendars": preferences["selected_calendars"]}
    else:
        raise HTTPException(status_code=404, detail="Calendar preferences not found")


async def update_user_calendar_preferences(
    user_id: str, selected_calendars: List[str]
) -> Dict[str, str]:
    """
    Update the user's selected calendar preferences in the database.

    Args:
        user_id (str): The ID of the user whose preferences are being updated.
        selected_calendars (List[str]): The list of selected calendar IDs to save.

    Returns:
        Dict[str, str]: A message indicating the result of the update operation.
    """
    result = await calendars_collection.update_one(
        {"user_id": user_id},
        {"$set": {"selected_calendars": selected_calendars}},
        upsert=True,
    )
    if result.modified_count or result.upserted_id:
        return {"message": "Calendar preferences updated successfully"}
    else:
        return {"message": "No changes made to calendar preferences"}


async def search_calendar_events_native(
    query: str,
    user_id: str,
    access_token: str,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search calendar events using Google Calendar API's native search functionality.
    This is much more efficient than fetching all events and filtering locally.

    Args:
        query (str): Search query string
        user_id (str): User identifier
        access_token (str): Access token
        refresh_token (Optional[str]): Refresh token
        time_min (Optional[str]): Start time filter
        time_max (Optional[str]): End time filter

    Returns:
        dict: Search results with matching events
    """

    # Get user's selected calendars - token refresh will be handled by the decorator
    calendar_list_data = await fetch_calendar_list(access_token)
    valid_token = access_token
    calendars = calendar_list_data.get("items", [])

    # Get user's calendar preferences
    user_selected_calendars: List[str] = []
    preferences = await calendars_collection.find_one({"user_id": user_id})
    if preferences and preferences.get("selected_calendars"):
        user_selected_calendars = preferences["selected_calendars"]
        logger.info(f"User has calendar preferences: {user_selected_calendars}")
    else:
        # Default to primary calendar if no preferences set
        primary_calendar = next((cal for cal in calendars if cal.get("primary")), None)
        if primary_calendar:
            user_selected_calendars = [primary_calendar["id"]]
            logger.info(
                f"No preferences found, defaulting to primary calendar: {primary_calendar['id']}"
            )
        else:
            logger.warning("No primary calendar found")

    # Filter the calendars to only those that are selected
    selected_cal_objs = [
        cal for cal in calendars if cal["id"] in user_selected_calendars
    ]

    logger.info(
        f"Searching in {len(selected_cal_objs)} calendars: {[cal['summary'] for cal in selected_cal_objs]}"
    )

    # If no calendars are selected, search all available calendars
    if not selected_cal_objs:
        logger.info("No selected calendars found, searching all available calendars")
        selected_cal_objs = calendars

    # Create tasks for searching events concurrently across selected calendars
    async def search_events_for_calendar(cal_id: str):
        return await search_events_in_calendar(
            cal_id, query, valid_token, time_min, time_max
        )

    tasks = [search_events_for_calendar(cal["id"]) for cal in selected_cal_objs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_matching_events = []
    total_events_searched = 0

    # Process results from all calendars
    for cal, result in zip(selected_cal_objs, results):
        if isinstance(result, Exception):
            logger.error(f"Error searching events in calendar {cal['id']}: {result}")
            continue

        # Cast result to a dictionary explicitly
        result_dict = cast(Dict[str, Any], result)

        events = result_dict.get("items", [])
        logger.info(
            f"Found {len(events)} events in calendar '{cal.get('summary', cal['id'])}'"
        )

        for event in events:
            event["calendarId"] = cal["id"]
            event["calendarTitle"] = cal.get("summary", "")

        filtered_events = filter_events(events)
        logger.info(
            f"After filtering: {len(filtered_events)} events in calendar '{cal.get('summary', cal['id'])}'"
        )

        all_matching_events.extend(filtered_events)

        # Add to total count for statistics
        total_events_searched += len(filtered_events)

    logger.info(
        f"Total matching events across all calendars: {len(all_matching_events)}"
    )

    # If no events found in selected calendars, try searching all calendars
    if not all_matching_events and selected_cal_objs != calendars:
        logger.info("No events found in selected calendars, searching all calendars...")

        # Search all calendars
        async def search_events_for_calendar(cal_id: str):
            return await search_events_in_calendar(
                cal_id, query, valid_token, time_min, time_max
            )

        all_calendar_tasks = [
            search_events_for_calendar(cal["id"]) for cal in calendars
        ]
        all_calendar_results = await asyncio.gather(
            *all_calendar_tasks, return_exceptions=True
        )

        # Process results from all calendars
        for cal, result in zip(calendars, all_calendar_results):
            if isinstance(result, Exception):
                logger.error(
                    f"Error searching events in calendar {cal['id']}: {result}"
                )
                continue

            result_dict = cast(Dict[str, Any], result)
            events = result_dict.get("items", [])

            if events:
                logger.info(
                    f"Found {len(events)} events in calendar '{cal.get('summary', cal['id'])}'"
                )

                for event in events:
                    event["calendarId"] = cal["id"]
                    event["calendarTitle"] = cal.get("summary", "")

                filtered_events = filter_events(events)
                all_matching_events.extend(filtered_events)
                total_events_searched += len(filtered_events)

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
    access_token: str,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search events in a specific calendar using Google Calendar API's native search.

    Args:
        calendar_id (str): Calendar identifier
        query (str): Search query string
        access_token (str): Access token
        time_min (Optional[str]): Start time filter
        time_max (Optional[str]): End time filter

    Returns:
        dict: Search results from the specific calendar
    """
    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    headers = {"Authorization": f"Bearer {access_token}"}

    params: Dict[str, Union[str, int, bool]] = {
        "q": query,  # This is the key parameter for native search
        "maxResults": 50,
        "singleEvents": True,
        "orderBy": "startTime",
    }

    # Only add time filters if they are explicitly provided
    if time_min:
        params["timeMin"] = time_min
    if time_max:
        params["timeMax"] = time_max

    try:
        logger.info(
            f"Searching calendar {calendar_id} with query '{query}' and params: {params}"
        )
        response = await http_async_client.get(url, headers=headers, params=params)
        if response.status_code == 200:
            result = response.json()
            event_count = len(result.get("items", []))
            logger.info(f"Calendar {calendar_id} search returned {event_count} events")
            return result
        else:
            error_detail = (
                response.json().get("error", {}).get("message", "Unknown error")
            )
            logger.error(
                f"Calendar {calendar_id} search failed: {response.status_code} - {error_detail}"
            )
            raise HTTPException(status_code=response.status_code, detail=error_detail)
    except httpx.RequestError as e:
        logger.error(f"HTTP search request failed for calendar {calendar_id}: {e}")
        raise HTTPException(status_code=500, detail=f"HTTP search request failed: {e}")


async def delete_calendar_event(
    event: EventDeleteRequest,
    access_token: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Delete a calendar event using the Google Calendar API.

    Args:
        event (EventDeleteRequest): The event deletion request details.
        access_token (str): The access token.
        user_id (Optional[str]): User ID for token refresh if needed.

    Returns:
        dict: Confirmation of deletion.

    Raises:
        HTTPException: If event deletion fails.
    """
    calendar_id = event.calendar_id or "primary"
    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event.event_id}"

    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(url, headers=headers)

        if response.status_code == 204:
            return {"success": True, "message": "Event deleted successfully"}
        elif response.status_code == 404:
            raise HTTPException(
                status_code=404, detail="Event not found or already deleted"
            )
        elif response.status_code == 401:
            # The decorator will handle token refresh, but we need to raise a 401 to trigger it
            raise HTTPException(status_code=401, detail="Authentication failed")
        else:
            error_msg = "Unknown error occurred during deletion"
            if response.content:
                try:
                    error_json = response.json()
                    if isinstance(error_json, dict):
                        error_msg = error_json.get("error", {}).get(
                            "message", error_msg
                        )
                except Exception as json_error:
                    logger.warning(
                        f"Failed to parse error response JSON: {str(json_error)}"
                    )
            raise HTTPException(status_code=response.status_code, detail=error_msg)
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete event: {str(e)}")


async def update_calendar_event(
    event: EventUpdateRequest,
    access_token: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update a calendar event using the Google Calendar API.

    Args:
        event (EventUpdateRequest): The event update request details.
        access_token (str): The access token.
        user_id (Optional[str]): User ID for token refresh if needed.

    Returns:
        dict: The updated event details.

    Raises:
        HTTPException: If event update fails.
    """
    calendar_id = event.calendar_id or "primary"
    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event.event_id}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # First, get the existing event to preserve fields that weren't updated
    try:
        async with httpx.AsyncClient() as client:
            get_response = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )

        if get_response.status_code != 200:
            raise HTTPException(
                status_code=404, detail="Event not found or access denied"
            )

        existing_event = get_response.json()

    except httpx.RequestError as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch existing event: {str(e)}"
        )

    # Create the update payload, preserving existing values for unspecified fields
    event_payload = {
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

    # Handle recurrence updates if provided
    if event.recurrence is not None:
        try:
            # Convert recurrence data to Google Calendar format
            recurrence_rules = event.recurrence.to_google_calendar_format()
            event_payload["recurrence"] = recurrence_rules
        except Exception as e:
            logger.error(f"Error processing recurrence rules: {e}")
            raise HTTPException(
                status_code=400, detail=f"Invalid recurrence rule format: {str(e)}"
            )
    elif "recurrence" in existing_event:
        # Preserve existing recurrence if not being updated
        event_payload["recurrence"] = existing_event.get("recurrence", [])

    # Handle time updates
    if event.start is not None or event.end is not None or event.is_all_day is not None:
        is_all_day = (
            event.is_all_day
            if event.is_all_day is not None
            else existing_event.get("start", {}).get("date") is not None
        )

        if is_all_day:
            # Handle all-day event updates
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
            # Handle time-specific event updates
            try:
                # Use processed times directly from calendar tool
                if event.start is not None:
                    start_time = event.start
                else:
                    # Keep existing start time
                    start_time = existing_event.get("start", {}).get("dateTime", "")

                if event.end is not None:
                    end_time = event.end
                else:
                    # Keep existing end time
                    end_time = existing_event.get("end", {}).get("dateTime", "")

                # Preserve the timezone from the request or existing event
                timezone = None
                if event.timezone:
                    # Use timezone from the request
                    timezone = event.timezone
                elif hasattr(event, "timezone_offset") and event.timezone_offset:
                    # If timezone_offset is provided, use it (though we prefer full timezone names)
                    timezone = event.timezone_offset
                elif existing_event.get("start", {}).get("timeZone"):
                    # Preserve existing timezone
                    timezone = existing_event.get("start", {}).get("timeZone")

                # Ensure times have timezone indicator if they don't
                if (
                    start_time
                    and not start_time.endswith("Z")
                    and "+" not in start_time
                    and "-" not in start_time[-6:]
                ):
                    # No timezone info, add Z for UTC
                    start_time = start_time + "Z"
                if (
                    end_time
                    and not end_time.endswith("Z")
                    and "+" not in end_time
                    and "-" not in end_time[-6:]
                ):
                    end_time = end_time + "Z"

                start_payload = {"dateTime": start_time}
                end_payload = {"dateTime": end_time}

                if timezone:
                    start_payload["timeZone"] = timezone
                    end_payload["timeZone"] = timezone

                event_payload["start"] = start_payload
                event_payload["end"] = end_payload
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid datetime format: {str(e)}",
                )
    else:
        # Preserve existing start/end times
        event_payload["start"] = existing_event.get("start", {})
        event_payload["end"] = existing_event.get("end", {})

    # Send request to update the event
    try:
        async with httpx.AsyncClient() as client:
            response = await client.put(url, headers=headers, json=event_payload)

        if response.status_code == 200:
            updated_event = response.json()
            # Add calendarId to match the format of fetched events
            updated_event["calendarId"] = calendar_id
            return updated_event
        elif response.status_code == 404:
            raise HTTPException(
                status_code=404, detail="Event not found or access denied"
            )
        elif response.status_code == 401:
            # The decorator will handle token refresh, but we need to raise a 401 to trigger it
            raise HTTPException(status_code=401, detail="Authentication failed")
        else:
            response_json = response.json()
            if isinstance(response_json, dict):
                error_detail = response_json.get("error", {}).get(
                    "message", "Unknown error"
                )
            else:
                error_detail = "Unknown error"
            raise HTTPException(status_code=response.status_code, detail=error_detail)
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Failed to update event: {str(e)}")
