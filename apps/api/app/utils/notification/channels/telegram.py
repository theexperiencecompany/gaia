"""Telegram notification channel adapter.

Uses Telegram's native MessageEntity API (no parse_mode) via telegramify-markdown,
which properly converts LLM Markdown output to rich Telegram formatting.

Sends are done as plain text + entity objects — the correct Telegram approach
that works regardless of special characters in the content.
"""

from typing import Any, Dict, List

import aiohttp
from app.config.settings import settings
from app.constants.notifications import TELEGRAM_BOT_API_BASE
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

    @property
    def channel_type(self) -> str:
        return "telegram"

    @property
    def platform_name(self) -> str:
        return "telegram"

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
        """Store (session, ctx) as instance vars so _deliver_content can reach them.

        Returns a no-op SendFn to satisfy the base class contract; the actual
        sending is done via _send_message in our _deliver_content override.
        """
        # Stash for _deliver_content (cleaned up in finally block below).
        self._tg_session = session  # type: ignore[attr-defined]
        self._tg_ctx = ctx  # type: ignore[attr-defined]

        async def _noop(text: str) -> str | None:  # satisfies SendFn signature
            return None

        return _noop, None  # type: ignore[return-value]

    async def _deliver_content(
        self, send_fn: SendFn, content: Dict[str, Any]
    ) -> ChannelDeliveryStatus:
        """Send content using Telegram MessageEntity API.

        Overrides the base class implementation to use entity-based formatting
        instead of parse_mode HTML. send_fn is unused (replaced by _send_message).
        """
        session: aiohttp.ClientSession = self._tg_session  # type: ignore[attr-defined]
        ctx: Dict[str, Any] = self._tg_ctx  # type: ignore[attr-defined]

        async def send_plain(text: str) -> str | None:
            """Send plain/emoji text with no Markdown conversion."""
            return await self._send_message(session, ctx, text, [])

        async def send_markdown(text: str) -> str | None:
            """Convert Markdown → entities and send, chunking if necessary."""
            for chunk_text, chunk_entities in self._chunks_from_md(
                text,
                self.MAX_MESSAGE_LENGTH - 6,  # small headroom
            ):
                err = await self._send_message(session, ctx, chunk_text, chunk_entities)
                if err:
                    return err
            return None

        if content.get("type") == "workflow_messages":
            if header := content.get("header"):
                if err := await send_plain(header):
                    return self._error(f"Telegram header error: {err}")

            for msg in content.get("messages", []):
                if err := await send_markdown(msg):
                    return self._error(f"Telegram message error: {err}")

            if footer := content.get("footer"):
                if err := await send_markdown(footer):
                    return self._error(f"Telegram footer error: {err}")

            return self._success()

        # Standard single message — also Markdown-converted
        if err := await send_markdown(content.get("text", "")):
            return self._error(f"Telegram message error: {err}")
        return self._success()

    async def deliver(
        self, content: Dict[str, Any], user_id: str
    ) -> ChannelDeliveryStatus:
        """Override to clean up _tg_session / _tg_ctx after delivery."""
        try:
            return await super().deliver(content, user_id)
        finally:
            # Remove temp instance vars set by _setup_sender
            self.__dict__.pop("_tg_session", None)
            self.__dict__.pop("_tg_ctx", None)
