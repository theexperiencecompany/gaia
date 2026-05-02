"""WhatsApp notification channel adapter via Kapso.

Sends notifications to the user's linked WhatsApp phone number using the
Kapso Meta proxy API. No SDK needed — plain aiohttp POST.

The platform_user_id stored in platform_links.whatsapp is the wa_id
(phone number without leading '+'), e.g. "15551234567".
"""

from typing import Any, Dict

import aiohttp
from app.config.settings import settings
from app.constants.notifications import (
    CHANNEL_TYPE_WHATSAPP,
    KAPSO_API_BASE_URL,
)
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
)
from app.utils.notification.channels.base import SendFn
from app.utils.notification.channels.external import ExternalPlatformAdapter
from app.utils.platform_markdown import convert_to_whatsapp_markdown


class WhatsAppChannelAdapter(ExternalPlatformAdapter):
    """Delivers notifications to the user's linked WhatsApp account via Kapso."""

    MAX_MESSAGE_LENGTH = 4096  # WhatsApp's text message limit

    @property
    def channel_type(self) -> str:
        return CHANNEL_TYPE_WHATSAPP

    @property
    def platform_name(self) -> str:
        return CHANNEL_TYPE_WHATSAPP

    @property
    def bold_marker(self) -> str:
        # WhatsApp uses *bold* (single asterisk)
        return "*"

    async def transform(self, notification: NotificationRequest) -> Dict[str, Any]:
        """Build the notification payload and convert any CommonMark Markdown in
        the body/messages to WhatsApp's native formatting so ``**bold**`` and
        ``### headings`` don't render as literal characters in the chat bubble.

        Order matters: we convert here (in ``transform``) rather than inside
        ``_deliver_content``. The base class's splitter
        (``_split_text`` → ``MAX_MESSAGE_LENGTH``) runs on the transformed
        text during delivery, so chunk boundaries reflect the final WhatsApp
        payload and link expansion (``[x](url)`` → ``x (url)``) won't push a
        boundary past 4096 characters unexpectedly.
        """
        payload = await super().transform(notification)
        if payload.get("type") == "workflow_messages":
            if header := payload.get("header"):
                payload["header"] = convert_to_whatsapp_markdown(header)
            payload["messages"] = [
                convert_to_whatsapp_markdown(m) for m in payload.get("messages", [])
            ]
            if footer := payload.get("footer"):
                payload["footer"] = convert_to_whatsapp_markdown(footer)
            return payload
        if text := payload.get("text"):
            payload["text"] = convert_to_whatsapp_markdown(text)
        return payload

    def _get_bot_token(self) -> str | None:
        # For WhatsApp via Kapso, authentication is the API key, not a bot token.
        # We return the API key so _get_platform_context's token-check passes.
        return settings.KAPSO_API_KEY

    def _session_kwargs(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "headers": {
                "X-API-Key": ctx["token"],  # KAPSO_API_KEY
                "Content-Type": "application/json",
            }
        }

    async def _setup_sender(
        self,
        session: aiohttp.ClientSession,
        ctx: Dict[str, Any],
    ) -> tuple[SendFn | None, ChannelDeliveryStatus | None]:
        """Return send function that POSTs to Kapso's Meta WhatsApp proxy."""
        phone_number_id = settings.KAPSO_PHONE_NUMBER_ID
        if not phone_number_id:
            return None, self._skipped("KAPSO_PHONE_NUMBER_ID not configured")

        wa_id = ctx["platform_user_id"]
        url = f"{KAPSO_API_BASE_URL}/meta/whatsapp/v24.0/{phone_number_id}/messages"

        async def send_text(text: str) -> str | None:
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": f"+{wa_id}",
                "type": "text",
                "text": {"body": text, "preview_url": False},
            }
            async with session.post(url, json=payload) as resp:
                if resp.status not in (200, 201):
                    return await resp.text()
            return None

        return send_text, None
