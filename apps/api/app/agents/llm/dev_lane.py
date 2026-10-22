"""The custom OpenAI-compatible endpoint, and the dev-only switch that sends every LLM call to it.

The endpoint is the custom provider's credential: a saved one, else (in
development) the DEV_LLM_* settings. In development, DEV_DEFAULT_MODEL naming
the menu's custom entry forces every lane onto it: the agent graph
(resolve_lane), every one-shot (resolve_model), the browser's text model, with
no fallback to another provider. Production never reads the switch.
"""

from dataclasses import dataclass
from functools import cache

import httpx
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.agents.llm.exceptions import LLMNotConfiguredError
from app.config.settings import settings
from app.constants.llm import (
    DEFAULT_MAX_TOKENS,
    DEV_LLM_BROWSER_HEADERS,
    DEV_LLM_CONNECT_TIMEOUT_SECONDS,
    DEV_LLM_DEFAULT_REASONING,
    DEV_LLM_READ_TIMEOUT_SECONDS,
    DEV_MODEL_OPTIONS,
    OPENAI_REASONING_EFFORT,
    DevLLMApi,
    DevModelOption,
    LLMProviderName,
    ReasoningLevel,
)
from app.constants.log_tags import LogTag
from app.constants.providers import CredentialProviderName
from app.services.providers.provider_credentials_service import is_usable, resolved_config
from shared.py.wide_events import log

CUSTOM_ENDPOINT_NOT_CONFIGURED_MESSAGE = (
    "The custom endpoint needs an API key, base URL and model: save them in "
    "Settings → AI Providers, or in development set DEV_LLM_BASE_URL, "
    "DEV_LLM_API_KEY and DEV_LLM_MODEL."
)


@dataclass(frozen=True, slots=True)
class CustomEndpoint:
    """Where the custom lane's requests go."""

    base_url: str
    api_key: str
    model: str
    api: DevLLMApi


def custom_endpoint() -> CustomEndpoint:
    """Return the custom provider's endpoint; raise LLMNotConfiguredError unless its key, URL and model are all set."""
    config = resolved_config(CredentialProviderName.CUSTOM)
    if config is None or not is_usable(CredentialProviderName.CUSTOM, config):
        raise LLMNotConfiguredError(CUSTOM_ENDPOINT_NOT_CONFIGURED_MESSAGE)
    # DevLLMApi() again: the evals harness re-points these settings at runtime.
    return CustomEndpoint(
        base_url=str(config.base_url),
        api_key=str(config.api_key),
        model=str(config.model),
        api=DevLLMApi(settings.DEV_LLM_API),
    )


def dev_default_model_id() -> str | None:
    """Return the dev-menu key DEV_DEFAULT_MODEL names; None outside development, when unset, or unknown."""
    model_id = settings.DEV_DEFAULT_MODEL
    if not settings.deployment.dev_tools or not model_id:
        return None
    if model_id not in DEV_MODEL_OPTIONS:
        log.warning(
            f"{LogTag.AGENT} DEV_DEFAULT_MODEL is not a DEV_MODEL_OPTIONS key; "
            "keeping the plan-resolved lane",
            dev_default=model_id,
        )
        return None
    return model_id


def dev_default_option() -> DevModelOption | None:
    """Return the dev-menu entry DEV_DEFAULT_MODEL names, or None (see dev_default_model_id)."""
    model_id = dev_default_model_id()
    return DEV_MODEL_OPTIONS[model_id] if model_id else None


def custom_lane_forced() -> bool:
    """Whether every LLM call in this process must run on the custom endpoint."""
    option = dev_default_option()
    return option is not None and option.provider is LLMProviderName.CUSTOM


@cache
def build_custom_chat_model(
    *,
    temperature: float,
    max_tokens: int,
    endpoint: CustomEndpoint,
    reasoning: ReasoningLevel | None = None,
) -> ChatOpenAI:
    """Build the endpoint's chat model for the API that DEV_LLM_API names.

    ChatOpenAI, not ChatOpenRouter: the OpenRouter SDK requires a system
    fingerprint that OpenAI-compatible lanes omit. Cached per endpoint and shape,
    so each keeps one connection pool and a changed credential builds anew.
    """
    responses = endpoint.api is DevLLMApi.RESPONSES
    effort = OPENAI_REASONING_EFFORT[
        reasoning if reasoning is not None else DEV_LLM_DEFAULT_REASONING
    ]
    llm = ChatOpenAI(
        model=endpoint.model,
        # OpenAI's reasoning models accept only the default temperature once
        # reasoning is on (gpt-6-luna: 400 "Unsupported parameter").
        temperature=None if responses else temperature,
        streaming=True,
        stream_usage=True,
        max_completion_tokens=max_tokens,
        # The OpenAI SDK honors max_retries=0, so retries stay with with_llm_retry.
        max_retries=0,
        api_key=SecretStr(endpoint.api_key),
        base_url=endpoint.base_url,
        # Bounded per request so a stalled reply fails fast and with_llm_retry
        # retries it; the SDK default (600 s) outlasts the whole call budget.
        timeout=httpx.Timeout(
            DEV_LLM_READ_TIMEOUT_SECONDS, connect=DEV_LLM_CONNECT_TIMEOUT_SECONDS
        ),
        # Discounted lanes sit behind Cloudflare, which 403s programmatic user
        # agents. A default header, not the httpx client's: the SDK sets its own
        # User-Agent per request, which overrides a client-level one.
        default_headers=DEV_LLM_BROWSER_HEADERS,
        use_responses_api=responses,
        reasoning={"effort": effort} if responses else None,
        reasoning_effort=None if responses else effort,
    )
    # Fractional-window middleware reads the window off the profile at graph-build
    # time and raises without one; an arbitrary endpoint has no curated profile.
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return llm
