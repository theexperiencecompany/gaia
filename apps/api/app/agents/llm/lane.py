"""The resolved answer to "which model will this run call, and how".

One immutable :class:`ModelLane` is resolved once per user turn by
:func:`resolve_lane` and then carried verbatim — to the executor, to every
handoff subagent, across a queue hop, through a HIL resume. Everything
downstream reads the lane instead of re-deriving a model from loose keys, so
there is exactly one place a lane can be wrong.

This replaces a pipeline of in-place mutations spread across six files in which
every key propagated by a different rule: some parent-overrides, some
child-wins, ``reasoning`` deliberately not inherited at all, and several dropped
entirely by the queue's serializer. That table is what made model selection
unreadable and its bugs invisible.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from app.agents.llm.client import PROVIDER_MODELS, next_fallback_provider
from app.agents.llm.types import LLMProviderName
from app.config.rate_limits import RateLimitPeriod, get_reset_time, get_time_window_key
from app.config.settings import settings
from app.constants.cache import COST_BUDGET_NOTIFIED_KEY
from app.constants.llm import (
    COMMS_REASONING,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
    DEV_MODEL_OPTIONS,
    MODEL_FIELD_ID,
    MODEL_KWARGS_FIELD_ID,
    MONTHLY_BUDGET_TTL_SECONDS,
    OPENROUTER_REASONING,
    PAID_MODEL_MODEL_KWARGS,
    PAID_MODEL_NAME,
    PAID_MODEL_PROVIDER,
    PRO_MONTHLY_COST_BUDGET_USD,
    PROVIDER_FIELD_ID,
    REASONING_FIELD_ID,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.agent_models import AgentConfigurable
from app.models.models_models import DevModelOption
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
)
from app.models.payment_models import PlanType
from app.services.cost_budget import get_cost
from app.services.notification_service import notification_service
from app.services.payments.payment_service import payment_service
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log

#: Every configurable key a lane owns. These must be REPLACED wholesale on a lane
#: change, never merged into — a leftover key is the previous lane still steering
#: the request.
BINDING_FIELD_IDS: frozenset[str] = frozenset(
    {PROVIDER_FIELD_ID, MODEL_FIELD_ID, REASONING_FIELD_ID, MODEL_KWARGS_FIELD_ID}
)


class AgentRole(StrEnum):
    """Which tier is asking for a lane.

    Only the reasoning budget differs by role today: comms is mostly routing and
    acknowledgement work, so a paid turn spends its thinking budget on the
    executor's tool selection instead.
    """

    COMMS = "comms"
    EXECUTOR = "executor"
    SUBAGENT = "subagent"


@dataclass(frozen=True, slots=True)
class ModelLane:
    """A complete, resolved model selection. Immutable on purpose: a lane is
    decided once per turn and inherited, never edited in flight."""

    #: The logical lane, not a free string: an unknown provider must fail at the
    #: boundary that produced it, not as a silent miss in the alternatives map.
    provider: LLMProviderName
    #: ``None`` means "let the client use its own configured default" — the
    #: env-defined custom dev endpoint serves ``DEV_LLM_MODEL`` this way.
    model: str | None
    reasoning: dict[str, Any] | None
    #: OpenRouter provider-routing pin. Provider-specific by definition, so it
    #: never survives :meth:`fallback`.
    provider_pin: dict[str, Any] | None
    max_input_tokens: int

    def to_configurable(self) -> dict[str, Any]:
        """The JSON-safe form stored on ``configurable[LANE_CONFIG_KEY]``."""
        return {
            "provider": self.provider,
            "model": self.model,
            "reasoning": self.reasoning,
            "provider_pin": self.provider_pin,
            "max_input_tokens": self.max_input_tokens,
        }

    def binding_keys(self) -> AgentConfigurable:
        """The top-level ``configurable`` keys LangChain's own field resolution
        reads — ``provider`` picks the alternative, the rest are ConfigurableFields
        (see ``client._openrouter_wire_configurables``).

        Written ONLY by ``build_agent_config`` from the lane, and read only by
        LangChain. GAIA code reads the lane. A key is omitted rather than set to
        ``None`` so the client's own default survives — the custom dev endpoint
        pins no model, and a non-reasoning model must not carry a reasoning pin.
        """
        # Literal keys, not the *_FIELD_ID constants: the return is an
        # AgentConfigurable, and mypy only checks TypedDict keys when they are
        # literals (`literal-required`). The TypedDict IS the enforcement here —
        # stronger than a constant, since it also checks the value types.
        # BINDING_FIELD_IDS below keeps the id set itself in one place.
        keys: AgentConfigurable = {"provider": self.provider}
        if self.model is not None:
            keys["model"] = self.model
        if self.reasoning is not None:
            keys["reasoning"] = self.reasoning
        if self.provider_pin is not None:
            keys["model_kwargs"] = self.provider_pin
        return keys

    def rebind(self, configurable: Mapping[str, Any]) -> dict[str, Any]:
        """``configurable`` with THIS lane's binding keys, and the previous lane's cleared.

        A plain merge is not enough, and that is why the fallback silently did
        nothing: LangChain merges a passed config OVER a ``with_config`` one
        (later wins), so re-passing the run's config restored the very provider
        that had just failed. Stale keys must be REMOVED, not just overwritten —
        the fallback drops the pin, and an un-cleared ``model_kwargs`` would carry
        the old provider's routing onto the new one.
        """
        return {
            **{k: v for k, v in configurable.items() if k not in BINDING_FIELD_IDS},
            **self.binding_keys(),
        }

    @classmethod
    def from_configurable(cls, raw: object) -> "ModelLane | None":
        """Rebuild a lane from a configurable, or ``None`` when there isn't one.

        ``None`` is a real answer, not an error: a bag written before lanes
        existed (an in-flight queue item or a stored HIL ``resume_item``) has no
        lane, and the caller resolves a fresh one rather than crashing on it.
        """
        if not isinstance(raw, dict) or "provider" not in raw:
            return None
        return cls(
            provider=LLMProviderName(raw["provider"]),
            model=raw.get("model"),
            reasoning=raw.get("reasoning"),
            provider_pin=raw.get("provider_pin"),
            max_input_tokens=int(raw.get("max_input_tokens") or DEFAULT_MAX_TOKENS),
        )

    def fallback(self) -> "ModelLane | None":
        """The same run on the next configured provider, or ``None`` when there
        is no other one.

        The pin AND the reasoning config are dropped: both are OpenRouter-wire
        concepts (``client._openrouter_wire_configurables`` declares them, while
        the Gemini lane declares only the model), so carrying either onto a
        different provider is how a fallback turns one failure into two.
        """
        nxt = next_fallback_provider(self.provider)
        if nxt is None:
            return None
        provider, model = nxt
        return replace(self, provider=provider, model=model, provider_pin=None, reasoning=None)


def _reasoning_for(role: AgentRole, paid: bool) -> dict[str, Any]:
    """Today's effective effort per (role, tier).

    Characterization, not endorsement: a FREE comms turn resolves ``medium``
    because it never set the key and inherited the client default, while a PAID
    comms turn explicitly set ``low`` — so free currently out-thinks pro. That is
    a deliberate open non-decision (see the plan's Task 2); it is written out
    explicitly here so it is visible and cannot change by accident.
    """
    if paid and role is AgentRole.COMMS:
        return COMMS_REASONING
    return OPENROUTER_REASONING


def _default_lane() -> ModelLane:
    return ModelLane(
        provider=LLMProviderName(DEFAULT_LLM_PROVIDER),
        model=DEFAULT_MODEL_NAME,
        reasoning=OPENROUTER_REASONING,
        provider_pin=None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def _dev_lane(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the lane resolves the SAME name the client would have used on its own —
    ``PROVIDER_MODELS[provider]``, read once at import from ``DEV_LLM_MODEL``. It
    changes nothing about which model runs, and it is what keeps the name visible
    to accounting: a lane with no model prices the call as "unknown", which falls
    through to DEFAULT_PRICING (~11x our default model's real rate) and
    undercharges the budget. Left ``None`` only when the lane genuinely has no
    resolved name — the custom endpoint is unconfigured — since pinning a
    placeholder would price the call against a model that does not exist.

    Non-reasoning models get no reasoning config at all rather than an inherited
    one, so a prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    provider = LLMProviderName(option["provider"])
    return ModelLane(
        provider=provider,
        model=option["model"] or PROVIDER_MODELS.get(provider) or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def dev_model_id(model_id: str | None, use_defaults: bool) -> str | None:
    """The dev-menu key a request selected, or ``None``.

    ``use_defaults`` means the request expressed no preference, so the
    env-configured ``DEV_DEFAULT_MODEL`` applies — that is what routes bots,
    scripts and plain requests onto the dev model too. An explicit choice wins
    over it; an unknown id selects nothing.
    """
    if use_defaults:
        dev_default = settings.DEV_DEFAULT_MODEL
        if dev_default and dev_default not in DEV_MODEL_OPTIONS:
            log.warning(
                f"{LogTag.AGENT} DEV_DEFAULT_MODEL is not a DEV_MODEL_OPTIONS key; "
                "keeping the plan-resolved lane",
                dev_default=dev_default,
            )
            return None
        model_id = dev_default
    return model_id if model_id in DEV_MODEL_OPTIONS else None


def dev_option(model_id: str | None) -> DevModelOption | None:
    """The dev-menu entry for an ALREADY-resolved id.

    What the executor needs: comms resolved the request's preference once and
    stashed the winning id, so re-running that resolution downstream would only
    give ``DEV_DEFAULT_MODEL`` a second chance to override an explicit choice.
    """
    return DEV_MODEL_OPTIONS.get(model_id) if model_id else None


def dev_option_for(model_id: str | None, use_defaults: bool) -> DevModelOption | None:
    """The dev-menu entry a request selected, or ``None``."""
    return dev_option(dev_model_id(model_id, use_defaults))


async def resolve_lane(
    user_id: str | None,
    role: AgentRole,
    dev_option: DevModelOption | None = None,
) -> tuple[ModelLane, PlanType | None]:
    """The single place a model is chosen. Returns the lane and the plan tier it
    was resolved from (``None`` when there is no user to resolve one for).

    Free runs the default model; every paid tier gets the paid model and the
    first-party provider pin, so a new paid plan is covered without touching
    this. A paid user whose monthly spend has crossed the economic guard is
    degraded to the free lane rather than blocked — a paying user is never
    hard-walled mid-month, and every other pro entitlement stays intact.

    ``dev_option`` (development only) wins over all of it.
    """
    if dev_option is not None:
        return _dev_lane(dev_option, role), None

    if not user_id:
        return _default_lane(), None

    try:
        plan = await payment_service.get_cached_plan_type(user_id)
    except Exception as e:
        # A transient lookup failure must not fail the turn — keep the default.
        log.warning(f"{LogTag.AGENT} plan lookup failed; keeping the default lane", error=str(e))
        return _default_lane(), None

    if plan == PlanType.FREE:
        return _default_lane(), plan

    if await _pro_monthly_budget_exhausted(user_id):
        log.warning(
            "pro_model_degraded",
            event_name="pro_model_degraded",
            user_id=user_id,
            plan=plan.value,
        )
        spawn_background_task(_notify_degrade_once(user_id))
        return _default_lane(), plan

    return (
        ModelLane(
            provider=LLMProviderName(PAID_MODEL_PROVIDER),
            model=PAID_MODEL_NAME,
            reasoning=_reasoning_for(role, paid=True),
            provider_pin=PAID_MODEL_MODEL_KWARGS,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
    )


async def _pro_monthly_budget_exhausted(user_id: str) -> bool:
    """True when the month's spend has crossed the pro economic guard.

    Fails open (False) on infra errors — never punish a paying user for a Redis
    hiccup.
    """
    try:
        spent = await get_cost(user_id, RateLimitPeriod.MONTH)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Monthly budget read failed; keeping the paid lane",
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
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=user_id, window=get_time_window_key(RateLimitPeriod.MONTH)
        )
        if not await client.set(key, "1", nx=True, ex=MONTHLY_BUDGET_TTL_SECONDS):
            return
        reset_time = get_reset_time(RateLimitPeriod.MONTH)
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.USAGE_LIMIT,
                # type is left to NotificationRequest's own default (INFO) rather
                # than restated here — one source of truth for it.
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


__all__ = [
    "AgentRole",
    "LLMProviderName",
    "ModelLane",
    "dev_model_id",
    "dev_option",
    "dev_option_for",
    "resolve_lane",
]
