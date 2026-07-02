"""Curated provider/infra exception sets for the LLM retry + fallback policy.

Kept out of client.py so the policy lives in one named place instead of as
module-level globals next to the invocation logic.
"""

from google.genai.errors import APIError as GeminiAPIError, ServerError as GeminiServerError
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
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


class LLMNotConfiguredError(RuntimeError):
    """No provider key is configured for the requested model (e.g. the default
    Gemini model without ``GOOGLE_API_KEY``). Typed so degrade-gracefully callers
    can catch exactly this instead of every ``RuntimeError``."""


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
# attempt. The agent model node wraps the bound model in ``with_retry`` on these.
# Provider 429s are the provider's own quota, distinct from the application rate
# limiter (``LangChainRateLimitException``) which must NOT be retried.
#
# Gemini: ``langchain-google-genai`` (google-genai SDK) lets ``ServerError`` (5xx)
# propagate raw but wraps every ``ClientError`` (4xx, INCLUDING transient 429s)
# into ``ChatGoogleGenerativeAIError``, hiding the status class. Retrying that
# wrapper would burn retries on permanent 400/401/404 errors, so Gemini 429s are
# not retried — they fall through to the fallback set instead.
LLM_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    # Gemini (google-genai SDK)
    GeminiServerError,
    # OpenRouter SDK
    *_OPENROUTER_TRANSIENT_ERRORS,
    # stdlib
    ConnectionError,
    TimeoutError,
)

# Provider/infra failures that trigger a fallback to the default model once retries
# are exhausted — or immediately for the non-transient ones (402 out-of-credits, 401
# auth). A curated provider-error set, NOT a bare ``Exception``: a programming bug
# must fail loud, not silently downgrade the model. ``OpenRouterError`` is the base of
# every OpenRouter response error (new error types are covered automatically);
# ``NoResponseError`` is the SDK's connection failure and is not an ``OpenRouterError``.
# ``ChatGoogleGenerativeAIError`` is langchain-google-genai's wrapper around Gemini
# 4xx responses; ``GeminiAPIError`` is the google-genai SDK base covering raw 5xx
# (``ServerError``) and any unwrapped 4xx.
LLM_FALLBACK_EXCEPTIONS: tuple[type[BaseException], ...] = (
    OpenRouterError,  # every OpenRouter response error, incl. 402 insufficient credits
    NoResponseError,
    ChatGoogleGenerativeAIError,
    GeminiAPIError,
    ConnectionError,
    TimeoutError,
)

# chatbot.py one-shot helper: operational failures degrade to a friendly message;
# programming bugs (TypeError, KeyError, bare RuntimeError, ...) and CancelledError
# stay fail-loud.
CHATBOT_FALLBACK_EXCEPTIONS: tuple[type[BaseException], ...] = (
    LLMNotConfiguredError,
    *LLM_FALLBACK_EXCEPTIONS,
)
