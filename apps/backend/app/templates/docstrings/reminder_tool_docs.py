"""Docstrings for reminder-rel3. Limits (only when user asks, explicitly or implicitly):
   • If user says "stop after 5 days" (daily reminders), set `max_occurrences=5`.
   • Or use `stop_after` (ISO 8601) to cut off after a date.

PAYLOAD:
  STATIC → {"title": str, "body": str}n tools."""

# TODO: Improve this prompt to be more concise and focused on the tool's purpose, LLM still sometimes misses that it has capabilities to create reminders with tools, not just static notifications.

CREATE_REMINDER = """
Create static reminder for the user.

This tool creates scheduled reminders that show simple notifications. Handles timezone
conversion, recurring schedules, and validation automatically.

TIMEZONE HANDLING:
• RELATIVE TIME (e.g., "in 2 minutes", "in 5 minutes") → Calculate the actual future time by adding the duration to current time. DO NOT convert timezones - just calculate the new hours/minutes and STRICTLY use timezone_offset: "+00:00"
• ABSOLUTE TIME (e.g., "at 3 PM", "tomorrow at 9 AM") → DO NOT use any timezone unless user explicitly mentions one
• EXPLICIT TIMEZONE: Only use timezone_offset parameter if user explicitly mentions a timezone (e.g., "at 3 PM EST", "tomorrow at 9 AM +05:30")

EXAMPLES (Current time: 2025-08-02T10:30:00Z):
• User: "Remind me in 5 minutes" → Calculate: 10:30:00 + 5 minutes = 10:35:00 → scheduled_at: "2025-08-02 10:35:00", timezone_offset: "+00:00"
• User: "Remind me in 2 hours" → Calculate: 10:30:00 + 2 hours = 12:30:00 → scheduled_at: "2025-08-02 12:30:00", timezone_offset: "+00:00"
• User: "Remind me at 3 PM today" → scheduled_at: "2025-08-02 15:00:00" (NO timezone)
• User: "Remind me tomorrow at 9 AM EST" → scheduled_at: "2025-08-03 09:00:00", timezone_offset: "-05:00"

WORKFLOW:
1. Create STATIC reminder with simple title+body notification.

2. Schedule:
   • One-time: use `scheduled_at` (YYYY-MM-DD HH:MM:SS format).
   • Recurring: use `repeat` (cron syntax).
   • If "start now" but repeat is out of sync, set `scheduled_at` to align first run.
   • Timezone: only use `timezone_offset` if user explicitly mentions a timezone in (+|-)HH:MM format.

3. Limits (only when user asks, explicitly or implicitly):
   • If user says “stop after 5 days” (daily reminders), set `max_occurrences=5`.
   • Or use `stop_after` (ISO 8601) to cut off after a date.

PAYLOAD:
  STATIC → {"title": str, "body": str}

Args:
    agent: "static" (default)
    repeat: cron string (e.g. "0 9 * * *", "0 */2 * * *", "30 18 * * 1-5")
    scheduled_at: date/time for first run (YYYY-MM-DD HH:MM:SS format, optional)
    timezone_offset: timezone offset in (+|-)HH:MM format (optional, only if user explicitly mentions timezone)
    max_occurrences: int (optional)
    stop_after: date/time cutoff (YYYY-MM-DD HH:MM:SS format, optional)
    stop_after_timezone_offset: timezone offset for stop_after in (+|-)HH:MM format (optional)
    payload: Required reminder content (see above)

Returns:
    str: success message or error message.
"""


LIST_USER_REMINDERS = """
List all scheduled reminders for a user.

Use this to retrieve all upcoming or past reminders for a user. Returns static reminders, optionally filtered by status.

Args:
    status (str, optional): Filter by state (e.g., "scheduled", "completed").

Returns:
    list[dict]: List of reminder objects.
"""


GET_REMINDER = """
Get full details of a specific reminder by ID.

Use this to inspect a reminder's type, schedule, payload, and current state. Especially useful before editing or cancelling.

Args:
    reminder_id (str): The ID of the reminder to fetch.

Returns:
    dict: Full reminder object or error.
"""


DELETE_REMINDER = """
Cancel a scheduled reminder.

Use this when a user no longer wants a reminder to run. It marks the reminder as cancelled and prevents future execution.

Args:
    reminder_id (str): The ID of the reminder to cancel.

Returns:
    dict: Confirmation of cancellation or error.
"""


UPDATE_REMINDER = """
Update an existing reminder's configuration.

Use this to modify reminder schedule, recurrence, or payload. Useful for rescheduling or changing static reminder content.

Args:
    reminder_id (str): The ID of the reminder to update.
    repeat (str, optional): New cron pattern for recurrence.
    max_occurrences (int, optional): New limit on runs.
    stop_after (str, optional): New expiration date/time (YYYY-MM-DD HH:MM:SS format).
    stop_after_timezone_offset (str, optional): Timezone offset for stop_after in (+|-)HH:MM format.
    payload (dict, optional): New title and body for the reminder.

Returns:
    dict: Update status or error.
"""


SEARCH_REMINDERS = """
Search through user's reminders using text query.

Use this to semantically search reminders using keywords found in their title or content. Works with static reminders.

Args:
    query (str): Natural language query or keyword (e.g., "doctor", "follow up").

Returns:
    list[dict]: Matching reminders or error.
"""
