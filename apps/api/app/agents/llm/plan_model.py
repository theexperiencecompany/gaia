"""Per-plan LLM routing: free -> Gemini, any paid plan -> MiniMax (OpenRouter), hardcoded
by subscription plan. Set on the comms configurable; executor/subagents inherit it.
"""

from app.constants.llm import (
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MODEL_NAME,
    PAID_MODEL_EXTRA_BODY,
    PAID_MODEL_NAME,
    PAID_MODEL_PROVIDER,
)
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
        log.warning("plan_model lookup failed; keeping default model", error=str(e))
        return

    # Free runs the default model; every other (paid) tier gets the better model,
    # so new paid plans are covered without touching this routing.
    if plan == PlanType.FREE:
        _pin_model(configurable, DEFAULT_LLM_PROVIDER, DEFAULT_MODEL_NAME)
    else:
        _pin_model(configurable, PAID_MODEL_PROVIDER, PAID_MODEL_NAME)
        # Force the first-party MiniMax provider on OpenRouter so paid turns never
        # land on a throttled reseller (e.g. Parasail) from the shared pool.
        configurable["extra_body"] = PAID_MODEL_EXTRA_BODY

    log.set(plan_model={"plan": plan.value, "model": configurable["model"]})
