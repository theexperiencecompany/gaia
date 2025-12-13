"""Docstrings for calendar-related tools."""

CALENDAR_EVENT = """
CALENDAR — CREATE: This tool is used to create calendar events.

This tool processes event details and returns a structured JSON response. The frontend will use this response to render event options that the user must manually confirm.

TIMEZONE HANDLING:
• SIMPLIFIED APPROACH: Use only two fields for handling time
  - `time_str`: For relative times, use offset format like "+02:30" (2 hours and 30 minutes from now)
  - `time_str`: For absolute times, use ISO format like "2025-08-08T16:30:00"
  - `duration_minutes`: Specify event duration in minutes (defaults to 30 if not provided)

• **MANDATORY TIMEZONE RULE**:
  - If the user explicitly mentions a timezone (e.g., "EST", "PST", "IST", "GMT+5:30"), you MUST always include the corresponding `timezone_offset` in the output.
  - This is **not optional** — never omit `timezone_offset` if a timezone is stated.
  - If no timezone is mentioned, do not provide `timezone_offset`.

EXAMPLES (Current time: 2025-08-08T14:30:00Z):
• User: "Create event in 2 hours" → time_str: "+02:00", duration_minutes: 30
• User: "Schedule meeting at 4:30 PM today for 1 hour" → time_str: "2025-08-08T16:30:00", duration_minutes: 60
• User: "Book appointment tomorrow at 9 AM EST for 45 minutes" → time_str: "2025-08-09T09:00:00", timezone_offset: "-05:00", duration_minutes: 45
• User: "Create event for classes tomorrow at 10 AM PST for 1 hour" → time_str: "2025-08-09T10:00:00", timezone_offset: "-08:00", duration_minutes: 60

The backend will handle all timezone calculations automatically. Your only responsibility is to include `timezone_offset` whenever the user states a timezone.

Important:
- This tool does NOT directly create calendar events.
- The user must review and confirm the events before they are added to their calendar.
- For relative times (like "in 2 hours"), provide time_str as an offset string (e.g., "+02:00")
- For absolute times (like "at 3 PM"), provide time_str in ISO format (e.g., "2025-08-08T16:30:00")
- Specify duration_minutes for how long the event should last (defaults to 30 minutes if not specified)
- Only provide timezone_offset when a specific timezone is explicitly mentioned.

---

WHEN TO USE:

Use this tool when the user wants to:
- Schedule a single or recurring event
- Set up meetings, calls, appointments, or reminders
- Define repeating events like "every Monday", "1st of every month", or "every January and June"
- Create multiple events at once (use array input)

This tool handles both single events and multiple events in one call:
- Single event: Pass one EventCreateRequest object
- Multiple events: Pass an array of EventCreateRequest objects

IMPORTANT: When creating multiple events, always use a single tool call with an array.
Never make separate tool calls for each event in the same message.

---

EVENT FORMAT: `CalendarEventToolRequest`

Each event must include the following fields:

- `summary` (str): Required. Title or name of the event.
- `description` (str): Optional. Extra information about the event.
- `is_all_day` (bool): Required. Set to `true` if the event is an all-day event.
- `time_str` (str): Required if `is_all_day` is `false`. Either:
  - Relative time offset in format "+HH:MM" (e.g., "+02:30" for 2 hours and 30 minutes from now)
  - Absolute time in ISO 8601 format: `YYYY-MM-DDTHH:MM:SS`.
- `duration_minutes` (int): Optional. Duration of the event in minutes. Defaults to 30 if not specified.
- `timezone_offset` (str): Optional. Only provide when user explicitly mentions a timezone (e.g., "-05:00" for EST).
- `calendar_id` (str): Optional. ID of the calendar to add the event to.
- `recurrence` (RecurrenceData): Optional. Used for recurring events.

---

RECURRING EVENTS: `RecurrenceData`

Use the `recurrence` object when the event repeats on a schedule.

It consists of:

### `rrule` (object) — Required

Defines the recurrence pattern.

- `frequency` (str): Required. One of `"DAILY"`, `"WEEKLY"`, `"MONTHLY"`, or `"YEARLY"`.
  - `"DAILY"`: Repeats every N days
  - `"WEEKLY"`: Repeats every N weeks
  - `"MONTHLY"`: Repeats every N months
  - `"YEARLY"`: Repeats every N years

- `interval` (int): Optional. Defaults to 1. Indicates how often the event repeats, based on the frequency.
  - Example: `interval = 2` with `frequency = "WEEKLY"` means every 2 weeks.

- `count` (int): Optional. Total number of times the event should occur. Use either `count` or `until`, not both.

- `until` (str): Optional. ISO date (e.g., `2025-09-30`). Specifies when the recurrence should stop. Do not use `until` to skip specific dates — use `exclude_dates` for that.

- `by_day` (list of str): Optional. Only for `WEEKLY`, `MONTHLY`, or `YEARLY` frequency.
  - Specifies **days of the week** on which the event should repeat.
  - Values: `["MO", "TU", "WE", "TH", "FR", "SA", "SU"]`
  - Example: A weekly event on Monday and Wednesday → `by_day = ["MO", "WE"]`

- `by_month_day` (list of int): Optional. For `MONTHLY` or `YEARLY` frequency.
  - Specifies **days of the month** when the event should occur.
  - Example: An event on the 1st and 15th of each month → `by_month_day = [1, 15]`

- `by_month` (list of int): Optional. For `YEARLY` frequency.
  - Specifies **which months** the event should occur in (1 = January, 12 = December).
  - Example: An event in January and June every year → `by_month = [1, 6]`

#### How `by_day`, `by_month_day`, and `by_month` Work Together:

- Use `by_day` to specify **which days of the week** (like "every Monday").
- Use `by_month_day` to specify **which days of the month** (like "1st and 15th").
- Use `by_month` to specify **which months** (like "January and June only").

You can combine these for more advanced rules:

- Example: `"YEARLY"` + `by_day=["MO"]`, `by_month=[1, 6]`
  → Every Monday in January and June, every year.

Avoid combining these unless the user has described a complex recurring pattern.

- `exclude_dates` (list of str): Optional. Dates in `YYYY-MM-DD` format to explicitly skip, even if they match the recurrence rule.
  - Example: Skip a specific Monday due to a holiday.

- `include_dates` (list of str): Optional. Dates to explicitly include, even if they don't match the rule.
  - Example: Add a makeup session on a Saturday, even though the normal rule is "every Friday".

---

RULES TO FOLLOW:

- Use a single event unless the user clearly wants recurrence.
- Do NOT use `until` to skip dates — use `exclude_dates`.
- Do NOT modify the `rrule` to force in one-off events — use `include_dates`.
- Use only one of `count` or `until`, unless both are explicitly requested.

---

EXAMPLES:

1. **Simple weekly event:**

User says: *“Set up a team sync every Monday at 10 AM for the next 4 weeks.”*

```json
[{
  "summary": "Team Sync",
  "description": "Weekly standup with dev team",
  "is_all_day": false,
  "time_str": "2025-08-04T10:00:00",
  "duration_minutes": 30,
  "recurrence": {
    "rrule": {
      "frequency": "WEEKLY",
      "interval": 1,
      "count": 4,
      "by_day": ["MO"]
    }
  }
}]
````

2. **Monthly event with skipped and added dates:**

User says: *“Can you please create recurring calendar event for everyday at 10PM PST about standup meeting on every Mon, Tue, Friday in Aug, Sep, Oct, excluding 8 Aug”*

```json
[{
  "summary": "Standup Meeting",
  "description": "Recurring team standup",
  "is_all_day": false,
  "time_str": "2025-08-04T22:00:00",
  "duration_minutes": 30,
  "timezone_offset": "-08:00",
  "recurrence": {
    "rrule": {
      "frequency": "WEEKLY",
      "interval": 1,
      "by_day": ["MO", "TU", "FR"],
      "by_month": [8, 9, 10],
      "exclude_dates": ["2025-08-08"]
    }
  }
}]
```

---

CRITICAL USAGE RULE:

This tool takes an ARRAY input and is designed to handle multiple events in a single call.
NEVER call this tool multiple times in the same message, even if creating multiple events.

✓ CORRECT: Pass all events in one array: [event1, event2, event3]
✗ INCORRECT: Call the tool separately for each event (causes system issues)

Always batch multiple event creations into a single tool call using the array parameter.
This prevents conflicts and ensures proper event processing.

---

Args:
    events_data: array of CalendarEventToolRequest objects

Returns:
    str: Confirmation message or JSON string containing formatted calendar event options for user confirmation.
"""


