"""Provider catalog shared by the credentials service, LLM client, setup API, and web UI.

Single source of truth for user-configurable providers: display metadata,
preset endpoints (so configuring OpenCode or Nous means pasting only an API
key), the model each LLM provider runs per role, and the order lanes try them.
Brand icons resolve client-side from the favicon service via favicon_domain.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict

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
# The credential names of those providers: a working chat lane, and what the live probe can test.
LLM_PROVIDER_KEYS: tuple[str, ...] = tuple(p.value for p in LLM_PROVIDER_PRIORITY)

# Production runs these on comms' own lane only, selected by name and on the
# catalog model: never a default lane, a fallback, or a stored model choice.
HOSTED_COMMS_ONLY_PROVIDERS: frozenset[LLMProviderName] = frozenset({LLMProviderName.OPENAI})

# Production's one-shot routing, never walked past. Memory sits on a different
# provider from the graph so concurrent calls don't wipe each other's prompt cache.
HOSTED_ONE_SHOT_PROVIDERS: dict[ModelUse, LLMProviderName] = {
    ModelUse.HELPER: LLMProviderName.OPENROUTER,
    ModelUse.JUDGE: LLMProviderName.OPENROUTER,
    ModelUse.MEMORY: LLMProviderName.GEMINI,
    ModelUse.VISION: LLMProviderName.GEMINI,
}


# The chat model a setup card prefills; empty when the operator must choose one.
_CATALOG_CHAT_MODELS: dict[LLMProviderName, str] = {
    provider: profile.chat or "" for provider, profile in LLM_MODEL_PROFILES.items()
}


class CredentialSource(StrEnum):
    """Where a provider's active credential comes from: a saved one wins over env."""

    STORED = "stored"
    ENV = "env"
    UNSET = "unset"


class ProviderPreset(TypedDict):
    label: str
    description: str  # empty ⇒ offered only as a chip inside the custom card
    key_url: str  # empty ⇒ no page issues a key for it
    base_url: str  # empty ⇒ provider has no configurable endpoint
    default_model: str  # empty ⇒ fetched from the endpoint at configure time
    favicon_domain: str
    needs_base_url: bool  # UI shows the base-URL field (Ollama/custom)
    api_key_label: str  # what the card calls api_key, e.g. Google's client secret
    account_id_label: str  # empty ⇒ no account field (Cloudinary cloud name, Google client id)
    second_key_label: (
        str  # empty ⇒ no second key field (Cloudinary API secret, stored as api_secret)
    )


PresetName = Literal["opencode", "nous"]

