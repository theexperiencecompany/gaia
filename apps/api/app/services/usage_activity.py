"""Daily activity rollup for the usage heatmap.

One document per user per UTC day in the ``usage_daily`` collection
(``{user_id, date, count}``), incremented on every metered action — so the
year contribution grid and the percentile badge are backed by durable Mongo
data, not the short-lived Redis rate-limit counters.
"""

from datetime import UTC, datetime, timedelta
import json
from typing import NamedTuple, cast

from pymongo.errors import PyMongoError

from app.config.rate_limits import FEATURE_LIMITS
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.db.repositories.usage_daily import UsageDailyIncrement, usage_daily_repository
from app.db.repositories.users import user_repository
from app.models.user_models import UserDocument
from app.schemas.usage import ActivityDay, UsageActivityResponse
from app.services.email import send_badge_earned_email
from shared.py.wide_events import log

_THRESHOLDS_KEY = "usage:activity_pct_thresholds"
_THRESHOLDS_TTL = 86_400  # recompute the cross-user distribution at most daily
_PERCENTILE_WINDOW_DAYS = 30

# Badge tiers, weakest → strongest. Order doubles as the promotion ranking:
# a user is only ever "promoted" to a tier later in this tuple.
TIER_KEYS: tuple[str, ...] = ("bronze", "silver", "gold", "diamond")


class _TierMeta(NamedTuple):
    threshold_key: str  # key into the cached thresholds dict
    percentile: float  # value the API reports for the earned tier
    top_label: str  # user-facing "top X%" wording


_TIER_META: dict[str, _TierMeta] = {
    "diamond": _TierMeta("p999", 99.9, "0.1%"),
    "gold": _TierMeta("p99", 99.0, "1%"),
    "silver": _TierMeta("p90", 90.0, "10%"),
    "bronze": _TierMeta("p75", 75.0, "25%"),
}


def _tier_for_total(total: int, thresholds: dict[str, float]) -> str | None:
    """The strongest tier a 30-day total qualifies for, or None."""
    for tier in reversed(TIER_KEYS):
        if total >= thresholds[_TIER_META[tier].threshold_key]:
            return tier
    return None


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
        await usage_daily_repository.increment(
            user_id, _day(datetime.now(UTC)), UsageDailyIncrement(count=amount)
        )
    except PyMongoError as e:
        log.warning(
            f"{LogTag.MONGO} record_activity failed",
            user={"id": user_id},
            error=str(e),
            error_type=type(e).__name__,
        )


async def record_cost(user_id: str, spend: UsageDailyIncrement, *, charged: bool = True) -> None:
    """Add real LLM spend and its token counts to today's durable rollup. Never raises.

    Redis cost windows expire in ~26h, so this is the ONLY per-day cost
    history — it's what lets usage charts show cost-based (nearest-wall)
    percentages for past days instead of message counts alone. The token
    counts land in the same write so a mispriced call can be re-derived from
    raw usage later, instead of only the dollar amount surviving — including
    when pricing itself failed and ``spend.cost`` is 0 for a call that still
    burned real tokens.

    ``spend`` carries the dollar figure and the four token counts (see
    :class:`UsageDailyIncrement`). ``charged=False`` books everything under the
    ``aux_*`` fields instead:
    auxiliary background work (memory pipeline, onboarding, workflow
    generation, …) is tracked for per-user COGS but never counts against the
    user's allowance, so ``cost``/``input_tokens``/etc. stay an exact durable
    mirror of the Redis windows the budget wall enforces.
    """
    if not user_id:
        return
    has_tokens = bool(
        spend.input_tokens or spend.output_tokens or spend.cached_tokens or spend.reasoning_tokens
    )
    if spend.cost <= 0 and not has_tokens:
        return
    try:
        await usage_daily_repository.increment(
            user_id, _day(datetime.now(UTC)), spend, charged=charged
        )
    except PyMongoError as e:
        log.warning(
            f"{LogTag.MONGO} record_cost failed",
            user={"id": user_id},
            error=str(e),
            error_type=type(e).__name__,
        )


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


async def get_activity(user_id: str, days: int) -> UsageActivityResponse:
    """Trailing ``days`` of daily counts and tokens, plus streak, percentile, and tier."""
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days - 1)

    # NOTE: usage_daily docs also carry a durable per-day `cost` (see
    # record_cost) — deliberately NOT exposed here. Raw USD never goes to the
    # client (see get_budget_status); tokens do go out, because they are a
    # capability number the user already sees, not our per-request COGS.
    rows = await usage_daily_repository.rollups_since(user_id, _day(start))
    by_day = {row.date: row for row in rows}
    counts = {date: row.count for date, row in by_day.items()}

    day_list: list[ActivityDay] = []
    total = 0
    total_tokens = 0
    cursor = start
    while cursor <= end:
        key = _day(cursor)
        row = by_day.get(key)
        c = row.count if row else 0
        tokens = (row.input_tokens + row.output_tokens) if row else 0
        total += c
        total_tokens += tokens
        day_list.append(
            ActivityDay(
                date=key,
                count=c,
                tokens=tokens,
                input_tokens=row.input_tokens if row else 0,
                output_tokens=row.output_tokens if row else 0,
                cached_tokens=row.cached_tokens if row else 0,
                reasoning_tokens=row.reasoning_tokens if row else 0,
            )
        )
        cursor += timedelta(days=1)

    # Reuse the already-loaded window for the percentile total instead of a
    # second find over the same rows — valid whenever this window fully covers
    # the trailing 30 days (i.e. start is on or before window_start). Short
    # windows (days <= 30) don't, so _percentile_tier reads it itself.
    window_start = _percentile_window_start()
    mine = (
        sum(c for d, c in counts.items() if d >= window_start)
        if _day(start) <= window_start
        else None
    )
    percentile, tier = await _percentile_tier(user_id, window_start, mine)
    return UsageActivityResponse(
        days=day_list,
        total=total,
        total_tokens=total_tokens,
        streak=_current_streak(counts, end),
        percentile=percentile,
        tier=tier,
    )


