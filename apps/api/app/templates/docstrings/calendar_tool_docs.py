"""Docstrings for calendar-related tools."""

CUSTOM_CREATE_EVENT = """
CALENDAR — CREATE EVENT

Creates a calendar event with optional attendees and location. By default, sends event to frontend for user confirmation.

TIMEZONE HANDLING:
• Convert all times to user's timezone before calling
• Use ISO format: "2025-01-15T10:00:00"
• Duration is specified in hours and minutes

CONFIRMATION BEHAVIOR:
• confirm_immediately=False (default): Sends event to frontend for user confirmation
• confirm_immediately=True: Creates event immediately without confirmation

Args:
    summary (str): Required. Title of the event.
    start_datetime (str): Required. Start time in ISO format (use user's timezone).
    duration_hours (int): Duration hours (0-23), default 0.
    duration_minutes (int): Duration minutes (0-59), default 30.
    calendar_id (str): Calendar ID, default "primary".
    description (str): Optional. Event description.
    location (str): Optional. Event location.
    attendees (List[str]): Optional. List of attendee email addresses.
    is_all_day (bool): True for all-day events, default False.
    confirm_immediately (bool): If True, create immediately. Default False (send to frontend).

Returns:
    Dict with success status and event details, or streams confirmation to frontend.
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

Fetches events from a calendar within an optional time range.

DEFAULT BEHAVIOR: Fetches future events starting from current time.

Args:
    calendar_id (str): Calendar ID, default "primary".
    time_min (str): Optional. Start time filter in ISO format. Defaults to current time.
    time_max (str): Optional. End time filter in ISO format.
    max_results (int): Maximum events to return (1-250), default 20.

Returns:
    Dict with success status and list of events.
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
CALENDAR — GET EVENT

Gets a single calendar event by ID.

Args:
    event_id (str): Required. The event ID to retrieve.
    calendar_id (str): Calendar ID containing the event, default "primary".

Returns:
    Dict with success status and full event details.
"""

CUSTOM_DELETE_EVENT = """
CALENDAR — DELETE EVENT

Deletes a calendar event by ID.

Args:
    event_id (str): Required. The event ID to delete.
    calendar_id (str): Calendar ID containing the event, default "primary".
    send_updates (str): Notify attendees: 'all', 'externalOnly', 'none'. Default 'all'.

Returns:
    Dict with success status and confirmation message.
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
