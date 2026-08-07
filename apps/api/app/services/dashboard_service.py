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
from app.constants.todos import GAIA_TODO_EXECUTIONS_FEATURE
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.todos import todo_repository
from app.models.payment_models import PlanType
from app.models.todo_models import TodoDocument
from app.services.calendar_service import fetch_calendar_events
from shared.py.wide_events import log

_SECTION_LIMIT = 25


def _day_bounds(tz: ZoneInfo) -> tuple[datetime, datetime]:
    today = datetime.now(tz).date()
    start = datetime.combine(today, time.min, tzinfo=tz)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _base_item(doc: TodoDocument) -> dict[str, Any]:
    return {
        "todo_id": doc.id,
        "title": doc.title or "untitled",
        "serves": doc.serves,
    }


async def _needs_you(user_id: str) -> list[dict[str, Any]]:
    docs = await todo_repository.list_needs_you(user_id, limit=_SECTION_LIMIT)
    return [
        {
            **_base_item(doc),
            "execution_status": doc.execution_status.value if doc.execution_status else None,
            "blocker_question": doc.blocker_question,
            "conversation_id": doc.last_run_conversation_id,
        }
        for doc in docs
    ]


async def _in_flight(user_id: str) -> list[dict[str, Any]]:
    docs = await todo_repository.list_in_flight(user_id, limit=_SECTION_LIMIT)
    return [
        {
            **_base_item(doc),
            "execution_status": doc.execution_status.value if doc.execution_status else None,
            "started_at": _iso(doc.scheduled_at),
            "conversation_id": doc.last_run_conversation_id,
        }
        for doc in docs
    ]


async def _suggested(user_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    # Due-today todos already render in "Your tasks" (with the offer tag), so
    # this section only surfaces offers the day view would otherwise miss.
    docs = await todo_repository.list_suggested_offers(
        user_id, day_start=start, day_end=end, limit=_SECTION_LIMIT
    )
    return [{**_base_item(doc), "gaia_offer": doc.gaia_offer} for doc in docs]


async def _your_tasks(user_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    # Deadline-only on purpose: a scheduled_at is GAIA's plumbing, a due_date
    # is the user's own commitment for the day.
    docs = await todo_repository.list_due_today(
        user_id, day_start=start, day_end=end, limit=_SECTION_LIMIT
    )
    return [
        {
            **_base_item(doc),
            "due_at": _iso(doc.due_date or doc.scheduled_at),
            # A dismissed offer keeps the task but drops its handoff tag.
            "gaia_offer": None if doc.gaia_offer_dismissed else doc.gaia_offer,
        }
        for doc in docs
    ]


async def _done_today(user_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    docs = await todo_repository.list_completed_today(
        user_id, day_start=start, day_end=end, limit=_SECTION_LIMIT
    )
    return [
        {
            **_base_item(doc),
            "completed_at": _iso(doc.completed_at),
            "assignee": doc.assignee,
            "conversation_id": doc.last_run_conversation_id,
        }
        for doc in docs
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
    briefing = await briefing_repository.get_latest(user_id)
    if briefing and briefing.date == now_local.date().isoformat() and briefing.payload.headline:
        return briefing.payload.headline
    return fallback


async def _next_event(user_id: str, end: datetime) -> dict[str, Any] | None:
    """First calendar event still ahead today; an outage degrades to None."""
    try:
        data = await fetch_calendar_events(
            "primary",
            user_id,
            time_min=datetime.now(UTC).isoformat(),
            time_max=end.isoformat(),
            max_results=5,
        )
    except Exception as e:
        log.warning("dashboard.calendar_fetch_failed", user_id=user_id, error=str(e))
        return None
    for ev in data.items:
        start = ev.start
        when = start.dateTime if start and start.dateTime else (start.date if start else None)
        if when:
            return {"time": when, "title": ev.summary or "(no title)"}
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

    (
        needs_you,
        in_flight,
        suggested,
        your_tasks,
        done_today,
        runs,
        next_event,
    ) = await asyncio.gather(
        _needs_you(user_id),
        _in_flight(user_id),
        _suggested(user_id, start, end),
        _your_tasks(user_id, start, end),
        _done_today(user_id, start, end),
        _runs(user_id, user_plan),
        _next_event(user_id, end),
    )

    fallback = _fallback_headline(len(needs_you), len(in_flight), len(done_today))
    headline = await _headline(user_id, tz, fallback)

    return {
        "headline": headline,
        "subline": {
            "date": datetime.now(tz).date().isoformat(),
            "needs_you": len(needs_you),
            "next_event": next_event,
        },
        "runs": runs,
        "needs_you": needs_you,
        "suggested": suggested,
        "in_flight": in_flight,
        "your_tasks": your_tasks,
        "done_today": done_today,
    }
