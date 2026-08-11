from posthog import Posthog

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider


@lazy_provider(
    name="posthog",
    required_keys=[
        settings.POSTHOG_API_KEY,
    ],
    auto_initialize=False,
    is_global_context=False,
    strategy=MissingKeyStrategy.SILENT,
)
def init_posthog() -> Posthog:
    """
    Initialize and configure the PostHog client.

    Returns:
        Posthog: Configured PostHog client instance.
    """
    # The lazy provider only initializes when the key is present (required_keys
    # gate above); the fallback satisfies the type without changing behavior.
    posthog = Posthog(settings.POSTHOG_API_KEY or "", host="https://us.i.posthog.com")

    return posthog
