"""Unified credit metering.

Orchestrates the two credit pools behind a single API:
  * Pool 1 — plan allotment, a resetting day/month counter in Redis (the tiered
    rate limiter).
  * Pool 2 — the persistent top-up wallet, backed by Dodo Credit-Based Billing.

A charge consumes Pool 1 first and overflows into Pool 2. Per-turn totals are
recorded so an errored turn can be refunded (a cancelled turn is not).
"""

import math

from app.api.v1.middleware.tiered_rate_limiter import tiered_limiter
from app.constants.credits import ACTION_CREDIT_COSTS, CREDIT_VALUE_USD
from app.db.redis import redis_cache
from app.models.payment_models import PlanType
from app.services.credits import credit_wallet_service
from shared.py.wide_events import log

_TURN_TTL_SECONDS = 2 * 60 * 60


def usd_to_credits(cost_usd: float) -> int:
    """Convert a raw USD cost to whole credits (1 credit = $0.0001)."""
    return math.ceil(max(0.0, cost_usd) / CREDIT_VALUE_USD)


def _turn_key(thread_id: str, pool: str) -> str:
    return f"credits_turn:{pool}:{thread_id}"


async def get_balance(user_id: str, plan: PlanType) -> dict[str, int]:
    """Return the user's remaining credits across both pools."""
    pool1 = await tiered_limiter.get_pool1_remaining(user_id, plan)
    pool2 = await credit_wallet_service.get_balance(user_id)
    return {"allotment": pool1, "topup": pool2, "total": pool1 + pool2}


async def has_credits(user_id: str, plan: PlanType) -> bool:
    """Whether the user has any credits left (allotment or top-up)."""
    if await tiered_limiter.get_pool1_remaining(user_id, plan) > 0:
        return True
    return await credit_wallet_service.get_balance(user_id) > 0


async def charge(
    user_id: str,
    plan: PlanType,
    amount: int,
    *,
    reason: str,
    thread_id: str | None = None,
) -> tuple[int, int]:
    """Charge ``amount`` credits: plan allotment first, top-up wallet for overflow.

    Returns ``(from_allotment, from_topup)``. Records per-turn totals (keyed by
    ``thread_id``) so the turn can be refunded on error.
    """
    if amount <= 0:
        return (0, 0)
    from_allotment = await tiered_limiter.add_credit_usage(user_id, plan, amount)
    from_topup = 0
    overflow = amount - from_allotment
    if overflow > 0:
        from_topup = await credit_wallet_service.debit(user_id, overflow, reason=reason)

    if thread_id and redis_cache.redis:
        for pool, value in (("p1", from_allotment), ("p2", from_topup)):
            if value > 0:
                key = _turn_key(thread_id, pool)
                await redis_cache.redis.incrby(key, value)
                await redis_cache.redis.expire(key, _TURN_TTL_SECONDS)
    return (from_allotment, from_topup)


async def charge_action(config: dict, action: str) -> None:
    """Charge a fixed-cost non-LLM action (image gen, web search, …) to the
    unified pool, reading user/plan/thread from the agent's ``RunnableConfig``.

    Safe to call from any tool — does nothing if the action has no configured
    cost or the user can't be resolved.
    """
    amount = ACTION_CREDIT_COSTS.get(action, 0)
    if amount <= 0:
        return
    configurable = (config or {}).get("configurable", {}) or {}
    user_id = configurable.get("user_id")
    if not user_id:
        return
    plan = PlanType(configurable.get("plan_type") or PlanType.FREE.value)
    thread_id = str(configurable.get("thread_id") or configurable.get("stream_id") or "unknown")
    from_allotment, from_topup = await charge(
        str(user_id), plan, amount, reason=f"action:{action}", thread_id=thread_id
    )
    log.info(
        "credits_charged",
        credit_event="credits_charged",
        user_id=user_id,
        thread_id=thread_id,
        credits=amount,
        from_allotment=from_allotment,
        from_topup=from_topup,
        action=action,
    )


async def refund_turn(user_id: str, plan: PlanType, thread_id: str) -> int:
    """Refund everything charged during a turn (used when the turn errors)."""
    from_allotment = int(await redis_cache.get(_turn_key(thread_id, "p1")) or 0)
    from_topup = int(await redis_cache.get(_turn_key(thread_id, "p2")) or 0)
    if from_allotment > 0:
        await tiered_limiter.remove_credit_usage(user_id, plan, from_allotment)
    if from_topup > 0:
        await credit_wallet_service.credit_back(
            user_id, from_topup, reason=f"refund:error:{thread_id}"
        )
    await finalize_turn(thread_id)
    refunded = from_allotment + from_topup
    if refunded:
        log.info(f"Refunded {refunded} credits to {user_id} for errored turn {thread_id}")
    return refunded


async def finalize_turn(thread_id: str) -> None:
    """Drop the per-turn accumulator (charge stands — success or cancellation)."""
    if redis_cache.redis:
        await redis_cache.redis.delete(_turn_key(thread_id, "p1"), _turn_key(thread_id, "p2"))
