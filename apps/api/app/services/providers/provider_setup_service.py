"""Save a provider credential the one way every admin surface does: presets, partial merges, SSRF guard.

The setup API's PUT and the CLI's first-boot save (app/scripts/save_provider.py)
both build what they store with merge_provider_credential, so gaia up accepts
exactly what the wizard and Settings accept.
"""

from app.config.settings import settings
from app.constants.providers import CREDENTIAL_PROVIDERS, PRESETS, PresetName, ProviderPreset
from app.schemas.providers import ProviderCredentialBody
from app.services.providers.provider_credentials_service import (
    ProviderConfig,
    resolve,
    upsert,
)
from app.utils.errors import AppError
from app.utils.url_safety import assert_endpoint_url_allowed, assert_endpoint_url_shape

# Providers whose outbound traffic targets a caller-configurable base_url — the
# only stored base_urls the SSRF guard applies to (openrouter/gemini dial
# canonical endpoints; the tool keys carry no endpoint).
BASE_URL_PROVIDERS = frozenset({"custom", "ollama", "searxng"})

_UNPROCESSABLE = 422
_NOT_FOUND = 404

_PRIVATE_URL_HINT = (
    "This URL looks private or unreachable — use a public endpoint or set "
    "OLLAMA_BASE_URL in your .env for local Ollama"
)


def ensure_known_provider(provider: str) -> None:
    """Refuse a provider name the credential store does not hold."""
    if provider not in CREDENTIAL_PROVIDERS:
        raise AppError(message=f"Unknown provider: {provider}", status_code=_NOT_FOUND)


def apply_preset(
    preset: PresetName | None, base_url: str | None, model: str | None
) -> tuple[str | None, str | None]:
    """Explicit values win; a preset fills whatever the caller omitted."""
    if preset is None:
        return base_url, model
    spec: ProviderPreset = PRESETS[preset]
    return base_url or (spec["base_url"] or None), model or (spec["default_model"] or None)


def allows_private_endpoint(provider: str) -> bool:
    """Whether a provider's base_url may be a private address.

    Ollama always may; where the deployment allows private-network endpoints any
    admin-configured one may too, so a LAN vLLM or LM Studio server works.
    """
    return provider == "ollama" or settings.deployment.private_network_endpoints


async def assert_endpoint_safe(base_url: str | None, *, allow_private: bool = False) -> None:
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


def _kept(given: str | None, stored: str | None) -> str | None:
    """Return the given value, else the stored one; None means "not provided", never "clear"."""
    return stored if given is None else given


async def merge_provider_credential(provider: str, body: ProviderCredentialBody) -> ProviderConfig:
    """Validate body and merge its omitted fields with the stored config: what a save stores."""
    ensure_known_provider(provider)
    if all(v is None for v in body.model_dump().values()):
        raise AppError(message="No fields to update", status_code=_UNPROCESSABLE)
    stored = await resolve(provider) or ProviderConfig()
    preset_base_url, preset_model = apply_preset(body.preset, body.base_url, body.model)
    merged_base_url = _kept(preset_base_url, stored.base_url)
    if provider in BASE_URL_PROVIDERS:
        await assert_endpoint_safe(merged_base_url, allow_private=allows_private_endpoint(provider))
    return ProviderConfig(
        api_key=_kept(body.api_key, stored.api_key),
        base_url=merged_base_url,
        model=_kept(preset_model, stored.model),
        preset=_kept(body.preset, stored.preset),
        account_id=_kept(body.account_id, stored.account_id),
        api_secret=_kept(body.api_secret, stored.api_secret),
    )


async def save_provider_credential(provider: str, body: ProviderCredentialBody) -> None:
    """Store one provider's credential, merging omitted fields with the stored config."""
    await upsert(provider, await merge_provider_credential(provider, body))
