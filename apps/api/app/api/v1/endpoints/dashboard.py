"""Mission Control aggregation endpoints.

The dashboard is a pure view over records other systems already write —
todos (both assignees), calendar events, and workflow executions. No new
event store: `/dashboard/today` interleaves them chronologically and
`/dashboard/heatmap` derives the contribution grid + streak from
`completed_at` alone (only real completed work colors a day — heartbeat
activity never counts, so gray days are honest).
"""

from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_user_timezone_from_preferences,
)
from app.db.mongodb.collections import todos_collection, workflow_executions_collection
from app.services.calendar_service import fetch_calendar_events
from shared.py.wide_events import log

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

_HEATMAP_MAX_DAYS = 366


def _day_bounds(tz: ZoneInfo) -> tuple[datetime, datetime]:
    today = datetime.now(tz).date()
    start = datetime.combine(today, time.min, tzinfo=tz)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def _todo_item(doc: dict[str, Any]) -> dict[str, Any]:
    completed = bool(doc.get("completed"))
    when = doc.get("completed_at") or doc.get("scheduled_at") or doc.get("due_date")
    return {
        "type": "todo",
        "time": when.isoformat() if when else None,
        "title": doc.get("title", "untitled"),
        "status": doc.get("execution_status") or ("done" if completed else "pending"),
        "assignee": doc.get("assignee", "user"),
        "todo_id": str(doc["_id"]),
        "subtitle": doc.get("serves"),
    }


def _execution_item(doc: dict[str, Any]) -> dict[str, Any]:
    when = doc.get("completed_at") or doc.get("started_at")
    return {
        "type": "execution",
        "time": when.isoformat() if when else None,
        "title": doc.get("workflow_title") or "Workflow run",
        "status": doc.get("status"),
        "assignee": "gaia",
        "subtitle": doc.get("summary"),
    }


def _event_items(user_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Today's primary-calendar events; a calendar outage degrades to an empty
    section rather than failing the whole timeline (other sources still render)."""
    try:
        data = fetch_calendar_events(
            "primary",
            user_id,
            time_min=start.isoformat(),
            time_max=end.isoformat(),
            max_results=25,
        )
    except Exception as e:
        log.warning("dashboard.calendar_fetch_failed", user_id=user_id, error=str(e))
        return []
    items = []
    for ev in data.get("items", []):
        start_raw = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
        items.append(
            {
                "type": "event",
                "time": start_raw,
                "title": ev.get("summary", "(no title)"),
                "status": None,
                "subtitle": ev.get("location"),
            }
        )
    return items


@router.get("/today")
async def get_today(
    user: Annotated[dict, Depends(get_current_user)],
    user_timezone: str = Depends(get_user_timezone_from_preferences),
) -> dict[str, Any]:
    """Today's timeline: todos + calendar events + workflow executions, chronological."""
    user_id = user["user_id"]
    tz = ZoneInfo(user_timezone or "UTC")
    start, end = _day_bounds(tz)

    todo_query = {
        "user_id": user_id,
        "$or": [
            {"completed_at": {"$gte": start, "$lt": end}},
            {"completed": False, "scheduled_at": {"$gte": start, "$lt": end}},
            {"completed": False, "due_date": {"$gte": start, "$lt": end}},
            # Active GAIA work belongs on today's board even when unscheduled.
            {
                "completed": False,
                "execution_status": {"$in": ["proposed", "queued", "running", "needs_you"]},
            },
        ],
    }
    todos = [_todo_item(d) async for d in todos_collection.find(todo_query).limit(100)]

    exec_query = {"user_id": user_id, "started_at": {"$gte": start, "$lt": end}}
    executions = [
        _execution_item(d) async for d in workflow_executions_collection.find(exec_query).limit(50)
    ]

    items = todos + executions + _event_items(user_id, start, end)
    items.sort(key=lambda i: i["time"] or "9999")
    return {"items": items}


@router.get("/heatmap")
async def get_heatmap(
    user: Annotated[dict, Depends(get_current_user)],
    user_timezone: str = Depends(get_user_timezone_from_preferences),
    days: int = Query(default=365, ge=7, le=_HEATMAP_MAX_DAYS),
) -> dict[str, Any]:
    """Contribution grid over completed todos (both assignees) + current streak."""
    user_id = user["user_id"]
    tz = ZoneInfo(user_timezone or "UTC")
    today = datetime.now(tz).date()

    counts = await completed_day_counts(user_id, tz, window_start_utc(tz, days))
    day_list = [
        {"date": d, **counts.get(d, {"user_count": 0, "gaia_count": 0})}
        for d in (
            (today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)
        )
    ]
    streak = streak_from_counts(counts, today, days)

    return {"days": day_list, "streak": streak}
