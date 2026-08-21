import asyncio
from functools import cache
from typing import Any, TypeVar, cast

from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler
from langchain_core.language_models import LanguageModelInput, LanguageModelLike
from langchain_core.language_models.chat_models import (
    BaseChatModel,
)
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.runnables.utils import ConfigurableField
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openrouter import ChatOpenRouter
from openrouter.utils import BackoffStrategy, RetryConfig
from pydantic import BaseModel, SecretStr

from app.agents.llm.exceptions import (
    LLM_FALLBACK_EXCEPTIONS,
    LLM_RETRYABLE_EXCEPTIONS,
    LLMNotConfiguredError,
)
from app.agents.llm.types import (
    LLMFallback,
    LLMProvider,
    LLMProviderKey,
    LLMProviderName,
    ProviderLLM,
)
from app.config.settings import settings
from app.constants.llm import (
    AUX_MODEL_NAME,
    AUX_SESSION_SUFFIX,
    DEFAULT_GEMINI_MODEL_NAME,
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
    DEV_LLM_MAX_OUTPUT_TOKENS,
    HELPER_MAX_OUTPUT_TOKENS,
    LLM_INVOKE_TIMEOUT_SECONDS,
    LLM_RETRY_MAX_ATTEMPTS,
    MEMORY_MODEL_NAME,
    MODEL_FIELD_ID,
    MODEL_KWARGS_FIELD_ID,
    OPENROUTER_APP_CATEGORIES,
    OPENROUTER_APP_TITLE,
    OPENROUTER_MAX_OUTPUT_TOKENS,
    OPENROUTER_REASONING,
    REASONING_FIELD_ID,
    SIM_STUB_API_KEY,
    SIM_STUB_BASE_URL,
    SIM_STUB_MODEL_NAME,
    STICKY_FLIP_RETRY_MIN_HIT,
    STICKY_FLIP_RETRY_MIN_INPUT,
    STICKY_ROUTING_PROVIDERS,
    VISION_MODEL_NAME,
)
from app.constants.log_tags import LogTag
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.models.agent_models import agent_configurable
from app.services.llm_metering import (
    extract_message_model,
    extract_message_usage,
    record_llm_call,
)
from shared.py.wide_events import log

_StructuredT = TypeVar("_StructuredT", bound=BaseModel)
_ResultT = TypeVar("_ResultT")


def without_sdk_retry(llm: ChatOpenRouter) -> ChatOpenRouter:
    """Leave retrying to :func:`with_llm_retry`; the SDK's own loop nests under
    ours and turned 3 attempts into 40 requests. ``max_retries=0`` does NOT
    disable it — the SDK then applies a one-hour default; only this does."""
    llm.client.sdk_configuration.retry_config = RetryConfig(
        # Any strategy but "backoff" skips the retry path, so the (required)
        # backoff values below are never read.
        strategy="none",
        backoff=BackoffStrategy(
            initial_interval=0, max_interval=0, exponent=1.0, max_elapsed_time=0
        ),
        retry_connection_errors=False,
    )
    return llm


def with_llm_retry(runnable: Runnable, *, max_attempts: int = LLM_RETRY_MAX_ATTEMPTS) -> Runnable:
    """The single, canonical LLM retry. Wraps a (tool-bound) model runnable so
    transient provider/infra errors are retried with exponential backoff before
    the caller falls back to the default model. Applied AFTER ``bind_tools`` so
    the ``RunnableRetry`` wrapper never has to expose ``bind_tools``.
    ``max_attempts=1`` disables retry for callers on a hard latency budget."""
    return runnable.with_retry(
        retry_if_exception_type=LLM_RETRYABLE_EXCEPTIONS,
        stop_after_attempt=max_attempts,
        wait_exponential_jitter=True,
    )


PROVIDER_MODELS: dict[LLMProviderName, str] = {
    LLMProviderName.GEMINI: DEFAULT_GEMINI_MODEL_NAME,
    LLMProviderName.OPENROUTER: DEFAULT_MODEL_NAME,
    # The env-defined custom dev endpoint; empty when unset — the provider is
    # only registered in development with all DEV_LLM_* settings present.
    LLMProviderName.CUSTOM: settings.DEV_LLM_MODEL or "",
}
PROVIDER_PRIORITY: dict[int, LLMProviderName] = {
    1: LLMProviderName.OPENROUTER,
    2: LLMProviderName.GEMINI,
    3: LLMProviderName.CUSTOM,
}


@cache
def _sim_llm(temperature: float = DEFAULT_LLM_TEMPERATURE) -> BaseChatModel:
    """The one model used for EVERYTHING under GAIA_SIM_MODE: an OpenAI-wire
    client pointed at the local scripted stub (tools/llm-stub). Deliberately
    exposes no configurable fields — provider/model pinning is meaningless when
    every request lands on the stub, so pinned config is silently ignored."""
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
# _openrouter_wire_configurables). The two used to be exposed under SWAPPED
# configurable ids in one flat namespace (prefix_keys=False), so a bag naming
# only one of them silently resolved a different model on the other lane — which
# is why every writer had to set both keys. One id, one meaning.
_MODEL_FIELD = ConfigurableField(id=MODEL_FIELD_ID, name="Model", description="Which model to use")


