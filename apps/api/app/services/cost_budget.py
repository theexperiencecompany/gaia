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

from app.config.rate_limits import (
    RateLimitPeriod,
    get_daily_cost_budget_usd,
    get_per_request_token_ceiling,
    get_time_window_key,
)
from app.constants.llm import (
    DAILY_BUDGET_TTL_SECONDS,
    MONTHLY_BUDGET_TTL_SECONDS,
    REQUEST_TOKEN_COUNTER_TTL_SECONDS,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.payment_models import PlanType
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


async def add_cost(user_id: str, cost_usd: float) -> None:
    """Add real LLM spend to the user's current day AND month windows."""
    if cost_usd <= 0:
        return
    client = redis_cache.redis
    if client is None:
        log.warning(f"{LogTag.STORAGE} Redis unavailable — cost budget not recorded.")
        return
    for period, ttl in _PERIOD_TTL_SECONDS.items():
        key = _budget_key(user_id, period)
        await client.incrbyfloat(key, cost_usd)
        await client.expire(key, ttl)


async def get_cost(user_id: str, period: RateLimitPeriod) -> float:
    """Return the current window's accumulated USD cost (0.0 if unset)."""
    client = redis_cache.redis
    if client is None:
        log.warning(f"{LogTag.STORAGE} Redis unavailable — cost budget reads 0.")
        return 0.0
    raw = await client.get(_budget_key(user_id, period))
    return float(raw) if raw is not None else 0.0


async def add_request_tokens(root_request_id: str, tokens: int) -> None:
    """Add tokens to a request's aggregate counter (shared across the whole
    comms -> executor -> subagent tree via the inherited ``root_request_id``)."""
    if tokens <= 0:
        return
    client = redis_cache.redis
    if client is None:
        log.warning(f"{LogTag.STORAGE} Redis unavailable — request tokens not recorded.")
        return
    key = _REQUEST_TOKENS_KEY.format(root_request_id=root_request_id)
    await client.incrby(key, tokens)
    await client.expire(key, REQUEST_TOKEN_COUNTER_TTL_SECONDS)


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

    spent = await get_cost(user_id, RateLimitPeriod.DAY)
    if spent >= get_daily_cost_budget_usd(plan_type):
        return DAILY_BUDGET_STOP_FREE if plan_type == PlanType.FREE else DAILY_BUDGET_STOP_PRO

    if root_request_id is None:
        log.warning(
            f"{LogTag.AGENT} Per-request ceiling skipped — missing root_request_id "
            "in configurable (threading gap?)."
        )
        return None

    used = await get_request_tokens(root_request_id)
    if used >= get_per_request_token_ceiling(plan_type):
        return REQUEST_CEILING_STOP_FREE if plan_type == PlanType.FREE else REQUEST_CEILING_STOP_PRO

    return None
