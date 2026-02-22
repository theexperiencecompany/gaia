from typing import Any, Dict

import aiohttp

from app.config.settings import settings
from app.constants.notifications import TELEGRAM_BOT_API_BASE
from app.models.notification.notification_models import ChannelDeliveryStatus
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
        return "*"

    def _get_bot_token(self) -> str | None:
        return settings.TELEGRAM_BOT_TOKEN

    def _session_kwargs(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    async def _setup_sender(
        self, session: aiohttp.ClientSession, ctx: Dict[str, Any]
    ) -> tuple[SendFn | None, ChannelDeliveryStatus | None]:
        url = f"{TELEGRAM_BOT_API_BASE}{ctx['token']}/sendMessage"
        chat_id = ctx["platform_user_id"]

        async def send(text: str) -> str | None:
            payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    return await resp.text()
            return None

        return send, None
