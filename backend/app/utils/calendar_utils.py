from typing import Any, Dict, List, Set

from fastapi import HTTPException
import pendulum

from app.config.loggers import chat_logger as logger


def resolve_timezone(timezone: str) -> str:
    """
    Use Pendulum to convert a potentially non-canonical timezone name
    (e.g. "Asia/Calcutta") to its canonical form (e.g. "Asia/Kolkata").
    """
    try:
        # pendulum.timezone(...) returns a Pendulum timezone instance.
        # Its `.name` property holds the canonical name.
        return pendulum.timezone(timezone).name
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid timezone: '{timezone}'")


async def fetch_calendar_color(calendar_id: str, user_id: str) -> tuple[str, str]:
    """
    Fetch calendar name and background color for a given calendar_id.

    Args:
        calendar_id: The calendar ID to fetch color for
        user_id: The user ID

    Returns:
        tuple: (calendar_name, background_color)
    """
    from app.services.calendar_service import list_calendars

    try:
        calendar_list = await list_calendars(user_id)
        for cal in calendar_list.get("items", []):
            if cal.get("id") == calendar_id:
                return (
                    cal.get("summary", "Calendar"),
                    cal.get("backgroundColor", "#00bbff"),
                )
    except Exception as e:
        logger.warning(f"Could not fetch calendar color: {e}")

    return "Calendar", "#00bbff"


def extract_event_dates(calendar_options: List[Dict[str, Any]]) -> Set[str]:
    """
    Extract unique dates from calendar options.

    Args:
        calendar_options: List of calendar event options

    Returns:
        Set of date strings in YYYY-MM-DD format
    """
    event_dates = set()
    for event_option in calendar_options:
        start_time = event_option.get("start", "")
        if start_time:
            if "T" in start_time:
                event_date = start_time.split("T")[0]
            else:
                event_date = start_time
            event_dates.add(event_date)
    return event_dates


async def fetch_same_day_events(
    event_dates: Set[str],
    access_token: str,
    user_id: str,
) -> List[Dict[str, Any]]:
    """
    Fetch all events for the given dates.

    Args:
        event_dates: Set of date strings in YYYY-MM-DD format
        access_token: Google OAuth access token
        user_id: The user ID

    Returns:
        List of events across all specified dates
    """
    from app.services.calendar_service import get_calendar_events
    import asyncio

    async def fetch_events_for_date(event_date: str) -> List[Dict[str, Any]]:
        try:
            time_min = f"{event_date}T00:00:00Z"
            time_max = f"{event_date}T23:59:59Z"

            events_response = await get_calendar_events(
                access_token=access_token,
                user_id=user_id,
                time_min=time_min,
                time_max=time_max,
            )

            return events_response.get("events", []) if events_response else []
        except Exception as e:
            logger.warning(f"Error fetching events for {event_date}: {str(e)}")
            return []

    # Fetch events for all dates in parallel
    results = await asyncio.gather(
        *[fetch_events_for_date(date) for date in event_dates]
    )

    # Flatten the list of lists
    return [event for sublist in results for event in sublist]
