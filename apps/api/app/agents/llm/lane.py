"""The resolved answer to "which model will this run call, and how".

One immutable :class:ModelLane is resolved once per user turn by
:func:resolve_lane and then carried verbatim — to the executor, to every
spawned subagent, across a queue hop, through a HIL resume. Everything
downstream reads the lane instead of re-deriving a model from loose keys, so
there is exactly one place a lane can be wrong.

This replaces a pipeline of in-place mutations spread across six files in which
every key propagated by a different rule: some parent-overrides, some
child-wins, reasoning deliberately not inherited at all, and several dropped
entirely by the queue's serializer. That table is what made model selection
unreadable and its bugs invisible.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from pydantic import TypeAdapter

from app.agents.llm.client import chat_model, chat_route, provider_configured
from app.agents.llm.dev_lane import dev_default_model_id, dev_default_option
from app.config.settings import settings
from app.constants.llm import (
    AUX_MODEL_NAME,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
    DEV_MODEL_OPTIONS,
    MODEL_FIELD_ID,
    MODEL_KWARGS_FIELD_ID,
    OPENROUTER_PROVIDER_ROUTING,
    OPENROUTER_REASONING,
    PAID_COMMS_REASONING,
    PAID_MODEL_NAME,
    PAID_MODEL_PROVIDER,
    PROVIDER_FIELD_ID,
    REASONING_FIELD_ID,
    DevModelOption,
    LaneConfig,
    LLMProviderName,
    OpenRouterModelKwargs,
    OpenRouterReasoning,
)
from app.constants.log_tags import LogTag
from app.models.agent_models import AgentConfigurable
from app.models.payment_models import PlanType
from app.services.payments.payment_service import payment_service
from shared.py.wide_events import log

#: Every configurable key a lane owns. These must be REPLACED wholesale on a lane
#: change, never merged into — a leftover key is the previous lane still steering
#: the request.
BINDING_FIELD_IDS: frozenset[str] = frozenset(
    {PROVIDER_FIELD_ID, MODEL_FIELD_ID, REASONING_FIELD_ID, MODEL_KWARGS_FIELD_ID}
)


#: Validates a stored lane at the boundary where it comes back off a configurable:
#: a queue hop and a HIL resume hand it back as plain JSON.
_LANE_CONFIG: TypeAdapter[LaneConfig] = TypeAdapter(LaneConfig)


class AgentRole(StrEnum):
    """Which tier is asking for a lane.

    Only the reasoning budget differs by role today — see :func:_reasoning_for.
    """

    COMMS = "comms"
    EXECUTOR = "executor"
    SUBAGENT = "subagent"


@dataclass(frozen=True, slots=True)
class ModelLane:
    """A complete, resolved model selection.

    Immutable on purpose: a lane is decided once per turn and inherited,
    never edited in flight.
    """

    #: The logical lane, not a free string: an unknown provider must fail at the
    #: boundary that produced it, not as a silent miss in the alternatives map.
    provider: LLMProviderName
    #: ``None`` means "let the client use its own configured default" — the
    #: env-defined custom dev endpoint serves ``DEV_LLM_MODEL`` this way.
    model: str | None
    reasoning: OpenRouterReasoning | None
    #: The model's own OpenRouter routing, from OPENROUTER_PROVIDER_ROUTING via
    #: _provider_pin wherever a lane picks its model.
    provider_pin: OpenRouterModelKwargs | None
    max_input_tokens: int

    def to_configurable(self) -> LaneConfig:
        """Return the JSON-safe form stored on configurable[LANE_CONFIG_KEY]."""
        return {
            "provider": self.provider,
            "model": self.model,
            "reasoning": self.reasoning,
            "provider_pin": self.provider_pin,
            "max_input_tokens": self.max_input_tokens,
        }

    def binding_keys(self) -> AgentConfigurable:
        """Return the top-level configurable keys LangChain's own field resolution reads.

        Written ONLY by build_agent_config, read only by LangChain. A key is
        omitted rather than set to None so the client's own default survives —
        the custom dev endpoint pins no model, and a non-reasoning model must
        not carry a reasoning pin.
        """
        # Literal keys, not the *_FIELD_ID constants: mypy only checks TypedDict
        # keys when they are literals (`literal-required`).
        keys: AgentConfigurable = {"provider": self.provider}
        if self.model is not None:
            keys["model"] = self.model
        if self.reasoning is not None:
            keys["reasoning"] = self.reasoning
        if self.provider_pin is not None:
            keys["model_kwargs"] = self.provider_pin
        return keys

    def rebind(self, configurable: Mapping[str, object]) -> dict[str, object]:
        """Build configurable with THIS lane's binding keys, and the previous lane's cleared.

        A plain merge is not enough: LangChain merges a passed config OVER a
        with_config one, so re-passing the run's config restored the just-failed
        provider. Stale keys must be REMOVED, not overwritten — an un-cleared
        model_kwargs would carry the old provider's routing onto the new one.
        """
        return {
            **{k: v for k, v in configurable.items() if k not in BINDING_FIELD_IDS},
            **self.binding_keys(),
        }

    @classmethod
    def from_configurable(cls, raw: object) -> "ModelLane | None":
        """Rebuild a lane from a configurable, or None when there isn't one.

        A bag written before lanes existed has none, and the caller resolves a
        fresh lane. A present lane is validated whole and raises ValidationError.
        """
        if not isinstance(raw, dict) or "provider" not in raw:
            return None
        config: LaneConfig = _LANE_CONFIG.validate_python(raw)
        return cls(
            provider=config["provider"],
            model=config["model"],
            reasoning=config["reasoning"],
            provider_pin=config["provider_pin"],
            max_input_tokens=config["max_input_tokens"],
        )

    def fallback(self) -> "ModelLane | None":
        """Return the same run on the next configured provider, or None when there is no other one.

        The reasoning config is dropped and the pin re-derived for the new model:
        carrying either onto a different provider is how a fallback turns one
        failure into two.
        """
        nxt = chat_route(self.provider)
        if nxt is None:
            return None
        provider, model = nxt
        return replace(
            self,
            provider=provider,
            model=model,
            provider_pin=_provider_pin(provider, model),
            reasoning=None,
        )


def _provider_pin(provider: LLMProviderName, model: str | None) -> OpenRouterModelKwargs | None:
    """Return model's routing pin on OpenRouter; any other provider takes none."""
    if provider is not LLMProviderName.OPENROUTER or model is None:
        return None
    return OPENROUTER_PROVIDER_ROUTING.get(model)