def _openrouter_wire_configurables(llm: ChatOpenRouter) -> LanguageModelLike:
    """Attach the per-request configurable fields shared by every OpenRouter-wire
    client (the real OpenRouter and the env-defined custom endpoint). The field
    ids form one namespace across provider alternatives (``prefix_keys=False``),
    so every compatible client must expose identical ids."""
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
    required_keys=[SIM_STUB_API_KEY if settings.GAIA_SIM_MODE else settings.GOOGLE_API_KEY],
    strategy=MissingKeyStrategy.WARN,
    warning_message="Google API key not configured. Models provided by Google Gemini will not work.",
)
def init_gemini_llm() -> LanguageModelLike:
    """Initialize Gemini LLM with default model."""
    if settings.GAIA_SIM_MODE:
        return _sim_llm()
    llm = ChatGoogleGenerativeAI(
        model=PROVIDER_MODELS[LLMProviderName.GEMINI],
        temperature=DEFAULT_LLM_TEMPERATURE,
        streaming=True,
    )
    # Every chat LLM must carry the context-window profile — fractional-token
    # middleware (summarization/compaction triggers) raises without it. Same
    # contract as _build_default_llm/_sim_llm/init_custom_llm.
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return llm.configurable_fields(model=_MODEL_FIELD)


@lazy_provider(
    name=LLMProviderKey.OPENROUTER,
    required_keys=[SIM_STUB_API_KEY if settings.GAIA_SIM_MODE else settings.OPENROUTER_API_KEY],
    strategy=MissingKeyStrategy.WARN,
    warning_message="OpenRouter API key not configured. Models provided via OpenRouter (Grok, etc.) will not work.",
)
def init_openrouter_llm() -> LanguageModelLike:
    """Initialize the OpenRouter LLM (MiniMax M3, Grok, etc.).

    Uses ChatOpenRouter (langchain-openrouter), not ChatOpenAI, because it parses
    OpenRouter's `reasoning`/`reasoning_details` fields into standard reasoning
    content blocks — ChatOpenAI silently drops them. That is what lets us surface
    the model's thinking. Reasoning effort is the native `reasoning` field; provider
    routing (the first-party MiniMax pin) rides `model_kwargs` (OpenRouter's
    `provider` request param). Both are per-request configurable.
    """
    if settings.GAIA_SIM_MODE:
        return _sim_llm()
    llm = without_sdk_retry(
        ChatOpenRouter(
            model=PROVIDER_MODELS[LLMProviderName.OPENROUTER],
            temperature=DEFAULT_LLM_TEMPERATURE,
            streaming=True,
            stream_usage=True,
            # Output cap; must stay well under the model's shared input+output context
            # window (see OPENROUTER_MAX_OUTPUT_TOKENS) or OpenRouter rejects the request.
            max_tokens=OPENROUTER_MAX_OUTPUT_TOKENS,
            api_key=settings.OPENROUTER_API_KEY,
            # App attribution → OpenRouter rankings/analytics. ChatOpenRouter exposes
            # these as dedicated params (NOT `default_headers`, which it forwards to
            # send_async and crashes on). https://openrouter.ai/docs/app-attribution
            app_url=settings.FRONTEND_URL,
            app_title=OPENROUTER_APP_TITLE,
            app_categories=OPENROUTER_APP_CATEGORIES,
            reasoning=OPENROUTER_REASONING,
        )
    )
    # Every chat LLM must carry the context-window profile — fractional-token
    # middleware (summarization/compaction triggers) raises without it. Same
    # contract as _build_default_llm/_sim_llm/init_gemini_llm/init_custom_llm.
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return _openrouter_wire_configurables(llm)


@lazy_provider(
    name=LLMProviderKey.CUSTOM,
    required_keys=[SIM_STUB_API_KEY]
    if settings.GAIA_SIM_MODE
    else [settings.DEV_LLM_BASE_URL, settings.DEV_LLM_API_KEY, settings.DEV_LLM_MODEL],
    strategy=MissingKeyStrategy.WARN,
    warning_message="DEV_LLM_BASE_URL / DEV_LLM_API_KEY / DEV_LLM_MODEL not configured. The custom dev LLM endpoint will not work.",
)
def init_custom_llm() -> LanguageModelLike:
    """DEV-ONLY: the env-defined custom provider — any OpenRouter/OpenAI-compatible
    endpoint, with base URL, key, and model all from the DEV_LLM_* settings. Routes
    bulk test traffic to heavily discounted lanes (e.g. Nous Research's DeepSeek
    models) without spending real credits. ChatOpenRouter works against such
    endpoints unchanged, including reasoning parsing — only the base URL and key
    differ. Registered only when ENV=development (see register_llm_providers).
    """
    if settings.GAIA_SIM_MODE:
        return _sim_llm()
    llm = without_sdk_retry(
        ChatOpenRouter(
            model=PROVIDER_MODELS[LLMProviderName.CUSTOM],
            temperature=DEFAULT_LLM_TEMPERATURE,
            streaming=True,
            stream_usage=True,
            max_tokens=DEV_LLM_MAX_OUTPUT_TOKENS,
            api_key=settings.DEV_LLM_API_KEY,
            base_url=settings.DEV_LLM_BASE_URL,
        )
    )
    # Fractional-window middleware (the summarization/compaction triggers)
    # resolves the context window from the model's profile at graph-build time
    # and raises without it — same contract _build_default_llm satisfies for the
    # default model and _sim_llm for the stub. The DEV_LLM_* model is env-defined
    # and has no curated registry entry, so pin the shared default window here.
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return _openrouter_wire_configurables(llm)


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
    if preferred_provider and preferred_provider not in PROVIDER_MODELS:
        valid_providers = list(PROVIDER_MODELS.keys())
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
            "model": PROVIDER_MODELS.get(primary_provider["name"], primary_provider["name"]),
            "provider": primary_provider["name"],
            "is_free": False,
        }
    )
    return _create_configurable_llm(primary_provider, alternative_providers)


