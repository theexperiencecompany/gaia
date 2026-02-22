from typing import Any, Dict

import aiohttp

from app.config.settings import settings
from app.constants.notifications import DISCORD_API_BASE
from app.models.notification.notification_models import ChannelDeliveryStatus
from app.utils.notification.channels.base import SendFn
from app.utils.notification.channels.external import ExternalPlatformAdapter


class DiscordChannelAdapter(ExternalPlatformAdapter):
    """Delivers notifications to a user's linked Discord account via DM."""

    DISCORD_API = DISCORD_API_BASE
    MAX_MESSAGE_LENGTH = 2000

    @property
    def channel_type(self) -> str:
        return "discord"

    @property
    def platform_name(self) -> str:
        return "discord"

    @property
    def bold_marker(self) -> str:
        return "**"

    def _get_bot_token(self) -> str | None:
        return settings.DISCORD_BOT_TOKEN

    def _session_kwargs(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "headers": {
                "Authorization": f"Bot {ctx['token']}",
                "Content-Type": "application/json",
            }
        }

    async def _setup_sender(
        self, session: aiohttp.ClientSession, ctx: Dict[str, Any]
    ) -> tuple[SendFn | None, ChannelDeliveryStatus | None]:
        # Open DM channel
        async with session.post(
            f"{self.DISCORD_API}/users/@me/channels",
            json={"recipient_id": ctx["platform_user_id"]},
        ) as resp:
            if resp.status not in (200, 201):
                err = await resp.text()
                return None, self._error(
                    f"Discord DM channel error {resp.status}: {err}"
                )
            data = await resp.json()
            dm_channel_id = data.get("id")
            if not dm_channel_id:
                return None, self._error("Discord DM channel id missing from response")

        dm_url = f"{self.DISCORD_API}/channels/{dm_channel_id}/messages"

        async def send(text: str) -> str | None:
            async with session.post(dm_url, json={"content": text}) as r:
                if r.status not in (200, 201):
                    return await r.text()
            return None

        return send, None
