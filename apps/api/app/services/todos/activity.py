"""Completed-work aggregation — the single source for the streak.

Everything here derives from ``completed_at`` only. The streak counts a day iff
the *user* completed at least one todo that day in their timezone: GAIA's night
shift completes its own todos autonomously, so counting those would let GAIA pad
the user's streak. ``DayCounts`` still carries ``gaia_count`` for display copy
(the weekly digest narrates GAIA's work), but only ``user_count`` advances the
streak. Heartbeat activity (sweeps, syncs) never has a ``completed_at`` and so
never counts — gray days stay honest, and there is no mechanism to pad or repair a
streak. The briefing engine and badges consume these helpers so no two surfaces
can disagree.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.constants.todos import ASSIGNEE_GAIA
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoDocument

# date-iso -> {"user_count": n, "gaia_count": n}
DayCounts = dict[str, dict[str, int]]

# Default streak lookback — long enough to cover the 30-day badge with headroom.
DEFAULT_STREAK_LOOKBACK_DAYS = 366


def _is_gaia(doc: TodoDocument) -> bool:
    return doc.assignee == ASSIGNEE_GAIA


def window_start_utc(tz: ZoneInfo, days: int) -> datetime:
    """UTC start of the local day ``days-1`` days before today (inclusive window)."""
    today = datetime.now(tz).date()
    return datetime.combine(today - timedelta(days=days - 1), time.min, tzinfo=tz).astimezone(UTC)


async def completed_day_counts(user_id: str, tz: ZoneInfo, since: datetime) -> DayCounts:
    """Per-local-day completed-todo counts split by assignee, since ``since`` (UTC)."""
    counts: DayCounts = {}
    docs = await todo_repository.list_completed_since(user_id, since=since)
    for doc in docs:
        if doc.completed_at is None:
            continue
        day = doc.completed_at.astimezone(tz).date().isoformat()
        bucket = counts.setdefault(day, {"user_count": 0, "gaia_count": 0})
        bucket["gaia_count" if _is_gaia(doc) else "user_count"] += 1
    return counts


def streak_from_counts(counts: DayCounts, today: date, max_days: int) -> int:
    """Consecutive days (ending today) with >=1 user completion. Empty today is grace.

    Only the user's own completions count — GAIA's autonomous night-shift work
    never advances the streak. An empty *today* does not break the streak (the day
    isn't over); any earlier empty day does.
    """
    streak = 0
    for offset in range(max_days):
        bucket = counts.get((today - timedelta(days=offset)).isoformat())
        if bucket and bucket["user_count"] > 0:
            streak += 1
        elif offset == 0:
            continue
        else:
            break
    return streak


async def compute_streak(
    user_id: str, tz: ZoneInfo, lookback_days: int = DEFAULT_STREAK_LOOKBACK_DAYS
) -> int:
    """Current honest streak length for the user, in their timezone."""
    counts = await completed_day_counts(user_id, tz, window_start_utc(tz, lookback_days))
    return streak_from_counts(counts, datetime.now(tz).date(), lookback_days)