def _get_available_providers() -> dict[LLMProviderName, ProviderLLM]:
    """Retrieve available LLM provider instances from the global registry,
    mapped by provider name."""
    provider_instance_mapping: dict[LLMProviderName, LLMProviderKey] = {
        LLMProviderName.GEMINI: LLMProviderKey.GEMINI,
        LLMProviderName.OPENROUTER: LLMProviderKey.OPENROUTER,
        LLMProviderName.CUSTOM: LLMProviderKey.CUSTOM,
    }

    available: dict[LLMProviderName, ProviderLLM] = {}
    for provider_name, instance_key in provider_instance_mapping.items():
        # custom_llm is only registered in development; providers.get() raises
        # KeyError on an unregistered name, which took every agent graph down.
        if not providers.is_available(instance_key):
            continue
        instance = cast(ProviderLLM | None, providers.get(instance_key))
        if instance is not None:
            available[provider_name] = instance

    return available


def next_fallback_provider(current: str | None) -> tuple[LLMProviderName, str] | None:
    """The highest-priority configured provider other than ``current``, and the
    model to run on it. ``None`` when nothing else is usable.

    The agent graph selects its lane by ``configurable["provider"]`` and never
    fails over on its own, so this is what a caller that caught a provider
    failure retries onto. A provider with no model configured is skipped rather
    than returned with an empty model: the custom dev endpoint's
    ``PROVIDER_MODELS`` entry is ``settings.DEV_LLM_MODEL or ""``, and pinning
    ``""`` would trade one dead provider for a guaranteed bad request.
    """
    available = _get_available_providers()
    for priority in sorted(PROVIDER_PRIORITY):
        name = PROVIDER_PRIORITY[priority]
        if name == current or name not in available:
            continue
        if model := PROVIDER_MODELS.get(name):
            return name, model
    return None


def _get_ordered_providers(
    available_providers: dict[LLMProviderName, ProviderLLM],
    preferred_provider: LLMProviderName | None,
    fallback_enabled: bool,
) -> list[LLMProvider]:
    """Order providers by preference and availability, returning LLMProvider
    objects in priority order."""
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
        for priority in sorted(PROVIDER_PRIORITY.keys()):
            provider_name = PROVIDER_PRIORITY[priority]
            if provider_name in remaining_providers:
                ordered.append(
                    LLMProvider(name=provider_name, instance=remaining_providers[provider_name])
                )

    return ordered


def _create_configurable_llm(
    primary: LLMProvider, alternatives: list[LLMProvider]
) -> LanguageModelLike:
    """Create a configurable LLM instance with fallback alternatives."""
    if not alternatives:
        # Return primary instance directly if no alternatives
        return primary["instance"]

    # Keyword-expanded below, so the keys must be plain str, not enum members.
    alternatives_mapping = {str(alt["name"]): alt["instance"] for alt in alternatives}

    primary_instance = primary["instance"]

    return primary_instance.configurable_alternatives(
        ConfigurableField(id="provider"),
        default_key=primary["name"],
        prefix_keys=False,
        **alternatives_mapping,
    )


def register_llm_providers() -> None:
    """Register LLM providers in the lazy loader."""
    init_gemini_llm()
    init_openrouter_llm()
    # The custom endpoint is a dev/testing-only lane — never registered in
    # production, so DEV_LLM_* vars present in a prod environment can't route
    # real traffic.
    if settings.ENV == "development":
        init_custom_llm()


def get_default_llm(*, temperature: float = DEFAULT_LLM_TEMPERATURE) -> BaseChatModel:
    """The single factory for the default model (``DEFAULT_MODEL_NAME``, served over
    OpenRouter) used by EVERY auxiliary LLM task — follow-ups, research,
    integration inference, profile/holo cards, vision helpers, workflow
    generation, context summarization, onboarding, one-shot helpers. The memory
    pipeline is the one exception: it prefers direct Gemini for cache isolation
    and only lands here when that lane is unavailable (see
    :func:`ainvoke_structured_gemini`). The paid model is reserved for the main
    chat agent (see ``lane``); auxiliary tasks never use it.
    ``temperature`` lets creative tasks opt into more variation. Instances are
    cached per temperature so hot paths reuse one HTTP client instead of
    rebuilding it per call. Raises ``LLMNotConfiguredError`` if OpenRouter is not
    configured."""
    if settings.GAIA_SIM_MODE:
        return _sim_llm(temperature)
    if not settings.OPENROUTER_API_KEY:
        raise LLMNotConfiguredError("Default LLM not configured. Set OPENROUTER_API_KEY.")
    return _build_default_llm(temperature)


