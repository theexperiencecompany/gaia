"""Google Calendar v3 behind Composio's proxy: calendarList and events.list as Google answers them."""

from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

from briefsim.world.model import AppState, CalendarEvent

JsonObject = dict[str, object]
CALENDAR_ID = "sim-founder@example.com"
EVENTS_PREFIX = "/calendar/v3/calendars/"


def _iso(at: datetime, tz: str) -> str:
    return at.astimezone(ZoneInfo(tz)).isoformat()


def _when(event: CalendarEvent) -> tuple[JsonObject, JsonObject]:
    if event.all_day is not None:
        return (
            {"date": event.all_day.isoformat()},
            {"date": (event.all_day + timedelta(days=1)).isoformat()},
        )
    assert event.start is not None and event.end is not None
    return (
        {"dateTime": _iso(event.start, event.organizer_tz), "timeZone": event.organizer_tz},
        {"dateTime": _iso(event.end, event.organizer_tz), "timeZone": event.organizer_tz},
    )


def _render(event: CalendarEvent) -> JsonObject:
    start, end = _when(event)
    rendered: JsonObject = {
        "kind": "calendar#event",
        "id": event.id,
        "status": event.status,
        "htmlLink": f"https://www.google.com/calendar/event?eid={event.id}",
        "created": event.created.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "updated": event.updated.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "summary": event.title,
        "creator": {"email": CALENDAR_ID, "self": True},
        "organizer": {"email": CALENDAR_ID, "self": True},
        "start": start,
        "end": end,
        "attendees": [{"email": CALENDAR_ID, "self": True, "responseStatus": event.self_response}],
        "eventType": "default",
    }
    if event.location:
        rendered["location"] = event.location
    return rendered


def _span(event: CalendarEvent, tz: str) -> tuple[datetime, datetime]:
    if event.all_day is not None:
        start = datetime.combine(event.all_day, datetime.min.time(), ZoneInfo(tz))
        return start, start + timedelta(days=1)
    assert event.start is not None and event.end is not None
    return event.start, event.end


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def calendar_list(timezone: str) -> JsonObject:
    return {
        "kind": "calendar#calendarList",
        "items": [
            {
                "kind": "calendar#calendarListEntry",
                "id": CALENDAR_ID,
                "summary": CALENDAR_ID,
                "timeZone": timezone,
                "accessRole": "owner",
                "primary": True,
                "selected": True,
                "backgroundColor": "#9fe1e7",
            }
        ],
    }


def events(state: AppState, query: dict[str, str], timezone: str) -> JsonObject:
    """Answer events.list: overlap with [timeMin, timeMax), cancelled hidden, one page of maxResults."""
    low, high = _parse(query.get("timeMin")), _parse(query.get("timeMax"))
    hits = []
    for event in state.calendar.values():
        if event.status == "cancelled":
            continue
        start, end = _span(event, timezone)
        if (low is None or end > low) and (high is None or start < high):
            hits.append((start, event))
    hits.sort(key=lambda pair: pair[0])
    size = int(query.get("maxResults") or 250)
    offset = int(query.get("pageToken") or 0)
    page = hits[offset : offset + size]
    body: JsonObject = {
        "kind": "calendar#events",
        "summary": CALENDAR_ID,
        "timeZone": timezone,
        "items": [_render(e) for _, e in page],
    }
    if offset + size < len(hits):
        body["nextPageToken"] = str(offset + size)
    return body


def calendar_id_of(endpoint: str) -> str | None:
    """Return the calendar id an events.list URL addresses, or None for any other URL."""
    path = urlparse(endpoint).path
    if not path.startswith(EVENTS_PREFIX) or not path.endswith("/events"):
        return None
    return unquote(path[len(EVENTS_PREFIX) : -len("/events")])
