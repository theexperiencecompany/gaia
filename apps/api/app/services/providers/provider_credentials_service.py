"""Provider credentials: the one read path for every provider key.

Where the deployment allows runtime credentials, they live in Mongo as
Fernet-encrypted JSON keyed by the instance secret, never as plaintext; resolve
reads them with a 60 second cache: stored credential wins, then environment,
then None. Everywhere else the environment is the only source and the store is
never read. Writes invalidate locally and publish so other pods rebuild too.
"""

import importlib
import json
import os
from time import monotonic
from typing import NamedTuple, TypedDict

from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.providers import CREDENTIAL_PROVIDERS, CredentialSource
from app.core.lazy_loader import providers
from app.db.redis import redis_cache
from app.db.repositories.provider_credentials import provider_credentials_repository
from app.services.runtime.secrets_store import fernet_key_from, get_instance_secret
from shared.py.wide_events import log

# Other pods subscribe to this channel to invalidate their own caches; payload:
# {"scope": "provider:<name>"}.
RUNTIME_CONFIG_CHANNEL = "gaia:runtime-config-updated"

_CACHE_TTL_SECONDS = 60.0

# Registry key rebuilt per provider when its credential changes, so a newly
# saved credential takes effect on next access without a restart.
_REGISTRY_RESET_KEYS: dict[str, str] = {
    "openrouter": "openrouter_llm",
    "gemini": "gemini_llm",
    "ollama": "ollama_llm",
    "custom": "custom_llm",
    "openai": "openai_llm",
    "composio": "composio_service",
    "cloudinary": "cloudinary",
}


class ProviderConfig(TypedDict):
    """A decrypted provider payload."""

    api_key: str | None
    base_url: str | None
    model: str | None
    preset: str | None  # e.g. "opencode" | "nous"


class CredentialResolution(NamedTuple):
    """Which credential serves a provider and where it comes from."""

    config: ProviderConfig | None
    source: CredentialSource
    # A stored credential is active while the environment sets a different one.
    shadows_env: bool


# provider → (cached-at monotonic, resolved config). Entries may hold None-ish
# configs (unconfigured) too, so misses don't re-hit Mongo on every call.
_cache: dict[str, tuple[float, ProviderConfig]] = {}

# Latest resolve result per provider for sync consumers that cannot await;
# exactly one copy, also aliased as the LLM client snapshot.
resolved_configs: dict[str, ProviderConfig | None] = {}


def resolved_config(provider: str) -> ProviderConfig | None:
    """Return the provider's config synchronously: the last resolve, else the environment.

    Before any resolve has run a stored credential is not visible yet; async
    callers should await resolve when that matters.
    """
    if settings.deployment.runtime_credentials and provider in resolved_configs:
        return resolved_configs[provider]
    return env_config(provider)


async def resolve(provider: str) -> ProviderConfig | None:
    """Return the provider's active config: stored credential, then env, then None.

    Without runtime credentials this is the environment alone and the store is
    never touched.
    """
    if not settings.deployment.runtime_credentials:
        from_env = env_config(provider)
        resolved_configs[provider] = from_env
        return from_env

    hit, cached = _cache_get(provider)
    if hit:
        return cached

    config = (await inspect_credential(provider)).config
    if config is not None or provider in CREDENTIAL_PROVIDERS:
        # Cache known providers' outcomes (including unconfigured), so repeated
        # resolves don't hammer Mongo; unknown names return immediately.
        _cache_put(provider, config)
    resolved_configs[provider] = config
    return config


async def inspect_credential(provider: str) -> CredentialResolution:
    """Read, uncached, which credential serves the provider; warn when a stored one hides env.

    An undecryptable stored row (instance secret rotated) is logged where it is
    decrypted and falls through, so env still serves instead of bricking the provider.
    """
    from_env = env_config(provider)
    if settings.deployment.runtime_credentials:
        doc = await provider_credentials_repository.find_by_provider(provider)
        stored = await _decrypt_config(doc.data_encrypted) if doc is not None else None
        if stored is not None:
            shadows_env = from_env is not None and _credential_of(from_env) != _credential_of(
                stored
            )
            if shadows_env:
                log.warning(
                    f"{LogTag.API} A stored provider credential overrides a different env value",
                    provider=provider,
                    fix="delete the stored credential in Settings to use the env value, "
                    "or remove the env value",
                )
            return CredentialResolution(stored, CredentialSource.STORED, shadows_env)
    source = CredentialSource.UNSET if from_env is None else CredentialSource.ENV
    return CredentialResolution(from_env, source, shadows_env=False)


