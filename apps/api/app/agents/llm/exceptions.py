"""Curated provider/infra exception sets for the LLM retry + fallback policy.

Kept out of client.py so the policy lives in one named place instead of as
module-level globals next to the invocation logic.
"""

from google.api_core.exceptions import (
    DeadlineExceeded,
    GoogleAPICallError,
    InternalServerError,
    ResourceExhausted,
    ServiceUnavailable,
)
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
# Provider 429s (``ResourceExhausted`` / ``TooManyRequestsResponseError``) are the
# provider's own quota, distinct from the application rate limiter
# (``LangChainRateLimitException``) which must NOT be retried. Covers both Gemini
# (google-api-core) and OpenRouter so retry is provider-agnostic.
LLM_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
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

# Provider/infra failures that trigger a fallback to the default model once retries
# are exhausted — or immediately for the non-transient ones (402 out-of-credits, 401
# auth). A curated provider-error set, NOT a bare ``Exception``: a programming bug
# must fail loud, not silently downgrade the model. ``OpenRouterError`` is the base of
# every OpenRouter response error (new error types are covered automatically);
# ``NoResponseError`` is the SDK's connection failure and is not an ``OpenRouterError``.
LLM_FALLBACK_EXCEPTIONS: tuple[type[BaseException], ...] = (
    OpenRouterError,  # every OpenRouter response error, incl. 402 insufficient credits
    NoResponseError,
    GoogleAPICallError,  # every Gemini google-api-core error
    ConnectionError,
    TimeoutError,
)

# chatbot.py one-shot helper: operational failures degrade to a friendly message;
# programming bugs (TypeError, KeyError, ...) and CancelledError stay fail-loud.
CHATBOT_FALLBACK_EXCEPTIONS: tuple[type[BaseException], ...] = (
    RuntimeError,
    *LLM_FALLBACK_EXCEPTIONS,
)
