"""Rolling daily + monthly USD cost budgets for tier enforcement.

Day and month Redis keys accumulate real LLM USD cost per user. Writers and
readers:

- ``LLMAccountingMiddleware.aafter_model`` increments both windows after every
  model call (the single seam every execution path passes through — chat,
  workflows, bots, voice, subagents).
- The chat endpoint checks the daily window BEFORE running the agent (429 wall).
- ``LLMAccountingMiddleware.awrap_model_call`` checks the daily window and the
  per-request token ceiling as the unbypassable backstop; the monthly window
  drives the pro model degrade in ``apply_plan_model``.

Follows the RedisCache degradation philosophy: when Redis is unavailable these
helpers warn and no-op (enforcement fails open; startup ``verify_connection``
is what fails hard in production).
"""

import asyncio
from collections.abc import Awaitable
from typing import Any

from app.config.rate_limits import (
    RateLimitPeriod,
    get_daily_cost_budget_usd,
    get_per_request_token_ceiling,
    get_reset_time,
    get_time_window_key,
)
from app.constants.llm import (
    DAILY_BUDGET_TTL_SECONDS,
    MONTHLY_BUDGET_TTL_SECONDS,
    PRO_MONTHLY_COST_BUDGET_USD,
    REQUEST_TOKEN_COUNTER_TTL_SECONDS,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.payment_models import PlanType
from app.services.usage_activity import record_cost
from shared.py.wide_events import log

_BUDGET_KEY = "cost_budget:{user_id}:{period}:{window}"
_REQUEST_TOKENS_KEY = "req_tokens:{root_request_id}"

_PERIOD_TTL_SECONDS = {
    RateLimitPeriod.DAY: DAILY_BUDGET_TTL_SECONDS,
    RateLimitPeriod.MONTH: MONTHLY_BUDGET_TTL_SECONDS,
}

# User-facing stop texts returned as the final assistant message when a run is
# halted mid-flight. The free variants carry the upgrade CTA; pro budgets are
# abuse guards, so their copy stays neutral.
DAILY_BUDGET_STOP_FREE = (
    "You've reached today's usage limit on the free plan. "
    "Your limit resets tomorrow — or upgrade to Pro for much higher limits."
)
DAILY_BUDGET_STOP_PRO = (
    "You've reached today's usage limit. It resets tomorrow — "
    "contact support if you keep hitting this."
)
REQUEST_CEILING_STOP_FREE = (
    "I've hit the usage limit for this request, so I'm stopping here with what "
    "I have so far. Upgrade to Pro to run larger tasks like full-inbox triage."
)
REQUEST_CEILING_STOP_PRO = (
    "This request hit its safety ceiling, so I'm stopping here with what I "
    "have so far. Try splitting the task into smaller steps."
)


def _budget_key(user_id: str, period: RateLimitPeriod) -> str:
    return _BUDGET_KEY.format(
        user_id=user_id, period=period.value, window=get_time_window_key(period)
    )


async def record_model_call_usage(
    user_id: str | None,
    cost_usd: float,
    root_request_id: str | None,
    tokens: int,
) -> None:
    """Record one model call's spend and tokens in a single Redis round trip.

    The single metering seam ``LLMAccountingMiddleware.aafter_model`` calls after
    every model call on every execution path (chat, workflows, bots, voice,
    subagents). Batches the day + month USD cost increments and the request
    tree's aggregate token counter — each with its TTL — into one
    non-transactional pipeline, and runs the durable Mongo cost rollup
    concurrently. Fail-open: a Redis hiccup must never fail the model call.
    """
    record_spend = user_id is not None and cost_usd > 0
    record_tokens = root_request_id is not None and tokens > 0
    if not (record_spend or record_tokens):
        return

    awaitables: list[Awaitable[Any]] = []

    # Durable per-day rollup — the Redis windows expire in ~26h, so this is the
    # only cost history the usage charts can plot. Never raises. Runs
    # concurrently with the Redis pipeline below.
    if record_spend and user_id is not None:
        awaitables.append(record_cost(user_id, cost_usd))

    client = redis_cache.redis
    if client is None:
        log.warning(f"{LogTag.STORAGE} Redis unavailable — model call usage not recorded.")
    else:
        pipe = client.pipeline(transaction=False)
        if record_spend and user_id is not None:
            for period, ttl in _PERIOD_TTL_SECONDS.items():
                key = _budget_key(user_id, period)
                pipe.incrbyfloat(key, cost_usd)
                pipe.expire(key, ttl)
        if record_tokens and root_request_id is not None:
            key = _REQUEST_TOKENS_KEY.format(root_request_id=root_request_id)
            pipe.incrby(key, tokens)
            pipe.expire(key, REQUEST_TOKEN_COUNTER_TTL_SECONDS)
        awaitables.append(pipe.execute())

    await asyncio.gather(*awaitables)


async def get_cost(user_id: str, period: RateLimitPeriod) -> float:
    """Return the current window's accumulated USD cost (0.0 if unset)."""
    client = redis_cache.redis
    if client is None:
        log.warning(f"{LogTag.STORAGE} Redis unavailable — cost budget reads 0.")
        return 0.0
    raw = await client.get(_budget_key(user_id, period))
    return float(raw) if raw is not None else 0.0


async def get_request_tokens(root_request_id: str) -> int:
    """Return the request tree's aggregate token count so far (0 if unset)."""
    client = redis_cache.redis
    if client is None:
        return 0
    raw = await client.get(_REQUEST_TOKENS_KEY.format(root_request_id=root_request_id))
    return int(raw) if raw is not None else 0


async def get_budget_stop_reason(
    user_id: str | None,
    plan_type: PlanType | None,
    root_request_id: str | None,
) -> str | None:
    """Return the user-facing stop text when a budget wall binds, else None.

    Checked before every model call by ``LLMAccountingMiddleware`` — the one
    seam every execution path (chat, workflows, bots, voice, subagents) passes
    through, so no entry point can route around it. Two walls:

    1. Daily cost budget — catches entry points that skip the endpoint gate.
    2. Per-request aggregate token ceiling — stops runaway agentic loops.

    Missing context fails open (never crash a turn on a threading gap) but
    warns loudly so a broken config path is visible, not silent.
    """
    if user_id is None or plan_type is None:
        log.warning(
            f"{LogTag.AGENT} Budget check skipped — missing user_id/plan_type in "
            "configurable (threading gap?)."
        )
        return None

    daily_budget = get_daily_cost_budget_usd(plan_type)

    # Missing root_request_id → only the daily read is needed, so skip the
    # second round trip. The threading-gap warning stays scoped to a run that
    # is otherwise proceeding (daily wall not bound), exactly as before.
    if root_request_id is None:
        spent = await get_cost(user_id, RateLimitPeriod.DAY)
        if spent >= daily_budget:
            return DAILY_BUDGET_STOP_FREE if plan_type == PlanType.FREE else DAILY_BUDGET_STOP_PRO
        log.warning(
            f"{LogTag.AGENT} Per-request ceiling skipped — missing root_request_id "
            "in configurable (threading gap?)."
        )
        return None

    # Both reads are independent — issue them together so the hottest path (this
    # runs before every model call) pays one round trip, not two. The daily wall
    # still takes priority; the token read is harmless work when it binds.
    spent, used = await asyncio.gather(
        get_cost(user_id, RateLimitPeriod.DAY),
        get_request_tokens(root_request_id),
    )
    if spent >= daily_budget:
        return DAILY_BUDGET_STOP_FREE if plan_type == PlanType.FREE else DAILY_BUDGET_STOP_PRO
    if used >= get_per_request_token_ceiling(plan_type):
        return REQUEST_CEILING_STOP_FREE if plan_type == PlanType.FREE else REQUEST_CEILING_STOP_PRO

    return None


def _allowance_used(spent: float, budget: float, period: RateLimitPeriod) -> dict[str, Any]:
    """One window's allowance as a 0-100 percentage + when it resets. No dollars."""
    pct = round(min(spent / budget * 100, 100.0), 1) if budget > 0 else 0.0
    return {"percentage": pct, "reset_time": get_reset_time(period).isoformat()}


async def get_budget_status(user_id: str, plan_type: PlanType) -> dict[str, Any]:
    """Read-only cost-budget view for the Usage UI.

    Returns only the *percentage* of each window's allowance consumed (plus its
    reset time) and the per-request token ceiling — deliberately never the raw
    USD spend or the dollar budget, so the user sees how close they are to the
    wall without us leaking per-request COGS to the client. Reads the same Redis
    windows the accounting middleware enforces, so the number shown is the number
    that gates them. Free has no monthly cost budget, so ``monthly`` is null there.
    """
    # Pro reads both windows concurrently (one round trip); Free reads only day.
    if plan_type == PlanType.PRO:
        daily_spent, monthly_spent = await asyncio.gather(
            get_cost(user_id, RateLimitPeriod.DAY),
            get_cost(user_id, RateLimitPeriod.MONTH),
        )
        monthly = _allowance_used(monthly_spent, PRO_MONTHLY_COST_BUDGET_USD, RateLimitPeriod.MONTH)
    else:
        daily_spent = await get_cost(user_id, RateLimitPeriod.DAY)
        monthly = None

    daily = _allowance_used(daily_spent, get_daily_cost_budget_usd(plan_type), RateLimitPeriod.DAY)
    return {
        "daily": daily,
        "monthly": monthly,
        "per_request_token_ceiling": get_per_request_token_ceiling(plan_type),
    }
