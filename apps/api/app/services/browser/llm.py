"""LLM factory for the Browser-Use agent.

Deliberately decoupled from the chat harness model: browser automation always
gets a strong, vision-capable model chosen by ``BROWSER_USE_LLM_*`` settings,
regardless of which model the surrounding conversation runs on. Browser-Use
ships its own chat wrappers (it is not a LangChain model), so this builds one of
those. Imports are local so the heavy ``browser_use`` package loads only when a
browser task actually runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.config.settings import settings
from app.services.browser.exceptions import BrowserUnavailableError

if TYPE_CHECKING:
    from browser_use.llm.base import BaseChatModel


def _provider_fallback_keys() -> dict[str, str | None]:
    """The GAIA API key each provider falls back to when no browser-specific key is set.

    ``deepseek`` has no entry: GAIA holds no native DeepSeek key (see
    ``.env.example`` — only a Nous Research dev override exists for it), so
    that provider must either get ``BROWSER_USE_LLM_API_KEY`` explicitly, or
    the deployer should pick ``openrouter`` with a ``deepseek/...`` model,
    which already reaches DeepSeek through ``OPENROUTER_API_KEY`` (GAIA's own
    default chat model, ``DEFAULT_MODEL_NAME`` in ``app/constants/llm.py``, is
    exactly that: ``deepseek/deepseek-v4-flash-0731`` over OpenRouter).
    """
    return {
        "openai": settings.OPENAI_API_KEY,
        "openrouter": settings.OPENROUTER_API_KEY,
        "google": settings.GOOGLE_API_KEY,
    }


# OpenRouter is OpenAI-wire-compatible; Browser-Use talks to it via ChatOpenAI.
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Providers whose chat model cannot take image input, however it's delivered —
# used to force ``use_vision`` off rather than send screenshots a text-only
# model will ignore or reject. Browser-Use's DeepSeek wrapper (chat.completions
# against api.deepseek.com) is text-only; an OpenRouter-routed DeepSeek model
# is judged by the live catalog instead (see resolve_use_vision).
_TEXT_ONLY_PROVIDERS = frozenset({"deepseek"})


def _resolve_api_key(provider: str) -> str | None:
    override: str | None = settings.BROWSER_USE_LLM_API_KEY
    return override or _provider_fallback_keys().get(provider)


def build_browser_llm() -> BaseChatModel:
    """Build the Browser-Use chat model for the configured provider.

    Raises :class:`BrowserUnavailableError` when the provider is unknown or its
    API key is missing, so the tool reports a clean reason instead of the agent
    failing deep inside a run.
    """
    provider = settings.BROWSER_USE_LLM_PROVIDER.lower()
    model = settings.BROWSER_USE_LLM_MODEL
    api_key = _resolve_api_key(provider)
    if not api_key:
        raise BrowserUnavailableError(
            f"Browser agent LLM not configured: set an API key for provider '{provider}'."
        )

    if provider == "anthropic":
        from browser_use import ChatAnthropic  # noqa: PLC0415

        return ChatAnthropic(model=model, api_key=api_key)

    if provider == "google":
        from browser_use import ChatGoogle  # noqa: PLC0415

        return ChatGoogle(model=model, api_key=api_key)

    if provider == "deepseek":
        # Browser-Use's DeepSeek wrapper is NOT re-exported from the top-level
        # `browser_use` package (absent from its `_LAZY_IMPORTS`/`__all__`, unlike
        # ChatOpenAI/ChatGoogle/ChatAnthropic) — import it from its real module.
        from browser_use.llm.deepseek.chat import ChatDeepSeek  # noqa: PLC0415

        # Only override base_url when set — ChatDeepSeek's own default already
        # points at DeepSeek's official endpoint.
        if settings.BROWSER_USE_LLM_BASE_URL:
            return ChatDeepSeek(
                model=model, api_key=api_key, base_url=settings.BROWSER_USE_LLM_BASE_URL
            )
        return ChatDeepSeek(model=model, api_key=api_key)

    if provider in ("openai", "openrouter"):
        from browser_use import ChatOpenAI  # noqa: PLC0415

        base_url = settings.BROWSER_USE_LLM_BASE_URL or (
            _OPENROUTER_BASE_URL if provider == "openrouter" else None
        )
        # When the endpoint cannot serve `json_schema`, hand Browser-Use its own
        # fallback: schema in the system prompt, plain-text JSON parsed back.
        # Vision is unaffected — image input alone is fine on those lanes.
        schema_in_prompt = settings.BROWSER_USE_LLM_SCHEMA_IN_PROMPT
        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
            "add_schema_to_system_prompt": schema_in_prompt,
            "dont_force_structured_output": schema_in_prompt,
        }
        effort = settings.BROWSER_USE_LLM_REASONING_EFFORT
        if effort:
            # Naming this model in `reasoning_models` is what makes Browser-Use
            # forward `reasoning_effort` at all — its check is a substring match
            # against the model name, not a capability lookup.
            kwargs["reasoning_effort"] = effort
            kwargs["reasoning_models"] = [model]
        return ChatOpenAI(**kwargs)

    raise BrowserUnavailableError(f"Unknown browser LLM provider: '{provider}'.")


async def resolve_use_vision() -> bool:
    """Whether the browser agent should be sent step screenshots.

    ``BROWSER_USE_VISION`` is the operator's cost/reliability switch; this
    additionally forces it off when the *configured* provider/model plainly
    can't see images, so a text-only model isn't fed screenshots it will
    ignore or error on. OpenRouter models are checked against the live model
    catalog (the same source ``app/agents/llm/vision/capability.py`` uses for
    the chat lane) rather than curated here, since vision support varies
    per-model within that provider.
    """
    if not settings.BROWSER_USE_VISION:
        return False

    provider = settings.BROWSER_USE_LLM_PROVIDER.lower()
    if provider in _TEXT_ONLY_PROVIDERS:
        return False

    if provider == "openrouter":
        from app.agents.llm.model_catalog import get_openrouter_catalog  # noqa: PLC0415

        catalog = await get_openrouter_catalog()
        return await catalog.accepts_images(settings.BROWSER_USE_LLM_MODEL)

    return True
