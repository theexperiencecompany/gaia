"""Idle wind-down: pause the whole loop when GAIA has nothing to work on.

An idle day is a daily run that found no goal lanes and no goal knowledge — the
engine has nothing legitimate to advance. On day IDLE_WARN_DAYS the brief warns
plainly; on day IDLE_DORMANT_DAYS it says goodbye once and the loop goes
dormant: the daily brief, the night shift, and the weekly digest all early-exit
before any LLM call, so a goalless account costs a few Mongo reads a day.

Reactivation is pull-based, checked at run start (no hooks in the chat or todo
paths): a goal created, any authenticated activity, or any user message in any
conversation since dormancy began wakes the loop on its next run. Only the
daily run mutates dormancy state; the night shift and weekly digest read it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.constants.briefing import IDLE_DORMANT_DAYS, IDLE_WARN_DAYS
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.users import user_repository

# Marker on the user doc:
# {"idle_days": int, "date": "YYYY-MM-DD", "dormant_since": datetime | None}.
DORMANCY_FIELD = "briefing_dormancy"

WIND_DOWN_WARN = "warn"
WIND_DOWN_FINAL = "final"


@dataclass
class DormancyState:
    idle_days: int
    date: str | None
    dormant_since: datetime | None


def state_from_user(user: dict) -> DormancyState:
    marker = user.get(DORMANCY_FIELD) or {}
    since = marker.get("dormant_since")
    if isinstance(since, datetime):
        # Mongo returns naive UTC datetimes; normalize before comparing.
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
    else:
        since = None
    return DormancyState(
        idle_days=int(marker.get("idle_days", 0)),
        date=marker.get("date"),
        dormant_since=since,
    )


def wind_down_stage(idle_days: int) -> str | None:
    if idle_days >= IDLE_DORMANT_DAYS:
        return WIND_DOWN_FINAL
    if idle_days == IDLE_WARN_DAYS:
        return WIND_DOWN_WARN
    return None


async def reactivation_signal_since(user_id: str, since: datetime) -> bool:
    """True when the user did anything since ``since`` that should wake the loop.

    This is the canonical "the user was active since T" predicate: a goal created,
    authenticated activity (``last_active_at``), or any user message in any
    conversation. Shared by the dormancy ladder (wake a paused loop) and winback
    acknowledgement (``context.compute_winback_state``) so the two never diverge on
    what counts as the user showing up. ``since`` must be timezone-aware.
    """
    if await todo_repository.has_goal_created_since(user_id, since=since):
        return True

    last_active = await user_repository.get_last_active_at(user_id)
    if isinstance(last_active, datetime):
        if last_active.tzinfo is None:
            last_active = last_active.replace(tzinfo=UTC)
        if last_active >= since:
            return True

    # Bot turns don't pass the web auth middleware that bumps last_active_at, so
    # a Telegram reply is detected from the conversation record directly.
    return await conversation_repository.has_user_message_since(user_id, since)


async def record_idle_day(user_id: str, prior: DormancyState, idle: bool, date_str: str) -> int:
    """Persist today's idle/active outcome; returns the consecutive idle count.

    Same-day reruns don't double-count (the one-brief-per-day law applies to the
    ladder too), and an active day for a user with no marker writes nothing.
    """
    if prior.date == date_str:
        return prior.idle_days
    if not idle and prior.idle_days == 0 and prior.date is None:
        return 0
    idle_days = prior.idle_days + 1 if idle else 0
    await user_repository.set_dormancy_day(user_id, idle_days=idle_days, date_str=date_str)
    return idle_days


async def enter_dormancy(user_id: str) -> None:
    await user_repository.enter_briefing_dormancy(user_id)


async def clear_dormancy(user_id: str) -> None:
    await user_repository.clear_briefing_dormancy(user_id)