def _credential_of(config: ProviderConfig) -> tuple[str | None, str | None]:
    """Return the part of a config that names an account: its key and endpoint."""
    return config["api_key"], config["base_url"]


async def upsert(
    provider: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    preset: str | None = None,
) -> None:
    """Store (or replace) a provider's encrypted credential and fan out invalidation."""
    _ensure_writable(provider)
    payload = json.dumps(
        ProviderConfig(api_key=api_key, base_url=base_url, model=model, preset=preset)
    )
    data_encrypted = await _encrypt(payload)
    await provider_credentials_repository.upsert_encrypted(provider, data_encrypted)
    log.info(
        f"{LogTag.API} Provider credential updated",
        provider=provider,
        has_api_key=api_key is not None,
    )
    await invalidate(provider)
    # Warm the local cache so the credential is live before the HTTP 200 returns.
    # Without this, a chat arriving next tick would see the cleared snapshot and
    # fall through to env fallback (NO_PROVIDER_CONFIGURED) despite the DB row.
    await resolve(provider)


async def delete(provider: str) -> None:
    """Remove a stored credential (idempotent) and fan out invalidation."""
    _ensure_writable(provider)
    await provider_credentials_repository.delete(provider)
    log.info(f"{LogTag.API} Provider credential removed", provider=provider)
    await invalidate(provider)
    # Warm the snapshot (env fallback) so remote invalidation via the warmed
    # resolve is reflected locally before the caller resumes.
    await resolve(provider)


def invalidate_locally(provider: str) -> None:
    """Drop every pod-local cached view of a provider so consumers rebuild.

    Also the remote-update path: the runtime-config subscriber calls this for
    saves served by another pod.
    """
    _cache.pop(provider, None)

    registry_key = _REGISTRY_RESET_KEYS.get(provider)
    if registry_key is not None:
        try:
            providers.reset(registry_key)
        except KeyError:
            # The registry may not have registered this key yet (e.g. the
            # custom lane only registers under development) — nothing to reset.
            log.debug(
                f"{LogTag.API} Provider not registered, skipping reset",
                name=registry_key,
            )

    # Function-level import breaks a real cycle: the client module consumes
    # this module at import time, so a top-level import would close the loop.
    client_module = importlib.import_module("app.agents.llm.client")
    client_module.reset_aux_llm_caches()


async def invalidate(provider: str) -> None:
    """Drop this pod's cached config and tell every consumer (and pod) to rebuild."""
    invalidate_locally(provider)

    client = redis_cache.redis
    if client is not None:
        try:
            await client.publish(
                RUNTIME_CONFIG_CHANNEL, json.dumps({"scope": f"provider:{provider}"})
            )
        except Exception as e:
            # Deliberate degradation, loud: cross-pod refresh is missed but the
            # 60s TTL bounds staleness and local state is already consistent.
            log.error(
                f"{LogTag.API} Failed to publish runtime-config update",
                channel=RUNTIME_CONFIG_CHANNEL,
                provider=provider,
                error=str(e),
                error_type=type(e).__name__,
            )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _ensure_writable(provider: str) -> None:
    """Raise unless this deployment stores credentials and provider is one of the store's."""
    if not settings.deployment.runtime_credentials:
        raise RuntimeError(
            "This deployment reads provider credentials from the environment only; "
            "the credential store is not writable here"
        )
    if provider not in CREDENTIAL_PROVIDERS:
        raise ValueError(
            f"Unknown provider '{provider}' — expected one of {', '.join(CREDENTIAL_PROVIDERS)}"
        )


def _cache_get(provider: str) -> tuple[bool, ProviderConfig | None]:
    """Cache lookup for a provider; a None config is a cached miss that skips Mongo."""
    entry = _cache.get(provider)
    if entry is None:
        return False, None
    cached_at, config = entry
    if monotonic() - cached_at >= _CACHE_TTL_SECONDS:
        _cache.pop(provider, None)
        return False, None
    return True, config


def _cache_put(provider: str, config: ProviderConfig | None) -> None:
    _cache[provider] = (monotonic(), config)


def _openrouter_env() -> ProviderConfig | None:
    if not settings.OPENROUTER_API_KEY:
        return None
    return ProviderConfig(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
        model=None,
        preset=None,
    )