FETCH_CALENDAR_LIST = """
CALENDAR — LIST: This tool is used to fetch the user's calendar list.

This tool securely accesses the user's access token from the config metadata
and calls the calendar service to fetch all available calendars.

Use this tool when a user asks to:
- View their calendar list
- Choose a calendar for adding events
- Verify which calendars are connected
- See what calendars they have access to

USAGE NOTES:
- This tool requires NO parameters - it automatically uses the user's credentials from config
- Always use this when the user wants to see their available calendars
- Don't use this tool for fetching events - use fetch_calendar_events instead

Returns:
    str: Instructions on what to do next or an error message if the calendar list cannot be fetched.
"""

FETCH_CALENDAR_EVENTS = """
CALENDAR — FETCH EVENTS: This tool is used to fetch calendar events.

This tool retrieves events from the user's calendar based on optional filters like time range
and specific calendar selection. It uses the user's access token to securely fetch events.

**DEFAULT BEHAVIOR**: By default, this tool fetches only **future events** (starting from current time).
To fetch past events, you must explicitly set the time_min parameter to a past date.

Use this tool when a user wants to:
- View their upcoming events
- Check their schedule for a specific time period
- See events from specific calendars
- Get a general overview of their calendar

PARAMETER USAGE GUIDELINES:

TIME FILTERS (time_min, time_max):
- DEFAULT: Omit time_min to get future events only (system defaults to current time forward)
- USE time_min WHEN: User specifies "events after [date]", "starting from [date]", or wants past events
- USE time_max WHEN: User specifies "events before [date]", "until [date]", or "up to [date]"
- USE BOTH WHEN: User specifies a specific date range like "events between [date1] and [date2]"
- DON'T USE: For general requests like "show my events" or "what's on my calendar" (defaults to future events)

CALENDAR SELECTION (selected_calendars):
- DEFAULT: Omit to fetch from user's preferred calendars (from their settings)
- USE WHEN: User specifically mentions calendar names like "events from my work calendar"
- DON'T USE: For general calendar viewing - let the system use user preferences

LIMIT (limit):
- DEFAULT: 20 events per calendar
- USE WHEN: User requests a specific number of events like "show me 10 events" or "next 50 events"
- RANGE: Can be set from 1 to 250 (Google Calendar API limit)
- DON'T MODIFY: For general requests - 20 is a good default for most use cases

Args:
    time_min (str, optional): Start time filter in ISO 8601 format (defaults to current time for future events only)
    time_max (str, optional): End time filter in ISO 8601 format - only use when user specifies an end date
    selected_calendars (List[str], optional): List of calendar IDs - only use when user specifies particular calendars
    limit (int, optional): Maximum number of events to return per calendar (default: 20, max: 250)

Returns:
    str: JSON string containing filtered events data with only essential fields, total count, selected calendars, and pagination token
"""

