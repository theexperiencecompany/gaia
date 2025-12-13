from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider
from posthog import Posthog


@lazy_provider(
    name="posthog",
    required_keys=[
        settings.POSTHOG_API_KEY,
    ],
    auto_initialize=False,
    is_global_context=False,
    strategy=MissingKeyStrategy.SILENT,
)
def init_posthog():
    """
    Initialize and configure the PostHog client.

    Returns:
        Posthog: Configured PostHog client instance.
    """
    posthog = Posthog(settings.POSTHOG_API_KEY, host="https://us.i.posthog.com")

    return posthog
