"""Per-plan LLM routing: free -> Gemini, any paid plan -> MiniMax (OpenRouter), hardcoded
by subscription plan. Set on the comms configurable; executor/subagents inherit it.
"""

from app.constants.llm import (
    COMMS_REASONING,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MODEL_NAME,
    DEV_MODEL_OPTIONS,
    OPENROUTER_REASONING,
    PAID_MODEL_MODEL_KWARGS,
    PAID_MODEL_NAME,
    PAID_MODEL_PROVIDER,
)
from app.constants.log_tags import LogTag
from app.models.payment_models import PlanType
from app.services.payments.payment_service import payment_service
from shared.py.wide_events import log


def _pin_model(configurable: dict, provider: str, model: str) -> None:
    # Gemini binds from ``model_name``, OpenRouter from ``model`` — set both.
    configurable["provider"] = provider
    configurable["model"] = model
    configurable["model_name"] = model


async def apply_plan_model(configurable: dict, user_id: str | None) -> None:
    """Route the model by plan: free -> Gemini, any paid plan -> MiniMax. No-op without a user_id."""
    if not user_id:
        return

    try:
        plan = await payment_service.get_cached_plan_type(user_id)
    except Exception as e:
        # A transient lookup failure must not fail the turn — keep the default model.
        log.warning(f"{LogTag.AGENT} plan_model lookup failed; keeping default model", error=str(e))
        return

    # Free runs the default model; every other (paid) tier gets the better model,
    # so new paid plans are covered without touching this routing.
    if plan == PlanType.FREE:
        _pin_model(configurable, DEFAULT_LLM_PROVIDER, DEFAULT_MODEL_NAME)
    else:
        # Paid: MiniMax M3 via OpenRouter, comms-specific reasoning, first-party
        # provider pin. The executor + provider subagents inherit this model and the
        # provider pin from `configurable` (see agent_helpers._inherit_from_parent_configurable).
        _pin_model(configurable, PAID_MODEL_PROVIDER, PAID_MODEL_NAME)
        configurable["reasoning"] = COMMS_REASONING
        configurable["model_kwargs"] = PAID_MODEL_MODEL_KWARGS

    log.set(plan_model={"plan": plan.value, "model": configurable["model"]})


def _apply_dev_model(configurable: dict, option: dict, reasoning_cfg: dict) -> None:
    """Pin a DEV_MODEL_OPTIONS entry onto a configurable, applying role-appropriate
    reasoning. Clears `model_kwargs`/`reasoning` for models that don't use them so a
    prior plan/inherited OpenRouter pin can't leak onto a Gemini-routed model."""
    _pin_model(configurable, option["provider"], option["model"])
    if option["model_kwargs"] is not None:
        configurable["model_kwargs"] = option["model_kwargs"]
    else:
        configurable.pop("model_kwargs", None)
    if option["reasoning"]:
        configurable["reasoning"] = reasoning_cfg
    else:
        configurable.pop("reasoning", None)


def apply_dev_model_override(
    configurable: dict,
    comms_model: str | None,
    executor_model: str | None,
    use_defaults: bool,
) -> None:
    """DEV-ONLY: override the comms model now and stash the executor model for the
    executor run. No-op when use_defaults is set or an id is unknown. Runs AFTER
    apply_plan_model so the dev selection wins over the plan model. Caller gates this
    to ENV=development; never reached in production."""
    if use_defaults:
        return
    comms_option = DEV_MODEL_OPTIONS.get(comms_model or "")
    if comms_option:
        _apply_dev_model(configurable, comms_option, COMMS_REASONING)
    # The executor builds its own configurable (inheriting comms's), so it can't be
    # pinned here. Stash the id; apply_dev_executor_model pins it after inheritance.
    if (executor_model or "") in DEV_MODEL_OPTIONS:
        configurable["__dev_executor_model__"] = executor_model
    if comms_option or (executor_model or "") in DEV_MODEL_OPTIONS:
        log.set(dev_model_override={"comms": comms_model, "executor": executor_model})


def apply_dev_executor_model(parent_configurable: dict, executor_configurable: dict) -> None:
    """DEV-ONLY: pin the dev-selected executor model on the executor configurable,
    overriding the model inherited from comms. No-op unless the parent stashed one."""
    option = DEV_MODEL_OPTIONS.get(parent_configurable.get("__dev_executor_model__") or "")
    if option:
        _apply_dev_model(executor_configurable, option, OPENROUTER_REASONING)
