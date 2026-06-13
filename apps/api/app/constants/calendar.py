"""Calendar-related constants."""

# Fallback event/calendar color used when a calendar has no resolvable color
# (unmapped calendar_id). Single source of truth so the streaming path
# (calendar_tool.py), the REST service (calendar_service.py), and the frontend
# fallback (CalendarListCard.tsx) all agree on the same default.
DEFAULT_CALENDAR_COLOR = "#00bbff"
