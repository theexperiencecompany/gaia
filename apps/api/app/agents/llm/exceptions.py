"""Curated provider/infra exception sets for the LLM retry + fallback policy.

Kept out of client.py so the policy lives in one named place instead of as
module-level globals next to the invocation logic.
"""

from google.genai.errors import APIError as GeminiAPIError, ServerError as GeminiServerError
from langchain_core.exceptions import OutputParserException
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
import openai
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


class MalformedStructuredOutputError(OutputParserException):
    """A structured reply that is not the whole, schema-valid answer.

    Raised instead of repairing it: a lenient parse of a broken reply returns a
    shortened value that looks like a real answer. Retryable, since another
    sample of the same request is usually well formed.
    """


class LLMNotConfiguredError(RuntimeError):
    """No provider key is configured for the requested model.

    Typed so degrade-gracefully callers can catch exactly this instead of
    every RuntimeError.
    """


# OpenRouter SDK transient response/network failures — worth retrying. The
# non-transient ones (402, 401/403, 404, 400/422) fall straight through to
# the fallback instead of burning retries.
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

# OpenAI SDK transient failures (the custom dev lane's ChatOpenAI). APIConnectionError
# covers APITimeoutError; the SDK's own retry is off, so these are the only retries.
_OPENAI_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)

# Transient provider/infra errors — safe to retry; the app rate limiter's
# LangChainRateLimitError must NOT be. Gemini wraps every 4xx (including 429s) into
# ChatGoogleGenerativeAIError, hiding the status class, so Gemini 429s fall through to fallback.
LLM_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    # Gemini (google-genai SDK)
    GeminiServerError,
    # OpenRouter SDK
    *_OPENROUTER_TRANSIENT_ERRORS,
    # OpenAI SDK
    *_OPENAI_TRANSIENT_ERRORS,
    # stdlib
    ConnectionError,
    TimeoutError,
    # A broken structured reply: re-asking samples a new one.
    MalformedStructuredOutputError,
)

# Fallback triggers once retries are exhausted, or immediately for non-transient errors
# (402 out-of-credits, 401 auth). Curated, NOT a bare Exception: a programming bug must fail
# loud, not silently downgrade the model. NoResponseError is not an OpenRouterError.
LLM_FALLBACK_EXCEPTIONS: tuple[type[BaseException], ...] = (
    OpenRouterError,  # every OpenRouter response error, incl. 402 insufficient credits
    NoResponseError,
    openai.APIError,  # every OpenAI SDK response and connection error
    ChatGoogleGenerativeAIError,
    GeminiAPIError,
    ConnectionError,
    TimeoutError,
)

# chatbot.py one-shot helper: operational failures are logged and re-raised for the
# caller to handle (e.g. degrade its own output to a placeholder); programming bugs
# (TypeError, KeyError, bare RuntimeError, ...) and CancelledError stay fail-loud.
CHATBOT_OPERATIONAL_EXCEPTIONS: tuple[type[BaseException], ...] = (
    LLMNotConfiguredError,
    *LLM_FALLBACK_EXCEPTIONS,
)
