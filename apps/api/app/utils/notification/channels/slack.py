"""Slack notification channel adapter.

Delivers messages to a user's linked Slack account via DM, using the
workspace bot token (``SLACK_BOT_TOKEN``) and Slack's Web API. The bot opens
a DM channel with the user (``conversations.open``) and posts to it
(``chat.postMessage``).

The platform_user_id stored in platform_links.slack is the Slack user id
(e.g. "U0123456789"). Markdown is converted to Slack's mrkdwn at send time.

Slack's Web API returns HTTP 200 even on logical failures, signalling the
real outcome via the ``ok`` field — so every response is parsed and checked.
"""

from typing import Any

import aiohttp

from app.config.settings import settings
from app.constants.notifications import CHANNEL_TYPE_SLACK, SLACK_API_BASE
from app.models.notification.notification_models import ChannelDeliveryStatus
from app.utils.notification.channels.base import SendFn
from app.utils.notification.channels.external import ExternalPlatformAdapter
from app.utils.platform_markdown import convert_to_slack_mrkdwn


class SlackChannelAdapter(ExternalPlatformAdapter):
    """Delivers notifications to a user's linked Slack account via DM."""

    MAX_MESSAGE_LENGTH = 3000  # Slack renders cleanly well below its 40k hard limit

    @property
    def channel_type(self) -> str:
        return CHANNEL_TYPE_SLACK

    @property
    def platform_name(self) -> str:
        return CHANNEL_TYPE_SLACK

    @property
    def bold_marker(self) -> str:
        # Slack uses *bold* (single asterisk); send-time mrkdwn conversion
        # normalises any **bold** in the body to the same form.
        return "*"

    def _get_bot_token(self) -> str | None:
        return settings.SLACK_BOT_TOKEN

    def _session_kwargs(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            "headers": {
                "Authorization": f"Bearer {ctx['token']}",
                "Content-Type": "application/json; charset=utf-8",
            }
        }

    async def _setup_sender(
        self, session: aiohttp.ClientSession, ctx: dict[str, Any]
    ) -> tuple[SendFn | None, ChannelDeliveryStatus | None]:
        # Open (or fetch) the DM channel with the user.
        async with session.post(
            f"{SLACK_API_BASE}/conversations.open",
            json={"users": ctx["platform_user_id"]},
        ) as resp:
            if resp.status != 200:
                return None, self._error(f"Slack conversations.open HTTP {resp.status}")
            data = await resp.json()

        if not data.get("ok"):
            return None, self._error(f"Slack conversations.open error: {data.get('error')}")

        dm_channel_id = (data.get("channel") or {}).get("id")
        if not dm_channel_id:
            return None, self._error("Slack DM channel id missing from response")

        post_url = f"{SLACK_API_BASE}/chat.postMessage"

        async def send(text: str) -> str | None:
            payload = {"channel": dm_channel_id, "text": convert_to_slack_mrkdwn(text)}
            async with session.post(post_url, json=payload) as r:
                if r.status != 200:
                    return await r.text()
                body = await r.json()
            if not body.get("ok"):
                return str(body.get("error"))
            return None

        return send, None
