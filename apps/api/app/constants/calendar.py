"""Calendar-related constants."""

from datetime import timedelta

# Fallback color for an unmapped calendar_id; single source so calendar_tool.py,
# calendar_service.py, and the frontend's CalendarListCard.tsx agree on the default.
DEFAULT_CALENDAR_COLOR = "#00bbff"

# Length a created event gets when the caller gives a start but no end_datetime.
DEFAULT_EVENT_DURATION = timedelta(minutes=30)
