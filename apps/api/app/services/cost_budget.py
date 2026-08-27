"""Rolling daily + monthly USD cost budgets for tier enforcement.

Day and month Redis keys accumulate real LLM USD cost per user. Writers and
readers:

- ``LLMAccountingMiddleware.aafter_model`` increments both windows after every
  model call (the single seam every execution path passes through — chat,
  workflows, bots, voice, subagents).
- ``ainvoke_structured`` prices its auxiliary one-shot calls (memory
  extraction/reconcile/consolidation, follow-ups, onboarding, …) through the
  same ``app.services.llm_metering.record_llm_call`` — but with
  ``charge_to_budget=False``: that spend is booked durably for COGS
  observability and never touches these windows, because background work must
  not consume the user's allowance.
- The chat endpoint checks the daily window BEFORE running the agent (429 wall).
- ``LLMAccountingMiddleware.awrap_model_call`` checks the daily window and the
  per-request token ceiling as the unbypassable backstop; the monthly window
  drives the pro model degrade in ``resolve_lane``.

Follows the RedisCache degradation philosophy: when Redis is unavailable these
helpers warn and no-op (enforcement fails open; startup ``verify_connection``
is what fails hard in production).
"""

import asyncio
from collections.abc import Awaitable
from typing import Any, NamedTuple

from redis.exceptions import RedisError

from app.config.rate_limits import (
    RateLimitPeriod,
    get_daily_cost_budget_usd,
    get_per_request_token_ceiling,
    get_reset_time,
    get_time_window_key,
)
from app.constants.llm import (
    BUDGET_WRAPUP_REMAINING_FRACTION,
    DAILY_BUDGET_TTL_SECONDS,
    MONTHLY_BUDGET_TTL_SECONDS,
    PRO_MONTHLY_COST_BUDGET_USD,
    REQUEST_TOKEN_COUNTER_TTL_SECONDS,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.payment_models import PlanType
from app.schemas.usage import BudgetWindow, UsageBudget
from app.services.payments.payment_service import payment_service
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
# Injected as a trailing HumanMessage (not returned as a stop text) when spend
# crosses BUDGET_WRAPUP_REMAINING_FRACTION but before the wall above binds — the
# run is told to land the plane instead of dying mid-tool-call on the hard stop.
BUDGET_WRAPUP_NOTICE = (
    "[System notice: your daily usage budget is almost exhausted. Stop gathering "
    "more information now. Answer the user's request with the best answer you can "
    "give using what you already have. Do not make further tool calls unless "
    "strictly necessary to complete the answer.]"
)


class BudgetCheck(NamedTuple):
    """Stop text (if bound) plus the daily spend read used to decide it, so
    callers can test the wrap-up threshold without a second Redis round trip."""

    stop_reason: str | None
    spent_usd: float | None
    plan_type: PlanType | None


def _budget_key(user_id: str, period: RateLimitPeriod) -> str:
    return _BUDGET_KEY.format(
        user_id=user_id, period=period.value, window=get_time_window_key(period)
    )


def _billable_request_tokens(input_tokens: int, cached_tokens: int, output_tokens: int) -> int:
    """Tokens a request tree is charged for: cache hits ride free, output counts."""
    return max(input_tokens - cached_tokens, 0) + output_tokens


def _is_charged_spend(user_id: str | None, cost_usd: float) -> bool:
    """Spend charges an allowance only when it belongs to a user and cost money."""
    return user_id is not None and cost_usd > 0


async def record_model_call_usage(
    user_id: str | None,
    cost_usd: float,
    root_request_id: str | None,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    reasoning_tokens: int = 0,
    charge_to_budget: bool,
) -> None:
    """Record one model call's spend and tokens in a single Redis round trip.

    Called by both metering routes via ``record_llm_call``. Batches the day +
    month USD cost increments and the request tree's aggregate token counter —
    each with its TTL — into one non-transactional pipeline, and runs the
    durable Mongo cost rollup concurrently. Fail-open: a Redis hiccup must
    never fail the model call.

    ``charge_to_budget`` decides whether the spend counts against the user's
    allowance: the agent middleware charges (chat/workflow/bot work the user
    asked for), auxiliary one-shot calls do not — their spend lands only in the
    durable rollup (under ``aux_cost``) so COGS stays measurable per user
    without a memory save or onboarding question eating chat allowance.

    The durable rollup records the token breakdown whenever there is spend OR
    token data — deliberately not gated on ``cost_usd`` alone, since a pricing
    lookup failure books ``cost_usd=0`` for a call that still burned real
    tokens (see ``llm_metering.record_llm_call``); the tokens must survive
    that so the call can be re-priced after the fact.
    """
    # The request ceiling bounds runaway loops, not cache economics: a cached
    # prefix rides nearly every call in a turn, so counting it trips the wall
    # on ordinary multi-call turns. The durable rollup below still books raw.
    billable_tokens = _billable_request_tokens(input_tokens, cached_tokens, output_tokens)
    record_spend = _is_charged_spend(user_id, cost_usd)
    record_tokens = root_request_id is not None and billable_tokens > 0
    has_token_data = bool(input_tokens or output_tokens or cached_tokens or reasoning_tokens)
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
                record_cost(
                    rollup_user_id,
                    cost_usd,
                    charged=charge_to_budget,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_tokens=cached_tokens,
                    reasoning_tokens=reasoning_tokens,
                ),
            )
        )

    client = redis_cache.redis
    if client is None:
        log.warning(f"{LogTag.STORAGE} Redis unavailable — model call usage not recorded.")
    else:
        pipe = client.pipeline(transaction=False)
        if charge_to_budget and record_spend and user_id is not None:
            for period, ttl in _PERIOD_TTL_SECONDS.items():
                key = _budget_key(user_id, period)
                pipe.incrbyfloat(key, cost_usd)
                pipe.expire(key, ttl)
        if record_tokens:
            # The flag already encodes "root_request_id present and something
            # billable" — re-checking it here would create a second copy of
            # the condition that tests cannot distinguish.
            key = _REQUEST_TOKENS_KEY.format(root_request_id=root_request_id)
            pipe.incrby(key, billable_tokens)
            pipe.expire(key, REQUEST_TOKEN_COUNTER_TTL_SECONDS)
        if pipe.command_stack:
            labeled.append(("redis_usage_pipeline", pipe.execute()))

    # Fail-open per op: a Redis or Mongo write failure here must never fail the
    # already-completed model call. ``return_exceptions`` keeps both writes
    # running to completion and lets us log each failure by name instead of one
    # aborting the other or bubbling out to the caller.
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
        raw = await client.get(_budget_key(user_id, period))
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

    Fails open (0) on Redis errors — same contract as :func:`get_cost`.
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
    """Return the user-facing stop text when a budget wall binds, else None.

    Checked before every model call by ``LLMAccountingMiddleware`` — the one
    seam every execution path (chat, workflows, bots, voice, subagents) passes
    through. The wall is self-sufficient: when ``plan_type`` was never stamped
    onto the configurable (a background/subagent path that skipped
    ``resolve_lane``), it is derived here from the Redis-cached tier so no
    entry point can be born unenforced. Two walls:

    1. Daily cost budget — catches entry points that skip the endpoint gate.
    2. Per-request aggregate token ceiling — stops runaway agentic loops.

    Also returns the daily spend + resolved plan actually read (or None when no
    read happened) so the caller can test the wrap-up threshold for free.

    Fails open only when there is genuinely nothing to enforce against
    (``user_id`` missing) or the plan lookup itself errors (infra hiccup) —
    both warn loudly so the gap stays visible, never silently skipped.
    """
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

    # Missing root_request_id → only the daily read is needed, so skip the
    # second round trip. The threading-gap warning stays scoped to a run that
    # is otherwise proceeding (daily wall not bound), exactly as before.
    if root_request_id is None:
        spent = await get_cost(user_id, RateLimitPeriod.DAY)
        if is_daily_budget_exhausted(spent, plan_type):
            stop = DAILY_BUDGET_STOP_FREE if plan_type == PlanType.FREE else DAILY_BUDGET_STOP_PRO
            return BudgetCheck(stop, spent, plan_type)
        log.warning(
            f"{LogTag.AGENT} Per-request ceiling skipped — missing root_request_id "
            "in configurable (threading gap?)."
        )
        return BudgetCheck(None, spent, plan_type)

    # Both reads are independent — issue them together so the hottest path (this
    # runs before every model call) pays one round trip, not two. The daily wall
    # still takes priority; the token read is harmless work when it binds.
    spent, used = await asyncio.gather(
        get_cost(user_id, RateLimitPeriod.DAY),
        get_request_tokens(root_request_id),
    )
    if is_daily_budget_exhausted(spent, plan_type):
        stop = DAILY_BUDGET_STOP_FREE if plan_type == PlanType.FREE else DAILY_BUDGET_STOP_PRO
        return BudgetCheck(stop, spent, plan_type)
    if used >= get_per_request_token_ceiling(plan_type):
        stop = REQUEST_CEILING_STOP_FREE if plan_type == PlanType.FREE else REQUEST_CEILING_STOP_PRO
        return BudgetCheck(stop, spent, plan_type)

    return BudgetCheck(None, spent, plan_type)


