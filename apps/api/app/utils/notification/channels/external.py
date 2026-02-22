"""
Abstract base for external messaging platform adapters (e.g. Telegram, Discord).

Sits between ChannelAdapter and concrete platform adapters. Handles shared concerns:
resolving the user's linked account, formatting notification content, splitting long
messages to respect platform limits, and orchestrating delivery via aiohttp.

Subclasses must implement: platform_name, bold_marker, _get_bot_token,
_session_kwargs, and _setup_sender.
"""

from abc import abstractmethod

from typing import Any, Dict, List

import aiohttp

from app.config.settings import settings
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationRequest,
)
from app.services.platform_link_service import PlatformLinkService
from app.utils.notification.channels.base import ChannelAdapter, SendFn


class ExternalPlatformAdapter(ChannelAdapter):
    """Base class for external messaging platform adapters."""

    MAX_MESSAGE_LENGTH: int = 2000

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Platform key used for platform-link lookups (e.g. 'telegram')."""
        pass

    @property
    @abstractmethod
    def bold_marker(self) -> str:
        """Markdown bold delimiter: '*' for Telegram, '**' for Discord."""
        pass

    @abstractmethod
    def _get_bot_token(self) -> str | None:
        """Return the bot token, or None if not configured."""
        pass

    @abstractmethod
    def _session_kwargs(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Return extra kwargs for ``aiohttp.ClientSession`` (e.g. headers)."""
        pass

    @abstractmethod
    async def _setup_sender(
        self, session: aiohttp.ClientSession, ctx: Dict[str, Any]
    ) -> tuple[SendFn | None, ChannelDeliveryStatus | None]:
        """
        Prepare a send function for this platform.

        Returns ``(send_fn, None)`` on success or ``(None, error_status)``
        on failure.  ``send_fn(text) -> error_string | None``.
        """
        pass

    # -- Shared implementations ---------------------------------------------

    def can_handle(self, notification: NotificationRequest) -> bool:
        # External adapters are auto-injected by the orchestrator regardless of the
        # explicit channel list, so they always report they can handle a notification.
        # The orchestrator's preference-check and platform-link lookup are the real guards.
        return True

    def _split_text(self, text: str, limit: int) -> List[str]:
        """Split text at paragraph/newline boundaries to respect char limits."""
        if len(text) <= limit:
            return [text]
        parts: List[str] = []
        while len(text) > limit:
            split_at = text.rfind("\n", 0, limit)
            if split_at == -1:
                split_at = limit
            parts.append(text[:split_at].rstrip())
            text = text[split_at:].lstrip()
        if text:
            parts.append(text)
        return parts

    async def transform(self, notification: NotificationRequest) -> Dict[str, Any]:
        content = notification.content
        rich = content.rich_content or {}
        b = self.bold_marker

        if rich.get("type") == "workflow_execution":
            title = content.title or ""
            body = content.body or ""
            header = f"\u2705 {b}{title}{b}\n\u23f0 {body}" if title else body
            messages = rich.get("messages", [])
            conversation_id = rich.get("conversation_id", "")
            app_url = settings.FRONTEND_URL
            footer = (
                f"\U0001f517 [View full results]({app_url}/c/{conversation_id})"
                if conversation_id
                else ""
            )
            return {
                "type": "workflow_messages",
                "header": header,
                "messages": messages,
                "footer": footer,
            }

        # Standard single-message format
        title = content.title or ""
        body = content.body or ""
        text = f"{b}{title}{b}\n{body}" if title else body
        return {"text": text}

    async def _get_platform_context(
        self, user_id: str
    ) -> tuple[Dict[str, Any] | None, ChannelDeliveryStatus | None]:
        """Validate platform link and bot token.

        Returns ``(context_dict, None)`` on success or
        ``(None, error_status)`` on failure.
        """
        linked = await PlatformLinkService.get_linked_platforms(user_id)
        platform_info = linked.get(self.platform_name)

        if not platform_info:
            return None, self._skipped(f"{self.platform_name} not linked")

        platform_user_id = platform_info.get("platformUserId")
        if not platform_user_id:
            return None, self._skipped(f"{self.platform_name} user id missing")

        token = self._get_bot_token()
        if not token:
            return None, self._skipped(f"{self.platform_name} bot token not configured")

        return {"platform_user_id": platform_user_id, "token": token}, None

    async def _deliver_content(
        self, send_fn: SendFn, content: Dict[str, Any]
    ) -> ChannelDeliveryStatus:
        """Route content through *send_fn*, handling workflow & standard msgs."""
        name = self.platform_name.capitalize()

        if content.get("type") == "workflow_messages":
            if content.get("header"):
                err = await send_fn(content["header"])
                if err:
                    return self._error(f"{name} header error: {err}")

            for msg in content.get("messages", []):
                for chunk in self._split_text(msg, self.MAX_MESSAGE_LENGTH):
                    err = await send_fn(chunk)
                    if err:
                        return self._error(f"{name} message error: {err}")

            if content.get("footer"):
                err = await send_fn(content["footer"])
                if err:
                    return self._error(f"{name} footer error: {err}")

            return self._success()

        # Standard single message
        err = await send_fn(content.get("text", ""))
        if err:
            return self._error(f"{name} message error: {err}")
        return self._success()

    async def deliver(
        self, content: Dict[str, Any], user_id: str
    ) -> ChannelDeliveryStatus:
        ctx, err = await self._get_platform_context(user_id)
        if err:
            return err
        if (
            ctx is None
        ):  # guaranteed by _get_platform_context invariant; guard for type narrowing
            raise RuntimeError(
                "ctx is None despite no error — this should never happen"
            )

        try:
            async with aiohttp.ClientSession(**self._session_kwargs(ctx)) as session:
                send_fn, setup_err = await self._setup_sender(session, ctx)
                if setup_err:
                    return setup_err
                return await self._deliver_content(send_fn, content)  # type: ignore[arg-type]
        except Exception as exc:
            return self._error(str(exc))
