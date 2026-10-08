"""Per-token call budgets for sandbox-to-GAIA endpoints, in Redis so every replica enforces one.

A total cap per token (its counter outlives the token, so it never resets
mid-run) and a per-minute cap: the wall a runaway or injected script hits.
"""

from dataclasses import dataclass
import time

from app.db.redis import redis_cache
from app.utils.errors import AppError

# Per-minute bucket TTL: two minutes, so a burst straddling a minute boundary
# counts against one window instead of resetting early.
RATE_BUCKET_TTL_SECONDS = 120


@dataclass(frozen=True)
class TokenBudget:
    """One endpoint's limits and the words its 429s use."""

    key_prefix: str
    max_calls: int
    max_per_minute: int
    window_seconds: int
    exhausted_message: str
    exhausted_fix: str
    rate_message: str
    rate_fix: str


async def enforce_token_budget(budget: TokenBudget, run_id: str) -> None:
    """Count one call against run_id's budget; raise 429 past the total or the per-minute cap."""
    total_key = f"{budget.key_prefix}:calls:{run_id}"
    total = await redis_cache.client.incr(total_key)
    if total == 1:
        await redis_cache.client.expire(total_key, budget.window_seconds)
    if total > budget.max_calls:
        raise AppError(
            message=budget.exhausted_message,
            why=f"more than {budget.max_calls} calls on one token",
            fix=budget.exhausted_fix,
            status_code=429,
        )
    minute_key = f"{budget.key_prefix}:rate:{run_id}:{int(time.time()) // 60}"
    rate = await redis_cache.client.incr(minute_key)
    if rate == 1:
        await redis_cache.client.expire(minute_key, RATE_BUCKET_TTL_SECONDS)
    if rate > budget.max_per_minute:
        raise AppError(
            message=budget.rate_message,
            why=f"more than {budget.max_per_minute} calls in one minute",
            fix=budget.rate_fix,
            status_code=429,
        )
