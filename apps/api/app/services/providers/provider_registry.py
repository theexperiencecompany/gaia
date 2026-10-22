"""One spec per credential-store provider: every fact about it the API and the web read.

A provider's card copy and the fields it takes (the preset), where the
environment configures it, which fields make a config usable, and the
lazy-provider registry entry a saved credential rebuilds. Adding a provider is
one CredentialProviderName member and one entry here.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from app.config.settings import settings
from app.constants.integrations import COMPOSIO_SERVICE_PROVIDER
from app.constants.llm import LLMProviderKey, LLMProviderName
from app.constants.providers import (
    CLOUDINARY_PROVIDER,
    LLM_MODEL_PROFILES,
    CredentialProviderName,
    ManagedAt,
    ProviderPreset,
    favicon_url,
)

ConfigField = Literal["api_key", "base_url", "model", "account_id", "api_secret"]
EnvReader = Callable[[], str | None]

_INTEGRATIONS_SETUP = ManagedAt(
    href="/settings/integrations-setup", label="Open Integrations setup"
)


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """One provider: its card, its environment fallback, and what makes a config of it usable.

    requires is both rules at once: a config serves its consumer only with every
    one of those fields set, and the environment configures the provider only
    when it sets all of them.
    """

    preset: ProviderPreset
    env: Mapping[ConfigField, EnvReader]
    requires: frozenset[ConfigField]
    registry_key: str | None = None  # the lazy provider a credential change rebuilds
    env_dev_only: bool = False  # the environment configures it only where dev tools run


def _api_key_spec(preset: ProviderPreset, read_key: EnvReader) -> ProviderSpec:
    """Return the spec of a tool configured by one API key."""
    return ProviderSpec(preset=preset, env={"api_key": read_key}, requires=frozenset({"api_key"}))


PROVIDER_SPECS: dict[CredentialProviderName, ProviderSpec] = {
    CredentialProviderName.OPENROUTER: ProviderSpec(
        preset=ProviderPreset(
            label="OpenRouter",
            description="One key for every major model. Easiest way to start.",
            key_url="https://openrouter.ai/keys",
            default_model=LLM_MODEL_PROFILES[LLMProviderName.OPENROUTER].chat,
            favicon_url=favicon_url("openrouter.ai"),
            takes_model=True,
        ),
        env={
            "api_key": lambda: settings.OPENROUTER_API_KEY,
            "base_url": lambda: settings.OPENROUTER_BASE_URL,
        },
        requires=frozenset({"api_key"}),
        registry_key=LLMProviderKey.OPENROUTER,
    ),
    CredentialProviderName.GEMINI: ProviderSpec(
        preset=ProviderPreset(
            label="Google Gemini",
            description="Google's models, with a generous free tier.",
            key_url="https://aistudio.google.com/apikey",
            default_model=LLM_MODEL_PROFILES[LLMProviderName.GEMINI].chat,
            favicon_url=favicon_url("ai.google.dev"),
            takes_model=True,
        ),
        env={"api_key": lambda: settings.GOOGLE_API_KEY},
        requires=frozenset({"api_key"}),
        registry_key=LLMProviderKey.GEMINI,
    ),
    CredentialProviderName.OLLAMA: ProviderSpec(
        preset=ProviderPreset(
            label="Ollama",
            description="Run models locally — no API key needed.",
            base_url="http://host.docker.internal:11434",
            default_model=LLM_MODEL_PROFILES[LLMProviderName.OLLAMA].chat,
            favicon_url=favicon_url("ollama.com"),
            needs_base_url=True,
            takes_model=True,
        ),
        env={"base_url": lambda: settings.OLLAMA_BASE_URL},
        requires=frozenset({"base_url"}),
        registry_key=LLMProviderKey.OLLAMA,
    ),
    # The custom OpenAI-compatible lane: its card offers CUSTOM_PRESETS as chips and
    # keeps the base-URL field editable for a manual gateway. The catalog has no
    # model for it, so a config without one cannot serve.
    CredentialProviderName.CUSTOM: ProviderSpec(
        preset=ProviderPreset(
            label="Custom",
            description="Use any service with an OpenAI-style API — like OpenCode or Nous — or enter your own server address.",
            favicon_url=favicon_url("opencode.ai"),
            needs_base_url=True,
            takes_model=True,
        ),
        env={
            "api_key": lambda: settings.DEV_LLM_API_KEY,
            "base_url": lambda: settings.DEV_LLM_BASE_URL,
            "model": lambda: settings.DEV_LLM_MODEL,
        },
        requires=frozenset({"api_key", "base_url", "model"}),
        registry_key=LLMProviderKey.CUSTOM,
        env_dev_only=True,
    ),
    # Search tool keys (SearXNG: an endpoint); no live probe, since the setup test
    # endpoint rejects every non-chat provider.
    CredentialProviderName.TAVILY: _api_key_spec(
        ProviderPreset(
            label="Tavily",
            description="Web search results grounded in live sources.",
            key_url="https://app.tavily.com",
            favicon_url=favicon_url("tavily.com"),
        ),
        lambda: settings.TAVILY_API_KEY,
    ),
    CredentialProviderName.EXA: _api_key_spec(
        ProviderPreset(
            label="Exa",
            description="Search that understands what you mean, not just the words.",
            key_url="https://dashboard.exa.ai/api-keys",
            favicon_url=favicon_url("exa.ai"),
        ),
        lambda: settings.EXA_API_KEY,
    ),
    CredentialProviderName.BRAVE: _api_key_spec(
        ProviderPreset(
            label="Brave Search",
            description="Brave's own independent web index.",
            key_url="https://api-dashboard.search.brave.com/app/keys",
            favicon_url=favicon_url("search.brave.com"),
        ),
        lambda: settings.BRAVE_API_KEY,
    ),
    CredentialProviderName.SEARXNG: ProviderSpec(
        preset=ProviderPreset(
            label="SearXNG",
            description="Your own private search server. Paste its address; no key needed.",
            favicon_url=favicon_url("searx.space"),  # searxng.org serves no favicon
            needs_base_url=True,
            takes_key=False,
        ),
        env={"base_url": lambda: settings.SEARXNG_BASE_URL},
        requires=frozenset({"base_url"}),
    ),
    CredentialProviderName.COMPOSIO: ProviderSpec(
        preset=ProviderPreset(
            label="Composio",
            description="Integration platform for Gmail, Calendar, Slack, and 200+ tools.",
            key_url="https://app.composio.dev",
            favicon_url=favicon_url("composio.dev"),
            managed_at=_INTEGRATIONS_SETUP,
        ),
        env={"api_key": lambda: settings.COMPOSIO_KEY},
        requires=frozenset({"api_key"}),
        registry_key=COMPOSIO_SERVICE_PROVIDER,
    ),
    CredentialProviderName.E2B: _api_key_spec(
        ProviderPreset(
            label="E2B Sandbox",
            description="Code execution sandbox for the agent's bash/code tools.",
            favicon_url=favicon_url("e2b.dev"),
        ),
        lambda: settings.E2B_API_KEY,
    ),
    CredentialProviderName.OPENAI: ProviderSpec(
        preset=ProviderPreset(
            label="OpenAI",
            description="GPT models directly from OpenAI. Also powers voice-note transcription.",
            key_url="https://platform.openai.com/api-keys",
            default_model=LLM_MODEL_PROFILES[LLMProviderName.OPENAI].chat,
            favicon_url=favicon_url("openai.com"),
            takes_model=True,
        ),
        env={"api_key": lambda: settings.OPENAI_API_KEY},
        requires=frozenset({"api_key"}),
        registry_key=LLMProviderKey.OPENAI,
    ),
    CredentialProviderName.RESEND: _api_key_spec(
        ProviderPreset(
            label="Resend Email",
            description="Outbound email for notifications and reminders.",
            key_url="https://resend.com/api-keys",
            favicon_url=favicon_url("resend.com"),
        ),
        lambda: settings.RESEND_API_KEY,
    ),
    CredentialProviderName.CLOUDINARY: ProviderSpec(
        preset=ProviderPreset(
            label="Cloudinary",
            description="Image upload and storage. Paste the cloud name, API key and API secret from your Cloudinary console.",
            key_url="https://console.cloudinary.com/settings/api-keys",
            favicon_url=favicon_url("cloudinary.com"),
            account_id_label="Cloud name",
            second_key_label="API secret",
        ),
        env={
            "account_id": lambda: settings.CLOUDINARY_CLOUD_NAME,
            "api_key": lambda: settings.CLOUDINARY_API_KEY,
            "api_secret": lambda: settings.CLOUDINARY_API_SECRET,
        },
        requires=frozenset({"account_id", "api_key", "api_secret"}),
        registry_key=CLOUDINARY_PROVIDER,
    ),
    # The secret travels as api_key, the client id as account_id; only the pair works.
    CredentialProviderName.GOOGLE_OAUTH: ProviderSpec(
        preset=ProviderPreset(
            label="Google OAuth",
            description="Google account integration (Gmail, Calendar). Paste the OAuth client ID and client secret from Google Cloud Console.",
            key_url="https://console.cloud.google.com/apis/credentials",
            favicon_url=favicon_url("accounts.google.com"),
            api_key_label="Client secret",
            account_id_label="Client ID",
        ),
        env={
            "account_id": lambda: settings.GOOGLE_CLIENT_ID,
            "api_key": lambda: settings.GOOGLE_CLIENT_SECRET,
        },
        requires=frozenset({"account_id", "api_key"}),
    ),
    CredentialProviderName.FIRECRAWL: _api_key_spec(
        ProviderPreset(
            label="Firecrawl",
            description="Advanced web scraping and crawling.",
            key_url="https://www.firecrawl.dev/app/api-keys",
            favicon_url=favicon_url("firecrawl.dev"),
        ),
        lambda: settings.FIRECRAWL_API_KEY,
    ),
    CredentialProviderName.OPENWEATHER: _api_key_spec(
        ProviderPreset(
            label="OpenWeather",
            description="Current weather and forecasts for any place.",
            key_url="https://home.openweathermap.org/api_keys",
            favicon_url=favicon_url("openweathermap.org"),
        ),
        lambda: settings.OPENWEATHER_API_KEY,
    ),
    CredentialProviderName.LLAMAPARSE: _api_key_spec(
        ProviderPreset(
            label="LlamaParse",
            description="Reads scanned PDFs and images of documents (OCR).",
            key_url="https://cloud.llamaindex.ai/api-key",
            favicon_url=favicon_url("llamaindex.ai"),
        ),
        lambda: settings.LLAMA_INDEX_KEY,
    ),
    CredentialProviderName.GITHUB: _api_key_spec(
        ProviderPreset(
            label="GitHub",
            description="A personal access token lifts GitHub's limit of 60 skill lookups an hour.",
            key_url="https://github.com/settings/tokens",
            favicon_url=favicon_url("github.com"),
        ),
        lambda: settings.GITHUB_TOKEN,
    ),
}
