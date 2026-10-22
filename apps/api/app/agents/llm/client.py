import asyncio
from contextlib import suppress
from dataclasses import dataclass, replace
from functools import cache
import math
import time
from typing import Any, TypedDict, TypeVar, cast
from urllib.parse import urlparse

from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler
from langchain_core.language_models import LanguageModelInput, LanguageModelLike
from langchain_core.language_models.chat_models import (
    BaseChatModel,
)
from langchain_core.messages import AIMessage, BaseMessage, InvalidToolCall, ToolCall
from langchain_core.messages.ai import InputTokenDetails, OutputTokenDetails, UsageMetadata
from langchain_core.outputs import LLMResult
from langchain_core.runnables import (
    Runnable,
    RunnableBinding,
    RunnableConfig,
    RunnableLambda,
    RunnableSequence,
)
from langchain_core.runnables.utils import ConfigurableField
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_openrouter import ChatOpenRouter
from openrouter.utils import BackoffStrategy, RetryConfig
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from app.agents.llm.dev_lane import (
    build_custom_chat_model,
    custom_endpoint,
    custom_lane_forced,
)
from app.agents.llm.exceptions import (
    LLM_FALLBACK_EXCEPTIONS,
    LLM_RETRYABLE_EXCEPTIONS,
    LLMNotConfiguredError,
    MalformedStructuredOutputError,
)
from app.agents.llm.types import LLMFallback, LLMProvider, ProviderLLM
from app.config.settings import settings
from app.constants.llm import (
    AUX_SESSION_SUFFIX,
    COMMS_REASONING_EFFORT,
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
    DEV_LLM_MAX_OUTPUT_TOKENS,
    FALLBACK_MODEL_METADATA_KEY,
    FELL_BACK_METADATA_KEY,
    HELPER_MAX_OUTPUT_TOKENS,
    HIL_JUDGE_FALLBACK_MODEL_NAMES,
    LLM_INVOKE_TIMEOUT_SECONDS,
    LLM_LABEL_METADATA_KEY,
    LLM_RETRY_MAX_ATTEMPTS,
    MODEL_FIELD_ID,
    MODEL_KWARGS_FIELD_ID,
    OLLAMA_PLACEHOLDER_API_KEY,
    OPENAI_MAX_OUTPUT_TOKENS,
    OPENAI_REASONING_EFFORT,
    OPENROUTER_APP_CATEGORIES,
    OPENROUTER_APP_TITLE,
    OPENROUTER_DEV_APP_TITLE,
    OPENROUTER_DEV_APP_URL,
    OPENROUTER_MAX_OUTPUT_TOKENS,
    OPENROUTER_REASONING,
    OPENROUTER_REASONING_EFFORT,
    REASONING_FIELD_ID,
    SIM_STUB_API_KEY,
    SIM_STUB_BASE_URL,
    SIM_STUB_MODEL_NAME,
    UNKNOWN_MODEL_NAME,
    LLMProviderKey,
    LLMProviderName,
    ModelUse,
    OpenRouterModelKwargs,
    ReasoningLevel,
)
from app.constants.log_tags import LogTag
from app.constants.providers import (
    HOSTED_COMMS_ONLY_PROVIDERS,
    HOSTED_ONE_SHOT_PROVIDERS,
    LLM_MODEL_PROFILES,
    LLM_PROVIDER_PRIORITY,
    CredentialProviderName,
)
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.models.agent_config import AgentConfigurable
from app.models.agent_models import agent_configurable
from app.services.llm_metering import (
    LLMCallContext,
    TokenUsage,
    extract_finish_reason,
    extract_message_cost,
    extract_message_provider,
    record_failed_llm_call,
    record_llm_call,
    resolve_channel,
)
from app.services.providers.provider_credentials_service import (
    ProviderConfig,
    is_usable,
    on_local_invalidation,
    resolve,
    resolved_config,
    resolved_configs,
)
from app.services.providers.provider_registry import PROVIDER_SPECS
from shared.py.wide_events import log

_StructuredT = TypeVar("_StructuredT", bound=BaseModel)
_ResultT = TypeVar("_ResultT")
# The custom lane runs ChatOpenAI, every other lane ChatOpenRouter; both are
# BaseChatModel. Identity-preserving so each caller keeps its concrete type.
_LLMT = TypeVar("_LLMT", bound=BaseChatModel)


# NOSONAR justification: intentional pass-through -- normalizes retries in place and returns the same client for chaining
def without_sdk_retry(llm: _LLMT) -> _LLMT:  # NOSONAR python:S3516
    """Disable the SDK's own retry loop so with_llm_retry is the only one.

    The SDK loop nests under ours and turned 3 attempts into 40 requests.
    max_retries=0 does NOT disable it (the SDK then applies a one-hour
    default); only clearing retry_config does.
    """
    sdk_client = getattr(llm, "client", None)
    sdk_config = getattr(sdk_client, "sdk_configuration", None)
    if sdk_config is None:
        # Not an OpenRouter-SDK client (e.g. ChatOpenAI on the custom lane):
        # nothing SDK-side to disable, retries are already ours alone.
        return llm
    # Equivalent to a None retry_config, which the SDK also runs without retrying.
    sdk_config.retry_config = RetryConfig(
        # Any strategy but "backoff" skips the retry path, so the (required)
        # backoff values below are never read.
        strategy="none",
        backoff=BackoffStrategy(
            initial_interval=0, max_interval=0, exponent=1.0, max_elapsed_time=0
        ),
        retry_connection_errors=False,
    )  # pragma: no mutate
    return llm


def with_llm_retry(runnable: Runnable, *, max_attempts: int = LLM_RETRY_MAX_ATTEMPTS) -> Runnable:
    """Wrap runnable with the single, canonical LLM retry policy.

    Applied AFTER bind_tools so the RunnableRetry wrapper never has to expose
    bind_tools. max_attempts=1 disables retry for callers on a hard latency
    budget.
    """
    return runnable.with_retry(
        retry_if_exception_type=LLM_RETRYABLE_EXCEPTIONS,
        stop_after_attempt=max_attempts,
        wait_exponential_jitter=True,
    )


NO_PROVIDER_CONFIGURED_MESSAGE = (
    "No AI provider configured. Open Settings → AI Providers or run the setup wizard."
)


async def refresh_provider_configs() -> None:
    """Resolve every credential-backed provider, so sync readers see the store without awaiting.

    Each resolve mirrors into the credential service's snapshot; until the first
    refresh lands, sync readers read the env fallback.
    """
    await asyncio.gather(*(resolve(name) for name in CredentialProviderName))


_refresh_tasks: set[asyncio.Task[None]] = set()


