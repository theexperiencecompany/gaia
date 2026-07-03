"""Completed-work aggregation — the single source for streak + heatmap.

Everything here derives from ``completed_at`` only: a day is green iff at least
one todo (either assignee) completed that day in the user's timezone. Heartbeat
activity (sweeps, syncs) never has a ``completed_at`` and so never counts — gray
days stay honest, and there is no mechanism to pad or repair a streak. Both the
dashboard heatmap endpoint and the briefing engine consume these helpers so the
two surfaces can never disagree.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.constants.todos import ASSIGNEE_GAIA, GAIA_TRACKED_LABEL
from app.db.mongodb.collections import todos_collection

# date-iso -> {"user_count": n, "gaia_count": n}
DayCounts = dict[str, dict[str, int]]

# Default streak lookback — long enough to cover the 30-day badge with headroom.
DEFAULT_STREAK_LOOKBACK_DAYS = 366


def _is_gaia(doc: dict) -> bool:
    # Dual-read during the migration window (assignee field OR legacy label).
    return doc.get("assignee") == ASSIGNEE_GAIA or GAIA_TRACKED_LABEL in doc.get("labels", [])


def window_start_utc(tz: ZoneInfo, days: int) -> datetime:
    """UTC start of the local day ``days-1`` days before today (inclusive window)."""
    today = datetime.now(tz).date()
    return datetime.combine(today - timedelta(days=days - 1), time.min, tzinfo=tz).astimezone(UTC)


async def completed_day_counts(user_id: str, tz: ZoneInfo, since: datetime) -> DayCounts:
    """Per-local-day completed-todo counts split by assignee, since ``since`` (UTC)."""
    counts: DayCounts = {}
    cursor = todos_collection.find(
        {"user_id": user_id, "completed_at": {"$gte": since}},
        {"completed_at": 1, "assignee": 1, "labels": 1},
    )
    async for doc in cursor:
        day = doc["completed_at"].astimezone(tz).date().isoformat()
        bucket = counts.setdefault(day, {"user_count": 0, "gaia_count": 0})
        bucket["gaia_count" if _is_gaia(doc) else "user_count"] += 1
    return counts


def streak_from_counts(counts: DayCounts, today: date, max_days: int) -> int:
    """Consecutive days (ending today) with >=1 completion. Empty today is grace.

    An empty *today* does not break the streak (the day isn't over); any earlier
    empty day does. Mirrors the heatmap's honest-streak rule exactly.
    """
    streak = 0
    for offset in range(max_days):
        bucket = counts.get((today - timedelta(days=offset)).isoformat())
        if bucket and (bucket["user_count"] + bucket["gaia_count"]) > 0:
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
