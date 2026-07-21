"""Mirror browser progress to messaging bots (Telegram/WhatsApp/…).

Bots consume backend-pushed messages over RabbitMQ, not the SSE stream. Step
screenshots are already uploaded to the CDN as signed URLs (see
``screenshots.py``), so a bot step is just a caption plus that link — the same
artifact the web card renders. One delivery path for every surface.
"""

from app.models.chat_models import ConversationSource
from app.schemas.browser import (
    BrowserHandoffSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
)
from app.services.outbound_delivery import publish_outbound_message


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
        # Only a real (http) CDN URL is worth sending; the dev-only inline data
        # URL fallback is not something to paste into a chat.
        if (
            self._stream_screenshots
            and snapshot.screenshot
            and snapshot.screenshot.startswith("http")
        ):
            caption += f"\n{snapshot.screenshot}"
        await self._text(caption)

    async def handoff(self, snapshot: BrowserHandoffSnapshot) -> None:
        msg = f"I need you to take over for this step: {snapshot.reason}"
        if snapshot.live_view_url:
            msg += f"\nOpen the live browser: {snapshot.live_view_url}"
        await self._text(msg)

    async def result(self, snapshot: BrowserResultSnapshot) -> None:
        await self._text(snapshot.summary)

    async def _text(self, message: str) -> None:
        await publish_outbound_message(self._platform, self._user_id, [message])