def _on_refresh_done(task: asyncio.Task[None]) -> None:
    """Drop the finished refresh task; log loud if it failed."""
    _refresh_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error(
            "Runtime provider-config refresh failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )


def _schedule_runtime_config_refresh() -> None:
    """Best-effort snapshot refresh when an event loop is already running.

    Fire-and-forget by design: registration and cache invalidation are sync
    seams inside async contexts (lifespan, request handlers), where blocking on
    the resolver is impossible. Outside a loop (eval scripts, unit tests) it is
    a no-op — those run on env fallback, which is their contract.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(refresh_provider_configs())
    _refresh_tasks.add(task)
    task.add_done_callback(_on_refresh_done)


def _require_provider_config(provider: LLMProviderName) -> ProviderConfig:
    """Return the provider's config for building a client; raise the actionable self-host error when it cannot serve one."""
    credential = CredentialProviderName(provider)
    config: ProviderConfig | None = resolved_config(credential)
    if config is None or not is_usable(credential, config):
        raise LLMNotConfiguredError(NO_PROVIDER_CONFIGURED_MESSAGE)
    return config


def chat_model(provider: LLMProviderName) -> str | None:
    """Return the model a provider's chat lane runs: the operator's configured one, else the catalog's.

    None only when neither exists (a custom endpoint saved without a model).
    Production reads env alone, which never names a model, so it runs the catalog's.
    """
    config: ProviderConfig | None = resolved_config(CredentialProviderName(provider))
    configured = config.model if config else None
    return configured or LLM_MODEL_PROFILES[provider].chat


def _is_hosted_comms_only(provider: LLMProviderName) -> bool:
    """Whether production keeps provider to comms' own lane (see HOSTED_COMMS_ONLY_PROVIDERS)."""
    return settings.deployment.hosted_models and provider in HOSTED_COMMS_ONLY_PROVIDERS


def _chat_priority() -> tuple[LLMProviderName, ...]:
    """Return the providers a default lane or fallback may take, in order; comms-only ones never in production."""
    return tuple(p for p in LLM_PROVIDER_PRIORITY if not _is_hosted_comms_only(p))


@cache
def _sim_llm(temperature: float = DEFAULT_LLM_TEMPERATURE) -> ChatOpenRouter:
    """Build the one model used for EVERYTHING under GAIA_SIM_MODE.

    An OpenAI-wire client pointed at the local scripted stub (tools/llm-stub).
    Exposes no configurable fields — pinned provider/model config is silently
    ignored, since every request lands on the stub regardless.
    """
    llm = without_sdk_retry(
        ChatOpenRouter(
            model=SIM_STUB_MODEL_NAME,
            temperature=temperature,
            streaming=True,
            stream_usage=True,
            api_key=SecretStr(settings.OPENROUTER_API_KEY or SIM_STUB_API_KEY),
            base_url=settings.OPENROUTER_BASE_URL or SIM_STUB_BASE_URL,
        )
    )
    # Same reason as _build_default_llm: fractional-window middleware needs a
    # context-window profile at graph-build time.
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return llm


# Gemini's own attribute is ``model``; OpenRouter's is ``model_name`` (see
# _openrouter_wire_configurables). One id, one meaning across both lanes.
_MODEL_FIELD = ConfigurableField(id=MODEL_FIELD_ID, name="Model", description="Which model to use")


def _openrouter_wire_configurables(llm: ChatOpenRouter) -> LanguageModelLike:
    """Attach the per-request configurable fields shared by every OpenRouter-wire client.

    Covers the real OpenRouter and the env-defined custom endpoint. The field
    ids form one namespace across provider alternatives (prefix_keys=False), so
    every compatible client must expose identical ids.
    """
    return llm.configurable_fields(
        model_name=_MODEL_FIELD,
        reasoning=ConfigurableField(
            id=REASONING_FIELD_ID,
            name="Reasoning",
            description="Reasoning effort (per-agent thinking budget)",
        ),
        model_kwargs=ConfigurableField(
            id=MODEL_KWARGS_FIELD_ID,
            name="Model kwargs",
            description="Extra request params (e.g. provider routing pin)",
        ),
    )


@lazy_provider(
    name=LLMProviderKey.GEMINI,
    required_keys=[],
    strategy=MissingKeyStrategy.WARN,
    warning_message="Google API key not configured. Models provided by Google Gemini will not work.",
)
def init_gemini_llm() -> LanguageModelLike:
    """Initialize Gemini LLM with default model."""
    if settings.GAIA_SIM_MODE:
        return _sim_llm()
    config: ProviderConfig = _require_provider_config(LLMProviderName.GEMINI)
    llm = ChatGoogleGenerativeAI(
        model=config.model or LLM_MODEL_PROFILES[LLMProviderName.GEMINI].chat,
        temperature=DEFAULT_LLM_TEMPERATURE,
        streaming=True,
        google_api_key=config.api_key,
    )
    # Every chat LLM must carry the context-window profile — fractional-token
    # middleware (summarization/compaction triggers) raises without it. Same
    # contract as _build_default_llm/_sim_llm/init_custom_llm.
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return llm.configurable_fields(model=_MODEL_FIELD)


class _AppAttribution(TypedDict):
    """Keyword shape of ChatOpenRouter's attribution params, checked against the client's signature."""

    app_url: str
    app_title: str
    app_categories: list[str]


def _app_attribution() -> _AppAttribution:
    """OpenRouter app-attribution params, for EVERY real OpenRouter client.

    Only GAIA Cloud is attributed to GAIA's app; elsewhere a synthetic referer
    stands in, since a localhost FRONTEND_URL lands in "unknown app". Shared by
    the graph and aux lanes, which once reported as "unknown" without it.
    """
    if settings.deployment.hosted_models:
        return {
            "app_url": settings.FRONTEND_URL,
            "app_title": OPENROUTER_APP_TITLE,
            "app_categories": OPENROUTER_APP_CATEGORIES,
        }
    return {
        "app_url": OPENROUTER_DEV_APP_URL,
        "app_title": OPENROUTER_DEV_APP_TITLE,
        "app_categories": OPENROUTER_APP_CATEGORIES,
    }


@lazy_provider(
    name=LLMProviderKey.OPENROUTER,
    required_keys=[],
    strategy=MissingKeyStrategy.WARN,
    warning_message="OpenRouter API key not configured. Models provided via OpenRouter (Grok, etc.) will not work.",
)
def init_openrouter_llm() -> LanguageModelLike:
    """Initialize the OpenRouter LLM (MiniMax M3, Grok, etc.).

    Uses ChatOpenRouter, not ChatOpenAI, because it parses OpenRouter's
    reasoning/reasoning_details fields into standard reasoning content blocks —
    ChatOpenAI silently drops them. Reasoning effort and provider routing
    (model_kwargs) are both per-request configurable.
    """
    if settings.GAIA_SIM_MODE:
        return _sim_llm()
    config: ProviderConfig = _require_provider_config(LLMProviderName.OPENROUTER)
    # No base_url kwarg unless the resolved config carries one: passing None
    # would override the field's OPENROUTER_API_BASE env default_factory.
    # Redirecting to the stub is sim mode's job (_sim_llm).
    base_url = config.base_url
    base_url_kwargs: dict[str, Any] = {"base_url": base_url} if base_url else {}
    llm = without_sdk_retry(
        ChatOpenRouter(
            model=config.model or LLM_MODEL_PROFILES[LLMProviderName.OPENROUTER].chat,
            temperature=DEFAULT_LLM_TEMPERATURE,
            streaming=True,
            stream_usage=True,
            # Output cap; must stay well under the model's shared input+output context
            # window (see OPENROUTER_MAX_OUTPUT_TOKENS) or OpenRouter rejects the request.
            max_tokens=OPENROUTER_MAX_OUTPUT_TOKENS,
            api_key=SecretStr(config.api_key),
            **base_url_kwargs,
            # App attribution → OpenRouter rankings/analytics. ChatOpenRouter exposes
            # these as dedicated params (NOT `default_headers`, which it forwards to
            # send_async and crashes on). https://openrouter.ai/docs/app-attribution
            **_app_attribution(),
            # Without it this lane drew twelve different upstreams in a month, at
            # rates 10x apart. session_id sticky routing composes with `order`
            # (measured: order + session lands on the ordered upstream every time).
            **_provider_order_kwargs(),
            # Unpacked: ChatOpenRouter declares reasoning as a plain dict.
            reasoning={**OPENROUTER_REASONING},
        )
    )
    # Every chat LLM must carry the context-window profile — fractional-token
    # middleware (summarization/compaction triggers) raises without it. Same
    # contract as _build_default_llm/_sim_llm/init_gemini_llm/init_custom_llm.
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return _openrouter_wire_configurables(llm)


@lazy_provider(
    name=LLMProviderKey.OLLAMA,
    required_keys=[],
    strategy=MissingKeyStrategy.WARN,
    warning_message="Ollama endpoint not configured. Models provided by Ollama will not work.",
)
def init_ollama_llm() -> LanguageModelLike:
    """Initialize the local keyless Ollama LLM over its OpenAI-wire API at base_url/v1.

    The key is a constant placeholder the OpenAI client requires but Ollama ignores.
    Available only with a configured endpoint: a store credential or OLLAMA_BASE_URL.
    """
    if settings.GAIA_SIM_MODE:
        return _sim_llm()
    config: ProviderConfig = _require_provider_config(LLMProviderName.OLLAMA)
    llm = ChatOpenAI(
        model=config.model or LLM_MODEL_PROFILES[LLMProviderName.OLLAMA].chat,
        temperature=DEFAULT_LLM_TEMPERATURE,
        streaming=True,
        base_url=_ollama_openai_url(config),
        api_key=SecretStr(OLLAMA_PLACEHOLDER_API_KEY),
        max_retries=0,
    )
    # Same reason as _build_default_llm: fractional-window middleware needs a
    # context-window profile at graph-build time.
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return llm


@lazy_provider(
    name=LLMProviderKey.CUSTOM,
    required_keys=[],
    strategy=MissingKeyStrategy.WARN,
    warning_message="DEV_LLM_BASE_URL / DEV_LLM_API_KEY / DEV_LLM_MODEL not configured. The custom dev LLM endpoint will not work.",
)
def init_custom_llm() -> LanguageModelLike:
    """Build the custom OpenAI-compatible provider, constructed by dev_lane.build_custom_chat_model.

    A store-saved key makes this lane usable outside development with no restart.
    With no store entry the resolver env fallback still yields the DEV_LLM_*
    endpoint, which is how the discounted dev lanes keep working.
    """
    if settings.GAIA_SIM_MODE:
        return _sim_llm()
    # model_name is the field id both ChatOpenAI and ChatOpenRouter expose, so the
    # per-request lane can retarget the model on this client.
    return build_custom_chat_model(
        temperature=DEFAULT_LLM_TEMPERATURE,
        max_tokens=DEV_LLM_MAX_OUTPUT_TOKENS,
        endpoint=custom_endpoint(),
    ).configurable_fields(model_name=_MODEL_FIELD)


def _ollama_openai_url(config: ProviderConfig) -> str:
    """Return Ollama's OpenAI-wire API root for a config whose base_url is already required."""
    return f"{str(config.base_url).rstrip('/')}/v1"


@lazy_provider(
    name=LLMProviderKey.OPENAI,
    required_keys=[],
    strategy=MissingKeyStrategy.WARN,
    warning_message="OpenAI API key not configured. Comms falls back to the default lane.",
)
def init_openai_llm() -> LanguageModelLike:
    """Initialize the direct OpenAI client: comms' own lane, and a chat lane like any other.

    reasoning_effort, never reasoning=: any reasoning= switches ChatOpenAI to the
    Responses API, while comms stays on chat completions.
    """
    if settings.GAIA_SIM_MODE:
        return _sim_llm()
    config: ProviderConfig = _require_provider_config(LLMProviderName.OPENAI)
    llm = without_sdk_retry(
        ChatOpenAI(
            model=chat_model(LLMProviderName.OPENAI),
            reasoning_effort=COMMS_REASONING_EFFORT,
            temperature=DEFAULT_LLM_TEMPERATURE,
            streaming=True,
            stream_usage=True,
            max_completion_tokens=OPENAI_MAX_OUTPUT_TOKENS,
            max_retries=0,
            api_key=SecretStr(str(config.api_key)),
        )
    )
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return llm.configurable_fields(model_name=_MODEL_FIELD)


def init_llm(
    preferred_provider: str | None = None,
    fallback_enabled: bool = True,
) -> LanguageModelLike:
    """Initialize an LLM with configurable fallback alternatives by provider priority.

    Without a preferred_provider, uses the default priority order. Raises
    ValueError on an unknown provider, RuntimeError if none are configured.
    """
    # preferred_provider is untrusted input (a request configurable), so it stays
    # a plain str on the signature and is narrowed to the enum once validated.
    if preferred_provider and preferred_provider not in LLM_MODEL_PROFILES:
        valid_providers = list(LLM_MODEL_PROFILES)
        raise ValueError(
            f"Invalid preferred_provider '{preferred_provider}'. "
            f"Valid providers are: {valid_providers}"
        )
    preferred = LLMProviderName(preferred_provider) if preferred_provider else None

    # Get available provider instances from global providers registry
    available_providers = _get_available_providers()

    if not available_providers:
        raise RuntimeError("No LLM providers are properly configured.")

    # Determine provider order based on preferred provider or default priority
    ordered_providers = _get_ordered_providers(available_providers, preferred, fallback_enabled)

    if not ordered_providers:
        raise RuntimeError(
            f"Preferred provider '{preferred_provider}' is not available "
            f"and fallback is {'disabled' if not fallback_enabled else 'failed'}."
        )

    # Set up primary provider and alternatives
    primary_provider = ordered_providers[0]
    alternative_providers = ordered_providers[1:] if fallback_enabled else []

    log.set(
        llm={
            "model": chat_model(primary_provider.name) or primary_provider.name,
            "provider": primary_provider.name,
            "is_free": False,
        }
    )
    return _create_configurable_llm(primary_provider, alternative_providers)


def _get_available_providers() -> dict[LLMProviderName, ProviderLLM]:
    """Return the usable provider instances from the global registry, mapped by name.

    Availability follows the resolved runtime config, never the registry's
    import-time required_keys. Missing registrations are skipped: providers.get
    raises KeyError on an unregistered name, which took every agent graph down.
    """
    available: dict[LLMProviderName, ProviderLLM] = {}
    for provider_name in LLM_PROVIDER_PRIORITY:
        instance_key = PROVIDER_SPECS[CredentialProviderName(provider_name)].registry_key
        if instance_key is None or not provider_configured(provider_name):
            continue
        try:
            instance = cast(ProviderLLM | None, providers.get(instance_key))
        except KeyError:
            continue
        if instance is not None:
            available[provider_name] = instance

    return available


def provider_configured(provider_name: LLMProviderName) -> bool:
    """Report whether provider_name can serve a request under the active runtime config."""
    if settings.GAIA_SIM_MODE:
        # Sim mode pins EVERY lane to the scripted stub (the loaders return
        # _sim_llm), mirroring the old behavior where the stub key satisfied
        # every import-time required_keys list.
        return True
    credential = CredentialProviderName(provider_name)
    return is_usable(credential, resolved_config(credential))


def chat_routes() -> list[tuple[LLMProviderName, str]]:
    """Return every usable chat provider and its model, in the order lanes take them.

    A provider with no model (a custom endpoint saved without one) is skipped.
    """
    available = _get_available_providers()
    return [
        (name, model)
        for name in _chat_priority()
        if name in available and (model := chat_model(name))
    ]


def chat_route(exclude: LLMProviderName | None = None) -> tuple[LLMProviderName, str] | None:
    """Return the highest-priority usable chat provider other than exclude, and its model.

    The default lane takes it with no exclusion; a lane's fallback excludes the
    provider that just failed. None when nothing (else) is usable.
    """
    return next((route for route in chat_routes() if route[0] != exclude), None)


def _get_ordered_providers(
    available_providers: dict[LLMProviderName, ProviderLLM],
    preferred_provider: LLMProviderName | None,
    fallback_enabled: bool,
) -> list[LLMProvider]:
    """Order providers by preference and availability, returning LLMProvider objects in priority order."""
    ordered: list[LLMProvider] = []
    remaining_providers = available_providers.copy()

    # If a preferred provider is specified and available, prioritize it
    if preferred_provider and preferred_provider in available_providers:
        ordered.append(
            LLMProvider(
                name=preferred_provider,
                instance=available_providers[preferred_provider],
            )
        )
        # Remove from remaining providers to avoid duplicates
        remaining_providers.pop(preferred_provider)

    # Add remaining providers based on priority order (if fallback enabled or no preferred provider)
    if fallback_enabled or not ordered:
        ordered.extend(
            LLMProvider(name=name, instance=remaining_providers[name])
            for name in _chat_priority()
            if name in remaining_providers
        )

    # Registered as alternatives so comms can select them by name, never as the primary.
    if fallback_enabled and ordered:
        ordered.extend(
            LLMProvider(name=name, instance=instance)
            for name, instance in remaining_providers.items()
            if _is_hosted_comms_only(name)
        )

    return ordered


def _create_configurable_llm(
    primary: LLMProvider, alternatives: list[LLMProvider]
) -> LanguageModelLike:
    """Create a configurable LLM instance with fallback alternatives."""
    if not alternatives:
        # Return primary instance directly if no alternatives
        return primary.instance

    # Keyword-expanded below, so the keys must be plain str, not enum members.
    alternatives_mapping = {str(alt.name): alt.instance for alt in alternatives}

    primary_instance = primary.instance

    return primary_instance.configurable_alternatives(
        ConfigurableField(id="provider"),
        default_key=primary.name,
        prefix_keys=False,
        **alternatives_mapping,
    )


def register_llm_providers() -> None:
    """Register LLM providers in the lazy loader."""
    init_gemini_llm()
    init_openrouter_llm()
    init_openai_llm()
    init_ollama_llm()
    # The custom endpoint never registers under SaaS production, so a stray
    # DEV_LLM_* env var there still can't route real traffic. Dev and self-host
    # register it; availability still follows the resolver.
    if not settings.deployment.hosted_models:
        init_custom_llm()
    # Pull the credential store's current state into the runtime snapshot so
    # the sync paths above serve store-configured providers without awaiting.
    # No-op outside a running loop (scripts/tests stay on env fallback).
    _schedule_runtime_config_refresh()


class _ProviderOrderKwargs(TypedDict, total=False):
    """Constructor kwargs for a routed client; empty when no order is configured.

    model_kwargs is the shape ChatOpenRouter declares (dict[str, Any]); the
    routing block it carries is OpenRouterModelKwargs, built below.
    """

    model_kwargs: dict[str, Any]


def _provider_order_kwargs() -> _ProviderOrderKwargs:
    """OpenRouter provider-routing preference, from OPENROUTER_PROVIDER_ORDER.

    allow_fallbacks=False binds the order, so OpenRouter raises for with_llm_retry rather than
    switch to an UNLISTED upstream. That pins the cache to the LISTED providers, NOT to exactly
    one: calls do split across members, each warming its own chain, so a split costs one cold
    read per member, once. Measured: 90-99% cached unsplit, 49 of 114 prod threads split."""
    raw = settings.OPENROUTER_PROVIDER_ORDER
    if not raw:
        return {}
    order = [slug.strip() for slug in raw.split(",") if slug.strip()]
    if not order:
        return {}
    routing: OpenRouterModelKwargs = {"provider": {"order": order, "allow_fallbacks": False}}
    return {"model_kwargs": dict(routing)}


@cache
def _build_default_llm(
    temperature: float, api_key: str, base_url: str | None = None
) -> ChatOpenRouter:
    kwargs: dict[str, Any] = {}
    # Only forward a truthy base_url: a None kwarg would override the field's
    # OPENROUTER_API_BASE env default_factory (the shared env fallback leaves it
    # unset unless OPENROUTER_BASE_URL was explicitly configured).
    if base_url:
        kwargs["base_url"] = base_url
    llm = without_sdk_retry(
        ChatOpenRouter(
            model=DEFAULT_MODEL_NAME,
            temperature=temperature,
            # stream_usage alone is inert without streaming=True. Both match
            # init_openrouter_llm so the model fallback streams, not one lump.
            streaming=True,
            stream_usage=True,
            max_tokens=OPENROUTER_MAX_OUTPUT_TOKENS,
            api_key=SecretStr(api_key),
            **_app_attribution(),
            **kwargs,
            **_provider_order_kwargs(),
        )
    )
    # LangChain's curated profile registry lags new model releases; the
    # summarization/compaction middleware expresses limits as a FRACTION of
    # the window and raises at construction without a profile here.
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return llm


def _one_shot_model(provider: LLMProviderName, use: ModelUse) -> str | None:
    """Return the model provider runs use on, or None when it cannot serve it.

    A text use the catalog leaves open runs on the provider's chat model;
    vision never does, since a chat pick may be blind.
    """
    catalog = LLM_MODEL_PROFILES[provider].for_use(use)
    if catalog is not None or use is ModelUse.VISION:
        return catalog
    return chat_model(provider)


def one_shot_route(use: ModelUse) -> tuple[LLMProviderName, str] | None:
    """Return the provider and model a one-shot use runs on, or None when nothing configured can serve it.

    Production runs the hosted table and nothing else. Elsewhere the hosted
    provider still comes first, then every configured provider in priority order.
    """
    hosted = HOSTED_ONE_SHOT_PROVIDERS[use]
    candidates = (
        (hosted,) if settings.deployment.hosted_models else (hosted, *LLM_PROVIDER_PRIORITY)
    )
    for provider in candidates:
        if provider_configured(provider) and (model := _one_shot_model(provider, use)):
            return provider, model
    return None


def resolve_model(
    use: ModelUse = ModelUse.HELPER,
    *,
    temperature: float = DEFAULT_LLM_TEMPERATURE,
    reasoning: ReasoningLevel | None = None,
) -> BaseChatModel:
    """Return the chat model a one-shot call for use runs on: the one place a one-shot's model is chosen.

    Sim mode wins, then the forced dev lane (every use on the custom endpoint),
    then one_shot_route. reasoning None keeps the model's default. Raises
    LLMNotConfiguredError naming the use when no configured provider can serve it.
    """
    if settings.GAIA_SIM_MODE:
        return _sim_llm(temperature)
    if custom_lane_forced():
        return build_custom_chat_model(
            temperature=temperature,
            max_tokens=HELPER_MAX_OUTPUT_TOKENS,
            endpoint=custom_endpoint(),
            reasoning=reasoning,
        )
    route = one_shot_route(use)
    if route is None:
        raise LLMNotConfiguredError(
            f"No configured AI provider can serve {use.value} calls. Configure "
            f"{HOSTED_ONE_SHOT_PROVIDERS[use].value} (or, off production, any provider that "
            "serves it) in Settings → AI Providers or via its API-key env var."
        )
    provider, model = route
    match provider:
        case LLMProviderName.OPENROUTER:
            return _openrouter_one_shot(
                temperature,
                reasoning,
                model_name=model,
                fallback_model_names=HIL_JUDGE_FALLBACK_MODEL_NAMES
                if use is ModelUse.JUDGE
                else (),
            )
        case LLMProviderName.GEMINI:
            config: ProviderConfig = _require_provider_config(provider)
            return _build_gemini_one_shot(model, temperature, api_key=str(config.api_key))
        case LLMProviderName.OPENAI:
            config = _require_provider_config(provider)
            effort = OPENAI_REASONING_EFFORT[reasoning or ReasoningLevel.OFF]
            return _build_openai_wire_one_shot(
                model,
                # OpenAI reasoning models reject a temperature once reasoning is on.
                temperature if effort == OPENAI_REASONING_EFFORT[ReasoningLevel.OFF] else None,
                api_key=str(config.api_key),
                base_url=None,
                reasoning_effort=effort,
            )
        case LLMProviderName.OLLAMA:
            config = _require_provider_config(provider)
            return _build_openai_wire_one_shot(
                model,
                temperature,
                api_key=OLLAMA_PLACEHOLDER_API_KEY,
                base_url=_ollama_openai_url(config),
                reasoning_effort=None,
            )
        case LLMProviderName.CUSTOM:
            return build_custom_chat_model(
                temperature=temperature,
                max_tokens=HELPER_MAX_OUTPUT_TOKENS,
                endpoint=custom_endpoint(),
                reasoning=reasoning,
            )


def _openrouter_one_shot(
    temperature: float,
    reasoning: ReasoningLevel | None,
    *,
    model_name: str,
    fallback_model_names: tuple[str, ...] = (),
) -> ChatOpenRouter:
    """Re-point the cached default client at model_name, capped to HELPER_MAX_OUTPUT_TOKENS.

    model_copy, not .bind(): bind_tools rebuilds the binding and drops a bound
    model or cap (measured: every aux call served DEFAULT_MODEL_NAME).
    fallback_model_names ride OpenRouter's models array, tried in order on
    transport errors only, with the provider order the client already carries.
    """
    config: ProviderConfig = _require_provider_config(LLMProviderName.OPENROUTER)
    base = _build_default_llm(temperature, api_key=str(config.api_key), base_url=config.base_url)
    update: dict[str, object] = {"max_tokens": HELPER_MAX_OUTPUT_TOKENS, "model_name": model_name}
    if reasoning is not None:
        update["reasoning"] = {"effort": OPENROUTER_REASONING_EFFORT[reasoning]}
    if fallback_model_names:
        update["model_kwargs"] = {
            **(base.model_kwargs or {}),
            "models": [model_name, *fallback_model_names],
        }
    return base.model_copy(update=update)


@cache
def _build_gemini_one_shot(model: str, temperature: float, api_key: str) -> BaseChatModel:
    llm = ChatGoogleGenerativeAI(model=model, temperature=temperature, google_api_key=api_key)
    # Same reason as _build_default_llm: fractional-window middleware reads this.
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return llm


@cache
def _build_openai_wire_one_shot(
    model: str,
    temperature: float | None,
    *,
    api_key: str,
    base_url: str | None,
    reasoning_effort: str | None,
) -> BaseChatModel:
    """Build a one-shot client for OpenAI itself (base_url None) or Ollama's OpenAI-wire API."""
    llm = ChatOpenAI(
        model=model,
        temperature=temperature,
        max_completion_tokens=HELPER_MAX_OUTPUT_TOKENS,
        # The OpenAI SDK honors max_retries=0, so retries stay with with_llm_retry.
        max_retries=0,
        api_key=SecretStr(api_key),
        base_url=base_url,
        reasoning_effort=reasoning_effort,
    )
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return llm


def memory_lane_available() -> bool:
    """Whether resolve_model(MEMORY) can serve a call instead of raising."""
    return settings.GAIA_SIM_MODE or one_shot_route(ModelUse.MEMORY) is not None


def aux_lane_available() -> bool:
    """Whether resolve_model(HELPER) can serve a call: the mirror of memory_lane_available."""
    if settings.GAIA_SIM_MODE or custom_lane_forced():
        return True
    return one_shot_route(ModelUse.HELPER) is not None


def reset_aux_llm_caches() -> None:
    """Clear every cached auxiliary builder and the runtime-config snapshot.

    The snapshot drops with the model caches so a rebuilt client cannot pin the
    old store key indefinitely. Called by the credential service invalidation
    fan-out after a Settings or setup-wizard save.
    """
    _sim_llm.cache_clear()
    _build_default_llm.cache_clear()
    _build_gemini_one_shot.cache_clear()
    _build_openai_wire_one_shot.cache_clear()
    resolved_configs.clear()
    _schedule_runtime_config_refresh()


on_local_invalidation(reset_aux_llm_caches)


def _stamp_fallback(result: _ResultT, model: str) -> _ResultT:
    """Mark a fallback-produced AIMessage with the model that served it, for the SSE notice and for pricing."""
    metadata = getattr(result, "response_metadata", None)
    if isinstance(metadata, dict):
        metadata[FELL_BACK_METADATA_KEY] = True
        metadata[FALLBACK_MODEL_METADATA_KEY] = model
    return result


def _allowed_fallback(fallback: LLMFallback) -> LLMFallback:
    """Return fallback, or None on the forced dev lane, where no call may leave the custom endpoint."""
    return None if custom_lane_forced() else fallback


def _materialize_fallback(fallback: LLMFallback) -> Runnable | None:
    """Resolve a fallback to a concrete runnable, calling a zero-arg factory."""
    return fallback() if callable(fallback) and not isinstance(fallback, Runnable) else fallback


#: How many wrapper hops to follow looking for the underlying client. Two is
#: what production builds (sequence -> binding -> model); the margin absorbs a
#: future wrapper without ever letting the walk run away.
_WIRE_WALK_MAX_HOPS = 6


def _wire_client(runnable: Runnable) -> object:
    """Return the chat model runnable ultimately calls, or None when the walk finds none.

    A tool-bound or structured runnable arrives wrapped, so the two wrappers
    LangChain builds are walked rather than type-checked: bind_tools/bind yield
    a RunnableBinding, with_structured_output a RunnableSequence. Bounded,
    since walking arbitrary attributes could hang on an object that generates them.
    """
    node: object = runnable
    for _ in range(_WIRE_WALK_MAX_HOPS):
        if isinstance(node, RunnableBinding):
            node = node.bound
        elif isinstance(node, RunnableSequence):
            node = node.first
        else:
            return node
    return None


def _is_default_or_host(base: object, host: str) -> bool:
    """Whether a client's base URL is unset (the SDK default) or points at exactly host."""
    return base is None or urlparse(str(base)).hostname == host


def _is_openrouter_wire(runnable: Runnable) -> bool:
    """Whether runnable calls OpenRouter's own service, the only one that understands session_id."""
    client = _wire_client(runnable)
    if not isinstance(client, ChatOpenRouter):
        return False
    # A ChatOpenRouter aimed at another OpenAI-compatible endpoint (the sim stub) rejects it.
    base = client.openrouter_api_base
    return _is_default_or_host(base, "openrouter.ai")


def _is_openai_wire(runnable: Runnable) -> bool:
    """Whether runnable calls OpenAI's own API, the only one that understands prompt_cache_key."""
    client = _wire_client(runnable)
    if not isinstance(client, ChatOpenAI):
        return False
    base = client.openai_api_base
    return _is_default_or_host(base, "api.openai.com")


def _resolve_fallback(
    fallback: LLMFallback,
    label: str,
    primary_error: BaseException,
    *,
    session_id: str | None = None,
) -> tuple[Runnable, str]:
    """Materialize the fallback, log the downgrade, and return the retry-wrapped runnable and the model it asks for.

    Re-raises primary_error when no fallback is available.
    """
    # ``session_id`` is BOUND, not passed in config: the config value is dropped before
    # the wire, while a bind survives bind_tools. Only onto an OpenRouter-wire fallback --
    # Google's client rejects unknown kwargs and would raise on the outage path itself.
    resolved = _materialize_fallback(fallback)
    if resolved is None:
        raise primary_error
    log.warning(
        f"{LogTag.AGENT} llm call failed; falling back to the default model",
        llm={"label": label, "error_type": type(primary_error).__name__, "fell_back": True},
        error=str(primary_error),
    )
    requested = _requested_model(resolved)
    if session_id and _is_openrouter_wire(resolved):
        resolved = resolved.bind(session_id=session_id)
    return with_llm_retry(resolved), requested


def _sticky_session_id(config: RunnableConfig | None, *, auxiliary: bool = False) -> str | None:
    """Return the provider's sticky-routing key for this call, or None when unset.

    Auxiliary one-shots get their own suffixed session: sharing the conversation's key
    re-pins its provider from a background call. Both the primary bind and the fallback
    resolve through here, so a fallback cannot quietly drop the suffix and re-pin the
    conversation.
    """
    configurable: AgentConfigurable = agent_configurable(config)
    session_id = configurable.get("session_id")
    if not session_id:
        return None
    return f"{session_id}{AUX_SESSION_SUFFIX}" if auxiliary else str(session_id)


def _requested_model(runnable: Any) -> str:  # noqa: ANN401 -- any Runnable shape
    """Return the model id this runnable was going to ask for, or UNKNOWN_MODEL_NAME.

    A failed call has no reply to read the served model off, so the ledger's
    model_requested is all there is. Read defensively: the bound runnable is a
    chat model on the graph lane but a with_structured_output wrapper on the
    auxiliary one.
    """
    for attribute in ("model_name", "model"):
        value = getattr(runnable, attribute, None)
        if isinstance(value, str) and value:
            return value
    return UNKNOWN_MODEL_NAME


def _invoke_context(
    config: RunnableConfig | None,
    label: str,
    *,
    background: bool,
    duration_ms: float | None,
) -> LLMCallContext:
    """Build the ledger identity of a call made through this seam.

    Shared by the auxiliary success path and the failure path so a call that
    fails is described the same way as one that succeeds.
    """
    configurable: AgentConfigurable = agent_configurable(config)
    conversation_id = configurable.get("conversation_id")
    thread_id = configurable.get("thread_id")
    workflow_id = configurable.get("workflow_id")
    return LLMCallContext(
        agent_name=label,
        background=background,
        # Nothing reached the budget: the auxiliary route never charges, and a
        # failed call has no spend to charge.
        charge_to_budget=False,
        conversation_id=str(conversation_id) if conversation_id else None,
        thread_id=str(thread_id) if thread_id else None,
        workflow_id=str(workflow_id) if workflow_id else None,
        channel=resolve_channel(configurable, background=background),
        duration_ms=duration_ms,
    )


@dataclass(frozen=True)
class LLMInvokeOptions:
    """The rarely-tuned knobs of :func:ainvoke_llm (and, where noted, :func:invoke_llm).

    Attributes:
        max_attempts: Retries before fallback; 1 disables retry for hard latency budgets.
        timeout: Wall-clock ceiling over retries, backoff and fallback (None disables it). ainvoke_llm only.
        meter_auxiliary: Auxiliary metering; the agent graph passes False since LLMAccountingMiddleware already meters it.
        fallback_config: Config the fallback runs under — reusing config made failover a no-op (merges OVER with_config).
        sticky_session_id: Sticky-routing key for the fallback, overriding :func:_sticky_session_id's derivation from config.
        fallback_model: The model fallback_config selects, stamped on its reply so it is priced as what served it.
    """

    max_attempts: int = LLM_RETRY_MAX_ATTEMPTS
    timeout: float | None = LLM_INVOKE_TIMEOUT_SECONDS
    meter_auxiliary: bool = True
    fallback_config: RunnableConfig | None = None
    sticky_session_id: str | None = None
    fallback_model: str | None = None


@dataclass(frozen=True)
class StructuredCallOptions:
    """The optional settings of :func:ainvoke_structured and :func:ainvoke_structured_gemini."""

    temperature: float = DEFAULT_LLM_TEMPERATURE
    timeout: float | None = LLM_INVOKE_TIMEOUT_SECONDS
    #: None keeps the model's default; the Gemini memory fallback ignores it.
    reasoning: ReasoningLevel | None = None
    #: What the call is for; resolve_model turns it into a provider and model.
    use: ModelUse = ModelUse.HELPER
    #: 1 disables retry, for a caller on a hard latency budget.
    max_attempts: int = LLM_RETRY_MAX_ATTEMPTS


_DEFAULT_STRUCTURED_OPTIONS = StructuredCallOptions()


async def ainvoke_llm(
    primary: Runnable,
    messages: LanguageModelInput,
    *,
    fallback: LLMFallback = None,
    config: RunnableConfig | None = None,
    label: str = "model",
    options: LLMInvokeOptions | None = None,
) -> Any:  # noqa: ANN401 -- overrides LangChain Runnable methods typed Any upstream
    """Invoke a runnable: retry transient errors, then fall back on a provider failure.

    Bugs and CancelledError propagate. timeout wall-clocks retries, backoff and the fallback attempt (None disables it) — expiring mid-fallback raises TimeoutError rather than starting a second unbounded attempt.

    Return stays Any (Type Safety item 14): a parametrized Runnable[LanguageModelInput, _ResultT] -> _ResultT breaks because _resolve_fallback's Runnable is unparametrized, and structured-output runnables return dict[str, Any] | BaseModel, defeating narrowing. Callers narrow it themselves (cast).
    """
    # The one metering seam for auxiliary spend. The agent graph also comes
    # through here but is already metered by LLMAccountingMiddleware, so it
    # passes meter_auxiliary=False — otherwise every graph call is booked twice.
    opts = options or LLMInvokeOptions()
    fallback = _allowed_fallback(fallback)
    config = _with_call_label(config, label)
    fallback_config = (
        _with_call_label(opts.fallback_config, label) if opts.fallback_config else None
    )
    usage_handler = UsageMetadataCallbackHandler() if opts.meter_auxiliary else None
    generation_handler = _GenerationIdCallback() if opts.meter_auxiliary else None
    call_configurable: AgentConfigurable = agent_configurable(config)
    user_id = call_configurable.get("user_id")
    # Wall time of the whole provider interaction, including retries and the
    # fallback attempt. Started before the timeout scope so a killed call still
    # reports how long it burned.
    invoke_start = time.monotonic()
    try:
        try:
            async with asyncio.timeout(opts.timeout):
                try:
                    return await with_llm_retry(primary, max_attempts=opts.max_attempts).ainvoke(
                        messages,
                        config=_with_usage_handler(
                            _with_usage_handler(config, usage_handler), generation_handler
                        ),
                    )
                except LLM_FALLBACK_EXCEPTIONS as primary_error:
                    # Runs under ``fallback_config``: reusing ``config`` made failover
                    # a no-op, since LangChain merges a passed config OVER a
                    # ``with_config`` one, putting the just-failed provider back.
                    fallback_runnable, fallback_requested = _resolve_fallback(
                        fallback,
                        label,
                        primary_error,
                        session_id=opts.sticky_session_id
                        or _sticky_session_id(config, auxiliary=opts.meter_auxiliary),
                    )
                    return _stamp_fallback(
                        await fallback_runnable.ainvoke(
                            messages,
                            config=_with_usage_handler(
                                _with_usage_handler(fallback_config or config, usage_handler),
                                generation_handler,
                            ),
                        ),
                        opts.fallback_model or fallback_requested,
                    )
        except Exception as call_error:
            # One row per failed CALL, not per attempt. ``except Exception``
            # deliberately excludes ``CancelledError`` — a caller hanging up is
            # not the provider failing.
            await record_failed_llm_call(
                user_id=str(user_id) if user_id else None,
                model_name=_requested_model(primary),
                error=call_error,
                context=_invoke_context(
                    config,
                    label,
                    background=opts.meter_auxiliary,
                    duration_ms=round((time.monotonic() - invoke_start) * 1000, 2),
                ),
            )
            raise
    finally:
        # ``finally``: a failed call still burned the tokens of every attempt the
        # retry and fallback made, and that spend is just as real.
        if usage_handler is not None:
            await _record_auxiliary_usage(
                usage_handler,
                label,
                str(user_id) if user_id else None,
                context=_invoke_context(
                    config,
                    label,
                    background=True,
                    duration_ms=round((time.monotonic() - invoke_start) * 1000, 2),
                ),
                facts=(generation_handler.facts if generation_handler else ResponseFacts()),
            )


def invoke_llm(
    primary: Runnable,
    messages: LanguageModelInput,
    *,
    fallback: LLMFallback = None,
    config: RunnableConfig | None = None,
    label: str = "model",
    options: LLMInvokeOptions | None = None,
) -> Any:  # noqa: ANN401 -- overrides LangChain Runnable methods typed Any upstream
    """Sync counterpart of :func:ainvoke_llm.

    Only options.max_attempts, options.fallback_config and
    options.sticky_session_id apply here — timeout/meter_auxiliary are
    async-only (see :class:LLMInvokeOptions).
    """
    opts = options or LLMInvokeOptions()
    fallback = _allowed_fallback(fallback)
    config = _with_call_label(config, label)
    try:
        return with_llm_retry(primary, max_attempts=opts.max_attempts).invoke(
            messages, config=config
        )
    except LLM_FALLBACK_EXCEPTIONS as primary_error:
        fallback_runnable, fallback_requested = _resolve_fallback(
            fallback,
            label,
            primary_error,
            # Passed through like the async path — this branch used to hand
            # _resolve_fallback nothing, so a sync fallback silently landed
            # on whatever provider the router picked.
            session_id=opts.sticky_session_id or _sticky_session_id(config),
        )
        return _stamp_fallback(
            fallback_runnable.invoke(
                messages,
                config=_with_call_label(opts.fallback_config, label)
                if opts.fallback_config
                else config,
            ),
            opts.fallback_model or fallback_requested,
        )


# Marks an internal one-shot LLM call so the chat stream drops its output instead of rendering
# it as assistant text: EVERY structured call made while a graph streams must carry it, or its
# tokens leak into the chat as a bot message. Merges with the ambient run config, keeping trace.
SILENT_LLM_CONFIG: RunnableConfig = {
    "silent": True,
    "metadata": {"silent": True},
}  # type: ignore[typeddict-unknown-key]  # custom key consumed by GAIA's stream helpers, not part of RunnableConfig


def metered_config(user_id: str) -> RunnableConfig:
    """Build the minimal run config for an auxiliary :func:ainvoke_structured call.

    Attributes spend for COGS observability — never charged to the user's
    budget. Callers already forwarding a graph config (carries
    configurable.user_id) don't need this.
    """
    return cast(RunnableConfig, {"configurable": {"user_id": user_id}})


def silent_metered_config(user_id: str) -> RunnableConfig:
    """:data:SILENT_LLM_CONFIG plus the spend attribution of :func:metered_config.

    For an internal call made while a graph is streaming, on behalf of a
    specific user. Both halves matter: without silent, structured output leaks
    into the chat as a bot message; without user_id, COGS lands on nobody.
    """
    return cast(
        RunnableConfig,
        {**SILENT_LLM_CONFIG, **metered_config(user_id)},
    )


class _TokenUsageOutput(TypedDict, total=False):
    """The token_usage sub-dict of an LLMResult.llm_output, as OpenRouter fills it."""

    cost: object


class _LLMOutput(TypedDict, total=False):
    """The provider-owned llm_output bag, limited to the keys this module reads.

    total=False throughout: every key is absent on some lane (streaming leaves
    token_usage on the message instead, and only OpenRouter reports a price).
    """

    id: object
    cost: object
    token_usage: _TokenUsageOutput


class _GenerationInfo(TypedDict, total=False):
    """The generation_info bag of one Generation, limited to the keys read here."""

    id: object
    finish_reason: object


def _reported_cost(response: LLMResult) -> float | None:
    """Return what OpenRouter charged for this call, from whichever shape carries it.

    Non-streaming puts token_usage in llm_output; streaming leaves it on the
    message's response_metadata. None means the lane reported no price and the
    caller falls back to the pricing table.
    """
    llm_output: _LLMOutput = cast(_LLMOutput, response.llm_output or {})
    token_usage: _TokenUsageOutput = llm_output.get("token_usage") or {}
    for candidate in (llm_output.get("cost"), token_usage.get("cost")):
        if candidate is not None:
            # A price that won't parse, is negative, or non-finite is skipped
            # rather than failing an already-succeeded call — the next shape
            # (then the table) answers instead.
            with suppress(TypeError, ValueError):
                parsed = float(cast(str | float, candidate))
                if math.isfinite(parsed) and parsed >= 0.0:
                    return parsed
    for generations in response.generations:
        for generation in generations:
            message = getattr(generation, "message", None)
            cost = extract_message_cost(message) if message is not None else None
            if cost is not None:
                return cost
    return None


@dataclass(frozen=True)
class ResponseFacts:
    """What the provider's reply says about ITSELF, captured in one place.

    Grouped rather than passed as four parallel keywords because they are read
    from one object and describe one call — and because passing them separately
    is precisely how three of them went missing one at a time.
    """

    generation_id: str | None = None
    provider: str | None = None
    finish_reason: str | None = None
    cost: float | None = None


class _GenerationIdCallback(BaseCallbackHandler):
    """Captures the upstream generation id for auxiliary calls.

    Structured one-shots return the parsed schema, not the AIMessage
    carrying response_metadata — so extract_generation_id has nothing
    to read and every follow-up / memory-family llm_call event logged no
    id. Without the id those lanes cannot be attributed to a serving upstream,
    and the per-provider cache table only covers the graph trio. ChatOpenRouter
    puts the id in llm_output on the non-streaming path and in
    generation_info when streaming; both are read here."""

    def __init__(self) -> None:
        self.generation_id: str | None = None
        self.provider: str | None = None
        self.finish_reason: str | None = None
        self._attempts = 0
        self._priced_attempts = 0
        self._cost_total = 0.0

    @property
    def facts(self) -> ResponseFacts:
        """Everything captured off the reply, as one value for the metering seam."""
        return ResponseFacts(
            generation_id=self.generation_id,
            provider=self.provider,
            finish_reason=self.finish_reason,
            cost=self.cost,
        )

    @property
    def cost(self) -> float | None:
        """Provider-reported spend summed over EVERY attempt this call made.

        Accumulated, not last-write-wins: UsageMetadataCallbackHandler sums
        tokens across retries and fallbacks, so only the final price would
        under-count. None when ANY attempt reported no price — a partial sum
        is not the call's cost, so the caller falls back to the pricing table.
        """
        if self._attempts == 0 or self._priced_attempts != self._attempts:
            return None
        return self._cost_total

    def on_llm_end(
        self,
        response: LLMResult,
        # The callback contract passes run_id/parent_run_id/tags by keyword;
        # the base signature types them Any and this handler reads none.
        **_kwargs: Any,  # noqa: ANN401 -- LangChain BaseCallbackHandler contract
    ) -> None:
        self._attempts += 1
        reported = _reported_cost(response)
        if reported is not None:
            self._priced_attempts += 1
            self._cost_total += reported
        self._read_response_facts(response)
        llm_output: _LLMOutput = cast(_LLMOutput, response.llm_output or {})
        if llm_output.get("id"):
            self.generation_id = str(llm_output["id"])
            return
        for generations in response.generations or []:
            for generation in generations:
                info: _GenerationInfo = cast(_GenerationInfo, generation.generation_info or {})
                if info.get("id"):
                    self.generation_id = str(info["id"])
                    return

    def _read_response_facts(self, response: LLMResult) -> None:
        """Capture what the reply says about ITSELF: the upstream and the finish.

        Read here, not at the metering seam: the auxiliary lane returns a
        parsed schema, not the AIMessage, so extract_message_provider has
        nothing to read there. Last non-empty attempt wins — on a retry or
        fallback it produced the answer the caller received.
        """
        for generations in response.generations or []:
            for generation in generations:
                # A plain ``Generation`` carries no message; only a
                # ``ChatGeneration`` can name an upstream. Keep scanning — a run
                # can mix them, and the one that matters may not be first.
                message = getattr(generation, "message", None)
                if isinstance(message, AIMessage):
                    provider = extract_message_provider(message)
                    if provider:
                        self.provider = provider
                    finish_reason = extract_finish_reason(message)
                    if finish_reason:
                        self.finish_reason = finish_reason
                # ``generation_info`` is where the NON-streaming path leaves the
                # finish reason — it never reaches the message, so it wins as
                # the more specific source.
                info: _GenerationInfo = cast(_GenerationInfo, generation.generation_info or {})
                if info.get("finish_reason"):
                    self.finish_reason = str(info["finish_reason"])


def _with_call_label(config: RunnableConfig | None, label: str) -> RunnableConfig:
    """Copy config with label published under LLM_LABEL_METADATA_KEY in run metadata.

    Never mutates the caller's object; TTFT callbacks attribute per-call
    samples by that label.
    """
    merged: RunnableConfig = cast(RunnableConfig, dict(config) if config else {})
    merged["metadata"] = {**(merged.get("metadata") or {}), LLM_LABEL_METADATA_KEY: label}
    return merged


def _with_usage_handler(
    config: RunnableConfig | None, handler: BaseCallbackHandler | None
) -> RunnableConfig:
    """Return config with handler attached, never mutating the caller's object.

    Several callers pass a shared module-level config constant, and graph
    nodes forward a config whose callbacks is a live manager. A None handler
    (caller meters the call itself) returns the config unchanged.
    """
    if handler is None:
        return config if config is not None else RunnableConfig()
    merged: RunnableConfig = cast(RunnableConfig, dict(config) if config else {})
    existing = merged.get("callbacks")
    if existing is None:
        merged["callbacks"] = [handler]
    elif isinstance(existing, list):
        merged["callbacks"] = [*existing, handler]
    else:
        manager = existing.copy()
        manager.add_handler(handler, inherit=True)
        merged["callbacks"] = manager
    return merged


async def _record_auxiliary_usage(
    handler: UsageMetadataCallbackHandler,
    label: str,
    user_id: str | None,
    *,
    context: LLMCallContext,
    facts: ResponseFacts,
) -> None:
    """Meter one auxiliary (non-agent) model call for COGS observability.

    ainvoke_structured runs outside the agent graph, so LLMAccountingMiddleware
    never sees it. Deliberately NOT charged to the user's allowance
    (charge_to_budget=False) — background work, not usage they asked for.
    Booked durably per user (usage_daily.aux_cost); llm_call carries background=True.
    """
    # A fanned-out call cannot attribute one price/generation to any one model,
    # so only the single-model case takes the reported figures. Resolved ONCE,
    # here, so booking, ``cost_source`` and the ledger never disagree.
    attributable = len(handler.usage_metadata) == 1
    booked_cost = facts.cost if attributable else None
    booked_generation_id = facts.generation_id if attributable else None
    # Same rule for the upstream: a fan-out cannot say which model any one
    # provider served, and naming the wrong one is worse than naming none.
    booked_provider = facts.provider if attributable else None
    for model_name, model_usage in handler.usage_metadata.items():
        usage: UsageMetadata = model_usage
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        if not (input_tokens or output_tokens):
            continue
        details: InputTokenDetails = usage.get("input_token_details") or {}
        cached_tokens = int(details.get("cache_read", 0) or 0)
        output_details: OutputTokenDetails = usage.get("output_token_details") or {}
        reasoning_tokens = int(output_details.get("reasoning", 0) or 0)

        if user_id is None:
            log.warning(
                f"{LogTag.AGENT} auxiliary llm spend not metered — no user_id in "
                "config.configurable (threading gap?)",
                llm={"label": label, "model": model_name},
            )

        cost = await record_llm_call(
            user_id=user_id,
            model_name=model_name,
            usage=TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                reasoning_tokens=reasoning_tokens,
            ),
            provider_cost=booked_cost,
            # ``provider`` stays None: the raw response never reaches here, so
            # the upstream name must not be guessed. ``generation_id`` must be
            # stamped HERE — the ledger is the durable record.
            context=replace(
                context,
                model_served=model_name,
                generation_id=booked_generation_id,
                provider=booked_provider,
                finish_reason=facts.finish_reason,
            ),
        )
        log.info(
            "llm_call",
            llm_event="llm_call",
            background=True,
            # What was actually booked, not merely available: a multi-model
            # fan-out is priced from the table even when a figure was
            # reported, or coverage reporting counts table prices as provider.
            cost_source="provider" if booked_cost is not None else "table",
            agent_name=label,
            model=model_name,
            # The attributed id, not the merely-captured one, so the event and
            # the ledger row for this call always name the same generation.
            generation_id=booked_generation_id,
            user_id=user_id,
            input_tokens=input_tokens,
            cached_tokens=cached_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            cost_usd=cost,
        )


