"""Mirror browser progress + screenshots to messaging bots (Telegram/WhatsApp/…).

Bots consume backend-pushed messages over RabbitMQ, not the SSE stream, so a
browser task running for a bot conversation delivers each step as a caption and
each screenshot as an image via the outbound-delivery service. Screenshot
delivery needs the JuiceFS-backed session store (dockered/prod); when that mount
is absent (native dev) it degrades to text captions instead of failing the run.
"""

import base64

from app.constants.log_tags import LogTag
from app.models.chat_models import ConversationSource
from app.schemas.browser import (
    BrowserHandoffSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
)
from app.services.outbound_delivery import publish_outbound_file, publish_outbound_message
from app.services.storage.juicefs import JuiceFSUnavailable, write_session_file
from shared.py.wide_events import log

_SCREENSHOT_DIR = "browser"


def _decode_data_url(data_url: str) -> bytes | None:
    marker = "base64,"
    idx = data_url.find(marker)
    if idx == -1:
        return None
    try:
        return base64.b64decode(data_url[idx + len(marker) :])
    except Exception:  # noqa: BLE001 — malformed screenshot is non-fatal
        return None


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
        if (
            self._stream_screenshots
            and snapshot.screenshot
            and await self._screenshot(snapshot, caption)
        ):
            return
        await self._text(caption)

    async def handoff(self, snapshot: BrowserHandoffSnapshot) -> None:
        msg = f"I need you to take over for this step: {snapshot.reason}"
        if snapshot.live_view_url:
            msg += f"\nOpen the live browser: {snapshot.live_view_url}"
        await self._text(msg)

    async def result(self, snapshot: BrowserResultSnapshot) -> None:
        await self._text(snapshot.summary)

    async def _screenshot(self, snapshot: BrowserStepSnapshot, caption: str) -> bool:
        png = _decode_data_url(snapshot.screenshot or "")
        if png is None:
            return False
        name = f"step_{snapshot.index}.png"
        try:
            await write_session_file(
                self._user_id,
                self._conversation_id,
                f"artifacts/{_SCREENSHOT_DIR}/{name}",
                png,
            )
        except JuiceFSUnavailable:
            log.warning(
                f"{LogTag.AGENT} Session store unavailable; sending browser step as text to bot."
            )
            return False
        return await publish_outbound_file(
            self._platform,
            self._user_id,
            self._conversation_id,
            path=f"{_SCREENSHOT_DIR}/{name}",
            filename=name,
            content_type="image/png",
            caption=caption,
        )

    async def _text(self, message: str) -> None:
        await publish_outbound_message(self._platform, self._user_id, [message])
