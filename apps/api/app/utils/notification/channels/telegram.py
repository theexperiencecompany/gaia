"""Telegram notification channel adapter.

Uses Telegram's native MessageEntity API (no parse_mode) via telegramify-markdown,
which properly converts LLM Markdown output to rich Telegram formatting.

Sends are done as plain text + entity objects — the correct Telegram approach
that works regardless of special characters in the content.
"""

from typing import Any, Dict, List

import aiohttp
from app.config.settings import settings
from app.constants.notifications import CHANNEL_TYPE_TELEGRAM, TELEGRAM_BOT_API_BASE
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
)
from app.utils.notification.channels.base import SendFn
from app.utils.notification.channels.external import ExternalPlatformAdapter
from telegramify_markdown import convert, split_entities


class TelegramChannelAdapter(ExternalPlatformAdapter):
    """Delivers notifications to a user's linked Telegram account.

    Overrides _deliver_content to use telegramify-markdown's convert() +
    split_entities(), sending plain text + MessageEntity objects rather than
    HTML parse_mode — the proper Telegram-native approach.
    """

    MAX_MESSAGE_LENGTH = 4096  # UTF-16 code units (Telegram's limit per message)
    TELEGRAM_MESSAGE_HEADROOM = 6
    # Reserve a few UTF-16 units to avoid edge cases at entity boundaries.

    @property
    def channel_type(self) -> str:
        return CHANNEL_TYPE_TELEGRAM

    @property
    def platform_name(self) -> str:
        return CHANNEL_TYPE_TELEGRAM

    @property
    def bold_marker(self) -> str:
        # Not used — transform/deliver overrides handle formatting directly.
        return ""

    def _get_bot_token(self) -> str | None:
        return settings.TELEGRAM_BOT_TOKEN

    def _session_kwargs(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    # ------------------------------------------------------------------
    # Markdown → entities conversion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _md_to_entities(text: str) -> tuple[str, List[Dict[str, Any]]]:
        """Convert Markdown to (plain_text, entity_dicts) via telegramify-markdown."""
        plain, entities = convert(text, latex_escape=False)
        return plain, [e.to_dict() for e in entities]

    @staticmethod
    def _chunks_from_md(
        text: str, max_len: int
    ) -> list[tuple[str, List[Dict[str, Any]]]]:
        """Convert Markdown and split into chunks within Telegram's length limit.

        Uses split_entities() so formatting entities are correctly clipped at
        chunk boundaries rather than broken.
        """
        plain, entities = convert(text, latex_escape=False)
        return [
            (chunk_text, [e.to_dict() for e in chunk_ents])
            for chunk_text, chunk_ents in split_entities(
                plain, entities, max_utf16_len=max_len
            )
        ]

    # ------------------------------------------------------------------
    # Transform — produce plain strings (entities added at send time)
    # ------------------------------------------------------------------

    async def transform(self, notification: NotificationRequest) -> Dict[str, Any]:
        """Produce plain-text content dict. Markdown → entities conversion
        happens in _deliver_content so split_entities can respect the chunk limit.
        """
        content = notification.content
        rich = content.rich_content or {}

        if rich.get("type") == "workflow_execution":
            title = content.title or ""
            body = content.body or ""
            header = f"✅ {title}\n⏰ {body}" if title else body
            messages = rich.get("messages", [])
            conversation_id = rich.get("conversation_id", "")
            app_url = settings.FRONTEND_URL
            footer = (
                f"🔗 [View full results]({app_url}/c/{conversation_id})"
                if conversation_id
                else ""
            )
            return {
                "type": "workflow_messages",
                "header": header,
                "messages": messages,
                "footer": footer,
            }

        title = content.title or ""
        body = content.body or ""
        text = f"{title}\n{body}" if title else body
        return {"text": text}

    # ------------------------------------------------------------------
    # Send layer — entities-aware sender
    # ------------------------------------------------------------------

    async def _send_message(
        self,
        session: aiohttp.ClientSession,
        ctx: Dict[str, Any],
        text: str,
        entities: List[Dict[str, Any]],
    ) -> str | None:
        """POST a single sendMessage call. Returns error text or None on success."""
        url = f"{TELEGRAM_BOT_API_BASE}{ctx['token']}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": ctx["platform_user_id"],
            "text": text,
        }
        if entities:
            payload["entities"] = entities
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                return await resp.text()
        return None

    async def _setup_sender(
        self, session: aiohttp.ClientSession, ctx: Dict[str, Any]
    ) -> tuple[SendFn | None, ChannelDeliveryStatus | None]:
        """Return a per-delivery sender closure bound to the current session/context."""

        async def send_plain(text: str) -> str | None:
            return await self._send_message(session, ctx, text, [])

        return send_plain, None

    async def _send_markdown(
        self, session: aiohttp.ClientSession, ctx: Dict[str, Any], text: str
    ) -> str | None:
        """Convert Markdown to entities and send chunked messages safely."""
        for chunk_text, chunk_entities in self._chunks_from_md(
            text,
            self.MAX_MESSAGE_LENGTH - self.TELEGRAM_MESSAGE_HEADROOM,
        ):
            err = await self._send_message(session, ctx, chunk_text, chunk_entities)
            if err:
                return err
        return None

    async def deliver(
        self, content: Dict[str, Any], user_id: str
    ) -> ChannelDeliveryStatus:
        """Deliver content without storing any per-request state on ``self``."""
        ctx, context_err = await self._get_platform_context(user_id)
        if context_err:
            return context_err
        if (
            ctx is None
        ):  # guaranteed by _get_platform_context invariant; guard for type narrowing
            raise RuntimeError(
                "ctx is None despite no error — this should never happen"
            )

        try:
            async with aiohttp.ClientSession(**self._session_kwargs(ctx)) as session:

                async def send_plain(text: str) -> str | None:
                    return await self._send_message(session, ctx, text, [])

                if content.get("type") == "workflow_messages":
                    if header := content.get("header"):
                        if send_err := await send_plain(header):
                            return self._error(f"Telegram header error: {send_err}")

                    for msg in content.get("messages", []):
                        if send_err := await self._send_markdown(session, ctx, msg):
                            return self._error(f"Telegram message error: {send_err}")

                    if footer := content.get("footer"):
                        if send_err := await self._send_markdown(session, ctx, footer):
                            return self._error(f"Telegram footer error: {send_err}")

                    return self._success()

                text = content.get("text", "")
                if send_err := await self._send_markdown(session, ctx, text):
                    return self._error(f"Telegram message error: {send_err}")
                return self._success()
        except Exception as exc:
            return self._error(str(exc))