@cache
def _build_default_llm(temperature: float) -> BaseChatModel:
    llm = without_sdk_retry(
        ChatOpenRouter(
            model=DEFAULT_MODEL_NAME,
            temperature=temperature,
            # ChatOpenRouter defaults streaming to False, and stream_usage only
            # attaches usage metadata to a stream — set alone it is inert. Both are
            # set so this matches init_openrouter_llm, and so the model fallback
            # (create_agent resolves it from here) streams like the primary it
            # replaces instead of arriving as one lump.
            streaming=True,
            stream_usage=True,
            max_tokens=OPENROUTER_MAX_OUTPUT_TOKENS,
            api_key=settings.OPENROUTER_API_KEY,
        )
    )
    # LangChain resolves a model's context window from its curated profile registry,
    # which lags new model releases (it has no profile for the current default model).
    # Consumers that express limits as a FRACTION of the window — the summarization
    # and compaction middleware — raise at construction without it, which fails the
    # whole agent graph build. Supply the window here so the default model always
    # carries it; harmless metadata for every other caller.
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return llm


def get_helper_llm(*, temperature: float = DEFAULT_LLM_TEMPERATURE) -> BaseChatModel:
    """:func:`get_default_llm`, capped to :data:`HELPER_MAX_OUTPUT_TOKENS`.

    For the one-shot helpers whose real output is small (titles, JSON blobs,
    classifications, short generated copy) — ``ainvoke_structured`` and every
    direct ``get_default_llm()`` call outside the agent graph. The two graph-
    adjacent consumers (the ``create_agent`` model fallback, the summarization/
    compaction middleware) keep the full reservation via ``get_default_llm()``
    directly, since they can legitimately produce long output.

    ``model_copy`` (not a new ``ChatOpenRouter(...)``) is deliberate: it shares
    the cached instance's ``client`` field by reference instead of opening a
    second connection pool. A ``.bind(max_tokens=...)`` wrapper was tried and
    rejected — ``RunnableBinding.__getattr__`` only preserves bound kwargs for
    methods that take a ``config`` argument, and neither ``bind_tools`` nor
    ``with_structured_output`` do, so the override silently vanished the moment
    a caller chained either of those on top of it.
    """
    llm = get_default_llm(temperature=temperature)
    if settings.GAIA_SIM_MODE:
        return llm
    return cast(BaseChatModel, llm.model_copy(update={"max_tokens": HELPER_MAX_OUTPUT_TOKENS}))


def get_vision_llm(*, temperature: float = DEFAULT_LLM_TEMPERATURE) -> BaseChatModel:
    """The factory for every image -> text call (``vision/describe.py``).

    Separate from :func:`get_default_llm` on purpose. The default model is picked
    for cheap text and may not be multimodal; this one must be able to see, or the
    vision fallback describes nothing — and it fails silently, since
    ``describe_image`` degrades to ``None``. Raises ``LLMNotConfiguredError`` when
    Google is not configured.
    """
    if settings.GAIA_SIM_MODE:
        return _sim_llm(temperature)
    if not settings.GOOGLE_API_KEY:
        raise LLMNotConfiguredError("Vision model not configured. Set GOOGLE_API_KEY.")
    return _build_vision_llm(temperature)


@cache
def _build_vision_llm(temperature: float) -> BaseChatModel:
    llm = ChatGoogleGenerativeAI(model=VISION_MODEL_NAME, temperature=temperature)
    # Same reason as _build_default_llm: fractional-window middleware reads this.
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return llm


def memory_lane_available() -> bool:
    """Whether the direct-Gemini memory lane can serve a call at all — the one
    check :func:`get_memory_llm` raises on and callers route around."""
    return bool(settings.GAIA_SIM_MODE or settings.GOOGLE_API_KEY)


def get_memory_llm(*, temperature: float = DEFAULT_LLM_TEMPERATURE) -> BaseChatModel:
    """The factory for every memory-pipeline call (extraction, categorization,
    reconciliation, consolidation).

    Runs on direct Gemini (:data:`MEMORY_MODEL_NAME`), NOT the OpenRouter lane,
    on purpose: the memory extraction is a fire-and-forget background task that
    overlaps the graph's next-turn requests, and concurrent requests on the
    same provider's cache store wipe each other's cached chains mid-read
    (measured: the comms chain collapses to ~0 under a concurrent alias-lane
    extraction and holds ~99.5% under a concurrent Gemini extraction — a
    different provider has no shared cache store, so the overlap is harmless).
    Raises ``LLMNotConfiguredError`` when Google is not configured.
    """
    if settings.GAIA_SIM_MODE:
        return _sim_llm(temperature)
    if not memory_lane_available():
        raise LLMNotConfiguredError("Memory model not configured. Set GOOGLE_API_KEY.")
    return _build_memory_llm(temperature)


@cache
def _build_memory_llm(temperature: float) -> BaseChatModel:
    llm = ChatGoogleGenerativeAI(model=MEMORY_MODEL_NAME, temperature=temperature)
    # Same reason as _build_default_llm: fractional-window middleware reads this.
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return llm


