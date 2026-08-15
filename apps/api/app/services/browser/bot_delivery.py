"""Mirror browser progress to messaging bots (Telegram/WhatsApp/…).

Bots consume backend-pushed messages over RabbitMQ, not the SSE stream. Step
screenshots are already uploaded to the CDN as signed URLs (see
``screenshots.py``), so a bot step is delivered as a real photo — the same
artifact the web card renders, sent through the platform's native image
message instead of a pasted link.
"""

from app.constants.browser import HandoffStatus
from app.models.chat_models import ConversationSource
from app.schemas.browser import (
    BrowserHandoffSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
)
from app.services.browser.live_view import live_view_link_with_token
from app.services.outbound_delivery import publish_outbound_message, publish_outbound_photo


class BotProgressDelivery:
    """Delivers browser card snapshots to a bot conversation."""

    def __init__(
        self,
        *,
        platform: ConversationSource,
        user_id: str,
        conversation_id: str,
        stream_screenshots: bool,
    ) -> None:
        self._platform = platform
        self._user_id = user_id
        self._conversation_id = conversation_id
        self._stream_screenshots = stream_screenshots

    async def session(self, snapshot: BrowserSessionSnapshot) -> None:
        await self._text(f"Using a browser to: {snapshot.task}")

    async def step(self, snapshot: BrowserStepSnapshot) -> None:
        caption = f"Step {snapshot.index}: {snapshot.goal}".strip()
        # Only a real (http) CDN URL is worth sending as a photo; the dev-only
        # inline data URL fallback is not something to upload to a platform.
        if (
            self._stream_screenshots
            and snapshot.screenshot
            and snapshot.screenshot.startswith("http")
        ):
            sent = await publish_outbound_photo(
                self._platform,
                self._user_id,
                snapshot.screenshot,
                filename=f"browser-step-{snapshot.index}.jpg",
                caption=caption,
            )
            if sent:
                return
        await self._text(caption)

    async def handoff(self, snapshot: BrowserHandoffSnapshot) -> None:
        if snapshot.status != HandoffStatus.PENDING:
            await self._text(f"Browser task handoff {snapshot.status.value}.")
            return

        msg = f"I need you to take over for this step: {snapshot.reason}\n\nReply *done* to continue or *stop* to cancel."
        if snapshot.session_id:
            link = live_view_link_with_token(snapshot.session_id, self._user_id)
            msg += f"\nOpen the live browser: {link}"
        await self._text(msg)

    async def result(self, snapshot: BrowserResultSnapshot) -> None:
        await self._text(snapshot.summary)

    async def _text(self, message: str) -> None:
        await publish_outbound_message(self._platform, self._user_id, [message])
