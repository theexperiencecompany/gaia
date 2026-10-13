"""Provider catalog shared by the credentials service, LLM client, setup API, and web UI.

Single source of truth for user-configurable providers: display metadata,
preset endpoints (so configuring OpenCode or Nous means pasting only an API
key), the model each LLM provider runs per role, and the order lanes try them.
Brand icons resolve client-side from the favicon service via favicon_domain.
"""

from dataclasses import dataclass
from typing import TypedDict

from app.constants.llm import (
    AUX_MODEL_NAME,
    COMMS_MODEL_NAME,
    DEFAULT_GEMINI_MODEL_NAME,
    DEFAULT_MODEL_NAME,
    HIL_JUDGE_MODEL_NAME,
    MEMORY_MODEL_NAME,
    OLLAMA_DEFAULT_MODEL_NAME,
    OPENROUTER_VISION_MODEL_NAME,
    VISION_MODEL_NAME,
    LLMProviderName,
    ModelUse,
)


@dataclass(frozen=True, slots=True)
class LLMModelProfile:
    """The model one LLM provider runs for each role.

    None on a one-shot text role means the provider's chat model serves it;
    None on chat means only an operator-configured model can; None on vision
    means the provider cannot see.
    """

    chat: str | None
    helper: str | None
    judge: str | None
    memory: str | None
    vision: str | None

    def for_use(self, use: ModelUse) -> str | None:
        """Return the catalog model for a one-shot use; None defers to the chat model (or, for vision, to nobody)."""
        match use:
            case ModelUse.HELPER:
                return self.helper
            case ModelUse.JUDGE:
                return self.judge
            case ModelUse.MEMORY:
                return self.memory
            case ModelUse.VISION:
                return self.vision


LLM_MODEL_PROFILES: dict[LLMProviderName, LLMModelProfile] = {
    LLMProviderName.OPENROUTER: LLMModelProfile(
        chat=DEFAULT_MODEL_NAME,
        helper=AUX_MODEL_NAME,
        judge=HIL_JUDGE_MODEL_NAME,
        memory=AUX_MODEL_NAME,
        vision=OPENROUTER_VISION_MODEL_NAME,
    ),
    LLMProviderName.GEMINI: LLMModelProfile(
        chat=DEFAULT_GEMINI_MODEL_NAME,
        helper=DEFAULT_GEMINI_MODEL_NAME,
        judge=DEFAULT_GEMINI_MODEL_NAME,
        memory=MEMORY_MODEL_NAME,
        vision=VISION_MODEL_NAME,
    ),
    LLMProviderName.OPENAI: LLMModelProfile(
        chat=COMMS_MODEL_NAME,
        helper=None,
        judge=None,
        memory=None,
        # Takes image input (OpenRouter catalog input_modalities for openai/gpt-5.6-luna).
        vision=COMMS_MODEL_NAME,
    ),
    LLMProviderName.OLLAMA: LLMModelProfile(
        chat=OLLAMA_DEFAULT_MODEL_NAME,
        helper=None,
        judge=None,
        memory=None,
        vision=None,
    ),
    LLMProviderName.CUSTOM: LLMModelProfile(
        chat=None,
        helper=None,
        judge=None,
        memory=None,
        vision=None,
    ),
}

# The order configured providers are taken in: the default chat lane, its
# fallback, and (outside production) every one-shot role after its hosted provider.
LLM_PROVIDER_PRIORITY: tuple[LLMProviderName, ...] = (
    LLMProviderName.OPENROUTER,
    LLMProviderName.GEMINI,
    LLMProviderName.OPENAI,
    LLMProviderName.OLLAMA,
    LLMProviderName.CUSTOM,
)

# Production's one-shot routing, never walked past. Memory sits on a different
# provider from the graph so concurrent calls don't wipe each other's prompt cache.
HOSTED_ONE_SHOT_PROVIDERS: dict[ModelUse, LLMProviderName] = {
    ModelUse.HELPER: LLMProviderName.OPENROUTER,
    ModelUse.JUDGE: LLMProviderName.OPENROUTER,
    ModelUse.MEMORY: LLMProviderName.GEMINI,
    ModelUse.VISION: LLMProviderName.GEMINI,
}


def _catalog_chat_model(provider: LLMProviderName) -> str:
    """Return the chat model a setup card prefills; empty when the operator must choose one."""
    return LLM_MODEL_PROFILES[provider].chat or ""


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
        "default_model": _catalog_chat_model(LLMProviderName.OPENROUTER),
        "favicon_domain": "openrouter.ai",
        "needs_base_url": False,
    },
    "gemini": {
        "label": "Google Gemini",
        "base_url": "",
        "default_model": _catalog_chat_model(LLMProviderName.GEMINI),
        "favicon_domain": "ai.google.dev",
        "needs_base_url": False,
    },
    "ollama": {
        "label": "Ollama",
        "base_url": "http://host.docker.internal:11434",
        "default_model": _catalog_chat_model(LLMProviderName.OLLAMA),
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
        "default_model": _catalog_chat_model(LLMProviderName.OPENAI),
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
    "CREDENTIAL_PROVIDERS",
    "FAVICON_URL_TEMPLATE",
    "HOSTED_ONE_SHOT_PROVIDERS",
    "LLM_MODEL_PROFILES",
    "LLM_PROVIDER_PRIORITY",
    "PRESETS",
    "LLMModelProfile",
    "ProviderPreset",
]