SEARCH_CALENDAR_EVENTS = """
CALENDAR — SEARCH EVENTS: This tool is used to search calendar events.

This tool searches through the user's calendar events to find matches based on event titles,
descriptions, or calendar names. It performs case-insensitive text matching.

Use this tool when a user wants to:
- Find events containing specific keywords
- Search for meetings with certain people
- Look for events related to specific topics

IMPORTANT: By default, search across ALL calendar events regardless of date/time.
Only use time_min and time_max filters when the user specifically requests to limit
the search to a particular date range. For general keyword searches, omit these
parameters to search through the entire calendar history.

Args:
    query (str): Search query text to match against event titles, descriptions, and calendar names
    time_min (str, optional): Start time filter in ISO 8601 format - ONLY use when user specifies a date range
    time_max (str, optional): End time filter in ISO 8601 format - ONLY use when user specifies a date range

Returns:
    str: JSON string containing matching events, search query, and result counts
"""

VIEW_CALENDAR_EVENT = """
CALENDAR — VIEW EVENT: This tool is used to view a calendar event by ID.

This tool fetches complete details for a single calendar event using its event ID and calendar ID.
It provides comprehensive information about the event including all metadata.

Use this tool when a user wants to:
- View full details of a specific event
- Get comprehensive information about an event they mentioned
- Check event details before making modifications
- See complete event information including attendees, location, etc.

PARAMETER USAGE GUIDELINES:

EVENT ID (event_id):
- ALWAYS REQUIRED: You must have the specific event ID to use this tool
- GET FROM: Previous calendar searches, event lists, or when user references a specific event
- DON'T USE: If you don't have a specific event ID - use search or fetch tools instead

CALENDAR ID (calendar_id):
- DEFAULT: Use "primary" (the user's main calendar) when not specified
- USE SPECIFIC ID WHEN: You know the event is in a particular calendar (from previous searches)
- USE "primary" WHEN: User doesn't specify a calendar or for general event viewing
- DON'T GUESS: If unsure, stick with "primary" - the system will find the event

WHEN NOT TO USE THIS TOOL:
- User asks for "all events" or "upcoming events" → use fetch_calendar_events
- User asks to "find events about X" → use search_calendar_events
- User asks for "today's events" → use fetch_calendar_events with time filters

Args:
    event_id (str): The unique identifier of the calendar event (REQUIRED - must be obtained from previous searches/lists)
    calendar_id (str): The calendar ID containing the event (defaults to "primary" if not specified)

Returns:
    str: JSON string containing complete event details including all metadata
"""

