"""Save a provider credential the one way every admin surface does: presets, partial merges, SSRF guard.

The setup API's PUT and the CLI's first-boot save (app/scripts/save_provider.py)
both write through save_provider_credential, so gaia up accepts exactly what
the wizard and Settings accept.
"""

from typing import Literal

from app.config.settings import settings
from app.constants.providers import CREDENTIAL_PROVIDERS, PRESETS, ProviderPreset
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

PresetName = Literal["opencode", "nous"]

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


_ConfigField = Literal["api_key", "base_url", "model", "preset", "account_id", "api_secret"]


def _kept(given: str | None, stored: ProviderConfig | None, field: _ConfigField) -> str | None:
    """Return the given value, else the stored one; None means "not provided", never "clear"."""
    if given is not None or stored is None:
        return given
    return stored[field]


async def save_provider_credential(
    provider: str,
    *,
    preset: PresetName | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    account_id: str | None = None,
    api_secret: str | None = None,
) -> None:
    """Store one provider's credential, merging omitted fields with the stored config."""
    ensure_known_provider(provider)
    if all(v is None for v in (preset, api_key, base_url, model, account_id, api_secret)):
        raise AppError(message="No fields to update", status_code=_UNPROCESSABLE)
    stored = await resolve(provider)
    preset_base_url, preset_model = apply_preset(preset, base_url, model)
    merged_base_url = _kept(preset_base_url, stored, "base_url")
    if provider in BASE_URL_PROVIDERS:
        await assert_endpoint_safe(merged_base_url, allow_private=allows_private_endpoint(provider))
    await upsert(
        provider,
        api_key=_kept(api_key, stored, "api_key"),
        base_url=merged_base_url,
        model=_kept(preset_model, stored, "model"),
        preset=_kept(preset, stored, "preset"),
        account_id=_kept(account_id, stored, "account_id"),
        api_secret=_kept(api_secret, stored, "api_secret"),
    )
