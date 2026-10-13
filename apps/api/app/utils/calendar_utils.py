"""Calendar URL helpers shared by calendar_service.py and calendar_tool.py."""

from urllib.parse import quote

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


def calendar_events_endpoint(calendar_id: str, event_id: str | None = None) -> str:
    """Build a Google Calendar events endpoint, percent-encoding the calendar and event IDs.

    Google calendar IDs commonly contain '@'/'#' (e.g. "user@group.calendar.google.com", "#contacts@group.v.calendar.google.com"), which break the URL path if interpolated raw.
    """
    endpoint = f"{CALENDAR_API_BASE}/calendars/{quote(calendar_id, safe='')}/events"
    if event_id is not None:
        endpoint += f"/{quote(event_id, safe='')}"
    return endpoint
