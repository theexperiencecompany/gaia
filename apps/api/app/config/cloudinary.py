"""Cloudinary SDK configuration from store-first resolved credentials.

The credential store currently carries a single ``api_key`` per provider; the
cloud name and secret have no stored representation yet and still come from
the environment. All three are required to configure the SDK, so a partially
resolvable setup degrades loudly (WARN strategy) instead of configuring the
global client with holes.
"""

import cloudinary

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider
from app.services.providers.provider_credentials_service import resolved_config


@lazy_provider(
    name="cloudinary",
    required_keys=[],
    auto_initialize=True,
    is_global_context=True,
    strategy=MissingKeyStrategy.WARN,
    warning_message="Cloudinary configuration is missing or incomplete. Cloudinary features will be disabled.",
)
def init_cloudinary() -> None:
    """
    Initialize and configure the Cloudinary service.

    The API key resolves through the credential store first (Settings →
    Cloudinary), falling back to the environment. Sync loader on purpose:
    this is a global-context provider initialized during startup warmup, and
    the sync read uses the credential service's runtime snapshot — populated
    by resolve() at startup and on every invalidation — exactly like the LLM
    lanes' loaders.

    Raises:
        RuntimeError: When cloud name, API key, or secret cannot be resolved.
            The WARN strategy logs it and leaves Cloudinary features disabled;
            the next access re-runs this, so credentials configured later
            pick up without a restart.
    """
    config = resolved_config("cloudinary")
    api_key = config["api_key"] if config else None
    if api_key is None:
        api_key = settings.CLOUDINARY_API_KEY
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
