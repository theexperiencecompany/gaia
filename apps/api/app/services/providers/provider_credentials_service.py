"""Provider credentials: the one read path for every provider key.

Where the deployment allows runtime credentials, they live in Mongo as
Fernet-encrypted JSON keyed by the instance secret, never as plaintext; resolve
reads them with a 60 second cache: stored credential wins, then environment,
then None. Everywhere else the environment is the only source and the store is
never read. Writes invalidate locally and publish so other pods rebuild too.
"""

from collections.abc import Callable
import json
from time import monotonic
from typing import NamedTuple, TypedDict

from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.providers import CREDENTIAL_PROVIDERS, CredentialSource
from app.core.lazy_loader import providers
from app.db.repositories.provider_credentials import provider_credentials_repository
from app.services.runtime.config_updates import PROVIDER_SCOPE_PREFIX, publish_config_update
from app.services.runtime.secrets_store import fernet_key_from, get_instance_secret
from shared.py.wide_events import log

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
    # The non-secret account half: Cloudinary's cloud name, Google's OAuth client id.
    account_id: str | None
    # A second secret beside api_key: Cloudinary's API secret.
    api_secret: str | None


class CredentialResolution(NamedTuple):
    """Which credential serves a provider and where it comes from."""

    config: ProviderConfig | None
    source: CredentialSource
    # A stored credential is active while the environment sets a different one.
    shadows_env: bool


class CloudinaryAccount(NamedTuple):
    """Everything the Cloudinary SDK needs."""

    cloud_name: str
    api_key: str
    api_secret: str


class GoogleOAuthClient(NamedTuple):
    """The OAuth client pair; the secret travels as api_key, the client id as account_id."""

    client_id: str
    client_secret: str


def cloudinary_account(config: ProviderConfig | None) -> CloudinaryAccount | None:
    """Return the Cloudinary account a resolved config names; None unless all three fields are set."""
    if config is None:
        return None
    cloud_name, api_key, api_secret = config["account_id"], config["api_key"], config["api_secret"]
    if not (cloud_name and api_key and api_secret):
        return None
    return CloudinaryAccount(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret)


def google_oauth_client(config: ProviderConfig | None) -> GoogleOAuthClient | None:
    """Return the OAuth client a resolved config names; None unless both halves are set."""
    if config is None:
        return None
    client_id, client_secret = config["account_id"], config["api_key"]
    if not (client_id and client_secret):
        return None
    return GoogleOAuthClient(client_id=client_id, client_secret=client_secret)


# Providers whose consumer needs more than one field of the config to work.
_COMPLETIONS: dict[str, Callable[[ProviderConfig | None], object | None]] = {
    "cloudinary": cloudinary_account,
    "google_oauth": google_oauth_client,
}


def is_usable(provider: str, config: ProviderConfig | None) -> bool:
    """Whether a resolved config can serve its consumer, multi-field accounts included."""
    if config is None:
        return False
    complete = _COMPLETIONS.get(provider)
    return complete is None or complete(config) is not None


# Pod-local caches built from resolved configs in modules that import this one,
# so they register here instead of being imported back.
_local_invalidation_hooks: list[Callable[[], None]] = []


def on_local_invalidation(hook: Callable[[], None]) -> None:
    """Run hook on every pod-local invalidation, local save or remote update alike."""
    _local_invalidation_hooks.append(hook)


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


def _credential_of(config: ProviderConfig) -> tuple[str | None, ...]:
    """Return the part of a config that names an account: its keys, endpoint and account id."""
    return config["api_key"], config["base_url"], config["account_id"], config["api_secret"]


async def upsert(
    provider: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    preset: str | None = None,
    account_id: str | None = None,
    api_secret: str | None = None,
) -> None:
    """Store (or replace) a provider's encrypted credential and fan out invalidation."""
    _ensure_writable(provider)
    payload = json.dumps(
        ProviderConfig(
            api_key=api_key,
            base_url=base_url,
            model=model,
            preset=preset,
            account_id=account_id,
            api_secret=api_secret,
        )
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

    for hook in _local_invalidation_hooks:
        hook()


async def invalidate(provider: str) -> None:
    """Drop this pod's cached config and tell every consumer (and pod) to rebuild."""
    invalidate_locally(provider)
    await publish_config_update(f"{PROVIDER_SCOPE_PREFIX}{provider}")


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
        return False, None  # resolve overwrites the expired entry with a fresh one
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
        account_id=None,
        api_secret=None,
    )


def _ollama_env() -> ProviderConfig | None:
    if not settings.OLLAMA_BASE_URL:
        return None
    return ProviderConfig(
        api_key=None,
        base_url=settings.OLLAMA_BASE_URL,
        model=None,
        preset=None,
        account_id=None,
        api_secret=None,
    )


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
        account_id=None,
        api_secret=None,
    )


def _searxng_env() -> ProviderConfig | None:
    if not settings.SEARXNG_BASE_URL:
        return None
    return ProviderConfig(
        api_key=None,
        base_url=settings.SEARXNG_BASE_URL,
        model=None,
        preset=None,
        account_id=None,
        api_secret=None,
    )


def _cloudinary_env() -> ProviderConfig | None:
    # Uploads need all three: cloud name + key + secret ship together.
    if not (
        settings.CLOUDINARY_CLOUD_NAME
        and settings.CLOUDINARY_API_KEY
        and settings.CLOUDINARY_API_SECRET
    ):
        return None
    return _key_config(
        settings.CLOUDINARY_API_KEY,
        account_id=settings.CLOUDINARY_CLOUD_NAME,
        api_secret=settings.CLOUDINARY_API_SECRET,
    )


def _google_oauth_env() -> ProviderConfig | None:
    # The client id/secret pair only works as a pair.
    if not (settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET):
        return None
    return _key_config(settings.GOOGLE_CLIENT_SECRET, account_id=settings.GOOGLE_CLIENT_ID)


def _key_config(
    api_key: str | None, *, account_id: str | None = None, api_secret: str | None = None
) -> ProviderConfig:
    return ProviderConfig(
        api_key=api_key,
        base_url=None,
        model=None,
        preset=None,
        account_id=account_id,
        api_secret=api_secret,
    )


# Providers whose env fallback is a single api-key setting each.
_SIMPLE_ENV_KEYS = {
    "gemini": "GOOGLE_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "exa": "EXA_API_KEY",
    "brave": "BRAVE_API_KEY",
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
    "searxng": _searxng_env,
    "cloudinary": _cloudinary_env,
    "google_oauth": _google_oauth_env,
}


def env_config(provider: str) -> ProviderConfig | None:
    """Return what the environment alone provides for a provider, or None."""
    if resolve := _BESPOKE_ENV_RESOLVERS.get(provider):
        return resolve()
    # Tool keys resolve on a single api key.
    if key_name := _SIMPLE_ENV_KEYS.get(provider):
        api_key = getattr(settings, key_name)
        if not api_key:
            return None
        return _key_config(api_key)
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
    """Project a decrypted dict onto the config shape; a field the row predates reads as None."""

    def opt_str(key: str) -> str | None:
        value = raw.get(key)
        return value if isinstance(value, str) else None

    return ProviderConfig(
        api_key=opt_str("api_key"),
        base_url=opt_str("base_url"),
        model=opt_str("model"),
        preset=opt_str("preset"),
        account_id=opt_str("account_id"),
        api_secret=opt_str("api_secret"),
    )