def _percentile_window_start() -> str:
    """First UTC day (inclusive) of the cross-user percentile comparison window.

    Mongo matches this boundary with an inclusive ``$gte``, so the window spans
    exactly ``_PERCENTILE_WINDOW_DAYS`` calendar days (today plus the prior
    ``_PERCENTILE_WINDOW_DAYS - 1``) — subtracting the full count would include
    one extra day.
    """
    return _day(datetime.now(UTC) - timedelta(days=_PERCENTILE_WINDOW_DAYS - 1))


async def _percentile_tier(
    user_id: str, window_start: str, mine: int | None
) -> tuple[float | None, str | None]:
    """The user's activity percentile vs all users, and the badge tier it earns.

    Compares the user's 30-day total against cross-user thresholds that are
    recomputed at most once a day (cached in Redis). ``mine`` is that total when
    the caller already has the window's rows loaded; pass None and it's read
    here — either way the per-request cost is just the user's own recent rows.
    """
    if mine is None:
        mine = sum((await usage_daily_repository.counts_since(user_id, window_start)).values())
    if mine <= 0:
        return None, None

    thresholds = await _percentile_thresholds(window_start)
    if not thresholds:
        return None, None
    tier = _tier_for_total(mine, thresholds)
    if tier is None:
        return None, None
    return _TIER_META[tier].percentile, tier


# RANK-based cutoffs (top-X% fractions, keyed by the cached threshold): the
# tier means "you are in the top X% of USERS", not "your total clears a value
# quantile". Value quantiles break under heavy skew — one whale stretches the
# p99 value past every other user, so the #2 most active user of hundreds would
# rank below gold. Sorting totals descending and reading the value at each
# top-X% rank position is robust to that.
_TIER_RANK_FRACTIONS: dict[str, float] = {
    "p999": 0.001,
    "p99": 0.01,
    "p90": 0.10,
    "p75": 0.25,
}


async def _percentile_thresholds(window_start: str) -> dict[str, float]:
    client = redis_cache.redis
    if client is not None:
        cached = await client.get(_THRESHOLDS_KEY)
        if cached:
            return cast(dict[str, float], json.loads(cached))

    thresholds = await usage_daily_repository.rank_thresholds(window_start, _TIER_RANK_FRACTIONS)
    if thresholds and client is not None:
        await client.setex(_THRESHOLDS_KEY, _THRESHOLDS_TTL, json.dumps(thresholds))
    return thresholds


async def _record_tier(user_id: str, tier: str) -> UserDocument | None:
    """Persist ``tier`` as the user's highest ever reached; return the user doc
    only on a FIRST-TIME promotion, else None.

    The guard is monotonic — a stored tier is only ever replaced by a stronger
    one — so downgrades are silent and re-crossing a boundary can never re-fire.
    The filtered update is also the idempotency lock: a retried job matches zero
    documents the second time. Non-ObjectId user_ids are skipped inside the
    repository (id encoding is its concern).
    """
    lower_tiers = list(TIER_KEYS[: TIER_KEYS.index(tier)])
    return await user_repository.record_activity_tier_promotion(user_id, tier, lower_tiers)


async def sync_activity_tiers(send_emails: bool = True) -> dict[str, int]:
    """Recompute every active user's badge tier and record first-time promotions.

    One aggregation pass over the trailing-30-day rollups (the same data and
    thresholds the usage page badge reads, so email and page always agree),
    then a guarded update per qualifying user. With ``send_emails`` each
    first-time promotion also gets the congratulations email — the promotion
    is recorded BEFORE sending, so a failed send is at most a lost email,
    never a duplicate one.

    ``send_emails=False`` seeds tiers silently — used by the deploy-day
    backfill so existing users' current standing doesn't trigger a mass blast;
    only promotions earned after that are emailed.
    """
    window_start = _percentile_window_start()
    thresholds = await _percentile_thresholds(window_start)
    stats = {"scanned": 0, "promoted": 0, "emailed": 0}
    if not thresholds:
        return stats

    for user_id, total in await usage_daily_repository.user_window_totals(window_start):
        stats["scanned"] += 1
        tier = _tier_for_total(total, thresholds)
        if tier is None:
            continue
        user = await _record_tier(user_id, tier)
        if user is None:
            continue
        stats["promoted"] += 1
        if not send_emails or not user.email:
            continue
        try:
            await send_badge_earned_email(
                user_email=user.email,
                user_name=user.name,
                tier=tier,
                top_label=_TIER_META[tier].top_label,
            )
            stats["emailed"] += 1
        except Exception as e:
            # One bounced address must not abort the whole sweep; the tier is
            # already recorded, so this user simply misses the (nice-to-have)
            # email rather than risking a duplicate on retry.
            log.error(
                f"{LogTag.MAIL} badge email failed",
                user={"id": user.id},
                tier=tier,
                error=str(e),
                error_type=type(e).__name__,
            )
    return stats
