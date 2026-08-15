"""Resend adapter (https://resend.com)."""

import asyncio

import resend

from app.config.settings import settings
from app.services.email.models import EmailMessage


class ResendEmailProvider:
    """EmailProvider backed by the Resend HTTP API."""

    def __init__(self) -> None:
        resend.api_key = settings.RESEND_API_KEY

    async def send(self, message: EmailMessage) -> None:
        """Deliver one message via Resend."""
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
