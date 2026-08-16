"""Mirror browser progress to messaging bots (Telegram/WhatsApp/…).

Bots consume backend-pushed messages over RabbitMQ, not the SSE stream. Step
screenshots are already uploaded to the CDN as signed URLs (see
``screenshots.py``), so a bot step is delivered as a real photo — the same
artifact the web card renders, sent through the platform's native image
message instead of a pasted link.
"""

from urllib.parse import urlparse

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

    async def session(self, _snapshot: BrowserSessionSnapshot) -> None:
        # No message: the HIL approval ack + the first step photo already tell the
        # user the browser has started. A third "opening a browser" line is noise.
        return

    async def step(self, snapshot: BrowserStepSnapshot) -> None:
        # The step photo IS the progress. Caption it with the page, not the
        # agent's internal reasoning ("goal") — that reads as noise to a user.
        caption = _step_caption(snapshot.index, snapshot.title, snapshot.url)
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

        msg = (
            f"I need you to take over for this step:\n{snapshot.reason}\n\n"
            "Reply *done* when you've finished, or *stop* to cancel."
        )
        if snapshot.session_id:
            link = live_view_link_with_token(snapshot.session_id, self._user_id)
            msg += f"\n\nOpen the live browser: {link}"
        await self._text(msg)

    async def result(self, snapshot: BrowserResultSnapshot) -> None:
        # Don't echo Browser-Use's raw final text — the assistant sends the
        # natural, user-facing summary right after. Just close out the progress.
        await self._text(
            "✅ Done." if snapshot.success else "⚠️ The browser task didn't fully complete."
        )

    async def _text(self, message: str) -> None:
        await publish_outbound_message(self._platform, self._user_id, [message])


def _step_caption(index: int, title: str | None, url: str | None) -> str:
    """A short, human caption for a step photo — the page, never the agent's goal."""
    label = (title or "").strip()
    if not label and url:
        host = urlparse(url).hostname
        label = host or ""
    return f"Step {index} · {label}" if label else f"Step {index}"
