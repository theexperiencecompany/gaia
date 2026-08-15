"""LLM factory for the Browser-Use agent.

Deliberately decoupled from the chat harness model: browser automation always
gets a strong, vision-capable model chosen by ``BROWSER_USE_LLM_*`` settings,
regardless of which model the surrounding conversation runs on. Browser-Use
ships its own chat wrappers (it is not a LangChain model), so this builds one of
those. Imports are local so the heavy ``browser_use`` package loads only when a
browser task actually runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config.settings import settings
from app.services.browser.exceptions import BrowserUnavailableError

if TYPE_CHECKING:
    from browser_use.llm.base import BaseChatModel


def _provider_fallback_keys() -> dict[str, str | None]:
    """The GAIA API key each provider falls back to when no browser-specific key is set."""
    return {
        "openai": settings.OPENAI_API_KEY,
        "openrouter": settings.OPENROUTER_API_KEY,
        "google": settings.GOOGLE_API_KEY,
    }


# OpenRouter is OpenAI-wire-compatible; Browser-Use talks to it via ChatOpenAI.
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


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

    if provider in ("openai", "openrouter"):
        from browser_use import ChatOpenAI  # noqa: PLC0415

        base_url = settings.BROWSER_USE_LLM_BASE_URL or (
            _OPENROUTER_BASE_URL if provider == "openrouter" else None
        )
        return ChatOpenAI(model=model, api_key=api_key, base_url=base_url)

    raise BrowserUnavailableError(f"Unknown browser LLM provider: '{provider}'.")