def _reasoning_for(role: AgentRole) -> OpenRouterReasoning:
    """Return the effort a PAID lane gives each role. The free lane's is fixed in :func:_default_lane.

    Comms gets its own knob so it can be raised past the executor's default.
    It must never resolve BELOW the free lane's effort — it once sat at low
    against free's medium, a paying user's agent thinking less than a free one's.
    """
    if role is AgentRole.COMMS:
        return PAID_COMMS_REASONING
    return OPENROUTER_REASONING


def _default_lane() -> ModelLane:
    """Return the lane for a default (free or unresolved-plan) turn.

    Hosted instances run OpenRouter's default model exactly as always. Without
    OpenRouter the highest-priority usable chat provider serves, so LangChain is
    never asked for a lane that has no config; with none at all, the OpenRouter
    lane fails loud at load time naming the fix.
    """
    route = chat_route()
    if route is not None:
        provider, model = route
        is_openrouter = provider is LLMProviderName.OPENROUTER
        return ModelLane(
            provider=provider,
            model=model,
            # A reasoning pin is OpenRouter-wire only.
            reasoning=OPENROUTER_REASONING if is_openrouter else None,
            provider_pin=_provider_pin(provider, model),
            max_input_tokens=DEFAULT_MAX_TOKENS,
        )
    return ModelLane(
        provider=LLMProviderName(DEFAULT_LLM_PROVIDER),
        model=DEFAULT_MODEL_NAME,
        reasoning=OPENROUTER_REASONING,
        provider_pin=_provider_pin(LLMProviderName(DEFAULT_LLM_PROVIDER), DEFAULT_MODEL_NAME),
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def helper_lane() -> ModelLane:
    """Return the lane resolve_model(ModelUse.HELPER) serves, for an agent graph run on it.

    Accounting prices a call by its run's lane, so a graph on the helper model needs this
    on its configurable or its calls price as unknown.
    """
    return ModelLane(
        provider=LLMProviderName.OPENROUTER,
        model=AUX_MODEL_NAME,
        reasoning=None,
        provider_pin=None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def _comms_lane() -> ModelLane | None:
    """Return comms' own direct-OpenAI lane, or None when OpenAI is not configured."""
    if not provider_configured(LLMProviderName.OPENAI):
        return None
    return ModelLane(
        provider=LLMProviderName.OPENAI,
        model=chat_model(LLMProviderName.OPENAI),
        # The effort is fixed on the client; a reasoning key would only be ignored.
        reasoning=None,
        provider_pin=None,
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def inherits_lane(parent_lane: ModelLane, role: AgentRole) -> bool:
    """Whether a child run in role takes its parent's lane; comms' OpenAI lane never passes down."""
    return role is AgentRole.COMMS or parent_lane.provider is not LLMProviderName.OPENAI


def _dev_lane(option: DevModelOption, role: AgentRole) -> ModelLane:
    """Build a lane pinned from the DEV-ONLY model menu.

    An entry may carry no model (the env-defined "custom" endpoint); the lane
    resolves the provider's chat model instead of leaving it None, so
    accounting sees the real name instead of metering as "unknown". None
    survives only when no model is configured at all.
    """
    model = option.model or chat_model(option.provider)
    return ModelLane(
        provider=option.provider,
        model=model,
        reasoning=_reasoning_for(role) if option.reasoning else None,
        provider_pin=_provider_pin(option.provider, model),
        max_input_tokens=DEFAULT_MAX_TOKENS,
    )


def dev_model_id(model_id: str | None, use_defaults: bool) -> str | None:
    """Return the dev-menu key a request selected, or None.

    use_defaults means the request expressed no preference, so the
    env-configured DEV_DEFAULT_MODEL applies. An explicit choice wins over it;
    an unknown id selects nothing.
    """
    if use_defaults:
        return dev_default_model_id()
    return model_id if model_id in DEV_MODEL_OPTIONS else None


def dev_option(model_id: str | None) -> DevModelOption | None:
    """Return the dev-menu entry for an ALREADY-resolved id.

    Re-running the resolution downstream would only give DEV_DEFAULT_MODEL a
    second chance to override comms' already-stashed explicit choice.
    """
    return DEV_MODEL_OPTIONS.get(model_id) if model_id else None


def dev_option_for(model_id: str | None, use_defaults: bool) -> DevModelOption | None:
    """Return the dev-menu entry a request selected, or None."""
    return dev_option(dev_model_id(model_id, use_defaults))


async def resolve_lane(
    user_id: str | None,
    role: AgentRole,
    dev_option: DevModelOption | None = None,
) -> tuple[ModelLane, PlanType | None]:
    """Choose the single model. Returns the lane and the plan tier it was resolved from.

    Comms runs its own lane on every plan, otherwise free runs the default model
    and paid the paid model.
    In development an explicit dev_option, else DEV_DEFAULT_MODEL, wins over all
    of it: every top-level run, not only chat, starts on it.
    """
    dev_option = dev_option or dev_default_option()
    if dev_option is not None:
        return _dev_lane(dev_option, role), None

    comms_lane = _comms_lane() if role is AgentRole.COMMS else None
    if not user_id:
        return comms_lane or _default_lane(), None

    try:
        plan = await payment_service.get_cached_plan_type(user_id)
    except Exception as e:
        # A transient lookup failure must not fail the turn — keep the default.
        log.warning(f"{LogTag.AGENT} plan lookup failed; keeping the default lane", error=str(e))
        return comms_lane or _default_lane(), None

    if comms_lane is not None:
        return comms_lane, plan

    # Without plans every user is Pro, yet the paid model is a hosted tier: the
    # instance's own configured lane serves everyone.
    if plan == PlanType.FREE or not settings.deployment.enforces_plans:
        return _default_lane(), plan

    return (
        ModelLane(
            provider=LLMProviderName(PAID_MODEL_PROVIDER),
            model=PAID_MODEL_NAME,
            reasoning=_reasoning_for(role),
            provider_pin=_provider_pin(LLMProviderName(PAID_MODEL_PROVIDER), PAID_MODEL_NAME),
            max_input_tokens=DEFAULT_MAX_TOKENS,
        ),
        plan,
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