class _OpenAIFunctionSpec(BaseModel):
    """The function block of an OpenAI tool spec, read for the name the model calls."""

    model_config = ConfigDict(extra="ignore")

    name: str


class _OpenAIToolSpec(BaseModel):
    """An OpenAI tool spec as convert_to_openai_tool builds it."""

    model_config = ConfigDict(extra="ignore")

    function: _OpenAIFunctionSpec


class _IncompleteDetails(BaseModel):
    """Why a Responses API reply ended incomplete."""

    model_config = ConfigDict(extra="ignore")

    reason: str | None = None


class _ReplyMetadata(BaseModel):
    """A reply's response_metadata, read for why generation stopped.

    Chat completions say it in finish_reason; the Responses API instead marks
    the reply incomplete and names the reason in incomplete_details.
    """

    model_config = ConfigDict(extra="ignore")

    finish_reason: str | None = None
    incomplete_details: _IncompleteDetails | None = None

    def stopped_at_output_cap(self) -> bool:
        """Whether the provider cut the reply off at its output-token limit."""
        return self.finish_reason == "length" or (
            self.incomplete_details is not None
            and self.incomplete_details.reason == "max_output_tokens"
        )


def _structured_tool_name(schema: type[BaseModel]) -> str:
    """Return the tool name a structured schema is offered to the model under."""
    return _OpenAIToolSpec.model_validate(convert_to_openai_tool(schema)).function.name


