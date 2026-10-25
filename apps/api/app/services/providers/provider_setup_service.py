"""Save a provider credential the one way every admin surface does: presets, partial merges, SSRF guard.

The setup API's PUT and the CLI's first-boot save (app/scripts/save_provider.py)
both build what they store with merge_provider_credential, so gaia up accepts
exactly what the wizard and Settings accept.
"""

from app.config.settings import settings
from app.constants.providers import CUSTOM_PRESETS, CredentialProviderName, PresetName
from app.schemas.providers import ProviderCredentialBody
from app.services.providers.provider_credentials_service import (
    ProviderConfig,
    resolve,
    upsert,
)
from app.services.providers.provider_registry import PROVIDER_SPECS
from app.utils.errors import AppError
from app.utils.url_safety import assert_endpoint_url_allowed, assert_endpoint_url_shape

_UNPROCESSABLE = 422

_PRIVATE_URL_HINT = (
    "This URL looks private or unreachable — use a public endpoint or set "
    "OLLAMA_BASE_URL in your .env for local Ollama"
)


def apply_preset(
    preset: PresetName | None, base_url: str | None, model: str | None
) -> tuple[str | None, str | None]:
    """Explicit values win; a gateway preset fills whatever the caller omitted."""
    if preset is None:
        return base_url, model
    return CUSTOM_PRESETS[preset].fill(base_url, model)


def allows_private_endpoint(provider: CredentialProviderName) -> bool:
    """Whether a provider's base_url may be a private address.

    Ollama always may; where the deployment allows private-network endpoints any
    admin-configured one may too, so a LAN vLLM or LM Studio server works.
    """
    return (
        provider == CredentialProviderName.OLLAMA or settings.deployment.private_network_endpoints
    )


async def _assert_endpoint_safe(base_url: str | None, *, allow_private: bool) -> None:
    """Refuse, as a 422, a base_url GAIA must not send requests to (SSRF), at save and at probe time.

    app.utils.url_safety owns the policy; this maps its refusal to the error an admin reads.
    """
    if not base_url:
        return
    try:
        # Literal-IP and shape refusals fail fast, before any DNS lookup.
        assert_endpoint_url_shape(base_url, allow_private=allow_private)
        await assert_endpoint_url_allowed(base_url, allow_private=allow_private)
    except ValueError as e:
        raise AppError(message=f"{_PRIVATE_URL_HINT} ({e})", status_code=_UNPROCESSABLE) from e


async def assert_provider_endpoint_safe(
    provider: CredentialProviderName, base_url: str | None
) -> None:
    """Refuse a base_url the provider would dial, at save and at probe time; the rest dial canonical endpoints."""
    if PROVIDER_SPECS[provider].preset.needs_base_url:
        await _assert_endpoint_safe(base_url, allow_private=allows_private_endpoint(provider))


def _kept(given: str | None, stored: str | None) -> str | None:
    """Return the given value, else the stored one; None means "not provided", never "clear"."""
    return stored if given is None else given


async def merge_provider_credential(
    provider: CredentialProviderName, body: ProviderCredentialBody
) -> ProviderConfig:
    """Validate body and merge its omitted fields with the stored config: what a save stores."""
    if all(v is None for v in body.model_dump().values()):
        raise AppError(message="No fields to update", status_code=_UNPROCESSABLE)
    stored = await resolve(provider) or ProviderConfig()
    preset_base_url, preset_model = apply_preset(body.preset, body.base_url, body.model)
    merged_base_url = _kept(preset_base_url, stored.base_url)
    await assert_provider_endpoint_safe(provider, merged_base_url)
    return ProviderConfig(
        api_key=_kept(body.api_key, stored.api_key),
        base_url=merged_base_url,
        model=_kept(preset_model, stored.model),
        preset=_kept(body.preset, stored.preset),
        account_id=_kept(body.account_id, stored.account_id),
        api_secret=_kept(body.api_secret, stored.api_secret),
    )


async def save_provider_credential(
    provider: CredentialProviderName, body: ProviderCredentialBody
) -> None:
    """Store one provider's credential, merging omitted fields with the stored config."""
    await upsert(provider, await merge_provider_credential(provider, body))
