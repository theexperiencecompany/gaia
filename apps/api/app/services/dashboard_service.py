"""Aggregation for the Today dashboard.

The dashboard is a read-only lens: five saved searches over the todos
collection, the latest briefing headline, the runs quota, and the next
calendar event, returned as one sectioned payload. Nothing here writes.
"""

import asyncio
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.api.v1.middleware.tiered_rate_limiter import tiered_limiter
from app.config.rate_limits import RateLimitPeriod, get_limits_for_plan, get_reset_time
from app.constants.todos import (
    GAIA_TODO_EXECUTIONS_FEATURE,
    gaia_assigned_filter,
    user_assigned_filter,
)
from app.db.mongodb.collections import todos_collection
from app.models.payment_models import PlanType
from app.models.todo_models import ExecutionStatus
from app.services.briefing.repository import get_latest_briefing
from app.services.calendar_service import fetch_calendar_events
from shared.py.wide_events import log

_SECTION_LIMIT = 25


def _day_bounds(tz: ZoneInfo) -> tuple[datetime, datetime]:
    today = datetime.now(tz).date()
    start = datetime.combine(today, time.min, tzinfo=tz)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _base_item(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "todo_id": str(doc["_id"]),
        "title": doc.get("title", "untitled"),
        "serves": doc.get("serves"),
    }


async def _needs_you(user_id: str) -> list[dict[str, Any]]:
    query = {
        "user_id": user_id,
        "completed": False,
        "kind": {"$ne": "goal"},
        "execution_status": {
            "$in": [ExecutionStatus.PROPOSED.value, ExecutionStatus.NEEDS_YOU.value]
        },
        **gaia_assigned_filter(),
    }
    cursor = todos_collection.find(query).sort("created_at", -1).limit(_SECTION_LIMIT)
    return [
        {
            **_base_item(doc),
            "execution_status": doc.get("execution_status"),
            "blocker_question": doc.get("blocker_question"),
            "conversation_id": doc.get("last_run_conversation_id"),
        }
        async for doc in cursor
    ]


async def _in_flight(user_id: str) -> list[dict[str, Any]]:
    query = {
        "user_id": user_id,
        "completed": False,
        "kind": {"$ne": "goal"},
        "execution_status": {"$in": [ExecutionStatus.QUEUED.value, ExecutionStatus.RUNNING.value]},
        **gaia_assigned_filter(),
    }
    cursor = todos_collection.find(query).sort("scheduled_at", -1).limit(_SECTION_LIMIT)
    return [
        {
            **_base_item(doc),
            "execution_status": doc.get("execution_status"),
            "started_at": _iso(doc.get("scheduled_at")),
            "conversation_id": doc.get("last_run_conversation_id"),
        }
        async for doc in cursor
    ]


