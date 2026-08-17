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

from app.agents.llm.client import next_fallback_provider
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
    NotificationType,
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


from mutmut.mutation.trampoline import wrap_in_trampoline as _mutmut_mutated, MutantDict


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
mutants_x__reasoning_for__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x__reasoning_for__mutmut)
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


def x__reasoning_for__mutmut_orig(role: AgentRole, paid: bool) -> dict[str, Any]:
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


def x__reasoning_for__mutmut_1(role: AgentRole, paid: bool) -> dict[str, Any]:
    """Today's effective effort per (role, tier).

    Characterization, not endorsement: a FREE comms turn resolves ``medium``
    because it never set the key and inherited the client default, while a PAID
    comms turn explicitly set ``low`` — so free currently out-thinks pro. That is
    a deliberate open non-decision (see the plan's Task 2); it is written out
    explicitly here so it is visible and cannot change by accident.
    """
    if paid or role is AgentRole.COMMS:
        return COMMS_REASONING
    return OPENROUTER_REASONING


def x__reasoning_for__mutmut_2(role: AgentRole, paid: bool) -> dict[str, Any]:
    """Today's effective effort per (role, tier).

    Characterization, not endorsement: a FREE comms turn resolves ``medium``
    because it never set the key and inherited the client default, while a PAID
    comms turn explicitly set ``low`` — so free currently out-thinks pro. That is
    a deliberate open non-decision (see the plan's Task 2); it is written out
    explicitly here so it is visible and cannot change by accident.
    """
    if paid and role is not AgentRole.COMMS:
        return COMMS_REASONING
    return OPENROUTER_REASONING

