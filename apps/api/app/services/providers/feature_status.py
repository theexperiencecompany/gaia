"""Which engines each provider feature runs on right now, read off the runtime's own chains.

Every feature asks the code that serves it (the chat lanes, the search and
page-fetch waterfalls, the sandbox and blob-store selectors) rather than
re-deriving their order here, so Settings can never disagree with the runtime.
"""

from pydantic import BaseModel, Field

from app.agents.llm.client import chat_routes, refresh_provider_configs
from app.config.settings import settings
from app.constants.providers import (
    PROVIDER_FEATURES,
    BuiltInEngine,
    CredentialProviderName,
    FeatureSpec,
    ProviderFeature,
)
from app.services.blob_store import LocalVolumeBlobStore, blob_store
from app.services.providers.provider_credentials_service import is_usable, resolved_config
from app.services.sandbox.errors import CodeExecutionDisabledError
from app.services.sandbox.lifecycle import use_local_sandbox
from app.utils.search.providers import default_providers
from app.utils.webpage_fetch import default_fetchers

FeatureEngine = CredentialProviderName | BuiltInEngine


class FeatureStatus(BaseModel):
    """Whether one feature works and what it runs on."""

    available: bool = Field(
        description="Whether this deployment can run the feature at all; "
        "false means its catalog self_host_gap explains why"
    )
    working: bool = Field(description="Whether the feature works right now")
    in_use: list[FeatureEngine] = Field(
        description="What the feature runs on, in the order it tries them; the first serves"
    )


async def feature_statuses() -> dict[ProviderFeature, FeatureStatus]:
    """Report every feature's status from a freshly resolved credential snapshot."""
    await refresh_provider_configs()
    chains: dict[ProviderFeature, list[str]] = {
        ProviderFeature.AI_MODELS: [name.value for name, _ in chat_routes()],
        ProviderFeature.WEB_SEARCH: [p.name for p in default_providers() if p.is_configured()],
        ProviderFeature.PAGE_READING: [
            f.name for f in await default_fetchers() if f.is_configured()
        ],
        ProviderFeature.CODE_RUNNING: await _code_runners(),
        ProviderFeature.FILE_STORAGE: _file_stores(),
        ProviderFeature.EMAIL: _usable_providers(ProviderFeature.EMAIL),
        ProviderFeature.INTEGRATIONS: _usable_providers(ProviderFeature.INTEGRATIONS),
        ProviderFeature.WEATHER: _usable_providers(ProviderFeature.WEATHER),
        ProviderFeature.SCANNED_DOCUMENTS: [
            *_usable_providers(ProviderFeature.SCANNED_DOCUMENTS),
            BuiltInEngine.LOCAL_PARSER,
        ],
        ProviderFeature.SKILL_INSTALLS: [
            *_usable_providers(ProviderFeature.SKILL_INSTALLS),
            BuiltInEngine.PUBLIC_GITHUB,
        ],
        ProviderFeature.BROWSER: _hosted_browser(),
        ProviderFeature.VOICE: _hosted_voice(),
    }
    return {
        feature: _status(PROVIDER_FEATURES[feature], chain, available=_available(feature))
        for feature, chain in chains.items()
    }


def _available(feature: ProviderFeature) -> bool:
    """Whether the deployment ships what the feature runs on; only features with a self-host gap may not."""
    match feature:
        case ProviderFeature.BROWSER:
            return settings.deployment.browser_automation
        case ProviderFeature.VOICE:
            return settings.deployment.voice
        case _:
            return True


def _hosted_browser() -> list[str]:
    usable = is_usable("openrouter", resolved_config("openrouter"))
    return [BuiltInEngine.HOSTED_BROWSER] if usable else []


def _hosted_voice() -> list[str]:
    configured = settings.LIVEKIT_URL and settings.LIVEKIT_API_KEY and settings.LIVEKIT_API_SECRET
    return [BuiltInEngine.HOSTED_VOICE] if configured else []


async def _code_runners() -> list[str]:
    try:
        if await use_local_sandbox():
            return [BuiltInEngine.LOCAL_SANDBOX]
    except CodeExecutionDisabledError:
        return []
    return _usable_providers(ProviderFeature.CODE_RUNNING)


def _file_stores() -> list[str]:
    if isinstance(blob_store(), LocalVolumeBlobStore):
        return [BuiltInEngine.LOCAL_DISK]
    return _usable_providers(ProviderFeature.FILE_STORAGE)


def _usable_providers(feature: ProviderFeature) -> list[str]:
    """Return the feature's providers whose resolved credential can serve it."""
    return [
        provider
        for provider in PROVIDER_FEATURES[feature].providers
        if is_usable(provider, resolved_config(provider))
    ]


def _status(spec: FeatureSpec, chain: list[str], *, available: bool) -> FeatureStatus:
    """Name each engine in the chain as the catalog does, keeping the first of any repeats."""
    if not available:
        return FeatureStatus(available=False, working=False, in_use=[])
    in_use: list[FeatureEngine] = []
    for engine in (_catalog_engine(spec, name) for name in chain):
        if engine not in in_use:
            in_use.append(engine)
    return FeatureStatus(available=True, working=bool(in_use), in_use=in_use)


def _catalog_engine(spec: FeatureSpec, engine: str) -> FeatureEngine:
    """Map a runtime engine name to its credential provider, or a keyless one to the built-in."""
    if engine in spec.providers:
        return CredentialProviderName(engine)
    if spec.built_in is None:
        raise ValueError(f"{spec.label} has no built-in engine, yet '{engine}' needs no key")
    return spec.built_in.engine
