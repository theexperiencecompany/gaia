"""Idle wind-down: pause the whole loop when GAIA has nothing to work on.

An idle day is a daily run that found no tracked work and no goal knowledge — the
engine has nothing legitimate to report. On day IDLE_WARN_DAYS the brief warns
plainly; on day IDLE_DORMANT_DAYS it says goodbye once and the loop goes
dormant: the daily brief and the weekly digest both early-exit before any LLM
call, so a goalless account costs a few Mongo reads a day.

Reactivation is pull-based, checked at run start (no hooks in the chat or todo
paths): any authenticated activity or any user message in any conversation since
dormancy began wakes the loop on its next run. Only the daily run mutates
dormancy state; the weekly digest reads it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.constants.briefing import IDLE_DORMANT_DAYS, IDLE_WARN_DAYS
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.users import user_repository
from app.models.user_models import BriefingDormancy, UserDocument

WIND_DOWN_WARN = "warn"
WIND_DOWN_FINAL = "final"


@dataclass
class DormancyState:
    idle_days: int
    date: str | None
    dormant_since: datetime | None


def state_from_user(user: UserDocument) -> DormancyState:
    marker = user.briefing_dormancy or BriefingDormancy()
    since = marker.dormant_since
    # Mongo returns naive UTC datetimes; normalize before comparing.
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return DormancyState(idle_days=marker.idle_days, date=marker.date, dormant_since=since)


def wind_down_stage(idle_days: int) -> str | None:
    if idle_days >= IDLE_DORMANT_DAYS:
        return WIND_DOWN_FINAL
    if idle_days == IDLE_WARN_DAYS:
        return WIND_DOWN_WARN
    return None


async def latest_activity_since(user: UserDocument, since: datetime) -> datetime | None:
    """Return when the user was last active, if at/after the cutoff; None when not since.

    The canonical "user was active since T" read: last_active_at on the loaded user
    document or any user message in any conversation. Read once per run and compared
    against every cutoff (the dormancy ladder, winback acknowledgement in
    context.compute_winback_state). The cutoff must be timezone-aware.
    """
    last_active = user.last_active_at
    if last_active is not None and last_active.tzinfo is None:
        last_active = last_active.replace(tzinfo=UTC)
    # Bot turns don't pass the web auth middleware that bumps last_active_at, so
    # a Telegram reply is detected from the conversation record directly.
    last_message = await conversation_repository.latest_user_message_since(user.id, since)
    seen = [t for t in (last_active, last_message) if t is not None and t >= since]
    return max(seen, default=None)


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
