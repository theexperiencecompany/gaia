"""Per-plan LLM routing: free -> Gemini, any paid plan -> MiniMax (OpenRouter), hardcoded
by subscription plan. Set on the comms configurable; executor/subagents inherit it.

Also the pro ECONOMIC guard: when a paid user's rolling monthly LLM spend
exceeds ``PRO_MONTHLY_COST_BUDGET_USD``, routing degrades to the free-tier
model for the rest of the month instead of blocking — a paying user is never
hard-walled mid-month. All other pro entitlements (rate limits, memory,
per-request ceiling) stay intact; only the model changes.
"""

from typing import Any

from app.config.rate_limits import RateLimitPeriod, get_reset_time, get_time_window_key
from app.config.settings import settings
from app.constants.llm import (
    COMMS_REASONING,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MODEL_NAME,
    DEV_MODEL_OPTIONS,
    MONTHLY_BUDGET_TTL_SECONDS,
    OPENROUTER_REASONING,
    PAID_MODEL_MODEL_KWARGS,
    PAID_MODEL_NAME,
    PAID_MODEL_PROVIDER,
    PRO_MONTHLY_COST_BUDGET_USD,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.agent_models import AgentConfigurable
from app.models.models_models import DevModelOption
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.models.payment_models import PlanType
from app.services.cost_budget import get_cost
from app.services.notification_service import notification_service
from app.services.payments.payment_service import payment_service
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log

_DEGRADE_NOTICE_KEY = "cost_budget_notified:{user_id}:{window}"


def _pin_model(configurable: AgentConfigurable, provider: str, model: str) -> None:
    # Gemini binds from ``model_name``, OpenRouter from ``model`` — set both.
    configurable["provider"] = provider
    configurable["model"] = model
    configurable["model_name"] = model


async def apply_plan_model(configurable: AgentConfigurable, user_id: str | None) -> None:
    """Route the model by plan: free -> Gemini, any paid plan -> MiniMax. No-op without a user_id."""
    if not user_id:
        return

    try:
        plan = await payment_service.get_cached_plan_type(user_id)
    except Exception as e:
        # A transient lookup failure must not fail the turn — keep the default model.
        log.warning(f"{LogTag.AGENT} plan_model lookup failed; keeping default model", error=str(e))
        return

    # Stamp the resolved plan on the configurable: children inherit it (see
    # agent_helpers.build_agent_config) and the accounting middleware reads it
    # for budget-wall enforcement.
    configurable["plan_type"] = plan.value

    # Free runs the default model; every other (paid) tier gets the better model,
    # so new paid plans are covered without touching this routing.
    degraded = False
    if plan == PlanType.FREE:
        _pin_model(configurable, DEFAULT_LLM_PROVIDER, DEFAULT_MODEL_NAME)
    elif await _pro_monthly_budget_exhausted(user_id):
        # Economic guard: this month's priority compute is spent — degrade to
        # the free-tier model instead of blocking. Entitlements stay pro.
        degraded = True
        _pin_model(configurable, DEFAULT_LLM_PROVIDER, DEFAULT_MODEL_NAME)
        log.warning(
            "pro_model_degraded",
            event_name="pro_model_degraded",
            user_id=user_id,
            plan=plan.value,
        )
        spawn_background_task(_notify_degrade_once(user_id))
    else:
        # Paid: MiniMax M3 via OpenRouter, comms-specific reasoning, first-party
        # provider pin. The executor + provider subagents inherit this model and the
        # provider pin from `configurable` (see agent_helpers._inherit_from_parent_configurable).
        _pin_model(configurable, PAID_MODEL_PROVIDER, PAID_MODEL_NAME)
        configurable["reasoning"] = COMMS_REASONING
        configurable["model_kwargs"] = PAID_MODEL_MODEL_KWARGS

    log.set(plan_model={"plan": plan.value, "model": configurable["model"], "degraded": degraded})


async def _pro_monthly_budget_exhausted(user_id: str) -> bool:
    """True when the month's spend has crossed the pro economic guard.

    Fails open (False) on infra errors — never punish a paying user for a
    Redis hiccup.
    """
    try:
        spent = await get_cost(user_id, RateLimitPeriod.MONTH)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Monthly budget read failed; keeping paid model",
            error=str(e),
            error_type=type(e).__name__,
        )
        return False
    return spent >= PRO_MONTHLY_COST_BUDGET_USD


