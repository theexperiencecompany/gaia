"""Runtime-configurable provider credentials (self-host credential store).

User-configured provider credentials live in Mongo as Fernet-encrypted JSON
(keyed by the instance secret — see ``secrets_store``); plaintext never touches
the database. ``resolve`` is the single read path every consumer uses:

    DB credential → env fallback → None

with a 60s in-process TTL cache in front of both, and every result mirrored
into :func:`resolved_config` for sync consumers. Writes go through
``upsert``/``delete`` which invalidate and fan out so every consumer rebuilds
against the new configuration:

- the lazy-loader registry entry for the provider is reset (LLM lanes plus
  the sync tool loaders — composio service, Cloudinary config),
- the aux-LLM caches inside ``app.agents.llm.client`` are cleared,
- a Redis publish on ``RUNTIME_CONFIG_CHANNEL`` tells other pods to do the same
  (subscribed to per pod by ``app.core.runtime_config_subscriber``, which
  applies remote updates through :func:`invalidate_locally`).
"""

import importlib
import json
import os
from time import monotonic
from typing import TypedDict

from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.providers import CREDENTIAL_PROVIDERS
from app.core.lazy_loader import providers
from app.db.redis import redis_cache
from app.db.repositories.provider_credentials import provider_credentials_repository
from app.services.runtime.secrets_store import fernet_key_from, get_instance_secret
from shared.py.wide_events import log

# Other pods subscribe to this channel to invalidate their own caches; payload:
# {"scope": "provider:<name>"}.
RUNTIME_CONFIG_CHANNEL = "gaia:runtime-config-updated"

_CACHE_TTL_SECONDS = 60.0

# Credential-store provider → lazy-loader registry key whose cached instance
# must be rebuilt when the credential changes. LLM lanes first; then the SYNC
# tool loaders (composio service factory, Cloudinary global config) that read
# the runtime snapshot instead of resolving per call — resetting them makes a
# newly saved credential take effect on the next access without a restart.
_REGISTRY_RESET_KEYS: dict[str, str] = {
    "openrouter": "openrouter_llm",
    "gemini": "gemini_llm",
    "ollama": "ollama_llm",
    "custom": "custom_llm",
    "composio": "composio_service",
    "cloudinary": "cloudinary",
}


class ProviderConfig(TypedDict):
    """A decrypted provider payload."""

    api_key: str | None
    base_url: str | None
    model: str | None
    preset: str | None  # e.g. "opencode" | "nous"


# provider → (cached-at monotonic, resolved config). Entries may hold None-ish
# configs (unconfigured) too, so misses don't re-hit Mongo on every call.
_cache: dict[str, tuple[float, ProviderConfig]] = {}

# The most recent resolve() result per provider, mirrored here so SYNC
# consumers — sync lazy loaders like the composio service factory and the
# Cloudinary config, which cannot await — can read a stored credential without
# blocking, exactly as the LLM lanes' loaders do. Populated by every resolve()
# (startup refresh, per-access, invalidation fan-out); app.agents.llm.client
# aliases this dict as its own snapshot, so there is exactly one copy of it.
resolved_configs: dict[str, ProviderConfig | None] = {}


def resolved_config(provider: str) -> ProviderConfig | None:
    """The last-known resolve() result for ``provider``, readable synchronously.

    ``None`` means "not resolved yet", NOT "unconfigured" — callers that must
    tell the two apart read :data:`resolved_configs` directly (the LLM client
    does). Sync consumers combine the result with their own env read under the
    LLM lanes' contract: store credentials win over env the moment a
    resolution has run, and never before. Async consumers should ``await
    resolve`` instead.
    """
    return resolved_configs.get(provider)


async def resolve(provider: str) -> ProviderConfig | None:
    """The provider's active config: stored credential → env fallback → None."""
    hit, cached = _cache_get(provider)
    if hit:
        return cached

    doc = await provider_credentials_repository.find_by_provider(provider)
    if doc is not None:
        config = await _decrypt_config(doc.data_encrypted)
        if config is not None:
            _cache_put(provider, config)
            resolved_configs[provider] = config
            return config
        # Undecryptable (instance secret rotated): logged loudly above; fall
        # through so env still works instead of bricking the provider.

    fallback = _env_fallback(provider)
    if fallback is not None or provider in CREDENTIAL_PROVIDERS:
        # Cache known providers' outcomes (including unconfigured), so repeated
        # resolves don't hammer Mongo; unknown names return immediately.
        _cache_put(provider, fallback)
    resolved_configs[provider] = fallback
    return fallback


async def upsert(
    provider: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    preset: str | None = None,
) -> None:
    """Store (or replace) a provider's encrypted credential and fan out invalidation."""
    _ensure_known(provider)
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
    _ensure_known(provider)
    await provider_credentials_repository.delete(provider)
    log.info(f"{LogTag.API} Provider credential removed", provider=provider)
    await invalidate(provider)
    # Warm the snapshot (env fallback) so remote invalidation via the warmed
    # resolve is reflected locally before the caller resumes.
    await resolve(provider)


