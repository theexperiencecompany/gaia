from typing import Any

from google.api_core.exceptions import (
    DeadlineExceeded,
    GoogleAPICallError,
    InternalServerError,
    ResourceExhausted,
    ServiceUnavailable,
)
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.chat_models import (
    BaseChatModel,
)
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.runnables.utils import ConfigurableField
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_openrouter import ChatOpenRouter
from openrouter.errors import (
    BadGatewayResponseError,
    EdgeNetworkTimeoutResponseError,
    InternalServerResponseError,
    NoResponseError,
    OpenRouterError,
    ProviderOverloadedResponseError,
    RequestTimeoutResponseError,
    ServiceUnavailableResponseError,
    TooManyRequestsResponseError,
)
from typing_extensions import TypedDict

from app.config.settings import settings
from app.constants.llm import (
    DEFAULT_GEMINI_MODEL_NAME,
    DEFAULT_GROK_MODEL_NAME,
    DEFAULT_MODEL_NAME,
    OPENROUTER_APP_CATEGORIES,
    OPENROUTER_APP_TITLE,
    OPENROUTER_MAX_OUTPUT_TOKENS,
    OPENROUTER_REASONING,
)
from app.constants.log_tags import LogTag
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from shared.py.wide_events import log

# OpenRouter SDK (the ``openrouter`` package used by ``langchain-openrouter``)
# transient response/network failures — worth retrying. The non-transient ones
# (402 out-of-credits, 401/403 auth, 404, 400/422) are deliberately excluded so
# they fall straight through to the fallback instead of burning retries.
_OPENROUTER_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    TooManyRequestsResponseError,
    InternalServerResponseError,
    BadGatewayResponseError,
    ServiceUnavailableResponseError,
    RequestTimeoutResponseError,
    EdgeNetworkTimeoutResponseError,
    ProviderOverloadedResponseError,
    NoResponseError,
)

# Transient provider/infra errors — safe to retry, usually succeed on a second
# attempt. The agent model node wraps the bound model in ``with_retry`` on these
# (applied AFTER ``bind_tools`` so the ``RunnableRetry`` wrapper need not expose
# it). Provider 429s (``ResourceExhausted`` / ``TooManyRequestsResponseError``)
# are the provider's own quota, distinct from the application rate limiter
# (``LangChainRateLimitException``) which must NOT be retried and never reaches
# the model node. Covers both Gemini (google-api-core) and OpenRouter so retry
# is provider-agnostic.
_LLM_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    # Gemini (google-api-core)
    ResourceExhausted,
    ServiceUnavailable,
    DeadlineExceeded,
    InternalServerError,
    # OpenRouter SDK
    *_OPENROUTER_TRANSIENT_ERRORS,
    # stdlib
    ConnectionError,
    TimeoutError,
)

# Provider/infra failures that trigger a fallback to the default model once
# retries are exhausted — or immediately for the non-transient ones like 402
# out-of-credits and 401 auth. Deliberately a curated provider-error set, NOT a
# bare ``Exception``: a programming bug must fail loud, not silently downgrade
# the model. ``OpenRouterError`` is the base of every OpenRouter response error
# (so new error types are covered automatically); ``NoResponseError`` is the
# SDK's connection failure and is not an ``OpenRouterError`` subclass.
_LLM_FALLBACK_EXCEPTIONS: tuple[type[BaseException], ...] = (
    OpenRouterError,  # every OpenRouter response error, incl. 402 insufficient credits
    NoResponseError,
    GoogleAPICallError,  # every Gemini google-api-core error
    ConnectionError,
    TimeoutError,
)

# Attempts for the model-level transient-error retry in the agent model node.
LLM_RETRY_MAX_ATTEMPTS = 3


def with_llm_retry(runnable: Runnable) -> Runnable:
    """The single, canonical LLM retry. Wraps a (tool-bound) model runnable so
    transient provider/infra errors are retried with exponential backoff before
    the caller falls back to the default model. Applied AFTER ``bind_tools`` so
    the ``RunnableRetry`` wrapper never has to expose ``bind_tools``."""
    return runnable.with_retry(
        retry_if_exception_type=_LLM_RETRYABLE_EXCEPTIONS,
        stop_after_attempt=LLM_RETRY_MAX_ATTEMPTS,
        wait_exponential_jitter=True,
    )


