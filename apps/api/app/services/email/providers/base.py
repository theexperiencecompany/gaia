"""Interface every outbound email provider adapter implements."""

from typing import Protocol

from app.services.email.models import EmailMessage


class EmailProvider(Protocol):
    async def send(self, message: EmailMessage) -> None:
        """Deliver one message. Raises on failure — retry/swallow policy belongs to callers."""
        ...