def _parse_structured_reply(message: BaseMessage, schema: type[_StructuredT]) -> _StructuredT:
    """Return the schema filled from the reply's one tool call; raise MalformedStructuredOutputError otherwise.

    Needs an unstreamed reply: its arguments went through json.loads, while a
    streamed one went through partial-JSON repair, which keeps whatever prefix parses.
    """
    name = _structured_tool_name(schema)
    if not isinstance(message, AIMessage):
        raise MalformedStructuredOutputError(
            f"{name}: expected an AI reply, got {type(message).__name__}"
        )
    if _ReplyMetadata.model_validate(message.response_metadata).stopped_at_output_cap():
        raise MalformedStructuredOutputError(f"{name}: reply stopped at the output cap")
    if message.invalid_tool_calls:
        invalid: InvalidToolCall = message.invalid_tool_calls[0]
        raw = str(invalid.get("args"))
        raise MalformedStructuredOutputError(
            f"{name}: tool-call arguments are not valid JSON: {raw[:300]!r}", llm_output=raw
        )
    tool_calls: list[ToolCall] = message.tool_calls
    calls = [call for call in tool_calls if call["name"] == name]
    if not calls:
        raise MalformedStructuredOutputError(
            f"{name}: reply made no {name} tool call (content: {str(message.content)[:200]!r})",
            llm_output=str(message.content),
        )
    try:
        chosen: ToolCall = calls[0]
        return schema.model_validate(chosen["args"])
    except ValidationError as error:
        raise MalformedStructuredOutputError(
            f"{name}: tool-call arguments do not fit the schema: {error}"
        ) from error