DELETE_CALENDAR_EVENT = """
CALENDAR — DELETE: This tool is used to delete or cancel calendar events (confirmation required).

Purpose:
Use this tool **only when the user wants to cancel or delete an existing calendar event**.

Do not use this tool for updating event details like time, title, or description — that is handled by EDIT_CALENDAR_EVENT.

Use this tool when:
- The user clearly expresses intent to remove, cancel, or delete an event
- You already have both `event_id` and `calendar_id` from earlier system context
- Or, you can generate a search `query` from the user's request

This tool deletes calendar events using one of two mutually exclusive methods:
1. Direct lookup with `event_id` and `calendar_id` — only if both are already known from system context
2. Search-based lookup using a `query` string — when identifiers are not available

Never assume or guess `event_id` or `calendar_id`. These should only be used if obtained earlier (e.g., from listing or search). If not, fall back to a `query` string from the user’s input.

Important:
This tool does not directly delete the event. It finds a match and sends it to the frontend for confirmation. Deletion occurs **only after** the user confirms.

Examples:
- "Delete my meeting with Sarah" → Use `query="meeting with Sarah"`
- You have `event_id="abc123"` and `calendar_id="def456"` from a previous step → Use direct lookup

Arguments:
    request (EventLookupRequest): Must include one of:
        - `event_id` and `calendar_id` (if both are already known)
        - OR `query` (parsed from user's request)

Returns:
    str: A confirmation message or JSON payload with event details for user confirmation before deletion.
"""

EDIT_CALENDAR_EVENT = """
CALENDAR — EDIT: This tool is used to modify or update existing calendar events.

Purpose:
Use this tool **only when the user wants to update, change, or modify details of an existing calendar event**.

Use this tool when:
- The user wants to:
    - Change the event's title, description, time, duration, or recurrence
    - Modify a meeting's details
- You already have both `event_id` and `calendar_id` from prior system context
- Or, you can derive a search `query` from the user's request

This tool edits calendar events using two mutually exclusive methods:
1. Direct lookup with `event_id` and `calendar_id` — only if both are already known
2. Search-based lookup using a `query` string — when identifiers are not available

Do not assume or guess `event_id` or `calendar_id`. Use only if previously retrieved. Otherwise, use a `query`.

TIMEZONE HANDLING FOR UPDATES:
• RELATIVE TIME (e.g., "move it 2 hours later", "shift by 30 minutes"): For any time described relative to the event's current time, you MUST calculate the new time and ALWAYS set `timezone_offset` to `"+00:00"`. This is a strict requirement. Do not use any other offset.
• ABSOLUTE TIME (e.g., "change to 4:30 PM", "move to tomorrow at 9 AM") → Provide the new time as-is, timezone_offset will be processed internally based on user's timezone
• EXPLICIT TIMEZONE: Use timezone_offset parameter if user explicitly mentions a timezone (e.g., "change to 3 PM EST", "move to 9 AM +05:30")

EXAMPLES FOR TIME UPDATES:
• User: "Move my meeting 2 hours later" → Calculate new time: original_start + 2 hours → start: "calculated_time", timezone_offset: "+00:00"
• User: "Change meeting to 4:30 PM today" → start: "2025-08-08T16:30:00" (timezone_offset: null - processed internally)
• User: "Reschedule to tomorrow at 9 AM PST" → start: "2025-08-09T09:00:00", timezone_offset: "-08:00"

The calendar tool will process all updated times internally and send final calculated times to the frontend.

Important:
This tool does not immediately apply updates. It sends the updated event to the frontend for user confirmation. Changes are finalized only after user approval.

Examples:
- "Move my meeting with Sarah to 3pm" → Use `query="meeting with Sarah"` and update `start`
- "Make my team meeting recur weekly on Monday and Wednesday" → Use `query` and update `recurrence`
- You have `event_id="abc123"` and `calendar_id="def456"` → Use direct lookup

Arguments:
    request (EventLookupRequest): Must include one of:
        - `event_id` and `calendar_id` (if already known)
        - OR `query` (from user's event description)
    summary (str, optional): New event title
    description (str, optional): New event description
    start (str, optional): New start time (ISO 8601 format: YYYY-MM-DDTHH:MM:SS)
    end (str, optional): New end time (ISO 8601 format: YYYY-MM-DDTHH:MM:SS)
    is_all_day (bool, optional): Whether it's an all-day event
    timezone_offset (str, optional): Timezone offset in (+|-)HH:MM format. Only use if user explicitly mentions a timezone
    recurrence (RecurrenceData, optional): New recurrence pattern

Returns:
    str: A confirmation message or JSON payload with updated event details for user review and confirmation.
"""