mutants_x__reasoning_for__mutmut['_mutmut_orig'] = x__reasoning_for__mutmut_orig # type: ignore # mutmut generated
mutants_x__reasoning_for__mutmut['x__reasoning_for__mutmut_1'] = x__reasoning_for__mutmut_1 # type: ignore # mutmut generated
mutants_x__reasoning_for__mutmut['x__reasoning_for__mutmut_2'] = x__reasoning_for__mutmut_2 # type: ignore # mutmut generated
mutants_x__default_lane__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x__default_lane__mutmut)
def _default_lane() -> ModelLane:
    return ModelLane(
        provider=LLMProviderName(DEFAULT_LLM_PROVIDER),
        model=DEFAULT_MODEL_NAME,
        reasoning=OPENROUTER_REASONING,
        provider_pin=None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__default_lane__mutmut_orig() -> ModelLane:
    return ModelLane(
        provider=LLMProviderName(DEFAULT_LLM_PROVIDER),
        model=DEFAULT_MODEL_NAME,
        reasoning=OPENROUTER_REASONING,
        provider_pin=None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__default_lane__mutmut_1() -> ModelLane:
    return ModelLane(
        provider=None,
        model=DEFAULT_MODEL_NAME,
        reasoning=OPENROUTER_REASONING,
        provider_pin=None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__default_lane__mutmut_2() -> ModelLane:
    return ModelLane(
        provider=LLMProviderName(DEFAULT_LLM_PROVIDER),
        model=None,
        reasoning=OPENROUTER_REASONING,
        provider_pin=None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__default_lane__mutmut_3() -> ModelLane:
    return ModelLane(
        provider=LLMProviderName(DEFAULT_LLM_PROVIDER),
        model=DEFAULT_MODEL_NAME,
        reasoning=None,
        provider_pin=None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__default_lane__mutmut_4() -> ModelLane:
    return ModelLane(
        provider=LLMProviderName(DEFAULT_LLM_PROVIDER),
        model=DEFAULT_MODEL_NAME,
        reasoning=OPENROUTER_REASONING,
        provider_pin=None,
        max_input_tokens=None,
    )


def x__default_lane__mutmut_5() -> ModelLane:
    return ModelLane(
        model=DEFAULT_MODEL_NAME,
        reasoning=OPENROUTER_REASONING,
        provider_pin=None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__default_lane__mutmut_6() -> ModelLane:
    return ModelLane(
        provider=LLMProviderName(DEFAULT_LLM_PROVIDER),
        reasoning=OPENROUTER_REASONING,
        provider_pin=None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__default_lane__mutmut_7() -> ModelLane:
    return ModelLane(
        provider=LLMProviderName(DEFAULT_LLM_PROVIDER),
        model=DEFAULT_MODEL_NAME,
        provider_pin=None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__default_lane__mutmut_8() -> ModelLane:
    return ModelLane(
        provider=LLMProviderName(DEFAULT_LLM_PROVIDER),
        model=DEFAULT_MODEL_NAME,
        reasoning=OPENROUTER_REASONING,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__default_lane__mutmut_9() -> ModelLane:
    return ModelLane(
        provider=LLMProviderName(DEFAULT_LLM_PROVIDER),
        model=DEFAULT_MODEL_NAME,
        reasoning=OPENROUTER_REASONING,
        provider_pin=None,
        )


def x__default_lane__mutmut_10() -> ModelLane:
    return ModelLane(
        provider=LLMProviderName(None),
        model=DEFAULT_MODEL_NAME,
        reasoning=OPENROUTER_REASONING,
        provider_pin=None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )

mutants_x__default_lane__mutmut['_mutmut_orig'] = x__default_lane__mutmut_orig # type: ignore # mutmut generated
mutants_x__default_lane__mutmut['x__default_lane__mutmut_1'] = x__default_lane__mutmut_1 # type: ignore # mutmut generated
mutants_x__default_lane__mutmut['x__default_lane__mutmut_2'] = x__default_lane__mutmut_2 # type: ignore # mutmut generated
mutants_x__default_lane__mutmut['x__default_lane__mutmut_3'] = x__default_lane__mutmut_3 # type: ignore # mutmut generated
mutants_x__default_lane__mutmut['x__default_lane__mutmut_4'] = x__default_lane__mutmut_4 # type: ignore # mutmut generated
mutants_x__default_lane__mutmut['x__default_lane__mutmut_5'] = x__default_lane__mutmut_5 # type: ignore # mutmut generated
mutants_x__default_lane__mutmut['x__default_lane__mutmut_6'] = x__default_lane__mutmut_6 # type: ignore # mutmut generated
mutants_x__default_lane__mutmut['x__default_lane__mutmut_7'] = x__default_lane__mutmut_7 # type: ignore # mutmut generated
mutants_x__default_lane__mutmut['x__default_lane__mutmut_8'] = x__default_lane__mutmut_8 # type: ignore # mutmut generated
mutants_x__default_lane__mutmut['x__default_lane__mutmut_9'] = x__default_lane__mutmut_9 # type: ignore # mutmut generated
mutants_x__default_lane__mutmut['x__default_lane__mutmut_10'] = x__default_lane__mutmut_10 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x__dev_lane__mutmut)
def _dev_lane(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_orig(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_1(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=None,
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_2(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_3(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_4(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_5(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=None,
    )


def x__dev_lane__mutmut_6(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_7(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_8(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_9(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_10(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        )


def x__dev_lane__mutmut_11(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(None),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_12(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["XXproviderXX"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_13(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["PROVIDER"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_14(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] and None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_15(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["XXmodelXX"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_16(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["MODEL"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_17(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(None, paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_18(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=None) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_19(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(paid=True) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_20(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, ) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_21(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=False) if option["reasoning"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_22(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["XXreasoningXX"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_23(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["REASONING"] else None,
        provider_pin=option["model_kwargs"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_24(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["XXmodel_kwargsXX"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def x__dev_lane__mutmut_25(option: DevModelOption, role: AgentRole) -> ModelLane:
    """A lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint), in which
    case the client's own ``DEV_LLM_MODEL`` serves the request. Non-reasoning
    models get no reasoning config at all rather than an inherited one, so a
    prior OpenRouter pin cannot leak onto a Gemini-routed model.
    """
    return ModelLane(
        provider=LLMProviderName(option["provider"]),
        model=option["model"] or None,
        reasoning=_reasoning_for(role, paid=True) if option["reasoning"] else None,
        provider_pin=option["MODEL_KWARGS"],
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )

mutants_x__dev_lane__mutmut['_mutmut_orig'] = x__dev_lane__mutmut_orig # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_1'] = x__dev_lane__mutmut_1 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_2'] = x__dev_lane__mutmut_2 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_3'] = x__dev_lane__mutmut_3 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_4'] = x__dev_lane__mutmut_4 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_5'] = x__dev_lane__mutmut_5 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_6'] = x__dev_lane__mutmut_6 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_7'] = x__dev_lane__mutmut_7 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_8'] = x__dev_lane__mutmut_8 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_9'] = x__dev_lane__mutmut_9 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_10'] = x__dev_lane__mutmut_10 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_11'] = x__dev_lane__mutmut_11 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_12'] = x__dev_lane__mutmut_12 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_13'] = x__dev_lane__mutmut_13 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_14'] = x__dev_lane__mutmut_14 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_15'] = x__dev_lane__mutmut_15 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_16'] = x__dev_lane__mutmut_16 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_17'] = x__dev_lane__mutmut_17 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_18'] = x__dev_lane__mutmut_18 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_19'] = x__dev_lane__mutmut_19 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_20'] = x__dev_lane__mutmut_20 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_21'] = x__dev_lane__mutmut_21 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_22'] = x__dev_lane__mutmut_22 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_23'] = x__dev_lane__mutmut_23 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_24'] = x__dev_lane__mutmut_24 # type: ignore # mutmut generated
mutants_x__dev_lane__mutmut['x__dev_lane__mutmut_25'] = x__dev_lane__mutmut_25 # type: ignore # mutmut generated
mutants_x_dev_model_id__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_dev_model_id__mutmut)
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


def x_dev_model_id__mutmut_orig(model_id: str | None, use_defaults: bool) -> str | None:
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


def x_dev_model_id__mutmut_1(model_id: str | None, use_defaults: bool) -> str | None:
    """The dev-menu key a request selected, or ``None``.

    ``use_defaults`` means the request expressed no preference, so the
    env-configured ``DEV_DEFAULT_MODEL`` applies — that is what routes bots,
    scripts and plain requests onto the dev model too. An explicit choice wins
    over it; an unknown id selects nothing.
    """
    if use_defaults:
        dev_default = None
        if dev_default and dev_default not in DEV_MODEL_OPTIONS:
            log.warning(
                f"{LogTag.AGENT} DEV_DEFAULT_MODEL is not a DEV_MODEL_OPTIONS key; "
                "keeping the plan-resolved lane",
                dev_default=dev_default,
            )
            return None
        model_id = dev_default
    return model_id if model_id in DEV_MODEL_OPTIONS else None


def x_dev_model_id__mutmut_2(model_id: str | None, use_defaults: bool) -> str | None:
    """The dev-menu key a request selected, or ``None``.

    ``use_defaults`` means the request expressed no preference, so the
    env-configured ``DEV_DEFAULT_MODEL`` applies — that is what routes bots,
    scripts and plain requests onto the dev model too. An explicit choice wins
    over it; an unknown id selects nothing.
    """
    if use_defaults:
        dev_default = settings.DEV_DEFAULT_MODEL
        if dev_default or dev_default not in DEV_MODEL_OPTIONS:
            log.warning(
                f"{LogTag.AGENT} DEV_DEFAULT_MODEL is not a DEV_MODEL_OPTIONS key; "
                "keeping the plan-resolved lane",
                dev_default=dev_default,
            )
            return None
        model_id = dev_default
    return model_id if model_id in DEV_MODEL_OPTIONS else None


def x_dev_model_id__mutmut_3(model_id: str | None, use_defaults: bool) -> str | None:
    """The dev-menu key a request selected, or ``None``.

    ``use_defaults`` means the request expressed no preference, so the
    env-configured ``DEV_DEFAULT_MODEL`` applies — that is what routes bots,
    scripts and plain requests onto the dev model too. An explicit choice wins
    over it; an unknown id selects nothing.
    """
    if use_defaults:
        dev_default = settings.DEV_DEFAULT_MODEL
        if dev_default and dev_default in DEV_MODEL_OPTIONS:
            log.warning(
                f"{LogTag.AGENT} DEV_DEFAULT_MODEL is not a DEV_MODEL_OPTIONS key; "
                "keeping the plan-resolved lane",
                dev_default=dev_default,
            )
            return None
        model_id = dev_default
    return model_id if model_id in DEV_MODEL_OPTIONS else None


def x_dev_model_id__mutmut_4(model_id: str | None, use_defaults: bool) -> str | None:
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
                None,
                dev_default=dev_default,
            )
            return None
        model_id = dev_default
    return model_id if model_id in DEV_MODEL_OPTIONS else None


def x_dev_model_id__mutmut_5(model_id: str | None, use_defaults: bool) -> str | None:
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
                dev_default=None,
            )
            return None
        model_id = dev_default
    return model_id if model_id in DEV_MODEL_OPTIONS else None


def x_dev_model_id__mutmut_6(model_id: str | None, use_defaults: bool) -> str | None:
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
                dev_default=dev_default,
            )
            return None
        model_id = dev_default
    return model_id if model_id in DEV_MODEL_OPTIONS else None


def x_dev_model_id__mutmut_7(model_id: str | None, use_defaults: bool) -> str | None:
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
                )
            return None
        model_id = dev_default
    return model_id if model_id in DEV_MODEL_OPTIONS else None


def x_dev_model_id__mutmut_8(model_id: str | None, use_defaults: bool) -> str | None:
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
                "XXkeeping the plan-resolved laneXX",
                dev_default=dev_default,
            )
            return None
        model_id = dev_default
    return model_id if model_id in DEV_MODEL_OPTIONS else None


def x_dev_model_id__mutmut_9(model_id: str | None, use_defaults: bool) -> str | None:
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
                "KEEPING THE PLAN-RESOLVED LANE",
                dev_default=dev_default,
            )
            return None
        model_id = dev_default
    return model_id if model_id in DEV_MODEL_OPTIONS else None


def x_dev_model_id__mutmut_10(model_id: str | None, use_defaults: bool) -> str | None:
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
        model_id = None
    return model_id if model_id in DEV_MODEL_OPTIONS else None


def x_dev_model_id__mutmut_11(model_id: str | None, use_defaults: bool) -> str | None:
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
    return model_id if model_id not in DEV_MODEL_OPTIONS else None

mutants_x_dev_model_id__mutmut['_mutmut_orig'] = x_dev_model_id__mutmut_orig # type: ignore # mutmut generated
mutants_x_dev_model_id__mutmut['x_dev_model_id__mutmut_1'] = x_dev_model_id__mutmut_1 # type: ignore # mutmut generated
mutants_x_dev_model_id__mutmut['x_dev_model_id__mutmut_2'] = x_dev_model_id__mutmut_2 # type: ignore # mutmut generated
mutants_x_dev_model_id__mutmut['x_dev_model_id__mutmut_3'] = x_dev_model_id__mutmut_3 # type: ignore # mutmut generated
mutants_x_dev_model_id__mutmut['x_dev_model_id__mutmut_4'] = x_dev_model_id__mutmut_4 # type: ignore # mutmut generated
mutants_x_dev_model_id__mutmut['x_dev_model_id__mutmut_5'] = x_dev_model_id__mutmut_5 # type: ignore # mutmut generated
mutants_x_dev_model_id__mutmut['x_dev_model_id__mutmut_6'] = x_dev_model_id__mutmut_6 # type: ignore # mutmut generated
mutants_x_dev_model_id__mutmut['x_dev_model_id__mutmut_7'] = x_dev_model_id__mutmut_7 # type: ignore # mutmut generated
mutants_x_dev_model_id__mutmut['x_dev_model_id__mutmut_8'] = x_dev_model_id__mutmut_8 # type: ignore # mutmut generated
mutants_x_dev_model_id__mutmut['x_dev_model_id__mutmut_9'] = x_dev_model_id__mutmut_9 # type: ignore # mutmut generated
mutants_x_dev_model_id__mutmut['x_dev_model_id__mutmut_10'] = x_dev_model_id__mutmut_10 # type: ignore # mutmut generated
mutants_x_dev_model_id__mutmut['x_dev_model_id__mutmut_11'] = x_dev_model_id__mutmut_11 # type: ignore # mutmut generated
mutants_x_dev_option_for__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_dev_option_for__mutmut)
def dev_option_for(model_id: str | None, use_defaults: bool) -> DevModelOption | None:
    """The dev-menu entry a request selected, or ``None``."""
    resolved = dev_model_id(model_id, use_defaults)
    return DEV_MODEL_OPTIONS.get(resolved) if resolved else None


def x_dev_option_for__mutmut_orig(model_id: str | None, use_defaults: bool) -> DevModelOption | None:
    """The dev-menu entry a request selected, or ``None``."""
    resolved = dev_model_id(model_id, use_defaults)
    return DEV_MODEL_OPTIONS.get(resolved) if resolved else None


def x_dev_option_for__mutmut_1(model_id: str | None, use_defaults: bool) -> DevModelOption | None:
    """The dev-menu entry a request selected, or ``None``."""
    resolved = None
    return DEV_MODEL_OPTIONS.get(resolved) if resolved else None


def x_dev_option_for__mutmut_2(model_id: str | None, use_defaults: bool) -> DevModelOption | None:
    """The dev-menu entry a request selected, or ``None``."""
    resolved = dev_model_id(None, use_defaults)
    return DEV_MODEL_OPTIONS.get(resolved) if resolved else None


def x_dev_option_for__mutmut_3(model_id: str | None, use_defaults: bool) -> DevModelOption | None:
    """The dev-menu entry a request selected, or ``None``."""
    resolved = dev_model_id(model_id, None)
    return DEV_MODEL_OPTIONS.get(resolved) if resolved else None


def x_dev_option_for__mutmut_4(model_id: str | None, use_defaults: bool) -> DevModelOption | None:
    """The dev-menu entry a request selected, or ``None``."""
    resolved = dev_model_id(use_defaults)
    return DEV_MODEL_OPTIONS.get(resolved) if resolved else None


def x_dev_option_for__mutmut_5(model_id: str | None, use_defaults: bool) -> DevModelOption | None:
    """The dev-menu entry a request selected, or ``None``."""
    resolved = dev_model_id(model_id, )
    return DEV_MODEL_OPTIONS.get(resolved) if resolved else None


def x_dev_option_for__mutmut_6(model_id: str | None, use_defaults: bool) -> DevModelOption | None:
    """The dev-menu entry a request selected, or ``None``."""
    resolved = dev_model_id(model_id, use_defaults)
    return DEV_MODEL_OPTIONS.get(None) if resolved else None

mutants_x_dev_option_for__mutmut['_mutmut_orig'] = x_dev_option_for__mutmut_orig # type: ignore # mutmut generated
mutants_x_dev_option_for__mutmut['x_dev_option_for__mutmut_1'] = x_dev_option_for__mutmut_1 # type: ignore # mutmut generated
mutants_x_dev_option_for__mutmut['x_dev_option_for__mutmut_2'] = x_dev_option_for__mutmut_2 # type: ignore # mutmut generated
mutants_x_dev_option_for__mutmut['x_dev_option_for__mutmut_3'] = x_dev_option_for__mutmut_3 # type: ignore # mutmut generated
mutants_x_dev_option_for__mutmut['x_dev_option_for__mutmut_4'] = x_dev_option_for__mutmut_4 # type: ignore # mutmut generated
mutants_x_dev_option_for__mutmut['x_dev_option_for__mutmut_5'] = x_dev_option_for__mutmut_5 # type: ignore # mutmut generated
mutants_x_dev_option_for__mutmut['x_dev_option_for__mutmut_6'] = x_dev_option_for__mutmut_6 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_resolve_lane__mutmut)
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


async def x_resolve_lane__mutmut_orig(
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


async def x_resolve_lane__mutmut_1(
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
    if dev_option is None:
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


async def x_resolve_lane__mutmut_2(
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
        return _dev_lane(None, role), None

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


async def x_resolve_lane__mutmut_3(
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
        return _dev_lane(dev_option, None), None

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


async def x_resolve_lane__mutmut_4(
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
        return _dev_lane(role), None

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


async def x_resolve_lane__mutmut_5(
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
        return _dev_lane(dev_option, ), None

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


async def x_resolve_lane__mutmut_6(
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

    if user_id:
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


async def x_resolve_lane__mutmut_7(
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
        plan = None
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


async def x_resolve_lane__mutmut_8(
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
        plan = await payment_service.get_cached_plan_type(None)
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


async def x_resolve_lane__mutmut_9(
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
        log.warning(None, error=str(e))
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


async def x_resolve_lane__mutmut_10(
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
        log.warning(f"{LogTag.AGENT} plan lookup failed; keeping the default lane", error=None)
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


async def x_resolve_lane__mutmut_11(
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
        log.warning(error=str(e))
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


async def x_resolve_lane__mutmut_12(
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
        log.warning(f"{LogTag.AGENT} plan lookup failed; keeping the default lane", )
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


async def x_resolve_lane__mutmut_13(
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
        log.warning(f"{LogTag.AGENT} plan lookup failed; keeping the default lane", error=str(None))
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


async def x_resolve_lane__mutmut_14(
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

    if plan != PlanType.FREE:
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


async def x_resolve_lane__mutmut_15(
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

    if await _pro_monthly_budget_exhausted(None):
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


async def x_resolve_lane__mutmut_16(
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
            None,
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


async def x_resolve_lane__mutmut_17(
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
            event_name=None,
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


async def x_resolve_lane__mutmut_18(
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
            user_id=None,
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


async def x_resolve_lane__mutmut_19(
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
            plan=None,
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


async def x_resolve_lane__mutmut_20(
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


async def x_resolve_lane__mutmut_21(
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


async def x_resolve_lane__mutmut_22(
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


async def x_resolve_lane__mutmut_23(
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


async def x_resolve_lane__mutmut_24(
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
            "XXpro_model_degradedXX",
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


async def x_resolve_lane__mutmut_25(
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
            "PRO_MODEL_DEGRADED",
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


async def x_resolve_lane__mutmut_26(
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
            event_name="XXpro_model_degradedXX",
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


async def x_resolve_lane__mutmut_27(
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
            event_name="PRO_MODEL_DEGRADED",
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


async def x_resolve_lane__mutmut_28(
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
        spawn_background_task(None)
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


async def x_resolve_lane__mutmut_29(
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
        spawn_background_task(_notify_degrade_once(None))
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


async def x_resolve_lane__mutmut_30(
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
            provider=None,
            model=PAID_MODEL_NAME,
            reasoning=_reasoning_for(role, paid=True),
            provider_pin=PAID_MODEL_MODEL_KWARGS,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
    )


async def x_resolve_lane__mutmut_31(
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
            model=None,
            reasoning=_reasoning_for(role, paid=True),
            provider_pin=PAID_MODEL_MODEL_KWARGS,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
    )


async def x_resolve_lane__mutmut_32(
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
            reasoning=None,
            provider_pin=PAID_MODEL_MODEL_KWARGS,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
    )


async def x_resolve_lane__mutmut_33(
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
            provider_pin=None,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
    )


async def x_resolve_lane__mutmut_34(
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
            max_input_tokens=None,
        ),
        plan,
    )


async def x_resolve_lane__mutmut_35(
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
            model=PAID_MODEL_NAME,
            reasoning=_reasoning_for(role, paid=True),
            provider_pin=PAID_MODEL_MODEL_KWARGS,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
    )


async def x_resolve_lane__mutmut_36(
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
            reasoning=_reasoning_for(role, paid=True),
            provider_pin=PAID_MODEL_MODEL_KWARGS,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
    )


async def x_resolve_lane__mutmut_37(
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
            provider_pin=PAID_MODEL_MODEL_KWARGS,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
    )


async def x_resolve_lane__mutmut_38(
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
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
    )


async def x_resolve_lane__mutmut_39(
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
            ),
        plan,
    )


async def x_resolve_lane__mutmut_40(
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
            provider=LLMProviderName(None),
            model=PAID_MODEL_NAME,
            reasoning=_reasoning_for(role, paid=True),
            provider_pin=PAID_MODEL_MODEL_KWARGS,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
    )


async def x_resolve_lane__mutmut_41(
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
            reasoning=_reasoning_for(None, paid=True),
            provider_pin=PAID_MODEL_MODEL_KWARGS,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
    )


async def x_resolve_lane__mutmut_42(
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
            reasoning=_reasoning_for(role, paid=None),
            provider_pin=PAID_MODEL_MODEL_KWARGS,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
    )


async def x_resolve_lane__mutmut_43(
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
            reasoning=_reasoning_for(paid=True),
            provider_pin=PAID_MODEL_MODEL_KWARGS,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
    )


async def x_resolve_lane__mutmut_44(
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
            reasoning=_reasoning_for(role, ),
            provider_pin=PAID_MODEL_MODEL_KWARGS,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
    )


async def x_resolve_lane__mutmut_45(
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
            reasoning=_reasoning_for(role, paid=False),
            provider_pin=PAID_MODEL_MODEL_KWARGS,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
    )

mutants_x_resolve_lane__mutmut['_mutmut_orig'] = x_resolve_lane__mutmut_orig # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_1'] = x_resolve_lane__mutmut_1 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_2'] = x_resolve_lane__mutmut_2 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_3'] = x_resolve_lane__mutmut_3 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_4'] = x_resolve_lane__mutmut_4 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_5'] = x_resolve_lane__mutmut_5 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_6'] = x_resolve_lane__mutmut_6 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_7'] = x_resolve_lane__mutmut_7 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_8'] = x_resolve_lane__mutmut_8 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_9'] = x_resolve_lane__mutmut_9 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_10'] = x_resolve_lane__mutmut_10 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_11'] = x_resolve_lane__mutmut_11 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_12'] = x_resolve_lane__mutmut_12 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_13'] = x_resolve_lane__mutmut_13 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_14'] = x_resolve_lane__mutmut_14 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_15'] = x_resolve_lane__mutmut_15 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_16'] = x_resolve_lane__mutmut_16 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_17'] = x_resolve_lane__mutmut_17 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_18'] = x_resolve_lane__mutmut_18 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_19'] = x_resolve_lane__mutmut_19 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_20'] = x_resolve_lane__mutmut_20 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_21'] = x_resolve_lane__mutmut_21 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_22'] = x_resolve_lane__mutmut_22 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_23'] = x_resolve_lane__mutmut_23 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_24'] = x_resolve_lane__mutmut_24 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_25'] = x_resolve_lane__mutmut_25 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_26'] = x_resolve_lane__mutmut_26 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_27'] = x_resolve_lane__mutmut_27 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_28'] = x_resolve_lane__mutmut_28 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_29'] = x_resolve_lane__mutmut_29 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_30'] = x_resolve_lane__mutmut_30 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_31'] = x_resolve_lane__mutmut_31 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_32'] = x_resolve_lane__mutmut_32 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_33'] = x_resolve_lane__mutmut_33 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_34'] = x_resolve_lane__mutmut_34 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_35'] = x_resolve_lane__mutmut_35 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_36'] = x_resolve_lane__mutmut_36 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_37'] = x_resolve_lane__mutmut_37 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_38'] = x_resolve_lane__mutmut_38 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_39'] = x_resolve_lane__mutmut_39 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_40'] = x_resolve_lane__mutmut_40 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_41'] = x_resolve_lane__mutmut_41 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_42'] = x_resolve_lane__mutmut_42 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_43'] = x_resolve_lane__mutmut_43 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_44'] = x_resolve_lane__mutmut_44 # type: ignore # mutmut generated
mutants_x_resolve_lane__mutmut['x_resolve_lane__mutmut_45'] = x_resolve_lane__mutmut_45 # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x__pro_monthly_budget_exhausted__mutmut)
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


async def x__pro_monthly_budget_exhausted__mutmut_orig(user_id: str) -> bool:
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


async def x__pro_monthly_budget_exhausted__mutmut_1(user_id: str) -> bool:
    """True when the month's spend has crossed the pro economic guard.

    Fails open (False) on infra errors — never punish a paying user for a Redis
    hiccup.
    """
    try:
        spent = None
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Monthly budget read failed; keeping the paid lane",
            error=str(e),
            error_type=type(e).__name__,
        )
        return False
    return spent >= PRO_MONTHLY_COST_BUDGET_USD


async def x__pro_monthly_budget_exhausted__mutmut_2(user_id: str) -> bool:
    """True when the month's spend has crossed the pro economic guard.

    Fails open (False) on infra errors — never punish a paying user for a Redis
    hiccup.
    """
    try:
        spent = await get_cost(None, RateLimitPeriod.MONTH)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Monthly budget read failed; keeping the paid lane",
            error=str(e),
            error_type=type(e).__name__,
        )
        return False
    return spent >= PRO_MONTHLY_COST_BUDGET_USD


async def x__pro_monthly_budget_exhausted__mutmut_3(user_id: str) -> bool:
    """True when the month's spend has crossed the pro economic guard.

    Fails open (False) on infra errors — never punish a paying user for a Redis
    hiccup.
    """
    try:
        spent = await get_cost(user_id, None)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Monthly budget read failed; keeping the paid lane",
            error=str(e),
            error_type=type(e).__name__,
        )
        return False
    return spent >= PRO_MONTHLY_COST_BUDGET_USD


async def x__pro_monthly_budget_exhausted__mutmut_4(user_id: str) -> bool:
    """True when the month's spend has crossed the pro economic guard.

    Fails open (False) on infra errors — never punish a paying user for a Redis
    hiccup.
    """
    try:
        spent = await get_cost(RateLimitPeriod.MONTH)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Monthly budget read failed; keeping the paid lane",
            error=str(e),
            error_type=type(e).__name__,
        )
        return False
    return spent >= PRO_MONTHLY_COST_BUDGET_USD


async def x__pro_monthly_budget_exhausted__mutmut_5(user_id: str) -> bool:
    """True when the month's spend has crossed the pro economic guard.

    Fails open (False) on infra errors — never punish a paying user for a Redis
    hiccup.
    """
    try:
        spent = await get_cost(user_id, )
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Monthly budget read failed; keeping the paid lane",
            error=str(e),
            error_type=type(e).__name__,
        )
        return False
    return spent >= PRO_MONTHLY_COST_BUDGET_USD


async def x__pro_monthly_budget_exhausted__mutmut_6(user_id: str) -> bool:
    """True when the month's spend has crossed the pro economic guard.

    Fails open (False) on infra errors — never punish a paying user for a Redis
    hiccup.
    """
    try:
        spent = await get_cost(user_id, RateLimitPeriod.MONTH)
    except Exception as e:
        log.warning(
            None,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False
    return spent >= PRO_MONTHLY_COST_BUDGET_USD


async def x__pro_monthly_budget_exhausted__mutmut_7(user_id: str) -> bool:
    """True when the month's spend has crossed the pro economic guard.

    Fails open (False) on infra errors — never punish a paying user for a Redis
    hiccup.
    """
    try:
        spent = await get_cost(user_id, RateLimitPeriod.MONTH)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Monthly budget read failed; keeping the paid lane",
            error=None,
            error_type=type(e).__name__,
        )
        return False
    return spent >= PRO_MONTHLY_COST_BUDGET_USD


async def x__pro_monthly_budget_exhausted__mutmut_8(user_id: str) -> bool:
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
            error_type=None,
        )
        return False
    return spent >= PRO_MONTHLY_COST_BUDGET_USD


async def x__pro_monthly_budget_exhausted__mutmut_9(user_id: str) -> bool:
    """True when the month's spend has crossed the pro economic guard.

    Fails open (False) on infra errors — never punish a paying user for a Redis
    hiccup.
    """
    try:
        spent = await get_cost(user_id, RateLimitPeriod.MONTH)
    except Exception as e:
        log.warning(
            error=str(e),
            error_type=type(e).__name__,
        )
        return False
    return spent >= PRO_MONTHLY_COST_BUDGET_USD


async def x__pro_monthly_budget_exhausted__mutmut_10(user_id: str) -> bool:
    """True when the month's spend has crossed the pro economic guard.

    Fails open (False) on infra errors — never punish a paying user for a Redis
    hiccup.
    """
    try:
        spent = await get_cost(user_id, RateLimitPeriod.MONTH)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Monthly budget read failed; keeping the paid lane",
            error_type=type(e).__name__,
        )
        return False
    return spent >= PRO_MONTHLY_COST_BUDGET_USD


async def x__pro_monthly_budget_exhausted__mutmut_11(user_id: str) -> bool:
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
            )
        return False
    return spent >= PRO_MONTHLY_COST_BUDGET_USD


async def x__pro_monthly_budget_exhausted__mutmut_12(user_id: str) -> bool:
    """True when the month's spend has crossed the pro economic guard.

    Fails open (False) on infra errors — never punish a paying user for a Redis
    hiccup.
    """
    try:
        spent = await get_cost(user_id, RateLimitPeriod.MONTH)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Monthly budget read failed; keeping the paid lane",
            error=str(None),
            error_type=type(e).__name__,
        )
        return False
    return spent >= PRO_MONTHLY_COST_BUDGET_USD


async def x__pro_monthly_budget_exhausted__mutmut_13(user_id: str) -> bool:
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
            error_type=type(None).__name__,
        )
        return False
    return spent >= PRO_MONTHLY_COST_BUDGET_USD


async def x__pro_monthly_budget_exhausted__mutmut_14(user_id: str) -> bool:
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
        return True
    return spent >= PRO_MONTHLY_COST_BUDGET_USD


async def x__pro_monthly_budget_exhausted__mutmut_15(user_id: str) -> bool:
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
    return spent > PRO_MONTHLY_COST_BUDGET_USD

mutants_x__pro_monthly_budget_exhausted__mutmut['_mutmut_orig'] = x__pro_monthly_budget_exhausted__mutmut_orig # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut['x__pro_monthly_budget_exhausted__mutmut_1'] = x__pro_monthly_budget_exhausted__mutmut_1 # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut['x__pro_monthly_budget_exhausted__mutmut_2'] = x__pro_monthly_budget_exhausted__mutmut_2 # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut['x__pro_monthly_budget_exhausted__mutmut_3'] = x__pro_monthly_budget_exhausted__mutmut_3 # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut['x__pro_monthly_budget_exhausted__mutmut_4'] = x__pro_monthly_budget_exhausted__mutmut_4 # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut['x__pro_monthly_budget_exhausted__mutmut_5'] = x__pro_monthly_budget_exhausted__mutmut_5 # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut['x__pro_monthly_budget_exhausted__mutmut_6'] = x__pro_monthly_budget_exhausted__mutmut_6 # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut['x__pro_monthly_budget_exhausted__mutmut_7'] = x__pro_monthly_budget_exhausted__mutmut_7 # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut['x__pro_monthly_budget_exhausted__mutmut_8'] = x__pro_monthly_budget_exhausted__mutmut_8 # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut['x__pro_monthly_budget_exhausted__mutmut_9'] = x__pro_monthly_budget_exhausted__mutmut_9 # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut['x__pro_monthly_budget_exhausted__mutmut_10'] = x__pro_monthly_budget_exhausted__mutmut_10 # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut['x__pro_monthly_budget_exhausted__mutmut_11'] = x__pro_monthly_budget_exhausted__mutmut_11 # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut['x__pro_monthly_budget_exhausted__mutmut_12'] = x__pro_monthly_budget_exhausted__mutmut_12 # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut['x__pro_monthly_budget_exhausted__mutmut_13'] = x__pro_monthly_budget_exhausted__mutmut_13 # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut['x__pro_monthly_budget_exhausted__mutmut_14'] = x__pro_monthly_budget_exhausted__mutmut_14 # type: ignore # mutmut generated
mutants_x__pro_monthly_budget_exhausted__mutmut['x__pro_monthly_budget_exhausted__mutmut_15'] = x__pro_monthly_budget_exhausted__mutmut_15 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x__notify_degrade_once__mutmut)
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


async def x__notify_degrade_once__mutmut_orig(user_id: str) -> None:
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


async def x__notify_degrade_once__mutmut_1(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = None
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


async def x__notify_degrade_once__mutmut_2(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is not None:
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


async def x__notify_degrade_once__mutmut_3(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = None
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


async def x__notify_degrade_once__mutmut_4(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=None, window=get_time_window_key(RateLimitPeriod.MONTH)
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


async def x__notify_degrade_once__mutmut_5(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=user_id, window=None
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


async def x__notify_degrade_once__mutmut_6(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            window=get_time_window_key(RateLimitPeriod.MONTH)
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


async def x__notify_degrade_once__mutmut_7(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=user_id, )
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


async def x__notify_degrade_once__mutmut_8(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=user_id, window=get_time_window_key(None)
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


async def x__notify_degrade_once__mutmut_9(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=user_id, window=get_time_window_key(RateLimitPeriod.MONTH)
        )
        if await client.set(key, "1", nx=True, ex=MONTHLY_BUDGET_TTL_SECONDS):
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


async def x__notify_degrade_once__mutmut_10(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=user_id, window=get_time_window_key(RateLimitPeriod.MONTH)
        )
        if not await client.set(None, "1", nx=True, ex=MONTHLY_BUDGET_TTL_SECONDS):
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


async def x__notify_degrade_once__mutmut_11(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=user_id, window=get_time_window_key(RateLimitPeriod.MONTH)
        )
        if not await client.set(key, None, nx=True, ex=MONTHLY_BUDGET_TTL_SECONDS):
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


async def x__notify_degrade_once__mutmut_12(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=user_id, window=get_time_window_key(RateLimitPeriod.MONTH)
        )
        if not await client.set(key, "1", nx=None, ex=MONTHLY_BUDGET_TTL_SECONDS):
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


async def x__notify_degrade_once__mutmut_13(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=user_id, window=get_time_window_key(RateLimitPeriod.MONTH)
        )
        if not await client.set(key, "1", nx=True, ex=None):
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


async def x__notify_degrade_once__mutmut_14(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=user_id, window=get_time_window_key(RateLimitPeriod.MONTH)
        )
        if not await client.set("1", nx=True, ex=MONTHLY_BUDGET_TTL_SECONDS):
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


async def x__notify_degrade_once__mutmut_15(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=user_id, window=get_time_window_key(RateLimitPeriod.MONTH)
        )
        if not await client.set(key, nx=True, ex=MONTHLY_BUDGET_TTL_SECONDS):
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


async def x__notify_degrade_once__mutmut_16(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=user_id, window=get_time_window_key(RateLimitPeriod.MONTH)
        )
        if not await client.set(key, "1", ex=MONTHLY_BUDGET_TTL_SECONDS):
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


async def x__notify_degrade_once__mutmut_17(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=user_id, window=get_time_window_key(RateLimitPeriod.MONTH)
        )
        if not await client.set(key, "1", nx=True, ):
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


async def x__notify_degrade_once__mutmut_18(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=user_id, window=get_time_window_key(RateLimitPeriod.MONTH)
        )
        if not await client.set(key, "XX1XX", nx=True, ex=MONTHLY_BUDGET_TTL_SECONDS):
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


async def x__notify_degrade_once__mutmut_19(user_id: str) -> None:
    """In-app notice on the FIRST degraded turn of the month (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        key = COST_BUDGET_NOTIFIED_KEY.format(
            user_id=user_id, window=get_time_window_key(RateLimitPeriod.MONTH)
        )
        if not await client.set(key, "1", nx=False, ex=MONTHLY_BUDGET_TTL_SECONDS):
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


async def x__notify_degrade_once__mutmut_20(user_id: str) -> None:
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
        reset_time = None
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


async def x__notify_degrade_once__mutmut_21(user_id: str) -> None:
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
        reset_time = get_reset_time(None)
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


async def x__notify_degrade_once__mutmut_22(user_id: str) -> None:
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
            None
        )
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Degrade notice failed",
            error=str(e),
            error_type=type(e).__name__,
        )


async def x__notify_degrade_once__mutmut_23(user_id: str) -> None:
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
                user_id=None,
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


async def x__notify_degrade_once__mutmut_24(user_id: str) -> None:
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
                source=None,
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


async def x__notify_degrade_once__mutmut_25(user_id: str) -> None:
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
                type=None,
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


async def x__notify_degrade_once__mutmut_26(user_id: str) -> None:
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
                type=NotificationType.INFO,
                content=None,
            )
        )
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Degrade notice failed",
            error=str(e),
            error_type=type(e).__name__,
        )


async def x__notify_degrade_once__mutmut_27(user_id: str) -> None:
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


async def x__notify_degrade_once__mutmut_28(user_id: str) -> None:
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


async def x__notify_degrade_once__mutmut_29(user_id: str) -> None:
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


async def x__notify_degrade_once__mutmut_30(user_id: str) -> None:
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
                type=NotificationType.INFO,
                )
        )
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Degrade notice failed",
            error=str(e),
            error_type=type(e).__name__,
        )


async def x__notify_degrade_once__mutmut_31(user_id: str) -> None:
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
                type=NotificationType.INFO,
                content=NotificationContent(
                    title=None,
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


async def x__notify_degrade_once__mutmut_32(user_id: str) -> None:
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
                type=NotificationType.INFO,
                content=NotificationContent(
                    title="Priority compute used for this month",
                    body=None,
                ),
            )
        )
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Degrade notice failed",
            error=str(e),
            error_type=type(e).__name__,
        )


async def x__notify_degrade_once__mutmut_33(user_id: str) -> None:
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
                type=NotificationType.INFO,
                content=NotificationContent(
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


async def x__notify_degrade_once__mutmut_34(user_id: str) -> None:
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
                type=NotificationType.INFO,
                content=NotificationContent(
                    title="Priority compute used for this month",
                    ),
            )
        )
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Degrade notice failed",
            error=str(e),
            error_type=type(e).__name__,
        )


async def x__notify_degrade_once__mutmut_35(user_id: str) -> None:
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
                type=NotificationType.INFO,
                content=NotificationContent(
                    title="XXPriority compute used for this monthXX",
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


async def x__notify_degrade_once__mutmut_36(user_id: str) -> None:
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
                type=NotificationType.INFO,
                content=NotificationContent(
                    title="priority compute used for this month",
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


async def x__notify_degrade_once__mutmut_37(user_id: str) -> None:
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
                type=NotificationType.INFO,
                content=NotificationContent(
                    title="PRIORITY COMPUTE USED FOR THIS MONTH",
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


async def x__notify_degrade_once__mutmut_38(user_id: str) -> None:
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
                type=NotificationType.INFO,
                content=NotificationContent(
                    title="Priority compute used for this month",
                    body=(
                        "XXYou've used this month's priority AI compute. GAIA keeps XX"
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


async def x__notify_degrade_once__mutmut_39(user_id: str) -> None:
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
                type=NotificationType.INFO,
                content=NotificationContent(
                    title="Priority compute used for this month",
                    body=(
                        "you've used this month's priority ai compute. gaia keeps "
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


async def x__notify_degrade_once__mutmut_40(user_id: str) -> None:
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
                type=NotificationType.INFO,
                content=NotificationContent(
                    title="Priority compute used for this month",
                    body=(
                        "YOU'VE USED THIS MONTH'S PRIORITY AI COMPUTE. GAIA KEEPS "
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


async def x__notify_degrade_once__mutmut_41(user_id: str) -> None:
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
            None,
            error=str(e),
            error_type=type(e).__name__,
        )


async def x__notify_degrade_once__mutmut_42(user_id: str) -> None:
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
            error=None,
            error_type=type(e).__name__,
        )


async def x__notify_degrade_once__mutmut_43(user_id: str) -> None:
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
            error_type=None,
        )


async def x__notify_degrade_once__mutmut_44(user_id: str) -> None:
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
            error=str(e),
            error_type=type(e).__name__,
        )


async def x__notify_degrade_once__mutmut_45(user_id: str) -> None:
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
            error_type=type(e).__name__,
        )


async def x__notify_degrade_once__mutmut_46(user_id: str) -> None:
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
            )


async def x__notify_degrade_once__mutmut_47(user_id: str) -> None:
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
            error=str(None),
            error_type=type(e).__name__,
        )


async def x__notify_degrade_once__mutmut_48(user_id: str) -> None:
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
            error_type=type(None).__name__,
        )

mutants_x__notify_degrade_once__mutmut['_mutmut_orig'] = x__notify_degrade_once__mutmut_orig # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_1'] = x__notify_degrade_once__mutmut_1 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_2'] = x__notify_degrade_once__mutmut_2 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_3'] = x__notify_degrade_once__mutmut_3 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_4'] = x__notify_degrade_once__mutmut_4 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_5'] = x__notify_degrade_once__mutmut_5 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_6'] = x__notify_degrade_once__mutmut_6 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_7'] = x__notify_degrade_once__mutmut_7 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_8'] = x__notify_degrade_once__mutmut_8 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_9'] = x__notify_degrade_once__mutmut_9 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_10'] = x__notify_degrade_once__mutmut_10 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_11'] = x__notify_degrade_once__mutmut_11 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_12'] = x__notify_degrade_once__mutmut_12 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_13'] = x__notify_degrade_once__mutmut_13 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_14'] = x__notify_degrade_once__mutmut_14 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_15'] = x__notify_degrade_once__mutmut_15 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_16'] = x__notify_degrade_once__mutmut_16 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_17'] = x__notify_degrade_once__mutmut_17 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_18'] = x__notify_degrade_once__mutmut_18 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_19'] = x__notify_degrade_once__mutmut_19 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_20'] = x__notify_degrade_once__mutmut_20 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_21'] = x__notify_degrade_once__mutmut_21 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_22'] = x__notify_degrade_once__mutmut_22 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_23'] = x__notify_degrade_once__mutmut_23 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_24'] = x__notify_degrade_once__mutmut_24 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_25'] = x__notify_degrade_once__mutmut_25 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_26'] = x__notify_degrade_once__mutmut_26 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_27'] = x__notify_degrade_once__mutmut_27 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_28'] = x__notify_degrade_once__mutmut_28 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_29'] = x__notify_degrade_once__mutmut_29 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_30'] = x__notify_degrade_once__mutmut_30 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_31'] = x__notify_degrade_once__mutmut_31 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_32'] = x__notify_degrade_once__mutmut_32 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_33'] = x__notify_degrade_once__mutmut_33 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_34'] = x__notify_degrade_once__mutmut_34 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_35'] = x__notify_degrade_once__mutmut_35 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_36'] = x__notify_degrade_once__mutmut_36 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_37'] = x__notify_degrade_once__mutmut_37 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_38'] = x__notify_degrade_once__mutmut_38 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_39'] = x__notify_degrade_once__mutmut_39 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_40'] = x__notify_degrade_once__mutmut_40 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_41'] = x__notify_degrade_once__mutmut_41 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_42'] = x__notify_degrade_once__mutmut_42 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_43'] = x__notify_degrade_once__mutmut_43 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_44'] = x__notify_degrade_once__mutmut_44 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_45'] = x__notify_degrade_once__mutmut_45 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_46'] = x__notify_degrade_once__mutmut_46 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_47'] = x__notify_degrade_once__mutmut_47 # type: ignore # mutmut generated
mutants_x__notify_degrade_once__mutmut['x__notify_degrade_once__mutmut_48'] = x__notify_degrade_once__mutmut_48 # type: ignore # mutmut generated


__all__ = [
    "AgentRole",
    "LLMProviderName",
    "ModelLane",
    "dev_model_id",
    "dev_option_for",
    "resolve_lane",
]
