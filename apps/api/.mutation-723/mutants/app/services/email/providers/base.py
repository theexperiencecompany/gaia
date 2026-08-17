"""Interfaces email provider adapters implement."""

from typing import Protocol, runtime_checkable

from app.services.email.models import EmailMessage


class EmailProvider(Protocol):
    async def send(self, message: EmailMessage) -> None:
        """Deliver one message. Raises on failure — retry/swallow policy belongs to callers."""
        ...


@runtime_checkable
class MarketingContactsProvider(Protocol):
    """Optional capability: providers that also manage a marketing audience."""

    async def add_contact(self, user_email: str, user_name: str | None = None) -> None: ...
