"""Rolling daily + monthly USD cost budgets for tier enforcement.

Day and month Redis keys accumulate real LLM USD cost per user.
LLMAccountingMiddleware.aafter_model increments both windows after every
model call; ainvoke_structured prices auxiliary one-shot calls the same way
but with charge_to_budget=False, so background work never eats the user's
allowance. The chat endpoint checks the daily window before running the
agent (429 wall); awrap_model_call checks it plus the per-request token
ceiling as the backstop. Pro also has a monthly window, billing day to
billing day: reaching it stops usage the same way until it resets.

Follows RedisCache's degradation philosophy: when Redis is unavailable these
helpers warn and no-op (enforcement fails open; startup verify_connection
fails hard in production).
"""

import asyncio
from collections.abc import Awaitable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, NamedTuple

from redis.exceptions import RedisError

from app.config.rate_limits import (
    RateLimitPeriod,
    billing_month_window,
    get_daily_cost_budget_usd,
    get_per_request_token_ceiling,
    get_reset_time,
    get_time_window_key,
)
from app.config.settings import settings
from app.constants.llm import (
    BUDGET_WRAPUP_REMAINING_FRACTION,
    DAILY_BUDGET_TTL_SECONDS,
    MONTHLY_BUDGET_TTL_SECONDS,
    PRO_MONTHLY_BUDGET_HEADS_UP_FRACTION,
    PRO_MONTHLY_COST_BUDGET_USD,
    REQUEST_TOKEN_COUNTER_TTL_SECONDS,
)
from app.constants.log_tags import LogTag
from app.db.redis import AsyncRedisCommands, redis_cache
from app.db.repositories.usage_daily import UsageDailyIncrement
from app.models.payment_models import PlanType
from app.schemas.usage import BudgetWindow, UsageBudget
from app.services.payments.payment_service import payment_service
from app.services.usage_activity import record_cost
from shared.py.analytics.catalog.billing import LimitWindow
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
    "Your limit resets tomorrow, or upgrade to Pro for much higher limits."
)
DAILY_BUDGET_STOP_PRO = (
    "You've reached today's usage limit. It resets tomorrow, "
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
# Injected as a trailing HumanMessage (not returned as a stop text) when spend
# crosses BUDGET_WRAPUP_REMAINING_FRACTION but before the wall above binds — the
# run is told to land the plane instead of dying mid-tool-call on the hard stop.
BUDGET_WRAPUP_NOTICE = (
    "[System notice: your daily usage budget is almost exhausted. Stop gathering "
    "more information now. Answer the user's request with the best answer you can "
    "give using what you already have. Do not make further tool calls unless "
    "strictly necessary to complete the answer.]"
)


class BudgetWall(StrEnum):
    """Which budget wall stopped a run; the value is the rate-limit card's feature."""

    DAILY_USAGE = "daily_usage"
    MONTHLY_USAGE = "monthly_usage"
    TASK_SIZE = "task_size"

    @property
    def limit_window(self) -> LimitWindow:
        """The rate_limit:hit window this wall reports."""
        return _LIMIT_WINDOWS[self]

    def stop_text(self, plan_type: PlanType | None, reset_at: datetime | None) -> str:
        """Return this wall's user-facing stop text, worded for the plan; the monthly one names its reset day."""
        if self is BudgetWall.MONTHLY_USAGE:
            if reset_at is None:
                raise ValueError("The monthly wall's stop text needs the day it resets.")
            return monthly_budget_stop_text(reset_at)
        free_text, paid_text = _STOP_TEXTS[self]
        return free_text if plan_type == PlanType.FREE else paid_text


_STOP_TEXTS: dict[BudgetWall, tuple[str, str]] = {
    BudgetWall.DAILY_USAGE: (DAILY_BUDGET_STOP_FREE, DAILY_BUDGET_STOP_PRO),
    BudgetWall.TASK_SIZE: (REQUEST_CEILING_STOP_FREE, REQUEST_CEILING_STOP_PRO),
}

_LIMIT_WINDOWS: dict[BudgetWall, LimitWindow] = {
    BudgetWall.DAILY_USAGE: "day",
    BudgetWall.MONTHLY_USAGE: "month",
    BudgetWall.TASK_SIZE: "request",
}


class BudgetCheck(NamedTuple):
    """The wall that binds (if any) plus the daily spend read used to decide it.

    Lets callers test the wrap-up threshold without a second Redis round trip.
    """

    wall: BudgetWall | None
    spent_usd: float | None
    plan_type: PlanType | None
    month_spent_usd: float | None = None
    #: When the bound wall lifts; None while nothing binds and for the task-size ceiling.
    reset_at: datetime | None = None

    @property
    def stop_reason(self) -> str | None:
        """The user-facing stop text for the bound wall, worded for the plan."""
        return self.wall.stop_text(self.plan_type, self.reset_at) if self.wall is not None else None


async def monthly_allowance_window(user_id: str) -> tuple[str, datetime]:
    """Return the user's current allowance month as (Redis window key, reset instant)."""
    billing_day = await payment_service.get_cached_billing_day(user_id)
    return billing_month_window(billing_day, datetime.now(UTC))


async def _budget_key(user_id: str, period: RateLimitPeriod) -> str:
    if period is RateLimitPeriod.DAY:
        window = get_time_window_key(period)
    else:
        window, _ = await monthly_allowance_window(user_id)
    return _BUDGET_KEY.format(user_id=user_id, period=period.value, window=window)


def _billable_request_tokens(input_tokens: int, cached_tokens: int, output_tokens: int) -> int:
    """Tokens a request tree is charged for: cache hits ride free, output counts."""
    return max(input_tokens - cached_tokens, 0) + output_tokens


def _is_charged_spend(user_id: str | None, cost_usd: float) -> bool:
    """Spend charges an allowance only when it belongs to a user and cost money."""
    return user_id is not None and cost_usd > 0


async def _write_usage_counters(
    client: AsyncRedisCommands,
    charged_user_id: str | None,
    cost: float,
    token_request_id: str | None,
    billable_tokens: int,
) -> None:
    """Book spend into both budget windows and tokens into the request counter, in one round trip.

    The month key reads the billing day, so resolving it is part of this write and fails open with it.
    """
    # pragma: no mutate start — MULTI/EXEC lands the same writes, so transaction is unobservable.
    pipe = client.pipeline(transaction=False)
    # pragma: no mutate end
    if charged_user_id is not None:
        for period, ttl in _PERIOD_TTL_SECONDS.items():
            key = await _budget_key(charged_user_id, period)
            pipe.incrbyfloat(key, cost)
            pipe.expire(key, ttl)
    if token_request_id is not None:
        key = _REQUEST_TOKENS_KEY.format(root_request_id=token_request_id)
        pipe.incrby(key, billable_tokens)
        pipe.expire(key, REQUEST_TOKEN_COUNTER_TTL_SECONDS)
    await pipe.execute()


async def record_model_call_usage(
    user_id: str | None,
    spend: UsageDailyIncrement,
    root_request_id: str | None,
    *,
    charge_to_budget: bool,
) -> None:
    """Record one model call's spend and tokens in a single Redis round trip.

    charge_to_budget decides whether spend counts against the user's allowance: the agent
    middleware charges, aux one-shot calls do not (booked only under aux_cost for COGS). The
    durable rollup still records token counts at cost_usd=0, since a pricing-lookup failure
    must not lose the data needed to re-price the call later.
    """
    # The request ceiling bounds runaway loops, not cache economics: a cached
    # prefix rides nearly every call in a turn, so counting it trips the wall
    # on ordinary multi-call turns. The durable rollup below still books raw.
    billable_tokens = _billable_request_tokens(
        spend.input_tokens, spend.cached_tokens, spend.output_tokens
    )
    record_spend = _is_charged_spend(user_id, spend.cost)
    record_tokens = root_request_id is not None and billable_tokens > 0
    has_token_data = bool(
        spend.input_tokens or spend.output_tokens or spend.cached_tokens or spend.reasoning_tokens
    )
    # The id itself, not a flag: the durable write below takes a non-optional
    # user_id, and carrying the narrowed value is what lets it type-check
    # without re-testing a None the flag has already ruled out.
    rollup_user_id = user_id if (record_spend or has_token_data) else None
    if rollup_user_id is None and not record_tokens:
        return

    # (operation label, awaitable) so a per-op failure can be logged by name.
    labeled: list[tuple[str, Awaitable[Any]]] = []

    # Durable per-day rollup — the Redis windows expire in ~26h, so this is the
    # only cost history the usage charts can plot. Runs concurrently with the
    # Redis pipeline below.
    if rollup_user_id is not None:
        labeled.append(
            (
                "mongo_cost_rollup",
                record_cost(rollup_user_id, spend, charged=charge_to_budget),
            )
        )

    client = redis_cache.redis
    charged_user_id = user_id if charge_to_budget and record_spend else None
    # The flag already encodes "root_request_id present and something billable".
    token_request_id = root_request_id if record_tokens else None
    if client is None:
        log.warning(f"{LogTag.STORAGE} Redis unavailable — model call usage not recorded.")
    elif charged_user_id is not None or token_request_id is not None:
        labeled.append(
            (
                "redis_usage_pipeline",
                _write_usage_counters(
                    client, charged_user_id, spend.cost, token_request_id, billable_tokens
                ),
            )
        )

    # Fail-open per op: a write failure here must never fail the already-completed
    # model call. return_exceptions keeps both writes running to completion and
    # lets us log each failure by name instead of one aborting the other.
    results = await asyncio.gather(*(aw for _, aw in labeled), return_exceptions=True)
    for (name, _), result in zip(labeled, results):
        if isinstance(result, Exception):
            log.warning(
                f"{LogTag.STORAGE} Model call usage write failed (failing open)",
                operation=name,
                error=str(result),
                error_type=type(result).__name__,
            )


async def get_cost(user_id: str, period: RateLimitPeriod) -> float:
    """Return the current window's accumulated USD cost (0.0 if unset).

    Fails open (0.0) when Redis is missing OR unreachable — per the module
    contract, a Redis blip must degrade enforcement, never fail the user's
    request (a raise here would 500 the chat gate / fail a workflow run).
    """
    client = redis_cache.redis
    if client is None:
        log.warning(f"{LogTag.STORAGE} Redis unavailable — cost budget reads 0.")
        return 0.0
    try:
        raw = await client.get(await _budget_key(user_id, period))
    except (RedisError, OSError) as e:
        log.warning(
            f"{LogTag.STORAGE} Cost budget read failed — reading 0",
            error=str(e),
            error_type=type(e).__name__,
        )
        return 0.0
    return float(raw) if raw is not None else 0.0


async def get_request_tokens(root_request_id: str) -> int:
    """Return the request tree's aggregate token count so far (0 if unset).

    Fails open (0) on Redis errors — same contract as :func:get_cost.
    """
    client = redis_cache.redis
    if client is None:
        return 0
    try:
        raw = await client.get(_REQUEST_TOKENS_KEY.format(root_request_id=root_request_id))
    except (RedisError, OSError) as e:
        log.warning(
            f"{LogTag.STORAGE} Request token read failed — reading 0",
            error=str(e),
            error_type=type(e).__name__,
        )
        return 0
    return int(raw) if raw is not None else 0


async def get_budget_stop_reason(
    user_id: str | None,
    plan_type: PlanType | None,
    root_request_id: str | None,
) -> BudgetCheck:
    """Return the budget read: wall names the limit that binds, else None.

    Self-sufficient: derives plan_type from the Redis-cached tier when never
    stamped onto the configurable. Checks a daily cost budget and a
    per-request token ceiling, and returns the spend/plan read so callers can
    test the wrap-up threshold for free. Fails open only when nothing can be enforced.
    """
    # Cost is still recorded where limits are off; only the wall stands down.
    if not settings.deployment.enforces_usage_limits:
        return BudgetCheck(None, None, None)

    if user_id is None:
        log.warning(
            f"{LogTag.AGENT} Budget check skipped — no user_id in configurable "
            "(nothing to enforce against; threading gap?)."
        )
        return BudgetCheck(None, None, None)

    if plan_type is None:
        # The stamp is missing (a path that skipped resolve_lane). Derive the
        # tier ourselves so the wall still binds; a lookup failure is the only
        # thing that fails open here, and it warns loudly.
        try:
            plan_type = await payment_service.get_cached_plan_type(user_id)
        except Exception as e:
            log.warning(
                f"{LogTag.AGENT} Budget check failing open — plan lookup failed",
                user={"id": user_id},
                error=str(e),
                error_type=type(e).__name__,
            )
            return BudgetCheck(None, None, None)
        log.warning(
            f"{LogTag.AGENT} plan_type missing from configurable — derived via "
            "cached lookup (upstream threading gap).",
            user={"id": user_id},
        )

    # One round trip for every read: this runs before every model call. Without a
    # root_request_id there is no token read, so the request ceiling cannot bind.
    used: int | None
    if root_request_id is None:
        spent, month_spent = await asyncio.gather(
            get_cost(user_id, RateLimitPeriod.DAY), get_cost(user_id, RateLimitPeriod.MONTH)
        )
        used = None
    else:
        spent, month_spent, used = await asyncio.gather(
            get_cost(user_id, RateLimitPeriod.DAY),
            get_cost(user_id, RateLimitPeriod.MONTH),
            get_request_tokens(root_request_id),
        )

    bound = await _bound_wall(user_id, spent, month_spent, used, plan_type)
    if bound is not None:
        wall, reset_at = bound
        return BudgetCheck(wall, spent, plan_type, month_spent, reset_at)
    if root_request_id is None:
        log.warning(
            f"{LogTag.AGENT} Per-request ceiling skipped — missing root_request_id "
            "in configurable (threading gap?)."
        )
    return BudgetCheck(None, spent, plan_type, month_spent)


async def _bound_wall(
    user_id: str, spent: float, month_spent: float, used: int | None, plan_type: PlanType
) -> tuple[BudgetWall, datetime | None] | None:
    """Return the first wall that binds (day, month, then request) and when it lifts."""
    if is_daily_budget_exhausted(spent, plan_type):
        return BudgetWall.DAILY_USAGE, get_reset_time(RateLimitPeriod.DAY)
    if is_monthly_budget_exhausted(month_spent, plan_type):
        _, reset = await monthly_allowance_window(user_id)
        return BudgetWall.MONTHLY_USAGE, reset
    if used is not None and used >= get_per_request_token_ceiling(plan_type):
        return BudgetWall.TASK_SIZE, None
    return None


def is_daily_budget_exhausted(spent: float, plan_type: PlanType) -> bool:
    """Check whether spent has consumed the plan's daily budget.

    Shared by the endpoint 429 gate and the middleware wall so the two
    enforcement points can never drift. Takes the already-read spend because
    each caller fetches it differently (solo read vs gathered with the token
    counter).
    """
    return spent >= get_daily_cost_budget_usd(plan_type)


def is_monthly_budget_exhausted(month_spent: float, plan_type: PlanType) -> bool:
    """Check whether a pro user's month has consumed the monthly allowance (free has none)."""
    return plan_type == PlanType.PRO and month_spent >= PRO_MONTHLY_COST_BUDGET_USD


def is_monthly_heads_up_due(month_spent: float, plan_type: PlanType) -> bool:
    """Check whether a pro user's month sits in the heads-up band below the allowance."""
    return (
        plan_type == PlanType.PRO
        and PRO_MONTHLY_COST_BUDGET_USD * PRO_MONTHLY_BUDGET_HEADS_UP_FRACTION
        <= month_spent
        < PRO_MONTHLY_COST_BUDGET_USD
    )


def format_reset_date(reset: datetime) -> str:
    """Render a budget reset as a day the user reads, e.g. "December 1"."""
    return f"{reset:%B} {reset.day}"


def monthly_budget_stop_text(reset_at: datetime) -> str:
    """Return the user-facing stop for a bound monthly allowance, naming the day it resets."""
    reset = format_reset_date(reset_at)
    return (
        "You've used this month's AI usage allowance, so chat, workflows and tracked "
        f"todos are paused until {reset}, when it resets."
    )


def is_budget_wrapup_threshold(spent: float, plan_type: PlanType) -> bool:
    """Check whether spend has crossed BUDGET_WRAPUP_REMAINING_FRACTION headroom.

    True before the hard wall above binds; same shared-comparison rationale
    as is_daily_budget_exhausted.
    """
    budget = get_daily_cost_budget_usd(plan_type)
    return budget > 0 and spent >= budget * (1 - BUDGET_WRAPUP_REMAINING_FRACTION)


def _allowance_used(spent: float, budget: float, reset: datetime) -> BudgetWindow:
    """One window's allowance as a 0-100 percentage + when it resets. No dollars."""
    pct = round(min(spent / budget * 100, 100.0), 1) if budget > 0 else 0.0
    return BudgetWindow(percentage=pct, reset_time=reset.isoformat())


async def get_budget_status(user_id: str, plan_type: PlanType) -> UsageBudget:
    """Read-only cost-budget view for the Usage UI.

    Returns only the percentage of each window's allowance consumed (plus
    its reset time), never the raw USD spend or dollar budget, so the client
    never sees per-request COGS. Free has no monthly cost budget, so monthly
    is null there.
    """
    # Pro reads both windows concurrently (one round trip); Free reads only day.
    if plan_type == PlanType.PRO:
        daily_spent, monthly_spent, (_, month_reset) = await asyncio.gather(
            get_cost(user_id, RateLimitPeriod.DAY),
            get_cost(user_id, RateLimitPeriod.MONTH),
            monthly_allowance_window(user_id),
        )
        monthly = _allowance_used(monthly_spent, PRO_MONTHLY_COST_BUDGET_USD, month_reset)
    else:
        daily_spent = await get_cost(user_id, RateLimitPeriod.DAY)
        monthly = None

    return UsageBudget(
        daily=_allowance_used(
            daily_spent,
            get_daily_cost_budget_usd(plan_type),
            get_reset_time(RateLimitPeriod.DAY),
        ),
        monthly=monthly,
        per_request_token_ceiling=get_per_request_token_ceiling(plan_type),
    )