async def _notify_degrade_once(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = _DEGRADE_NOTICE_KEY.format(
            user_id=user_id, window=get_time_window_key(RateLimitPeriod.MONTH)
        )
        if not await client.set(key, "1", nx=True, ex=MONTHLY_BUDGET_TTL_SECONDS):
            return
        reset_time = get_reset_time(RateLimitPeriod.MONTH)
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.USAGE_LIMIT,
                type=NotificationType.INFO,
                content=NotificationContent(
                    title="Priority compute used for this month",
                    body=(
                        "You've used this month's priority AI compute. GAIA keeps "
                        f"working on the standard model until {reset_time:%b %d}."
                    ),
                ),
            )
        )
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Degrade notice failed",
            error=str(e),
            error_type=type(e).__name__,
        )


def _apply_dev_model(
    configurable: AgentConfigurable, option: DevModelOption, reasoning_cfg: dict[str, Any]
) -> None:
    """Pin a DEV_MODEL_OPTIONS entry onto a configurable, applying role-appropriate
    reasoning. Clears `model_kwargs`/`reasoning` for models that don't use them so a
    prior plan/inherited OpenRouter pin can't leak onto a Gemini-routed model."""
    if option["model"]:
        _pin_model(configurable, option["provider"], option["model"])
    else:
        # Entry without a pinned model (the env-defined "custom" endpoint): route
        # by provider and clear any earlier model pin so the client's own default
        # (DEV_LLM_MODEL) serves the request.
        configurable["provider"] = option["provider"]
        configurable.pop("model", None)
        configurable.pop("model_name", None)
    if option["model_kwargs"] is not None:
        configurable["model_kwargs"] = option["model_kwargs"]
    else:
        configurable.pop("model_kwargs", None)
    if option["reasoning"]:
        configurable["reasoning"] = reasoning_cfg
    else:
        configurable.pop("reasoning", None)


def apply_dev_model_override(
    configurable: AgentConfigurable,
    comms_model: str | None,
    executor_model: str | None,
    use_defaults: bool,
) -> None:
    """DEV-ONLY: override the comms model now and stash the executor model for the
    executor run. Requests that don't pick a model (use_defaults) fall back to the
    env-configured DEV_DEFAULT_MODEL for both roles, so bots/scripts/plain requests
    route to it too; an explicit selector choice wins. No-op when neither is set or
    an id is unknown. Runs AFTER apply_plan_model so the dev selection wins over
    the plan model. Caller gates this to ENV=development; never reached in
    production."""
    if use_defaults:
        dev_default = settings.DEV_DEFAULT_MODEL
        if dev_default and dev_default not in DEV_MODEL_OPTIONS:
            log.warning(
                f"{LogTag.AGENT} DEV_DEFAULT_MODEL is not a DEV_MODEL_OPTIONS key; "
                "keeping the plan model",
                dev_default=dev_default,
            )
            return
        comms_model = executor_model = dev_default
    comms_option = DEV_MODEL_OPTIONS.get(comms_model or "")
    if comms_option:
        _apply_dev_model(configurable, comms_option, COMMS_REASONING)
    # The executor builds its own configurable (inheriting comms's), so it can't be
    # pinned here. Stash the id; apply_dev_executor_model pins it after inheritance.
    if (executor_model or "") in DEV_MODEL_OPTIONS:
        configurable["__dev_executor_model__"] = executor_model
    if comms_option or (executor_model or "") in DEV_MODEL_OPTIONS:
        log.set(dev_model_override={"comms": comms_model, "executor": executor_model})


def apply_dev_executor_model(
    parent_configurable: AgentConfigurable, executor_configurable: AgentConfigurable
) -> None:
    """DEV-ONLY: pin the dev-selected executor model on the executor configurable,
    overriding the model inherited from comms. No-op unless the parent stashed one."""
    option = DEV_MODEL_OPTIONS.get(parent_configurable.get("__dev_executor_model__") or "")
    if option:
        _apply_dev_model(executor_configurable, option, OPENROUTER_REASONING)
