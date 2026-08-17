import asyncio
from functools import cache
from typing import Any, TypeVar, cast

from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler
from langchain_core.language_models import LanguageModelInput, LanguageModelLike
from langchain_core.language_models.chat_models import (
    BaseChatModel,
)
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
    DEFAULT_GEMINI_MODEL_NAME,
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
    DEV_LLM_MAX_OUTPUT_TOKENS,
    LLM_INVOKE_TIMEOUT_SECONDS,
    LLM_RETRY_MAX_ATTEMPTS,
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
    VISION_MODEL_NAME,
)
from app.constants.log_tags import LogTag
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.services.llm_metering import record_llm_call
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
    ).configurable_fields(model=_MODEL_FIELD)
    return llm


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
    # No base_url kwarg here on purpose: passing None would override the field's
    # OPENROUTER_API_BASE env default_factory. Redirecting to the stub is sim
    # mode's job (_sim_llm); this construction is identical to pre-sim behavior.
    return _openrouter_wire_configurables(
        without_sdk_retry(
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
    )


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
    return _openrouter_wire_configurables(
        without_sdk_retry(
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
    )


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
    OpenRouter) used by EVERY auxiliary LLM task — follow-ups, research, memory
    extraction, integration inference, profile/holo cards, vision helpers, workflow
    generation, context summarization, onboarding, one-shot helpers. The pro model is
    reserved for the main chat agent (see ``lane``); auxiliary tasks never use it.
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


def _stamp_fallback(result: _ResultT) -> _ResultT:
    """Mark a fallback-produced AIMessage so downstream layers can surface the
    downgrade (SSE event, accounting). No-op for non-message results."""
    metadata = getattr(result, "response_metadata", None)
    if isinstance(metadata, dict):
        metadata["gaia_fell_back"] = True
        metadata["gaia_fallback_model"] = DEFAULT_MODEL_NAME
    return result


def _resolve_fallback(fallback: LLMFallback, label: str, primary_error: BaseException) -> Runnable:
    """Materialize the fallback (calling a factory if one was passed), log the
    downgrade, and return the retry-wrapped runnable. Re-raises ``primary_error``
    when no fallback is available."""
    resolved = fallback() if callable(fallback) and not isinstance(fallback, Runnable) else fallback
    if resolved is None:
        raise primary_error
    log.warning(
        f"{LogTag.AGENT} llm call failed; falling back to the default model",
        llm={"label": label, "error_type": type(primary_error).__name__, "fell_back": True},
        error=str(primary_error),
    )
    return with_llm_retry(resolved)


async def ainvoke_llm(
    primary: Runnable,
    messages: LanguageModelInput,
    *,
    fallback: LLMFallback = None,
    config: RunnableConfig | None = None,
    label: str = "model",
    max_attempts: int = LLM_RETRY_MAX_ATTEMPTS,
    timeout: float | None = LLM_INVOKE_TIMEOUT_SECONDS,
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
    # The agent graph does NOT come through this function (it runs the model via
    # LangGraph, metered by LLMAccountingMiddleware), so there is no double count.
    usage_handler = UsageMetadataCallbackHandler()
    user_id = (config or {}).get("configurable", {}).get("user_id")
    try:
        async with asyncio.timeout(timeout):
            try:
                return await with_llm_retry(primary, max_attempts=max_attempts).ainvoke(
                    messages, config=_with_usage_handler(config, usage_handler)
                )
            except LLM_FALLBACK_EXCEPTIONS as primary_error:
                # The fallback runs under ``fallback_config`` when given. Reusing
                # ``config`` here is what made provider failover a no-op: LangChain
                # merges a passed config OVER a ``with_config`` one, so the run's
                # own configurable put the just-failed provider straight back.
                return _stamp_fallback(
                    await _resolve_fallback(fallback, label, primary_error).ainvoke(
                        messages,
                        config=_with_usage_handler(fallback_config or config, usage_handler),
                    )
                )
    finally:
        # ``finally``: a failed call still burned the tokens of every attempt the
        # retry and fallback made, and that spend is just as real.
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


def _with_usage_handler(
    config: RunnableConfig | None, handler: BaseCallbackHandler
) -> RunnableConfig:
    """Return ``config`` with ``handler`` attached, never mutating the caller's
    object — several callers pass a shared module-level config constant, and
    graph nodes forward a config whose ``callbacks`` is a live manager."""
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
            cost_usd=cost,
        )


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
    of :func:`ainvoke_llm`. Returns the validated ``schema`` instance. Raises if Google
    is not configured (see ``get_default_llm``)."""
    structured = get_default_llm(temperature=temperature).with_structured_output(schema)
    # Metering lives in ainvoke_llm, which this delegates to — a handler here too
    # would record the same call twice and over-report the user's COGS.
    return cast(
        _StructuredT,
        await ainvoke_llm(structured, prompt, config=config, label=label, timeout=timeout),
    )
