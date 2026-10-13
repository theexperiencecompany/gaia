"""Cloudinary SDK configuration from store-first resolved credentials.

The credential store currently carries a single api_key per provider; the
cloud name and secret still come from the environment. All three are required
to configure the SDK, so a partially resolvable setup degrades loudly (WARN
strategy) instead of configuring the global client with holes.
"""

import cloudinary

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.services.providers.provider_credentials_service import (
    ProviderConfig,
    resolved_config,
)
from app.utils.errors import AppError


@lazy_provider(
    name="cloudinary",
    required_keys=[],
    auto_initialize=True,
    is_global_context=True,
    strategy=MissingKeyStrategy.WARN,
    warning_message="Cloudinary configuration is missing or incomplete. Cloudinary features will be disabled.",
)
def init_cloudinary() -> None:
    """Initialize and configure the Cloudinary service.

    The API key resolves store-first, then env; cloud name and secret are
    env-only. Raises RuntimeError unless all three resolve; the WARN strategy
    logs it and retries on next access.
    """
    config: ProviderConfig | None = resolved_config("cloudinary")
    api_key = config["api_key"] if config else None
    cloud_name = settings.CLOUDINARY_CLOUD_NAME
    api_secret = settings.CLOUDINARY_API_SECRET
    if not (cloud_name and api_key and api_secret):
        raise RuntimeError(
            "Cloudinary is not fully configured: cloud name, API key, and "
            "API secret are all required (a stored credential carries only "
            "the API key today; cloud name and secret come from env)"
        )
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
    )


def require_cloudinary() -> None:
    """Raise a 503 naming the fix when uploads have no blob store to land in."""
    if providers.get("cloudinary"):
        return
    raise AppError(
        message=(
            "File uploads are not set up on this instance. Ask the admin to add "
            "Cloudinary credentials (see the self-hosting docs)."
        ),
        why="Uploaded files are stored in Cloudinary, and no Cloudinary account is configured.",
        fix=(
            "Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET "
            "in apps/api/.env, then restart the API."
        ),
        status_code=503,
        code="file_storage_not_configured",
    )