def _ollama_env() -> ProviderConfig | None:
    # Only when the endpoint was explicitly provided; the settings default
    # is a docker-internal name that is unreachable from bare instances.
    explicit = os.environ.get("OLLAMA_BASE_URL")
    if not explicit:
        return None
    return ProviderConfig(api_key=None, base_url=explicit, model=None, preset=None)


def _custom_env() -> ProviderConfig | None:
    # The dev-only OpenAI-compatible lane; all three fields ship together.
    if not settings.deployment.dev_tools:
        return None
    if not (settings.DEV_LLM_BASE_URL and settings.DEV_LLM_API_KEY and settings.DEV_LLM_MODEL):
        return None
    return ProviderConfig(
        api_key=settings.DEV_LLM_API_KEY,
        base_url=settings.DEV_LLM_BASE_URL,
        model=settings.DEV_LLM_MODEL,
        preset=None,
    )


def _cloudinary_env() -> ProviderConfig | None:
    # Uploads need all three: cloud name + key + secret ship together.
    if not (
        settings.CLOUDINARY_CLOUD_NAME
        and settings.CLOUDINARY_API_KEY
        and settings.CLOUDINARY_API_SECRET
    ):
        return None
    return ProviderConfig(
        api_key=settings.CLOUDINARY_API_KEY, base_url=None, model=None, preset=None
    )


def _google_oauth_env() -> ProviderConfig | None:
    # The client id/secret pair only works as a pair.
    if not (settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET):
        return None
    return ProviderConfig(
        api_key=settings.GOOGLE_CLIENT_SECRET,
        base_url=None,
        model=None,
        preset=None,
    )


# Providers whose env fallback is a single api-key setting each.
_SIMPLE_ENV_KEYS = {
    "gemini": "GOOGLE_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "composio": "COMPOSIO_KEY",
    "e2b": "E2B_API_KEY",
    "openai": "OPENAI_API_KEY",
    "resend": "RESEND_API_KEY",
    "firecrawl": "FIRECRAWL_API_KEY",
}

# Providers with bespoke rules above, by name.
_BESPOKE_ENV_RESOLVERS = {
    "openrouter": _openrouter_env,
    "ollama": _ollama_env,
    "custom": _custom_env,
    "cloudinary": _cloudinary_env,
    "google_oauth": _google_oauth_env,
}


def env_config(provider: str) -> ProviderConfig | None:
    """Return what the environment alone provides for a provider, or None."""
    if resolve := _BESPOKE_ENV_RESOLVERS.get(provider):
        return resolve()
    # Tool keys resolve on a single api key.
    if key_name := _SIMPLE_ENV_KEYS.get(provider):
        api_key = getattr(settings, key_name, None)
        if not api_key:
            return None
        return ProviderConfig(api_key=api_key, base_url=None, model=None, preset=None)
    return None


async def _encrypt(payload_json: str) -> str:
    secret = await get_instance_secret()
    return Fernet(fernet_key_from(secret)).encrypt(payload_json.encode()).decode()


async def _decrypt_config(data_encrypted: str) -> ProviderConfig | None:
    """Decrypt a stored ciphertext into a config, or None when undecryptable.

    An InvalidToken means the instance secret changed since the row was written;
    that is recoverable by re-entering credentials, so it degrades with a loud
    error rather than raising out of every consumer's hot path.
    """
    secret = await get_instance_secret()
    try:
        plaintext = Fernet(fernet_key_from(secret)).decrypt(data_encrypted.encode())
    except InvalidToken as e:
        log.error(
            f"{LogTag.API} Stored provider credential cannot be decrypted",
            reason=f"instance secret mismatch ({e!r})",
            fix="re-enter the provider credentials; the old ciphertext is unreadable",
        )
        return None
    parsed: object = json.loads(plaintext)
    if not isinstance(parsed, dict):
        raise ValueError("decrypted provider credential payload is not a JSON object")
    return _coerce_config(parsed)


def _coerce_config(raw: dict[str, object]) -> ProviderConfig:
    """Project a decrypted dict onto the four-field config shape."""

    def opt_str(key: str) -> str | None:
        value = raw.get(key)
        return value if isinstance(value, str) else None

    return ProviderConfig(
        api_key=opt_str("api_key"),
        base_url=opt_str("base_url"),
        model=opt_str("model"),
        preset=opt_str("preset"),
    )