def _stamp_fallback(result: _ResultT) -> _ResultT:
    """Mark a fallback-produced AIMessage so downstream layers can surface the
    downgrade (SSE event, accounting). No-op for non-message results."""
    metadata = getattr(result, "response_metadata", None)
    if isinstance(metadata, dict):
        metadata["gaia_fell_back"] = True
        metadata["gaia_fallback_model"] = DEFAULT_MODEL_NAME
    return result


def _materialize_fallback(fallback: LLMFallback) -> Runnable | None:
    """Resolve a fallback to a concrete runnable, calling a zero-arg factory."""
    return fallback() if callable(fallback) and not isinstance(fallback, Runnable) else fallback


def _resolve_fallback(
    fallback: LLMFallback,
    label: str,
    primary_error: BaseException,
    *,
    session_id: str | None = None,
) -> Runnable:
    """Materialize the fallback, log the downgrade, and return the retry-wrapped
    runnable. Re-raises ``primary_error`` when no fallback is available."""
    # ``session_id`` (OpenRouter sticky-routing key) is bound on the resolved
    # runnable so the fallback's requests stay on the conversation's provider —
    # the config-based value is dropped before the wire, while a bind survives
    # bind_tools and reaches the request params.
    resolved = _materialize_fallback(fallback)
    if resolved is None:
        raise primary_error
    log.warning(
        f"{LogTag.AGENT} llm call failed; falling back to the default model",
        llm={"label": label, "error_type": type(primary_error).__name__, "fell_back": True},
        error=str(primary_error),
    )
    if session_id:
        resolved = resolved.bind(session_id=session_id)
    return with_llm_retry(resolved)


def _sticky_session_id(config: RunnableConfig | None, *, auxiliary: bool) -> str | None:
    """The provider's sticky-routing key for this call, or None when unset.

    Auxiliary one-shots get their own suffixed session: sharing the
    conversation's key re-pins its provider from a background call. Both the
    primary bind and the fallback resolve through here, so a fallback can no
    longer quietly drop the suffix and re-pin the conversation.
    """
    session_id = agent_configurable(config).get("session_id")
    if not session_id:
        return None
    return f"{session_id}{AUX_SESSION_SUFFIX}" if auxiliary else str(session_id)


async def _meter_discarded_replay(
    discarded: Any,
    config: RunnableConfig | None,
    label: str,
) -> None:
    """Meter the sticky-flip replay whose answer was thrown away — otherwise its
    tokens miss the daily budget, the per-request ceiling and COGS entirely.

    Graph-lane only by construction: the replay itself is gated on
    ``not meter_auxiliary``, and the graph lane meters from the AIMessage that
    lands in state — which is the FIRST answer's, never this discard's."""
    if not isinstance(discarded, AIMessage):
        return
    configurable = agent_configurable(config)
    usage = extract_message_usage(discarded)
    # The provider's own account of what it served. This seam cannot resolve the
    # lane the way accounting does — ``lane`` imports this module, so importing
    # ModelLane back would close the cycle.
    model_name = extract_message_model(discarded)
    user_id = configurable.get("user_id")
    root_request_id = configurable.get("root_request_id")
    cost = await record_llm_call(
        user_id=str(user_id) if user_id else None,
        model_name=model_name,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        cached_tokens=usage["cached_tokens"],
        reasoning_tokens=usage["reasoning_tokens"],
        root_request_id=str(root_request_id) if root_request_id else None,
        charge_to_budget=True,
    )
    log.info(
        "llm_call",
        llm_event="llm_call",
        sticky_flip_discarded=True,
        agent_name=label,
        model=model_name,
        user_id=user_id,
        input_tokens=usage["input_tokens"],
        cached_tokens=usage["cached_tokens"],
        output_tokens=usage["output_tokens"],
        reasoning_tokens=usage["reasoning_tokens"],
        cost_usd=cost,
    )