def _structured_tool_choice(llm: BaseChatModel) -> str:
    """Return how a structured one-shot offers its one tool to llm: forced on OpenAI-style APIs only.

    Forced tools get grammar-decoded on Baidu/Together, cutting at an unescaped quote:
    27 of 43 closing answers cut forced, 0 of 28 offered (deepseek-v4-flash replay).
    Offered, OpenAI models answer in prose instead: gpt-6-luna on the Responses API
    3 of 3, gpt-5.6-luna on OpenAI's chat completions on every follow-up.
    """
    forced = isinstance(llm, ChatOpenAI) and (llm.use_responses_api or _is_openai_wire(llm))
    return "required" if forced else "auto"


def _structured_tool_runnable(llm: BaseChatModel, schema: type[_StructuredT]) -> Runnable:
    """Build the one-tool structured runnable every non-Gemini one-shot runs on.

    Not with_structured_output: it forces the tool by name, and it parses streamed
    arguments leniently. The call is unstreamed (streaming=False also holds under
    astream_events), so :func:_parse_structured_reply sees the arguments exactly as sent.
    """
    tool = convert_to_openai_tool(schema)
    tool_choice = _structured_tool_choice(llm)
    bound = llm.model_copy(update={"streaming": False}).bind_tools(
        [schema],
        tool_choice=tool_choice,
        ls_structured_output_format={
            "kwargs": {"method": "function_calling", "tool_choice": tool_choice},
            "schema": tool,
        },
    )
    return bound | RunnableLambda(
        lambda message: _parse_structured_reply(message, schema),
        name=_structured_tool_name(schema),
    )


