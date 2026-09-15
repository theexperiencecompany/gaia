from posthog import Posthog

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider

#: The lazy-provider registry key of the shared PostHog client.
POSTHOG_PROVIDER_KEY = "posthog"


@lazy_provider(
    name=POSTHOG_PROVIDER_KEY,
    required_keys=[
        settings.POSTHOG_PROJECT_TOKEN,
        settings.POSTHOG_HOST,
    ],
    auto_initialize=False,
    is_global_context=False,
    strategy=MissingKeyStrategy.SILENT,
)
def init_posthog() -> Posthog:
    """Initialize the shared PostHog client from environment-backed settings."""
    return Posthog(
        settings.POSTHOG_PROJECT_TOKEN,
        host=settings.POSTHOG_HOST,
        enable_exception_autocapture=True,
    )
