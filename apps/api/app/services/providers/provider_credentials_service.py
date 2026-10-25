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
from typing import NamedTuple

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.providers import CredentialProviderName, CredentialSource
from app.core.lazy_loader import providers
from app.db.repositories.provider_credentials import provider_credentials_repository
from app.services.providers.provider_registry import PROVIDER_SPECS
from app.services.runtime.config_updates import PROVIDER_SCOPE_PREFIX, publish_config_update
from app.services.runtime.secrets_store import fernet_key_from, get_instance_secret
from shared.py.wide_events import log

_CACHE_TTL_SECONDS = 60.0


class ProviderConfig(BaseModel):
    """A decrypted provider payload; a field a stored row predates reads as None."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    preset: str | None = None  # e.g. "opencode" | "nous"
    # The non-secret account half: Cloudinary's cloud name, Google's OAuth client id.
    account_id: str | None = None
    # A second secret beside api_key: Cloudinary's API secret.
    api_secret: str | None = None


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
    cloud_name, api_key, api_secret = config.account_id, config.api_key, config.api_secret
    if not (cloud_name and api_key and api_secret):
        return None
    return CloudinaryAccount(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret)


def google_oauth_client(config: ProviderConfig | None) -> GoogleOAuthClient | None:
    """Return the OAuth client a resolved config names; None unless both halves are set."""
    if config is None:
        return None
    client_id, client_secret = config.account_id, config.api_key
    if not (client_id and client_secret):
        return None
    return GoogleOAuthClient(client_id=client_id, client_secret=client_secret)


def is_usable(provider: CredentialProviderName, config: ProviderConfig | None) -> bool:
    """Whether a resolved config can serve its consumer: every field the provider's spec requires is set."""
    if config is None:
        return False
    values = config.model_dump()
    return all(values[field] for field in PROVIDER_SPECS[provider].requires)


# Pod-local caches built from resolved configs in modules that import this one,
# so they register here instead of being imported back.
_local_invalidation_hooks: list[Callable[[], None]] = []


def on_local_invalidation(hook: Callable[[], None]) -> None:
    """Run hook on every pod-local invalidation, local save or remote update alike."""
    _local_invalidation_hooks.append(hook)


# provider → (cached-at monotonic, resolved config). Entries may hold None-ish
# configs (unconfigured) too, so misses don't re-hit Mongo on every call.
_cache: dict[CredentialProviderName, tuple[float, ProviderConfig | None]] = {}

# Latest resolve result per provider for sync consumers that cannot await;
# exactly one copy, also aliased as the LLM client snapshot.
resolved_configs: dict[CredentialProviderName, ProviderConfig | None] = {}


def resolved_config(provider: CredentialProviderName) -> ProviderConfig | None:
    """Return the provider's config synchronously: the last resolve, else the environment.

    Before any resolve has run a stored credential is not visible yet; async
    callers should await resolve when that matters.
    """
    if settings.deployment.runtime_credentials and provider in resolved_configs:
        return resolved_configs[provider]
    return env_config(provider)


async def resolve(provider: CredentialProviderName) -> ProviderConfig | None:
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
    # An unconfigured outcome is cached too, so repeated resolves don't hammer Mongo.
    _cache_put(provider, config)
    resolved_configs[provider] = config
    return config


async def inspect_credential(provider: CredentialProviderName) -> CredentialResolution:
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
    return config.api_key, config.base_url, config.account_id, config.api_secret


async def upsert(provider: CredentialProviderName, config: ProviderConfig) -> None:
    """Store (or replace) a provider's encrypted credential and fan out invalidation."""
    _ensure_writable()
    data_encrypted = await _encrypt(json.dumps(config.model_dump()))
    await provider_credentials_repository.upsert_encrypted(provider, data_encrypted)
    log.info(
        f"{LogTag.API} Provider credential updated",
        provider=provider,
        has_api_key=config.api_key is not None,
    )
    await invalidate(provider)
    # Warm the local cache so the credential is live before the HTTP 200 returns.
    # Without this, a chat arriving next tick would see the cleared snapshot and
    # fall through to env fallback (NO_PROVIDER_CONFIGURED) despite the DB row.
    await resolve(provider)


async def delete(provider: CredentialProviderName) -> None:
    """Remove a stored credential (idempotent) and fan out invalidation."""
    _ensure_writable()
    await provider_credentials_repository.delete(provider)
    log.info(f"{LogTag.API} Provider credential removed", provider=provider)
    await invalidate(provider)
    # Warm the snapshot (env fallback) so remote invalidation via the warmed
    # resolve is reflected locally before the caller resumes.
    await resolve(provider)


def invalidate_locally(provider: CredentialProviderName) -> None:
    """Drop every pod-local cached view of a provider so consumers rebuild.

    Also the remote-update path: the runtime-config subscriber calls this for
    saves served by another pod.
    """
    _cache.pop(provider, None)

    registry_key = PROVIDER_SPECS[provider].registry_key
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


async def invalidate(provider: CredentialProviderName) -> None:
    """Drop this pod's cached config and tell every consumer (and pod) to rebuild."""
    invalidate_locally(provider)
    await publish_config_update(f"{PROVIDER_SCOPE_PREFIX}{provider}")


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _ensure_writable() -> None:
    """Raise unless this deployment stores credentials."""
    if not settings.deployment.runtime_credentials:
        raise RuntimeError(
            "This deployment reads provider credentials from the environment only; "
            "the credential store is not writable here"
        )


def _cache_get(provider: CredentialProviderName) -> tuple[bool, ProviderConfig | None]:
    """Cache lookup for a provider; a None config is a cached miss that skips Mongo."""
    entry = _cache.get(provider)
    if entry is None:
        return False, None
    cached_at, config = entry
    if monotonic() - cached_at >= _CACHE_TTL_SECONDS:
        return False, None  # resolve overwrites the expired entry with a fresh one
    return True, config


def _cache_put(provider: CredentialProviderName, config: ProviderConfig | None) -> None:
    _cache[provider] = (monotonic(), config)


def env_config(provider: CredentialProviderName) -> ProviderConfig | None:
    """Return what the environment alone provides for a provider: None unless it sets every required field."""
    spec = PROVIDER_SPECS[provider]
    if spec.env_dev_only and not settings.deployment.dev_tools:
        return None
    values = {field: read() for field, read in spec.env.items()}
    if not all(values.get(field) for field in spec.requires):
        return None
    return ProviderConfig.model_validate(values)


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
    """Project a decrypted dict onto the config shape; an unknown or non-string field is dropped."""
    fields = ProviderConfig.model_fields
    return ProviderConfig.model_validate(
        {k: v for k, v in raw.items() if k in fields and isinstance(v, str)}
    )
