"""Idle wind-down: pause the whole loop when GAIA has nothing to work on.

An idle day is a daily run that found no tracked work and no goal knowledge — the
engine has nothing legitimate to report. On day IDLE_WARN_DAYS the brief warns
plainly; on day IDLE_DORMANT_DAYS it says goodbye once and the loop goes
dormant: the daily brief and the weekly digest both early-exit before any LLM
call, so a goalless account costs a few Mongo reads a day.

Reactivation is pull-based, checked at run start: any activity the user made on
any surface since dormancy began (users.last_active_at, the one activity record)
wakes the loop on its next run. Only the daily run mutates dormancy state; the
weekly digest reads it. This ladder is about having nothing to report, not about
the user being away; an absent user's briefing workflow is paused by the
user-dormancy sweep instead.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.constants.briefing import IDLE_DORMANT_DAYS, IDLE_WARN_DAYS
from app.db.repositories.users import user_repository
from app.models.user_models import BriefingDormancy, UserDocument
from app.utils.timezone import as_utc

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


async def latest_activity_since(user_id: str, since: datetime) -> datetime | None:
    """Return when the user last acted on any surface, if at/after since; None when not since.

    Read from Mongo, not the cached user, whose last_active_at can be days stale.
    The cutoff must be timezone-aware.
    """
    dates = await user_repository.get_activity_dates(user_id)
    last_active = as_utc(dates.last_active_at) if dates else None
    return last_active if last_active is not None and last_active >= since else None


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