PROVIDER_MODELS = {
    "gemini": DEFAULT_GEMINI_MODEL_NAME,
    "openai": "gpt-4o-mini",
    "openrouter": DEFAULT_GROK_MODEL_NAME,
}
PROVIDER_PRIORITY = {
    1: "gemini",
    2: "openai",
    3: "openrouter",
}


class LLMProvider(TypedDict):
    name: str
    instance: BaseChatModel


@lazy_provider(
    name="openai_llm",
    required_keys=[settings.OPENAI_API_KEY],
    strategy=MissingKeyStrategy.WARN,
    warning_message="OpenAI API key not configured. Models provided by openai will not work.",
)
def init_openai_llm():
    """Initialize OpenAI LLM with default model."""
    return ChatOpenAI(
        model=PROVIDER_MODELS["openai"],
        temperature=0.1,
        streaming=True,
        stream_usage=True,
    ).configurable_fields(
        model_name=ConfigurableField(id="model", name="Model", description="Which model to use"),
    )


@lazy_provider(
    name="gemini_llm",
    required_keys=[settings.GOOGLE_API_KEY],
    strategy=MissingKeyStrategy.WARN,
    warning_message="Google API key not configured. Models provided by Google Gemini will not work.",
)
def init_gemini_llm():
    """Initialize Gemini LLM with default model."""
    llm = ChatGoogleGenerativeAI(
        model=PROVIDER_MODELS["gemini"],
        temperature=0.1,
        streaming=True,
    ).configurable_fields(
        model=ConfigurableField(id="model_name", name="Model", description="Which model to use"),
    )
    return llm


@lazy_provider(
    name="openrouter_llm",
    required_keys=[settings.OPENROUTER_API_KEY],
    strategy=MissingKeyStrategy.WARN,
    warning_message="OpenRouter API key not configured. Models provided via OpenRouter (Grok, etc.) will not work.",
)
def init_openrouter_llm():
    """Initialize the OpenRouter LLM (MiniMax M3, Grok, etc.).

    Uses ChatOpenRouter (langchain-openrouter), not ChatOpenAI, because it parses
    OpenRouter's `reasoning`/`reasoning_details` fields into standard reasoning
    content blocks — ChatOpenAI silently drops them. That is what lets us surface
    the model's thinking. Reasoning effort is the native `reasoning` field; provider
    routing (the first-party MiniMax pin) rides `model_kwargs` (OpenRouter's
    `provider` request param). Both are per-request configurable.
    """
    return ChatOpenRouter(
        model=PROVIDER_MODELS["openrouter"],
        temperature=0.1,
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
    ).configurable_fields(
        model_name=ConfigurableField(id="model", name="Model", description="Which model to use"),
        reasoning=ConfigurableField(
            id="reasoning",
            name="Reasoning",
            description="OpenRouter reasoning effort (per-agent thinking budget)",
        ),
        model_kwargs=ConfigurableField(
            id="model_kwargs",
            name="Model kwargs",
            description="Extra OpenRouter request params (e.g. provider routing pin)",
        ),
    )


def init_llm(
    preferred_provider: str | None = None,
    fallback_enabled: bool = True,
):
    """Initialize an LLM with configurable fallback alternatives by provider priority.

    Without a preferred_provider, uses the default priority order. Raises
    ValueError on an unknown provider, RuntimeError if none are configured.
    """
    # Validate preferred provider if specified
    if preferred_provider and preferred_provider not in PROVIDER_MODELS:
        valid_providers = list(PROVIDER_MODELS.keys())
        raise ValueError(
            f"Invalid preferred_provider '{preferred_provider}'. "
            f"Valid providers are: {valid_providers}"
        )

    # Get available provider instances from global providers registry
    available_providers = _get_available_providers()

    if not available_providers:
        raise RuntimeError("No LLM providers are properly configured.")

    # Determine provider order based on preferred provider or default priority
    ordered_providers = _get_ordered_providers(
        available_providers, preferred_provider, fallback_enabled
    )

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


def _get_available_providers() -> dict[str, Any]:
    """Retrieve available LLM provider instances from the global registry,
    mapped by provider name."""
    # Mapping of provider names to their instance keys in the providers registry
    provider_instance_mapping = {
        "openai": "openai_llm",
        "gemini": "gemini_llm",
        "openrouter": "openrouter_llm",
    }

    available = {}
    for provider_name, instance_key in provider_instance_mapping.items():
        instance = providers.get(instance_key)
        if instance is not None:
            available[provider_name] = instance

    return available