async def ainvoke_llm(
    primary: Runnable,
    messages: LanguageModelInput,
    *,
    fallback: LLMFallback = None,
    config: RunnableConfig | None = None,
    label: str = "model",
    max_attempts: int = LLM_RETRY_MAX_ATTEMPTS,
    timeout: float | None = LLM_INVOKE_TIMEOUT_SECONDS,
    meter_auxiliary: bool = True,
    fallback_config: RunnableConfig | None = None,
) -> Any:
    """Invoke a runnable: retry transient errors, then fall back to ``fallback`` (if
    given) on a provider failure. Bugs and CancelledError propagate.

    ``timeout`` is a total wall-clock ceiling over the retries, their backoff sleeps
    and the fallback attempt — the guarantee being that this call cannot outlive it.
    Retry alone cannot cover a provider that accepts the connection and then never
    answers, because nothing is ever raised to retry on. ``None`` disables it.

    The ceiling deliberately wraps the fallback too. Expiring mid-fallback raising
    ``TimeoutError`` is the point: the alternative is catching it as a fallback trigger
    (``TimeoutError`` is in ``LLM_FALLBACK_EXCEPTIONS``) and starting a second,
    unbounded attempt — which is exactly the stall this exists to prevent.

    The return stays ``Any``, deliberately (Type Safety item 14). The obvious fix —
    ``primary: Runnable[LanguageModelInput, _ResultT] -> _ResultT`` — was tried and
    measured, and it does not hold at either end:

    - The fallback path resolves through ``LLMFallback``/``_resolve_fallback``, which
      are plain unparametrized ``Runnable``, so every return trips ``warn_return_any``
      unless those are made generic too.
    - Callers pass both plain chat models (yielding a ``BaseMessage``) and
      ``with_structured_output(...)`` runnables, which LangChain types as
      ``dict[str, Any] | BaseModel`` — so the type var binds to that union and the
      structured call sites stop type-checking against their real schema.

    Callers that know their shape narrow it themselves: ``ainvoke_structured`` casts
    to its ``schema``, and the chat-model call sites cast to ``BaseMessage``.
    """
    # The one metering seam for auxiliary spend. Every one-shot helper reaches a
    # provider through here — the vision describer, chatbot, research, PDF page
    # summaries, integration inference, profanity, onboarding — and each used to
    # spend real money that nothing recorded. Metering here rather than at each
    # call site is what stops the next helper from silently joining that list.
    #
    # The agent graph also comes through here (create_agent wants the retry +
    # fallback policy) but is already metered by LLMAccountingMiddleware, so it
    # passes meter_auxiliary=False — otherwise every graph call is booked twice.
    usage_handler = UsageMetadataCallbackHandler() if meter_auxiliary else None
    user_id = (config or {}).get("configurable", {}).get("user_id")
    try:
        async with asyncio.timeout(timeout):
            try:
                result = await with_llm_retry(primary, max_attempts=max_attempts).ainvoke(
                    messages, config=_with_usage_handler(config, usage_handler)
                )
                # OpenRouter's sticky routing expires after ~5 minutes and the
                # next request lands on a cold provider (a known OpenRouter
                # behavior) — the conversation's chain reads static-only or
                # nothing. The first attempt just WROTE the chain onto that
                # provider, so one immediate re-send hits it (~90%). Cheap: the
                # re-send is almost fully cached and only fires on the flipped
                # turns.
                usage = getattr(result, "usage_metadata", None) or {}
                details = usage.get("input_token_details") or {}
                # pragma: no mutate ×2 — a truthy stand-in for either 0 is
                # equivalent: 0 and 1 sit on the same side of the 8_000 input
                # floor, and cached is only compared once prompt >= 8_000, so
                # a 7_360 threshold treats 0 and 1 alike. Line-local proof is
                # threshold arithmetic the classifier does not do.
                cached = details.get("cache_read") or 0  # pragma: no mutate
                prompt = usage.get("input_tokens") or 0  # pragma: no mutate
                if (
                    # Graph lane on a sticky-routing provider only: auxiliary
                    # one-shots have no prior chain (cold IS their steady
                    # state), and Gemini has no stickiness to re-hit — for
                    # both, a replay is pure double billing.
                    not meter_auxiliary
                    and agent_configurable(config).get("provider") in STICKY_ROUTING_PROVIDERS
                    and prompt >= STICKY_FLIP_RETRY_MIN_INPUT
                    and cached < prompt * STICKY_FLIP_RETRY_MIN_HIT
                ):
                    try:
                        # silent: graph providers stream, and without it both
                        # invocations' tokens land in the same SSE stream —
                        # the user watches a second answer append to the first.
                        discarded = await with_llm_retry(primary, max_attempts=1).ainvoke(
                            messages,
                            # No usage handler to attach: this branch is gated
                            # on the graph lane, where usage_handler is None.
                            config=_silenced(config or {}),
                        )
                    except Exception as replay_error:
                        # The first answer is complete and in hand; a failed
                        # re-send (429, deadline) must never cost the turn.
                        log.warning(
                            f"{LogTag.AGENT} sticky-flip replay failed; keeping the first response",
                            agent_name=label,
                            error=str(replay_error),
                        )
                        return result
                    # The replay exists to write the chain onto the provider for
                    # the NEXT turn, so its answer is thrown away: the first one
                    # already streamed to the user, and returning the replay's
                    # would persist text that differs from what they watched.
                    await _meter_discarded_replay(discarded, config, label)
                return result
            except LLM_FALLBACK_EXCEPTIONS as primary_error:
                # The fallback runs under ``fallback_config`` when given. Reusing
                # ``config`` here is what made provider failover a no-op: LangChain
                # merges a passed config OVER a ``with_config`` one, so the run's
                # own configurable put the just-failed provider straight back.
                return _stamp_fallback(
                    await _resolve_fallback(
                        fallback,
                        label,
                        primary_error,
                        session_id=_sticky_session_id(config, auxiliary=meter_auxiliary),
                    ).ainvoke(
                        messages,
                        config=_with_usage_handler(fallback_config or config, usage_handler),
                    )
                )
    finally:
        # ``finally``: a failed call still burned the tokens of every attempt the
        # retry and fallback made, and that spend is just as real.
        if usage_handler is not None:
            await _record_auxiliary_usage(usage_handler, label, str(user_id) if user_id else None)


