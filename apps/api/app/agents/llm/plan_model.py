"""Per-plan LLM model routing (hardcoded policy; not user-selectable).

Free accounts run the default Gemini model; Pro accounts run a more capable
model (MiniMax) via OpenRouter. The choice is driven solely by the user's
subscription plan — there is no user-facing model picker.

This runs on the comms agent's configurable; the executor and provider subagents
inherit the model through the normal configurable propagation in
``build_agent_config``.
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
    """Pin the configurable to ``provider``/``model``.

    Mirrors how the LLM binds its model: Gemini reads ``model_name``, OpenRouter
    reads ``model`` — set both.
    """
    configurable["provider"] = provider
    configurable["model"] = model
    configurable["model_name"] = model


async def apply_plan_model(configurable: dict, user_id: str | None) -> None:
    """Route the model by the user's subscription plan: Free -> Gemini, Pro -> MiniMax.

    No-op without a ``user_id`` (the configurable keeps its default Gemini model).
    """
    if not user_id:
        return

    status = await payment_service.get_user_subscription_status(user_id)
    plan = status.plan_type or PlanType.FREE

    if plan == PlanType.PRO:
        _pin_model(configurable, PRO_MODEL_PROVIDER, PRO_MODEL_NAME)
    else:
        _pin_model(configurable, DEFAULT_LLM_PROVIDER, DEFAULT_MODEL_NAME)

    log.set(plan_model={"plan": plan.value, "model": configurable["model"]})