PRESETS: dict[str, ProviderPreset] = {
    "openrouter": {
        "label": "OpenRouter",
        "description": "One key for every major model. Easiest way to start.",
        "key_url": "https://openrouter.ai/keys",
        "base_url": "",
        "default_model": _CATALOG_CHAT_MODELS[LLMProviderName.OPENROUTER],
        "favicon_domain": "openrouter.ai",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    "gemini": {
        "label": "Google Gemini",
        "description": "Google's models, with a generous free tier.",
        "key_url": "https://aistudio.google.com/apikey",
        "base_url": "",
        "default_model": _CATALOG_CHAT_MODELS[LLMProviderName.GEMINI],
        "favicon_domain": "ai.google.dev",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    "ollama": {
        "label": "Ollama",
        "description": "Run models locally — no API key needed.",
        "key_url": "",
        "base_url": "http://host.docker.internal:11434",
        "default_model": _CATALOG_CHAT_MODELS[LLMProviderName.OLLAMA],
        "favicon_domain": "ollama.com",
        "needs_base_url": True,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    # Custom OpenAI-compatible lane. Presets below prefill base URL + model so
    # configuration is paste-a-key-only; the base-URL field stays editable for
    # manual gateways.
    "custom": {
        "label": "Custom",
        "description": "Use any service with an OpenAI-style API — like OpenCode or Nous — or enter your own server address.",
        "key_url": "",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "opencode.ai",
        "needs_base_url": True,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    "opencode": {
        "label": "OpenCode",
        "description": "",
        "key_url": "",
        "base_url": "https://opencode.ai/zen/go/v1",
        "default_model": "deepseek-v4-flash",
        "favicon_domain": "opencode.ai",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    "nous": {
        "label": "Nous Research",
        "description": "",
        "key_url": "",
        "base_url": "https://inference-api.nousresearch.com/v1",
        "default_model": "",
        "favicon_domain": "nousresearch.com",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    # Search tool keys (SearXNG: an endpoint) — no LLM endpoint and no live
    # probe (the setup test endpoint rejects every non-chat provider).
    "tavily": {
        "label": "Tavily",
        "description": "Web search results grounded in live sources.",
        "key_url": "https://app.tavily.com",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "tavily.com",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    "exa": {
        "label": "Exa",
        "description": "Search that understands what you mean, not just the words.",
        "key_url": "https://dashboard.exa.ai/api-keys",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "exa.ai",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    "brave": {
        "label": "Brave Search",
        "description": "Brave's own independent web index.",
        "key_url": "https://api-dashboard.search.brave.com/app/keys",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "search.brave.com",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    "searxng": {
        "label": "SearXNG",
        "description": "Your own private search server. Paste its address; no key needed.",
        "key_url": "",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "searxng.org",
        "needs_base_url": True,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    # Tool / integration keys — no LLM endpoint, single-credential cards.
    "composio": {
        "label": "Composio",
        "description": "Integration platform for Gmail, Calendar, Slack, and 200+ tools.",
        "key_url": "https://app.composio.dev",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "composio.dev",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    "e2b": {
        "label": "E2B Sandbox",
        "description": "Code execution sandbox for the agent's bash/code tools.",
        "key_url": "",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "e2b.dev",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    "openai": {
        "label": "OpenAI",
        "description": "GPT models directly from OpenAI. Also powers voice-note transcription.",
        "key_url": "https://platform.openai.com/api-keys",
        "base_url": "",
        "default_model": _CATALOG_CHAT_MODELS[LLMProviderName.OPENAI],
        "favicon_domain": "openai.com",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    "resend": {
        "label": "Resend Email",
        "description": "Outbound email for notifications and reminders.",
        "key_url": "https://resend.com/api-keys",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "resend.com",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    "cloudinary": {
        "label": "Cloudinary",
        "description": "Image upload and storage. Paste the cloud name, API key and API secret from your Cloudinary console.",
        "key_url": "https://console.cloudinary.com/settings/api-keys",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "cloudinary.com",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "Cloud name",
        "second_key_label": "API secret",
    },
    "google_oauth": {
        "label": "Google OAuth",
        "description": "Google account integration (Gmail, Calendar). Paste the OAuth client ID and client secret from Google Cloud Console.",
        "key_url": "https://console.cloud.google.com/apis/credentials",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "accounts.google.com",
        "needs_base_url": False,
        "api_key_label": "Client secret",
        "account_id_label": "Client ID",
        "second_key_label": "",
    },
    "firecrawl": {
        "label": "Firecrawl",
        "description": "Advanced web scraping and crawling.",
        "key_url": "https://www.firecrawl.dev/app/api-keys",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "firecrawl.dev",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    "openweather": {
        "label": "OpenWeather",
        "description": "Current weather and forecasts for any place.",
        "key_url": "https://home.openweathermap.org/api_keys",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "openweathermap.org",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    "llamaparse": {
        "label": "LlamaParse",
        "description": "Reads scanned PDFs and images of documents (OCR).",
        "key_url": "https://cloud.llamaindex.ai/api-key",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "llamaindex.ai",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
    "github": {
        "label": "GitHub",
        "description": "A personal access token lifts GitHub's limit of 60 skill lookups an hour.",
        "key_url": "https://github.com/settings/tokens",
        "base_url": "",
        "default_model": "",
        "favicon_domain": "github.com",
        "needs_base_url": False,
        "api_key_label": "API key",
        "account_id_label": "",
        "second_key_label": "",
    },
}


# Credential-store providers. "custom" covers OpenCode/Nous/any OpenAI-compatible
# gateway (its UI card exposes the preset chips); the rest are tool keys, not LLMs.
class CredentialProviderName(StrEnum):
    """A provider the credential store can hold, in display order."""

    OPENROUTER = "openrouter"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    CUSTOM = "custom"
    TAVILY = "tavily"
    EXA = "exa"
    BRAVE = "brave"
    SEARXNG = "searxng"
    COMPOSIO = "composio"
    E2B = "e2b"
    OPENAI = "openai"
    RESEND = "resend"
    CLOUDINARY = "cloudinary"
    GOOGLE_OAUTH = "google_oauth"
    FIRECRAWL = "firecrawl"
    OPENWEATHER = "openweather"
    LLAMAPARSE = "llamaparse"
    GITHUB = "github"


CREDENTIAL_PROVIDERS: tuple[str, ...] = tuple(p.value for p in CredentialProviderName)


class ProviderFeature(StrEnum):
    """What a provider is for, as Settings and the setup wizard group them."""

    AI_MODELS = "ai_models"
    WEB_SEARCH = "web_search"
    PAGE_READING = "page_reading"
    CODE_RUNNING = "code_running"
    FILE_STORAGE = "file_storage"
    EMAIL = "email"
    INTEGRATIONS = "integrations"
    WEATHER = "weather"
    SCANNED_DOCUMENTS = "scanned_documents"
    SKILL_INSTALLS = "skill_installs"
    BROWSER = "browser"
    VOICE = "voice"


class BuiltInEngine(StrEnum):
    """An engine a feature runs on with no credential at all."""

    DUCKDUCKGO = "duckduckgo"
    PAGE_READER = "page_reader"
    LOCAL_SANDBOX = "local_sandbox"
    LOCAL_DISK = "local_disk"
    LOCAL_PARSER = "local_parser"
    PUBLIC_GITHUB = "public_github"
    # Run by the deployment's own operator, not configured by a key in Settings.
    HOSTED_BROWSER = "hosted_browser"
    HOSTED_VOICE = "hosted_voice"


class BuiltInOption(BaseModel):
    """What a feature runs on with no key, as the UI names it."""

    model_config = ConfigDict(frozen=True)

    engine: BuiltInEngine
    label: str
    description: str


class SelfHostGap(BaseModel):
    """Why a feature cannot run on a self-hosted instance, and where the docs explain it."""

    model_config = ConfigDict(frozen=True)

    reason: str
    docs_url: str


class FeatureSpec(BaseModel):
    """One feature: what it does, its keyless engine if any, and the providers that upgrade it."""

    model_config = ConfigDict(frozen=True)

    label: str
    description: str
    built_in: BuiltInOption | None  # None ⇒ the feature is off until a provider is added
    providers: tuple[CredentialProviderName, ...]  # the optional upgrades, in display order
    self_host_gap: SelfHostGap | None = None  # set ⇒ unavailable on self-host, whatever is saved


_SELF_HOST_VS_CLOUD_DOCS = "https://docs.heygaia.io/self-hosting/docker-setup#self-host-vs-cloud"

VOICE_SELF_HOST_GAP = SelfHostGap(
    reason="Voice needs a LiveKit server and GAIA's voice worker, which the self-host install does not include.",
    docs_url=_SELF_HOST_VS_CLOUD_DOCS,
)

PROVIDER_FEATURES: dict[ProviderFeature, FeatureSpec] = {
    ProviderFeature.AI_MODELS: FeatureSpec(
        label="AI models",
        description="The models GAIA chats and reasons with. It needs at least one.",
        built_in=None,
        providers=tuple(CredentialProviderName(p.value) for p in LLM_PROVIDER_PRIORITY),
    ),
    ProviderFeature.WEB_SEARCH: FeatureSpec(
        label="Web search",
        description="Looks things up on the web while answering.",
        built_in=BuiltInOption(
            engine=BuiltInEngine.DUCKDUCKGO,
            label="DuckDuckGo",
            description="Free, no key needed.",
        ),
        providers=(
            CredentialProviderName.TAVILY,
            CredentialProviderName.EXA,
            CredentialProviderName.BRAVE,
            CredentialProviderName.SEARXNG,
        ),
    ),
    ProviderFeature.PAGE_READING: FeatureSpec(
        label="Reading web pages",
        description="Opens a link and reads the page.",
        built_in=BuiltInOption(
            engine=BuiltInEngine.PAGE_READER,
            label="Built-in reader",
            description="A headless browser on this server, no key needed.",
        ),
        providers=(CredentialProviderName.FIRECRAWL,),
    ),
    ProviderFeature.CODE_RUNNING: FeatureSpec(
        label="Running code",
        description="Lets GAIA write and run code in a sandbox.",
        built_in=BuiltInOption(
            engine=BuiltInEngine.LOCAL_SANDBOX,
            label="Local sandbox",
            description="Runs code in Docker on this server, when LOCAL_CODE_SANDBOX is on.",
        ),
        providers=(CredentialProviderName.E2B,),
    ),
    ProviderFeature.FILE_STORAGE: FeatureSpec(
        label="File storage",
        description="Where uploaded and generated files are kept.",
        built_in=BuiltInOption(
            engine=BuiltInEngine.LOCAL_DISK,
            label="This server's disk",
            description="Files stay on your own machine.",
        ),
        providers=(CredentialProviderName.CLOUDINARY,),
    ),
    ProviderFeature.EMAIL: FeatureSpec(
        label="Email",
        description="Sends notifications and reminders by email.",
        built_in=None,
        providers=(CredentialProviderName.RESEND,),
    ),
    ProviderFeature.INTEGRATIONS: FeatureSpec(
        label="Integrations",
        description="Connects your accounts, like Gmail, Calendar and Slack.",
        built_in=None,
        providers=(
            CredentialProviderName.COMPOSIO,
            CredentialProviderName.GOOGLE_OAUTH,
        ),
    ),
    ProviderFeature.WEATHER: FeatureSpec(
        label="Weather",
        description="Checks the weather and forecast for a place.",
        built_in=None,
        providers=(CredentialProviderName.OPENWEATHER,),
    ),
    ProviderFeature.SCANNED_DOCUMENTS: FeatureSpec(
        label="Scanned documents",
        description="Reads PDFs that are scanned pages or photos of text.",
        built_in=BuiltInOption(
            engine=BuiltInEngine.LOCAL_PARSER,
            label="Built-in parser",
            description="Reads text PDFs and Office files on this server; scanned pages need OCR.",
        ),
        providers=(CredentialProviderName.LLAMAPARSE,),
    ),
    ProviderFeature.SKILL_INSTALLS: FeatureSpec(
        label="Skill installs",
        description="Finds and installs skills published on GitHub.",
        built_in=BuiltInOption(
            engine=BuiltInEngine.PUBLIC_GITHUB,
            label="Public GitHub",
            description="No key needed, limited to 60 lookups an hour.",
        ),
        providers=(CredentialProviderName.GITHUB,),
    ),
    ProviderFeature.BROWSER: FeatureSpec(
        label="Browser automation",
        description="Lets GAIA open and use websites in a real browser.",
        built_in=BuiltInOption(
            engine=BuiltInEngine.HOSTED_BROWSER,
            label="GAIA's browser service",
            description="Runs on GAIA's own browser hosts.",
        ),
        providers=(),
        self_host_gap=SelfHostGap(
            reason="Browser automation needs GAIA's browser host service, which the self-host install does not include.",
            docs_url=_SELF_HOST_VS_CLOUD_DOCS,
        ),
    ),
    ProviderFeature.VOICE: FeatureSpec(
        label="Voice",
        description="Talk to GAIA out loud and hear it answer.",
        built_in=BuiltInOption(
            engine=BuiltInEngine.HOSTED_VOICE,
            label="GAIA's voice service",
            description="LiveKit, speech-to-text and text-to-speech run by GAIA.",
        ),
        providers=(),
        self_host_gap=VOICE_SELF_HOST_GAP,
    ),
}

FAVICON_URL_TEMPLATE = "https://www.google.com/s2/favicons?domain={domain}&sz=128"

__all__ = [
    "CREDENTIAL_PROVIDERS",
    "BuiltInEngine",
    "BuiltInOption",
    "CredentialProviderName",
    "FAVICON_URL_TEMPLATE",
    "FeatureSpec",
    "HOSTED_COMMS_ONLY_PROVIDERS",
    "HOSTED_ONE_SHOT_PROVIDERS",
    "LLM_MODEL_PROFILES",
    "LLM_PROVIDER_PRIORITY",
    "PRESETS",
    "PresetName",
    "PROVIDER_FEATURES",
    "LLMModelProfile",
    "ProviderFeature",
    "ProviderPreset",
    "SelfHostGap",
    "VOICE_SELF_HOST_GAP",
]
