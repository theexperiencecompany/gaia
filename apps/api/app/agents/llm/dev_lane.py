"""The DEV-ONLY custom endpoint (DEV_LLM_*), and the one switch that sends every LLM call to it.

In development, DEV_DEFAULT_MODEL naming the menu's custom entry forces every
lane onto the endpoint: the agent graph (resolve_lane), every one-shot
(resolve_model), the browser's text model, with no fallback to another provider.
Production never reads any of it.
"""

from dataclasses import dataclass
from functools import cache

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.agents.llm.exceptions import LLMNotConfiguredError
from app.config.settings import settings
from app.constants.llm import (
    DEFAULT_MAX_TOKENS,
    DEV_LLM_BROWSER_HEADERS,
    DEV_MODEL_OPTIONS,
    OPENAI_REASONING_EFFORT,
    DevLLMApi,
    DevModelOption,
    LLMProviderName,
    ReasoningLevel,
)
from app.constants.log_tags import LogTag
from shared.py.wide_events import log


@dataclass(frozen=True, slots=True)
class CustomEndpoint:
    """Where the custom lane's requests go, read from the DEV_LLM_* settings."""

    base_url: str
    api_key: str
    model: str
    api: DevLLMApi


def custom_endpoint() -> CustomEndpoint:
    """Return the configured endpoint; raise LLMNotConfiguredError naming what is missing."""
    base_url, api_key, model = (
        settings.DEV_LLM_BASE_URL,
        settings.DEV_LLM_API_KEY,
        settings.DEV_LLM_MODEL,
    )
    if not (base_url and api_key and model):
        raise LLMNotConfiguredError(
            "The custom dev endpoint needs DEV_LLM_BASE_URL, DEV_LLM_API_KEY and DEV_LLM_MODEL."  # pragma: no mutate
        )
    # DevLLMApi() again: the evals harness re-points these settings at runtime.
    return CustomEndpoint(
        base_url=base_url, api_key=api_key, model=model, api=DevLLMApi(settings.DEV_LLM_API)
    )


def dev_default_model_id() -> str | None:
    """Return the dev-menu key DEV_DEFAULT_MODEL names; None outside development, when unset, or unknown."""
    model_id = settings.DEV_DEFAULT_MODEL
    if settings.ENV != "development" or not model_id:
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
    *, temperature: float, max_tokens: int, reasoning: ReasoningLevel | None = None
) -> ChatOpenAI:
    """Build the custom endpoint's chat model, over the API DEV_LLM_API names.

    ChatOpenAI, not ChatOpenRouter: the openrouter SDK requires a
    system_fingerprint that OpenAI-compatible lanes omit. Cached so each shape
    builds one client instead of opening new ones per call.
    """
    endpoint = custom_endpoint()
    responses = endpoint.api is DevLLMApi.RESPONSES
    effort = OPENAI_REASONING_EFFORT[reasoning] if reasoning is not None else None
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
        # Discounted lanes sit behind Cloudflare, which 403s programmatic user agents.
        # default_headers, not an httpx client's: the SDK sets its own per request.
        default_headers=DEV_LLM_BROWSER_HEADERS,
        use_responses_api=responses,
        reasoning={"effort": effort} if responses and effort else None,
        reasoning_effort=None if responses else effort,
    )
    # Fractional-window middleware reads the window off the profile at graph-build
    # time and raises without one; an arbitrary endpoint has no curated profile.
    llm.profile = {"max_input_tokens": DEFAULT_MAX_TOKENS}
    return llm