def _get_ordered_providers(
    available_providers: dict[str, Any],
    preferred_provider: str | None,
    fallback_enabled: bool,
) -> list[LLMProvider]:
    """Order providers by preference and availability, returning LLMProvider
    objects in priority order."""
    ordered = []
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


def _create_configurable_llm(primary: LLMProvider, alternatives: list[LLMProvider]):
    """Create a configurable LLM instance with fallback alternatives."""
    if not alternatives:
        # Return primary instance directly if no alternatives
        return primary["instance"]

    # Create configurable alternatives mapping
    alternatives_mapping = {alt["name"]: alt["instance"] for alt in alternatives}

    primary_instance = primary["instance"]

    return primary_instance.configurable_alternatives(
        ConfigurableField(id="provider"),
        default_key=primary["name"],
        prefix_keys=False,
        **alternatives_mapping,
    )


def register_llm_providers():
    """Register LLM providers in the lazy loader."""
    init_openai_llm()
    init_gemini_llm()
    init_openrouter_llm()


def init_fallback_llm() -> BaseChatModel | None:
    """The default model (Gemini) used as the last-resort fallback when the
    user-selected model keeps failing mid-turn. Reuses the registered
    ``gemini_llm`` provider, pinned to the default model so a paid/dev selection
    can't leak in. Returns ``None`` when Google isn't configured, in which case
    the agent node skips the fallback instead of crashing."""
    gemini = providers.get("gemini_llm")
    if gemini is None:
        return None
    return gemini.with_config(configurable={"model_name": DEFAULT_MODEL_NAME})


def get_default_llm(*, temperature: float = 0.1) -> BaseChatModel:
    """The default model (direct Gemini) for every auxiliary LLM task — follow-ups,
    research, memory extraction, integration inference, profile/holo cards, vision
    helpers, workflow generation, one-shot helpers. The pro model is reserved for
    the main chat agent (see ``plan_model``); auxiliary tasks never use it. The
    optional ``temperature`` lets creative tasks opt into more variation. Raises if
    Google is not configured."""
    if not settings.GOOGLE_API_KEY:
        raise RuntimeError("Default LLM not configured. Set GOOGLE_API_KEY.")
    return ChatGoogleGenerativeAI(model=DEFAULT_GEMINI_MODEL_NAME, temperature=temperature)


async def ainvoke_llm(
    primary: Runnable,
    messages: LanguageModelInput,
    *,
    fallback: Runnable | None = None,
    config: RunnableConfig | None = None,
    label: str = "model",
) -> Any:
    """The single way to invoke an LLM. Retries transient provider/infra errors
    (``with_llm_retry``), then falls back to ``fallback`` (if given) on a provider
    failure (``_LLM_FALLBACK_EXCEPTIONS``). Programming bugs and
    ``asyncio.CancelledError`` propagate — they are never silently downgraded.
    Returns whatever the runnable returns: a ``BaseMessage`` for a chat model, or
    the parsed object for a ``with_structured_output`` runnable."""
    try:
        return await with_llm_retry(primary).ainvoke(messages, config=config)
    except _LLM_FALLBACK_EXCEPTIONS as primary_error:
        if fallback is None:
            raise
        log.warning(
            f"{LogTag.AGENT} llm '{label}' failed; falling back to the default model",
            llm={"label": label, "error_type": type(primary_error).__name__, "fell_back": True},
            error=str(primary_error),
        )
        return await fallback.ainvoke(messages, config=config)


def invoke_llm(
    primary: Runnable,
    messages: LanguageModelInput,
    *,
    fallback: Runnable | None = None,
    config: RunnableConfig | None = None,
    label: str = "model",
) -> Any:
    """Sync counterpart of :func:`ainvoke_llm`."""
    try:
        return with_llm_retry(primary).invoke(messages, config=config)
    except _LLM_FALLBACK_EXCEPTIONS as primary_error:
        if fallback is None:
            raise
        log.warning(
            f"{LogTag.AGENT} llm '{label}' failed; falling back to the default model",
            llm={"label": label, "error_type": type(primary_error).__name__, "fell_back": True},
            error=str(primary_error),
        )
        return fallback.invoke(messages, config=config)
