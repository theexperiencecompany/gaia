"""Per-plan LLM routing: free -> Gemini, pro -> MiniMax (OpenRouter), hardcoded by
subscription plan. Set on the comms configurable; executor/subagents inherit it.
"""

from app.constants.llm import (
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MODEL_NAME,
    PRO_MODEL_NAME,
    PRO_MODEL_PROVIDER,
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
    """Route the model by plan: free -> Gemini, pro -> MiniMax. No-op without a user_id."""
    if not user_id:
        return

    try:
        plan = await payment_service.get_cached_plan_type(user_id)
    except Exception as e:
        # A transient lookup failure must not fail the turn — keep the default model.
        log.warning("plan_model lookup failed; keeping default model", error=str(e))
        return

    if plan == PlanType.PRO:
        _pin_model(configurable, PRO_MODEL_PROVIDER, PRO_MODEL_NAME)
    else:
        _pin_model(configurable, DEFAULT_LLM_PROVIDER, DEFAULT_MODEL_NAME)

    log.set(plan_model={"plan": plan.value, "model": configurable["model"]})