def _structured_runnable(
    schema: type[_StructuredT], config: RunnableConfig | None, options: StructuredCallOptions
) -> Runnable:
    """Build the structured runnable a one-shot runs on, on the model resolve_model picks for it.

    Aux one-shots get their OWN suffixed sticky session, bound after bind_tools
    (which drops outer bindings): sharing the conversation's session_id re-pinned
    its provider (measured: rotation dips). Only an OpenRouter wire receives it.
    """
    model = resolve_model(options.use, temperature=options.temperature, reasoning=options.reasoning)
    structured = _structured_tool_runnable(model, schema)
    session_id = _sticky_session_id(config, auxiliary=True)
    if session_id and _is_openrouter_wire(structured):
        structured = structured.bind(session_id=session_id)
    return structured


async def ainvoke_structured(
    schema: type[_StructuredT],
    prompt: LanguageModelInput,
    *,
    label: str,
    config: RunnableConfig | None = None,
    options: StructuredCallOptions = _DEFAULT_STRUCTURED_OPTIONS,
) -> _StructuredT:
    """Run the single canonical one-shot structured call on the model options.use resolves to.

    Adds retry + fallback via :func:ainvoke_llm. Raises LLMNotConfiguredError
    when that model's provider has no key.
    """
    # Metering lives in ainvoke_llm, which this delegates to — a handler here too
    # would record the same call twice and over-report the user's COGS.
    return cast(
        _StructuredT,
        await ainvoke_llm(
            _structured_runnable(schema, config, options),
            prompt,
            config=config,
            label=label,
            options=LLMInvokeOptions(timeout=options.timeout, max_attempts=options.max_attempts),
        ),
    )


