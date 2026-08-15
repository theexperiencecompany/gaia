"""Provider registry — resolves the adapter configured via settings.EMAIL_PROVIDER."""

from collections.abc import Callable
from functools import lru_cache

from app.config.settings import settings
from app.services.email.providers.base import EmailProvider
from app.services.email.providers.resend_provider import ResendEmailProvider

_PROVIDER_FACTORIES: dict[str, Callable[[], EmailProvider]] = {
    "resend": ResendEmailProvider,
}


@lru_cache(maxsize=1)
def get_email_provider() -> EmailProvider:
    factory = _PROVIDER_FACTORIES.get(settings.EMAIL_PROVIDER)
    if factory is None:
        available = ", ".join(sorted(_PROVIDER_FACTORIES))
        raise ValueError(
            f"Unknown EMAIL_PROVIDER '{settings.EMAIL_PROVIDER}' (available: {available})"
        )
    return factory()