def is_daily_budget_exhausted(spent: float, plan_type: PlanType) -> bool:
    """The daily wall's one comparison: has ``spent`` consumed the plan's budget?

    Shared by the endpoint 429 gate (``enforce_daily_cost_budget``) and the
    middleware wall (:func:`get_budget_stop_reason`) so the operator and plan
    resolution can never drift between the two enforcement points. Takes the
    already-read spend because each caller fetches it differently (solo read vs
    gathered with the token counter).
    """
    return spent >= get_daily_cost_budget_usd(plan_type)


def is_budget_wrapup_threshold(spent: float, plan_type: PlanType) -> bool:
    """True once spend crosses BUDGET_WRAPUP_REMAINING_FRACTION headroom, before
    the hard wall above binds. Same shared-comparison rationale as
    :func:`is_daily_budget_exhausted`."""
    budget = get_daily_cost_budget_usd(plan_type)
    return budget > 0 and spent >= budget * (1 - BUDGET_WRAPUP_REMAINING_FRACTION)


def _allowance_used(spent: float, budget: float, period: RateLimitPeriod) -> BudgetWindow:
    """One window's allowance as a 0-100 percentage + when it resets. No dollars."""
    pct = round(min(spent / budget * 100, 100.0), 1) if budget > 0 else 0.0
    return BudgetWindow(percentage=pct, reset_time=get_reset_time(period).isoformat())


async def get_budget_status(user_id: str, plan_type: PlanType) -> UsageBudget:
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

    return UsageBudget(
        daily=_allowance_used(
            daily_spent, get_daily_cost_budget_usd(plan_type), RateLimitPeriod.DAY
        ),
        monthly=monthly,
        per_request_token_ceiling=get_per_request_token_ceiling(plan_type),
    )
