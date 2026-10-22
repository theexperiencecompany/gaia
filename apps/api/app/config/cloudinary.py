"""Cloudinary SDK configuration from store-first resolved credentials.

The cloud name, API key and API secret resolve together, from the Settings card
where runtime credentials exist, else the environment. All three are required to
configure the SDK, so a partial setup degrades loudly (WARN strategy) instead of
configuring the global client with holes.
"""

import cloudinary

from app.config.settings import settings
from app.constants.providers import CLOUDINARY_PROVIDER, CredentialProviderName
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.services.providers.provider_credentials_service import (
    cloudinary_account,
    resolved_config,
)
from app.utils.errors import AppError
from app.utils.exceptions import ProviderNotConfiguredError

_ENV_FIX = (
    "Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET "
    "in apps/api/.env, then restart the API."
)
_CARD_FIX = (
    "Add the cloud name, API key and API secret in Settings → Providers & Tools → Cloudinary."
)


@lazy_provider(
    name=CLOUDINARY_PROVIDER,
    required_keys=[],
    auto_initialize=True,
    is_global_context=True,
    strategy=MissingKeyStrategy.WARN,
    warning_message="Cloudinary configuration is missing or incomplete. Cloudinary features will be disabled.",
)
def init_cloudinary() -> None:
    """Initialize and configure the Cloudinary service.

    Raises ProviderNotConfiguredError unless all three resolve; the WARN
    strategy warns once and retries on next access.
    """
    account = cloudinary_account(resolved_config(CredentialProviderName.CLOUDINARY))
    if account is None:
        raise ProviderNotConfiguredError(
            "Cloudinary is not fully configured: cloud name, API key, and "
            "API secret are all required"
        )
    cloudinary.config(
        cloud_name=account.cloud_name,
        api_key=account.api_key,
        api_secret=account.api_secret,
    )


def require_cloudinary() -> None:
    """Raise a 503 naming the fix when uploads have no blob store to land in."""
    if providers.get(CLOUDINARY_PROVIDER):
        return
    raise AppError(
        message=(
            "File uploads are not set up on this instance. Ask the admin to add "
            "Cloudinary credentials."
        ),
        why="Uploaded files are stored in Cloudinary, and no Cloudinary account is configured.",
        fix=_CARD_FIX if settings.deployment.runtime_credentials else _ENV_FIX,
        status_code=503,
        code="file_storage_not_configured",
    )