def _memory_structured_runnable(schema: type[_StructuredT], temperature: float) -> Runnable:
    """Build the direct-Gemini structured runnable the memory pipeline falls back to."""
    return resolve_model(ModelUse.MEMORY, temperature=temperature).with_structured_output(schema)


async def ainvoke_structured_gemini(
    schema: type[_StructuredT],
    prompt: LanguageModelInput,
    *,
    label: str,
    config: RunnableConfig | None = None,
    options: StructuredCallOptions = _DEFAULT_STRUCTURED_OPTIONS,
) -> _StructuredT:
    """Run a structured one-shot on the lane that fails over: aux lane primary, direct Gemini fallback.

    Same contract as :func:ainvoke_structured. Preference is measured: Gemini
    flash-lite's cache never extends past tools+system (repeat prompts always
    read exactly 3,064 cached tokens), vs. 98.1% cached on the aux lane. A
    Google-only deployment still extracts memories on Gemini alone.
    """
    invoke_options = LLMInvokeOptions(timeout=options.timeout, max_attempts=options.max_attempts)
    if not aux_lane_available():
        if not memory_lane_available():
            # Delegates so the canonical LLMNotConfiguredError (naming the fix)
            # is the one extraction's callers catch.
            return await ainvoke_structured(
                schema,
                prompt,
                label=label,
                config=config,
                options=options,
            )
        return cast(
            _StructuredT,
            await ainvoke_llm(
                _memory_structured_runnable(schema, options.temperature),
                prompt,
                config=config,
                label=label,
                options=invoke_options,
            ),
        )
    # Metering lives in ainvoke_llm, which this delegates to — a handler here too
    # would record the same call twice and over-report the user's COGS.
    fallback: LLMFallback = (
        (lambda: _memory_structured_runnable(schema, options.temperature))
        if memory_lane_available()
        else None
    )
    return cast(
        _StructuredT,
        await ainvoke_llm(
            _structured_runnable(schema, config, options),
            prompt,
            fallback=fallback,
            config=config,
            label=label,
            options=invoke_options,
        ),
    )