def invalidate_locally(provider: str) -> None:
    """Drop every pod-local cached view of ``provider`` so consumers rebuild.

    The pod-local half of :func:`invalidate`, shared verbatim with the
    cross-pod path: the runtime-config subscriber applies REMOTE credential
    updates by calling this, so a save served by another pod rebuilds exactly
    what a local save does (service TTL cache → lazy-loader registry → aux LLM
    caches).
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

    # Imported lazily through the module: client.py sits ABOVE this service in
    # the import graph (its resolver consumes this module's symbols at module
    # level), so importing the client back at module level here would close a
    # real cycle — this function-level import is the legitimate cycle-breaker,
    # not a workaround. Contract: reset_aux_llm_caches lives on
    # app.agents.llm.client; a missing symbol fails loud here.
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


def _ensure_known(provider: str) -> None:
    """Raise on anything outside the credential-store provider set."""
    if provider not in CREDENTIAL_PROVIDERS:
        raise ValueError(
            f"Unknown provider '{provider}' — expected one of {', '.join(CREDENTIAL_PROVIDERS)}"
        )


def _cache_get(provider: str) -> tuple[bool, ProviderConfig | None]:
    """(hit?, config) for the provider's cache entry.

    A hit whose config is ``None`` is a cached *miss* (provider known but
    unconfigured) — it resolves to ``None`` without touching Mongo again.
    """
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


def _env_fallback(provider: str) -> ProviderConfig | None:
    """What the environment alone provides for ``provider``, or None."""
    if provider == "openrouter":
        if not settings.OPENROUTER_API_KEY:
            return None
        return ProviderConfig(
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL,
            model=None,
            preset=None,
        )
    if provider == "gemini":
        if not settings.GOOGLE_API_KEY:
            return None
        return ProviderConfig(
            api_key=settings.GOOGLE_API_KEY, base_url=None, model=None, preset=None
        )
    if provider == "ollama":
        # Keyless local lane. Only resolvable when the endpoint was EXPLICITLY
        # provided — settings.OLLAMA_BASE_URL carries a code default (the
        # docker-internal DNS name), and treating that default as a working
        # Ollama made bare instances route chat at an unreachable endpoint.
        explicit = os.environ.get("OLLAMA_BASE_URL")
        if not explicit:
            return None
        return ProviderConfig(api_key=None, base_url=explicit, model=None, preset=None)
    if provider == "tavily":
        if not settings.TAVILY_API_KEY:
            return None
        return ProviderConfig(
            api_key=settings.TAVILY_API_KEY, base_url=None, model=None, preset=None
        )
    if provider == "custom":
        # The dev-only OpenAI-compatible lane; all three fields ship together.
        if settings.ENV != "development":
            return None
        if not (settings.DEV_LLM_BASE_URL and settings.DEV_LLM_API_KEY and settings.DEV_LLM_MODEL):
            return None
        return ProviderConfig(
            api_key=settings.DEV_LLM_API_KEY,
            base_url=settings.DEV_LLM_BASE_URL,
            model=settings.DEV_LLM_MODEL,
            preset=None,
        )
    # Tool / integration keys below — single api_key lanes like tavily, except
    # where the service needs a multi-variable set to actually work (cloudinary,
    # google_oauth): those resolve only when EVERY variable is present, so a
    # half-set env never reports the provider as configured.
    if provider == "composio":
        if not settings.COMPOSIO_KEY:
            return None
        return ProviderConfig(api_key=settings.COMPOSIO_KEY, base_url=None, model=None, preset=None)
    if provider == "e2b":
        if not settings.E2B_API_KEY:
            return None
        return ProviderConfig(api_key=settings.E2B_API_KEY, base_url=None, model=None, preset=None)
    if provider == "openai":
        # Voice-note transcription (Whisper) key.
        if not settings.OPENAI_API_KEY:
            return None
        return ProviderConfig(
            api_key=settings.OPENAI_API_KEY, base_url=None, model=None, preset=None
        )
    if provider == "resend":
        if not settings.RESEND_API_KEY:
            return None
        return ProviderConfig(
            api_key=settings.RESEND_API_KEY, base_url=None, model=None, preset=None
        )
    if provider == "cloudinary":
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
    if provider == "google_oauth":
        # The client id/secret pair only works as a pair.
        if not (settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET):
            return None
        return ProviderConfig(
            api_key=settings.GOOGLE_CLIENT_SECRET,
            base_url=None,
            model=None,
            preset=None,
        )
    if provider == "firecrawl":
        if not settings.FIRECRAWL_API_KEY:
            return None
        return ProviderConfig(
            api_key=settings.FIRECRAWL_API_KEY, base_url=None, model=None, preset=None
        )
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
