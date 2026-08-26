"""Resend adapter (https://resend.com)."""

import asyncio

import resend

from app.config.settings import settings
from app.services.email.models import EmailMessage
from app.services.providers.provider_credentials_service import (
    resolve as resolve_resend_config,
)


class ResendEmailProvider:
    """EmailProvider backed by the Resend HTTP API."""

    async def _apply_api_key(self) -> None:
        """Point the Resend SDK's global key at the active credential.

        The SDK reads a module-global ``api_key``, so it is set on every call
        from the credential store first (Settings → Resend), falling back to
        ``RESEND_API_KEY`` — the store → env policy every runtime consumer
        follows, which also means a key configured at runtime applies without
        a restart.
        """
        config = await resolve_resend_config("resend")
        api_key = config["api_key"] if config else None
        if api_key is None:
            api_key = settings.RESEND_API_KEY
        if not api_key:
            raise RuntimeError(
                "Resend is not configured: store a Resend credential in "
                "Settings or set RESEND_API_KEY to send email."
            )
        resend.api_key = api_key

    async def send(self, message: EmailMessage) -> None:
        """Deliver one message via Resend."""
        await self._apply_api_key()
        params: resend.Emails.SendParams = {
            "from": message.sender,
            "to": message.to,
            "subject": message.subject,
            "html": message.html,
        }
        if message.reply_to:
            params["reply_to"] = message.reply_to
        if message.headers:
            params["headers"] = message.headers
        # The Resend SDK is synchronous — run it in a thread to keep the event loop free.
        await asyncio.to_thread(resend.Emails.send, params)

    async def add_contact(self, user_email: str, user_name: str | None = None) -> None:
        """Add a contact to the Resend audience. No-op when RESEND_AUDIENCE_ID is unset."""
        await self._apply_api_key()
        if not settings.RESEND_AUDIENCE_ID:
            return

        first_name = ""
        last_name = ""
        if user_name:
            name_parts = user_name.strip().split()
            first_name = name_parts[0] if name_parts else ""
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        params: resend.Contacts.CreateParams = {
            "email": user_email,
            "first_name": first_name,
            "last_name": last_name,
            "unsubscribed": False,
            "audience_id": settings.RESEND_AUDIENCE_ID,
        }
        await asyncio.to_thread(resend.Contacts.create, params)
