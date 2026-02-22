import html
from typing import Any, Dict

import aiohttp

from app.config.settings import settings
from app.constants.notifications import TELEGRAM_BOT_API_BASE
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
)
from app.utils.notification.channels.base import SendFn
from app.utils.notification.channels.external import ExternalPlatformAdapter


class TelegramChannelAdapter(ExternalPlatformAdapter):
    """Delivers notifications to a user's linked Telegram account."""

    MAX_MESSAGE_LENGTH = 4096

    @property
    def channel_type(self) -> str:
        return "telegram"

    @property
    def platform_name(self) -> str:
        return "telegram"

    @property
    def bold_marker(self) -> str:
        # Not used — transform() is overridden to produce HTML tags directly.
        return ""

    def _get_bot_token(self) -> str | None:
        return settings.TELEGRAM_BOT_TOKEN

    def _session_kwargs(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    @staticmethod
    def _escape(text: str) -> str:
        """Escape user-generated text for Telegram HTML parse mode.

        Telegram HTML only requires &, <, > to be escaped.
        Switching from legacy Markdown avoids failures caused by unescaped
        *, _, `, or [ characters in user-generated / workflow content.
        """
        return html.escape(text, quote=False)

    async def transform(self, notification: NotificationRequest) -> Dict[str, Any]:
        """Produce HTML-formatted content for Telegram."""
        content = notification.content
        rich = content.rich_content or {}

        if rich.get("type") == "workflow_execution":
            title = self._escape(content.title or "")
            body = self._escape(content.body or "")
            header = f"✅ <b>{title}</b>\n⏰ {body}" if title else body
            messages = [self._escape(m) for m in rich.get("messages", [])]
            conversation_id = rich.get("conversation_id", "")
            app_url = settings.FRONTEND_URL
            footer = (
                f'🔗 <a href="{app_url}/c/{conversation_id}">View full results</a>'
                if conversation_id
                else ""
            )
            return {
                "type": "workflow_messages",
                "header": header,
                "messages": messages,
                "footer": footer,
            }

        title = self._escape(content.title or "")
        body = self._escape(content.body or "")
        text = f"<b>{title}</b>\n{body}" if title else body
        return {"text": text}

    async def _setup_sender(
        self, session: aiohttp.ClientSession, ctx: Dict[str, Any]
    ) -> tuple[SendFn | None, ChannelDeliveryStatus | None]:
        url = f"{TELEGRAM_BOT_API_BASE}{ctx['token']}/sendMessage"
        chat_id = ctx["platform_user_id"]

        async def send(text: str) -> str | None:
            payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    return await resp.text()
            return None

        return send, None