def invoke_llm(
    primary: Runnable,
    messages: LanguageModelInput,
    *,
    fallback: LLMFallback = None,
    config: RunnableConfig | None = None,
    label: str = "model",
    max_attempts: int = LLM_RETRY_MAX_ATTEMPTS,
    fallback_config: RunnableConfig | None = None,
) -> Any:
    """Sync counterpart of :func:`ainvoke_llm`."""
    try:
        return with_llm_retry(primary, max_attempts=max_attempts).invoke(messages, config=config)
    except LLM_FALLBACK_EXCEPTIONS as primary_error:
        return _stamp_fallback(
            _resolve_fallback(fallback, label, primary_error).invoke(
                messages, config=fallback_config or config
            )
        )


# Marks an internal one-shot LLM call so the chat token stream drops its output instead
# of rendering it as assistant text. Any structured/internal call made while a graph is
# streaming (HIL tool classification, the intent judge, the conversational resolver) must
# carry this, or its structured-output tokens leak into the conversation as a bot message.
# ``silent`` is the flag the messages-stream consumers read (helpers/agent_helpers.py);
# ``metadata.silent`` is the canonical location, the top-level key mirrors it for the
# other consumers. Pass as ``config=SILENT_LLM_CONFIG``; it merges with the ambient run
# config, so tracing and thread context are preserved.
SILENT_LLM_CONFIG: RunnableConfig = {
    "silent": True,
    "metadata": {"silent": True},
}  # type: ignore[typeddict-unknown-key]


def metered_config(user_id: str) -> RunnableConfig:
    """The minimal run config for an auxiliary :func:`ainvoke_structured` call:
    who its spend is attributed to (COGS observability — never charged to the
    user's budget). Call sites that already forward a graph config (which
    carries ``configurable.user_id`` already) don't need this."""
    return cast(RunnableConfig, {"configurable": {"user_id": user_id}})


def silent_metered_config(user_id: str) -> RunnableConfig:
    """:data:`SILENT_LLM_CONFIG` plus the spend attribution of
    :func:`metered_config` — for an internal call made *while a graph is
    streaming* and on behalf of a specific user (the HIL intent judge and the
    conversational resolver).

    Both halves are needed and each is easy to forget alone: without the silent
    flags the structured output leaks into the chat as a bot message, and
    without ``user_id`` the call's real COGS lands on nobody.
    """
    return cast(
        RunnableConfig,
        {**SILENT_LLM_CONFIG, **metered_config(user_id)},
    )


def _silenced(config: RunnableConfig) -> RunnableConfig:
    """Copy of ``config`` whose metadata carries ``silent`` — the SSE consumer
    skips message chunks stamped with it (agent_helpers, stream_mode="messages")."""
    merged = dict(config)
    merged["metadata"] = {**(config.get("metadata") or {}), "silent": True}
    return cast(RunnableConfig, merged)


def _with_usage_handler(
    config: RunnableConfig | None, handler: BaseCallbackHandler | None
) -> RunnableConfig:
    """Return ``config`` with ``handler`` attached, never mutating the caller's
    object — several callers pass a shared module-level config constant, and
    graph nodes forward a config whose ``callbacks`` is a live manager. A None
    handler (caller meters the call itself) returns the config unchanged."""
    if handler is None:
        return config if config is not None else RunnableConfig()
    merged: dict[str, Any] = dict(config) if config else {}
    existing = merged.get("callbacks")
    if existing is None:
        merged["callbacks"] = [handler]
    elif isinstance(existing, list):
        merged["callbacks"] = [*existing, handler]
    else:
        manager = existing.copy()
        manager.add_handler(handler, inherit=True)
        merged["callbacks"] = manager
    return cast(RunnableConfig, merged)


async def _record_auxiliary_usage(
    handler: UsageMetadataCallbackHandler, label: str, user_id: str | None
) -> None:
    """Meter one auxiliary (non-agent) model call for COGS observability.

    ``ainvoke_structured`` runs outside the agent graph, so
    ``LLMAccountingMiddleware`` never sees it — without this, memory
    extraction/reconcile/consolidation and every other one-shot helper would
    spend real money that nothing ever measured.

    This spend is deliberately NOT charged to the user's allowance
    (``charge_to_budget=False``): a memory save or an onboarding question is
    background work GAIA does on the user's behalf, not usage they asked for,
    so it must never eat into their chat budget (memory volume is bounded by
    its own count cap). Tokens likewise never touch the per-request token
    ceiling — that counter bounds a single agent tree against runaway loops.
    The cost is booked durably per user (``usage_daily.aux_cost``) and the
    ``llm_call`` event carries ``background=True``, so auxiliary COGS stays
    fully measurable and splittable from in-turn agent spend.
    """
    for model_name, usage in handler.usage_metadata.items():
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        if not (input_tokens or output_tokens):
            continue
        details = usage.get("input_token_details") or {}
        cached_tokens = int(details.get("cache_read", 0) or 0)
        output_details = usage.get("output_token_details") or {}
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
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            reasoning_tokens=reasoning_tokens,
            charge_to_budget=False,
        )
        log.info(
            "llm_call",
            llm_event="llm_call",
            background=True,
            agent_name=label,
            model=model_name,
            user_id=user_id,
            input_tokens=input_tokens,
            cached_tokens=cached_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            cost_usd=cost,
        )