async def _suggested(user_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    # Due-today todos already render in "Your tasks" (with the offer tag), so
    # this section only surfaces offers the day view would otherwise miss.
    query = {
        "user_id": user_id,
        "completed": False,
        "gaia_offer": {"$nin": [None, ""]},
        "$nor": [
            {"due_date": {"$gte": start, "$lt": end}},
            {"scheduled_at": {"$gte": start, "$lt": end}},
        ],
        **user_assigned_filter(),
    }
    cursor = todos_collection.find(query).sort("updated_at", -1).limit(_SECTION_LIMIT)
    return [{**_base_item(doc), "gaia_offer": doc.get("gaia_offer")} async for doc in cursor]


async def _your_tasks(user_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    # Deadline-only on purpose: a scheduled_at is GAIA's plumbing, a due_date
    # is the user's own commitment for the day.
    query = {
        "user_id": user_id,
        "completed": False,
        "due_date": {"$gte": start, "$lt": end},
        **user_assigned_filter(),
    }
    cursor = todos_collection.find(query).sort("due_date", 1).limit(_SECTION_LIMIT)
    return [
        {
            **_base_item(doc),
            "due_at": _iso(doc.get("due_date") or doc.get("scheduled_at")),
            "gaia_offer": doc.get("gaia_offer"),
        }
        async for doc in cursor
    ]


async def _done_today(user_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    query = {
        "user_id": user_id,
        "kind": {"$ne": "goal"},
        "completed_at": {"$gte": start, "$lt": end},
    }
    cursor = todos_collection.find(query).sort("completed_at", -1).limit(_SECTION_LIMIT)
    return [
        {
            **_base_item(doc),
            "completed_at": _iso(doc.get("completed_at")),
            "assignee": doc.get("assignee", "user"),
            "conversation_id": doc.get("last_run_conversation_id"),
        }
        async for doc in cursor
    ]


def _fallback_headline(needs_you: int, in_flight: int, done_today: int) -> str:
    """Deterministic headline for afternoons and briefing-less mornings."""
    if needs_you == 1:
        return "One thing needs you."
    if needs_you:
        return f"{needs_you} things need you."
    if in_flight:
        return "GAIA is working. Nothing needs you."
    if done_today:
        return f"All clear. {done_today} done today."
    return "All clear."


async def _headline(user_id: str, tz: ZoneInfo, fallback: str) -> str:
    """The briefing's own headline until user-local noon, deterministic after.

    The morning push and this page share one sentence by construction; past
    noon the 8am voice is stale, so counts take over.
    """
    now_local = datetime.now(tz)
    if now_local.hour >= 12:
        return fallback
    briefing = await get_latest_briefing(user_id)
    if briefing and briefing.date == now_local.date().isoformat() and briefing.payload.headline:
        return briefing.payload.headline
    return fallback


def _next_event(user_id: str, start: datetime, end: datetime) -> dict[str, Any] | None:
    """First calendar event still ahead today; an outage degrades to None."""
    try:
        data = fetch_calendar_events(
            "primary",
            user_id,
            time_min=datetime.now(UTC).isoformat(),
            time_max=end.isoformat(),
            max_results=5,
        )
    except Exception as e:
        log.warning("dashboard.calendar_fetch_failed", user_id=user_id, error=str(e))
        return None
    for ev in data.get("items", []):
        when = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
        if when:
            return {"time": when, "title": ev.get("summary", "(no title)")}
    return None


async def _runs(user_id: str, user_plan: PlanType) -> dict[str, Any] | None:
    """Remaining GAIA executions for the metered window (monthly on free, daily on pro)."""
    limits = get_limits_for_plan(GAIA_TODO_EXECUTIONS_FEATURE, user_plan)
    period = RateLimitPeriod.MONTH if limits.month else RateLimitPeriod.DAY
    limit = limits.month or limits.day
    if not limit:
        return None
    used = await tiered_limiter.get_usage(user_id, GAIA_TODO_EXECUTIONS_FEATURE, period)
    return {
        "used": min(used, limit),
        "limit": limit,
        "period": period.value,
        "reset_time": get_reset_time(period).isoformat(),
    }


async def build_today_payload(
    user_id: str, timezone_name: str, user_plan: PlanType
) -> dict[str, Any]:
    tz = ZoneInfo(timezone_name or "UTC")
    start, end = _day_bounds(tz)

    needs_you, in_flight, suggested, your_tasks, done_today, runs = await asyncio.gather(
        _needs_you(user_id),
        _in_flight(user_id),
        _suggested(user_id, start, end),
        _your_tasks(user_id, start, end),
        _done_today(user_id, start, end),
        _runs(user_id, user_plan),
    )

    fallback = _fallback_headline(len(needs_you), len(in_flight), len(done_today))
    headline = await _headline(user_id, tz, fallback)

    return {
        "headline": headline,
        "subline": {
            "date": datetime.now(tz).date().isoformat(),
            "needs_you": len(needs_you),
            "next_event": _next_event(user_id, start, end),
        },
        "runs": runs,
        "needs_you": needs_you,
        "suggested": suggested,
        "in_flight": in_flight,
        "your_tasks": your_tasks,
        "done_today": done_today,
    }
