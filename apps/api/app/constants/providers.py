"""Provider catalog shared by the credentials service, setup API, and web UI.

Single source of truth for user-configurable providers: display metadata,
preset endpoints (so configuring OpenCode/Nous means pasting ONLY an API key),
and default models. Brand icons are resolved client-side from Google's favicon
service via ``favicon_domain``.
"""

from typing import TypedDict


class ProviderPreset(TypedDict):
    label: str
    base_url: str  # empty ⇒ provider has no configurable endpoint
    default_model: str  # empty ⇒ fetched from the endpoint at configure time
    favicon_domain: str
    needs_base_url: bool  # UI shows the base-URL field (Ollama/custom)


PRESETS: dict[str, ProviderPreset] = {
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "openrouter.ai",
        "needs_base_url": False,
    },
    "gemini": {
        "label": "Google Gemini",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "ai.google.dev",
        "needs_base_url": False,
    },
    "ollama": {
        "label": "Ollama",
        "base_url": "http://host.docker.internal:11434",
        "default_model": "llama3.2",
        "favicon_domain": "ollama.com",
        "needs_base_url": True,
    },
    # Custom OpenAI-compatible lane. Presets below prefill base URL + model so
    # configuration is paste-a-key-only; the base-URL field stays editable for
    # manual gateways.
    "custom": {
        "label": "Custom / OpenAI-compatible",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "opencode.ai",
        "needs_base_url": True,
    },
    "opencode": {
        "label": "OpenCode",
        "base_url": "https://opencode.ai/zen/go/v1",
        "default_model": "deepseek-v4-flash",
        "favicon_domain": "opencode.ai",
        "needs_base_url": False,
    },
    "nous": {
        "label": "Nous Research",
        "base_url": "https://inference-api.nousresearch.com/v1",
        "default_model": "",
        "favicon_domain": "nousresearch.com",
        "needs_base_url": False,
    },
    # Search tool key — a single credential, no LLM endpoint, and no live
    # probe (the setup test endpoint hard-rejects it).
    "tavily": {
        "label": "Tavily",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "tavily.com",
        "needs_base_url": False,
    },
    # Tool / integration keys — no LLM endpoint, single-credential cards.
    "composio": {
        "label": "Composio",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "composio.dev",
        "needs_base_url": False,
    },
    "e2b": {
        "label": "E2B Sandbox",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "e2b.dev",
        "needs_base_url": False,
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "openai.com",
        "needs_base_url": False,
    },
    "resend": {
        "label": "Resend Email",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "resend.com",
        "needs_base_url": False,
    },
    "cloudinary": {
        "label": "Cloudinary",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "cloudinary.com",
        "needs_base_url": False,
    },
    "google_oauth": {
        "label": "Google OAuth",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "accounts.google.com",
        "needs_base_url": False,
    },
    "firecrawl": {
        "label": "Firecrawl",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "firecrawl.dev",
        "needs_base_url": False,
    },
}

# Credential-store providers. "custom" covers OpenCode/Nous/any OpenAI-compatible
# gateway (its UI card exposes the preset chips); "tavily" is a tool key, not an LLM.
CREDENTIAL_PROVIDERS: tuple[str, ...] = (
    "openrouter",
    "gemini",
    "ollama",
    "custom",
    "tavily",
    "composio",
    "e2b",
    "openai",
    "resend",
    "cloudinary",
    "google_oauth",
    "firecrawl",
)

FAVICON_URL_TEMPLATE = "https://www.google.com/s2/favicons?domain={domain}&sz=128"

__all__ = [
    "PRESETS",
    "CREDENTIAL_PROVIDERS",
    "ProviderPreset",
    "FAVICON_URL_TEMPLATE",
]