def _aux_structured_runnable(
    schema: type[_StructuredT], temperature: float, config: RunnableConfig | None
) -> Runnable:
    """The structured runnable every auxiliary one-shot runs on: the helper LLM
    re-pointed at :data:`AUX_MODEL_NAME`, with the aux sticky-routing session."""
    # The helper LLM is the cached default instance; run the aux id. The alias
    # must be set on the INSTANCE via model_copy, NOT bound with
    # .bind(model=...): with_structured_output rebuilds the runnable through
    # bind_tools, which drops the outer binding's kwargs — the bound alias
    # silently vanished and every aux call served DEFAULT_MODEL_NAME in the
    # conversation's namespace (measured: the alias never reached the wire).
    # model_copy is the same escape hatch get_helper_llm itself uses for
    # max_tokens, for the identical reason.
    structured = (
        get_helper_llm(temperature=temperature)
        .model_copy(update={"model_name": AUX_MODEL_NAME})
        .with_structured_output(schema)
    )
    # OpenRouter sticky-routing key: bound AFTER with_structured_output (which
    # rebuilds the runnable via bind_tools and drops outer bindings). The aux
    # one-shots get their OWN sticky session (a suffixed id): the sticky
    # routing is per session, and sharing the conversation's session_id made
    # the aux requests re-pin the conversation's provider (measured: the
    # comms' rotation dips).
    session_id = _sticky_session_id(config, auxiliary=True)
    if session_id:
        structured = structured.bind(session_id=session_id)
    return structured


async def ainvoke_structured(
    schema: type[_StructuredT],
    prompt: LanguageModelInput,
    *,
    label: str,
    temperature: float = DEFAULT_LLM_TEMPERATURE,
    config: RunnableConfig | None = None,
    timeout: float | None = LLM_INVOKE_TIMEOUT_SECONDS,
) -> _StructuredT:
    """The single canonical one-shot structured call on the default model. ``prompt``
    is any LangChain input — a plain string (sent as one human message) or a full
    message list — and ``config`` carries optional run config (e.g. silent tags that
    keep internal tokens out of the chat stream, and ``configurable.user_id``, which
    is what the call's spend is metered against). Adds the transient-retry + fallback
    of :func:`ainvoke_llm`. Runs on :func:`get_helper_llm` — structured output is
    always a small JSON blob, never the large-output case. Returns the validated
    ``schema`` instance. Raises ``LLMNotConfiguredError`` when ``OPENROUTER_API_KEY``
    is unset — this lane is OpenRouter, not Google (see :func:`get_default_llm`).

    Runs on :data:`AUX_MODEL_NAME` — a separate model id (the ORIGINAL V4 Flash
    release, not the re-post-trained 0731 revision the graph uses), which is
    what gives these calls their own provider-side cache namespace. The agent
    graph's calls share the conversation's namespace; if the aux calls did
    too, their ~30k tokens/turn of new blocks would evict the conversation
    between turns (measured). Tradeoff: aux one-shots are served by the older
    model version."""
    # Metering lives in ainvoke_llm, which this delegates to — a handler here too
    # would record the same call twice and over-report the user's COGS.
    return cast(
        _StructuredT,
        await ainvoke_llm(
            _aux_structured_runnable(schema, temperature, config),
            prompt,
            config=config,
            label=label,
            timeout=timeout,
        ),
    )


async def ainvoke_structured_gemini(
    schema: type[_StructuredT],
    prompt: LanguageModelInput,
    *,
    label: str,
    temperature: float = DEFAULT_LLM_TEMPERATURE,
    config: RunnableConfig | None = None,
    timeout: float | None = LLM_INVOKE_TIMEOUT_SECONDS,
) -> _StructuredT:
    """The structured one-shot call for the memory pipeline, on direct Gemini.

    Same contract as :func:`ainvoke_structured` (retry + fallback, metering via
    :func:`ainvoke_llm`, validated ``schema`` output) but PREFERRING
    :func:`get_memory_llm` — a DIFFERENT provider from the graph's OpenRouter
    lane, deliberately. The memory extraction is a background task that
    overlaps the graph's next-turn requests; concurrent requests on the same
    provider's cache store wipe each other's cached chains mid-read (measured:
    the comms chain collapses to ~0 under a concurrent alias-lane extraction
    and holds ~99.5% under a concurrent Gemini extraction). A different
    provider has no shared cache store, so the overlap is harmless.

    The isolation is an optimisation, not a requirement: a deployment with only
    ``OPENROUTER_API_KEY`` (the documented self-host path) runs the whole
    pipeline on the aux lane instead, and a Gemini outage falls back to it
    mid-flight. Losing the isolation costs cache hit rate; losing the lane
    would cost the user every memory they never got."""
    if not memory_lane_available():
        return await ainvoke_structured(
            schema, prompt, label=label, temperature=temperature, config=config, timeout=timeout
        )
    structured = get_memory_llm(temperature=temperature).with_structured_output(schema)
    # Metering lives in ainvoke_llm, which this delegates to — a handler here too
    # would record the same call twice and over-report the user's COGS.
    return cast(
        _StructuredT,
        await ainvoke_llm(
            structured,
            prompt,
            fallback=lambda: _aux_structured_runnable(schema, temperature, config),
            config=config,
            label=label,
            timeout=timeout,
        ),
    )
