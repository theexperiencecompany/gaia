"""Daily activity rollup for the usage heatmap.

One document per user per UTC day in the ``usage_daily`` collection
(``{user_id, date, count}``), incremented on every metered action — so the
year contribution grid and the percentile badge are backed by durable Mongo
data, not the short-lived Redis rate-limit counters.
"""

from datetime import UTC, datetime, timedelta
import json
import math
from typing import Any

from app.config.rate_limits import FEATURE_LIMITS
from app.constants.log_tags import LogTag
from app.db.mongodb.collections import usage_daily_collection
from app.db.redis import redis_cache
from shared.py.wide_events import log

_THRESHOLDS_KEY = "usage:activity_pct_thresholds"
_THRESHOLDS_TTL = 86_400  # recompute the cross-user distribution at most daily
_PERCENTILE_WINDOW_DAYS = 30


def counts_as_activity(feature_key: str) -> bool:
    """Whether a metered feature call registers on the activity heatmap. The
    policy lives on the feature definition (``TieredRateLimits.counts_as_activity``)
    so there is a single source of truth alongside the limits themselves."""
    limits = FEATURE_LIMITS.get(feature_key)
    return limits.counts_as_activity if limits else True


def _day(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


async def record_activity(user_id: str, amount: int = 1) -> None:
    """Add to today's action count for a user. Fire-and-forget; never raises."""
    if not user_id or amount <= 0:
        return
    try:
        await usage_daily_collection.update_one(
            {"user_id": user_id, "date": _day(datetime.now(UTC))},
            {"$inc": {"count": amount}},
            upsert=True,
        )
    except Exception as e:
        log.warning(f"{LogTag.MONGO} record_activity failed for {user_id}: {e}")


async def record_cost(user_id: str, cost_usd: float) -> None:
    """Add real LLM spend to today's durable rollup. Never raises.

    Redis cost windows expire in ~26h, so this is the ONLY per-day cost
    history — it's what lets usage charts show cost-based (nearest-wall)
    percentages for past days instead of message counts alone.
    """
    if not user_id or cost_usd <= 0:
        return
    try:
        await usage_daily_collection.update_one(
            {"user_id": user_id, "date": _day(datetime.now(UTC))},
            {"$inc": {"cost": cost_usd}},
            upsert=True,
        )
    except Exception as e:
        log.warning(f"{LogTag.MONGO} record_cost failed for {user_id}: {e}")


def _current_streak(counts: dict[str, int], end: datetime) -> int:
    """Consecutive active days ending now. "Streak" reads as momentum, so a
    long run that ended months ago must show 0, not its historical length.
    Today not being active yet doesn't break the run — count from yesterday."""
    cursor = end
    if counts.get(_day(cursor), 0) <= 0:
        cursor -= timedelta(days=1)
    streak = 0
    while counts.get(_day(cursor), 0) > 0:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


async def get_activity(user_id: str, days: int) -> dict[str, Any]:
    """Trailing ``days`` of daily counts plus total, streak, percentile, and tier."""
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days - 1)

    # NOTE: usage_daily docs also carry a durable per-day `cost` (see
    # record_cost) — deliberately NOT exposed here. Raw USD never goes to the
    # client (see get_budget_status); the cost history exists so charts can be
    # served as percentage-of-allowance once that representation lands.
    counts: dict[str, int] = {}
    async for doc in usage_daily_collection.find(
        {"user_id": user_id, "date": {"$gte": _day(start)}},
        {"date": 1, "count": 1},
    ):
        counts[doc["date"]] = int(doc.get("count", 0))

    day_list: list[dict[str, Any]] = []
    total = 0
    cursor = start
    while cursor <= end:
        c = counts.get(_day(cursor), 0)
        total += c
        day_list.append({"date": _day(cursor), "count": c})
        cursor += timedelta(days=1)

    percentile, tier = await _percentile_tier(user_id)
    return {
        "days": day_list,
        "total": total,
        "streak": _current_streak(counts, end),
        "percentile": percentile,
        "tier": tier,
    }


async def _percentile_tier(user_id: str) -> tuple[float | None, str | None]:
    """The user's activity percentile vs all users, and the badge tier it earns.

    Compares the user's 30-day total against cross-user thresholds that are
    recomputed at most once a day (cached in Redis), so the per-request cost is
    just reading the user's own recent rows.
    """
    window_start = _day(datetime.now(UTC) - timedelta(days=_PERCENTILE_WINDOW_DAYS))
    mine = 0
    async for doc in usage_daily_collection.find(
        {"user_id": user_id, "date": {"$gte": window_start}}, {"count": 1}
    ):
        mine += int(doc.get("count", 0))
    if mine <= 0:
        return None, None

    thresholds = await _percentile_thresholds(window_start)
    if not thresholds:
        return None, None
    if mine >= thresholds["p999"]:
        return 99.9, "diamond"
    if mine >= thresholds["p99"]:
        return 99.0, "gold"
    if mine >= thresholds["p90"]:
        return 90.0, "silver"
    if mine >= thresholds["p75"]:
        return 75.0, "bronze"
    return None, None


async def _percentile_thresholds(window_start: str) -> dict[str, float]:
    client = redis_cache.redis
    if client is not None:
        cached = await client.get(_THRESHOLDS_KEY)
        if cached:
            return json.loads(cached)

    # RANK-based cutoffs, computed server-side in one sorted pass: the tier
    # means "you are in the top X% of USERS", not "your total clears a value
    # quantile". Value quantiles break under heavy skew — one whale stretches
    # the p99 value past every other user, so the #2 most active user of
    # hundreds would rank below gold. Sorting totals descending and reading
    # the value at each top-X% rank position is robust to that, and nothing
    # is transferred to app memory.
    n_docs = [
        d
        async for d in usage_daily_collection.aggregate(
            [
                {"$match": {"date": {"$gte": window_start}}},
                {"$group": {"_id": "$user_id"}},
                {"$count": "n"},
            ]
        )
    ]
    if not n_docs:
        return {}
    n = int(n_docs[0]["n"])

    def _rank_index(top_fraction: float) -> int:
        """0-based sorted-desc index of the last user inside the top X%."""
        return max(0, math.ceil(top_fraction * n) - 1)

    rank_indexes = {
        "p999": _rank_index(0.001),
        "p99": _rank_index(0.01),
        "p90": _rank_index(0.10),
        "p75": _rank_index(0.25),
    }
    results = [
        d
        async for d in usage_daily_collection.aggregate(
            [
                {"$match": {"date": {"$gte": window_start}}},
                {"$group": {"_id": "$user_id", "total": {"$sum": "$count"}}},
                {"$sort": {"total": -1}},
                {
                    "$facet": {
                        key: [{"$skip": idx}, {"$limit": 1}, {"$project": {"total": 1}}]
                        for key, idx in rank_indexes.items()
                    }
                },
            ]
        )
    ]
    if not results:
        return {}
    facets = results[0]
    thresholds = {
        key: float(facets[key][0]["total"]) if facets[key] else 0.0 for key in rank_indexes
    }
    if client is not None:
        await client.setex(_THRESHOLDS_KEY, _THRESHOLDS_TTL, json.dumps(thresholds))
    return thresholds
