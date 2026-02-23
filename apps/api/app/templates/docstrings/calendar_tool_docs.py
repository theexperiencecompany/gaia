"""Docstrings for calendar-related tools."""

CUSTOM_CREATE_EVENT = """
CALENDAR — CREATE EVENT(S)

Creates one or more calendar events. Supports batch creation with ID mapping for adding recurrence.

TIMEZONE: Use ISO format with user's timezone: "2025-01-15T10:00:00"

Args:
    events (List): List of events to create, each with:
        - summary (str): Required. Title.
        - start_datetime (str): Required. Start time (ISO format).
        - duration_hours/minutes (int): Duration, default 30min.
        - calendar_id (str): Calendar ID, default "primary".
        - description, location, attendees: Optional.
        - is_all_day (bool): Default False.
    confirm_immediately (bool): If True, create immediately. Default False.

Returns (when confirm_immediately=True):
    {
        "created_events": [{"index": 0, "summary": "...", "event_id": "abc123", ...}],
        "total_created": N
    }
    Use event_id with ADD_RECURRENCE to make events recurring.
"""

CUSTOM_GET_DAY_SUMMARY = """
CALENDAR — GET DAY SUMMARY

Gets a quick summary of a day's schedule including events, busy hours, and next upcoming event.
Uses user's timezone from their profile preferences.

USE THIS TOOL FIRST when user asks:
• "What does my day look like?"
• "What's on my schedule today/tomorrow?"
• "Am I busy on Thursday?"

Args:
    date (str): Optional. Date to get summary for (YYYY-MM-DD). Defaults to today.

Returns:
    {
        "date": "2025-01-15",
        "events": [...],
        "total_events": N,
        "next_event": {...} or null,
        "busy_hours": 5.5
    }
"""

CUSTOM_LIST_CALENDARS = """
CALENDAR — LIST CALENDARS

Lists all calendars accessible to the user.

Args:
    short (bool): If True (default), return only essential fields (id, summary, description, backgroundColor).

Returns:
    Dict with success status and list of calendars.
"""

CUSTOM_FETCH_EVENTS = """
CALENDAR — FETCH EVENTS

Fetches events from one or more calendars within an optional time range.

USAGE:
• "What does my day look like?" → calendar_ids=None (fetches ALL selected calendars)
• Events from specific calendar → calendar_ids=["calendar_id_here"]
• Events from primary only → calendar_ids=["primary"]

DEFAULT BEHAVIOR: If calendar_ids is None, fetches from ALL user's selected calendars.

Args:
    calendar_ids (List[str]): Optional. Calendar IDs to fetch from. If None, fetches from all selected calendars.
    time_min (str): Optional. Start time filter in ISO format. Defaults to current time.
    time_max (str): Optional. End time filter in ISO format.
    max_results (int): Maximum events to return (1-250), default 50.

Returns:
    Dict with success status, events list, calendars_fetched, and has_more flag.
"""

CUSTOM_FIND_EVENT = """
CALENDAR — SEARCH/FIND EVENT

Searches for events by text query. Searches event titles, descriptions, and other text fields.

Args:
    query (str): Required. Search query text.
    calendar_id (str): Calendar ID to search, default "primary".
    time_min (str): Optional. Start time filter in ISO format.
    time_max (str): Optional. End time filter in ISO format.

Returns:
    Dict with success status, matching events, and count.
"""

CUSTOM_GET_EVENT = """
CALENDAR — GET EVENT(S)

Gets one or more calendar events by ID.

Args:
    events (List): List of events to get, each with:
        - event_id (str): Required. The event ID.
        - calendar_id (str): Calendar ID, default "primary".

Returns:
    {
        "events": [{"event_id": "...", "calendar_id": "...", "event": {...}}],
        "total_retrieved": N
    }
"""

CUSTOM_DELETE_EVENT = """
CALENDAR — DELETE EVENT(S)

Deletes one or more calendar events.

Args:
    events (List): List of events to delete, each with:
        - event_id (str): Required. The event ID.
        - calendar_id (str): Calendar ID, default "primary".
    send_updates (str): Notify attendees: 'all', 'externalOnly', 'none'. Default 'all'.

Returns:
    {
        "deleted": [{"event_id": "...", "calendar_id": "..."}],
        "total_deleted": N
    }
"""

CUSTOM_PATCH_EVENT = """
CALENDAR — UPDATE/PATCH EVENT

Updates an existing calendar event. Only the fields provided will be updated.

Args:
    event_id (str): Required. The event ID to update.
    calendar_id (str): Calendar ID, default "primary".
    summary (str): Optional. New title.
    description (str): Optional. New description.
    start_datetime (str): Optional. New start time (ISO format).
    end_datetime (str): Optional. New end time (ISO format).
    location (str): Optional. New location.
    attendees (List[str]): Optional. New attendees list.
    send_updates (str): Notify attendees: 'all', 'externalOnly', 'none'. Default 'all'.

Returns:
    Dict with success status and updated event details.
"""

CUSTOM_ADD_RECURRENCE = """
CALENDAR — ADD RECURRENCE

Adds a recurrence pattern to an existing event. Use this to make an event repeating.

RECURRENCE PATTERNS (RFC 5545):

FREQUENCY VALUES:
- "DAILY": Repeats every N days
- "WEEKLY": Repeats every N weeks (use by_day for specific days)
- "MONTHLY": Repeats every N months
- "YEARLY": Repeats every N years

EXAMPLES:

1. Every Monday and Wednesday:
   frequency="WEEKLY", by_day=["MO", "WE"]

2. Every 2 weeks on Friday:
   frequency="WEEKLY", interval=2, by_day=["FR"]

3. Daily for 10 occurrences:
   frequency="DAILY", count=10

4. Weekly until Dec 31, 2025:
   frequency="WEEKLY", until_date="2025-12-31", by_day=["MO"]

5. Monthly on the first Monday:
   frequency="MONTHLY", by_day=["1MO"]

RULES:
- Use either 'count' OR 'until_date', not both
- by_day values: 'SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'
- Can prefix with number for nth occurrence (e.g., '1MO' = first Monday)

Args:
    event_id (str): Required. Event ID to add recurrence to.
    calendar_id (str): Calendar ID, default "primary".
    frequency (str): Required. One of: "DAILY", "WEEKLY", "MONTHLY", "YEARLY".
    interval (int): Interval between occurrences, default 1.
    count (int): Optional. Number of occurrences (don't use with until_date).
    until_date (str): Optional. End date "YYYY-MM-DD" (don't use with count).
    by_day (List[str]): Optional. Days of week: 'SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'.

Returns:
    Dict with success status, updated event, and RRULE string.
"""
