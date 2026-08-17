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
from app.services.browser.captions import caption_from_action_summary
from app.services.browser.live_view import create_live_view_link
from app.services.outbound_delivery import publish_outbound_message, publish_outbound_photo

# A photo caption should be a glanceable phrase, not a paragraph of the agent's goal.
_CAPTION_MAX_CHARS = 90
# One update per step buries the conversation: a real shopping task runs 20+ steps,
# which is 20 photos in a chat the user also has to read replies in. They already
# get the live-view link up front and the full recap at the end, so the stream only
# needs to show that work is happening.
_MAX_STEP_UPDATES = 5


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
        self._step_updates_sent = 0

    async def session(self, snapshot: BrowserSessionSnapshot) -> None:
        # Surface the live-view link up front so the user can watch the run as it
        # happens — and is already oriented if a handoff comes later. The link only
        # exists once the session is allocated, which is exactly now.
        if not snapshot.session_id:
            return
        link = await create_live_view_link(snapshot.session_id, self._user_id)
        await self._text(f"On it — watch along live here:\n{link}")

    async def step(self, snapshot: BrowserStepSnapshot) -> None:
        # Skip the pre-navigation blank tab: its screenshot is an empty white page
        # and "Empty Tab" tells the user nothing. The real first step is the loaded
        # page.
        if _is_blank_tab(snapshot.url):
            return
        if self._step_updates_sent >= _MAX_STEP_UPDATES:
            return
        self._step_updates_sent += 1
        # Caption with what the agent is DOING this step (its goal), not the page
        # URL — a raw link reads as noise and invites a mis-click.
        caption = _step_caption(snapshot.index, snapshot.goal, snapshot.action)
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
        # Only the PENDING snapshot needs a message (the takeover request itself).
        # Resolution is already acked in-chat ("Got it, continuing." / "Okay, I've
        # stopped."), and the final result line closes the task — a separate
        # "Browser task handoff completed." here is just noise.
        if snapshot.status != HandoffStatus.PENDING:
            return

        msg = (
            f"I need you to take over for this step:\n{snapshot.reason}\n\n"
            "Reply *done* when you've finished, or *stop* to cancel."
        )
        if snapshot.session_id:
            link = await create_live_view_link(snapshot.session_id, self._user_id)
            msg += f"\n\nOpen the live browser: {link}"
        await self._text(msg)

    async def result(self, snapshot: BrowserResultSnapshot) -> None:
        # Don't echo Browser-Use's raw final text — the assistant sends the
        # natural, user-facing summary right after. Just close out the progress,
        # plus a recap slideshow of every step (offered whether it succeeded or not).
        msg = "✅ Done." if snapshot.success else "⚠️ The browser task didn't fully complete."
        if snapshot.replay_url:
            msg += f"\n\n📽 Here's a recap you can watch: {snapshot.replay_url}"
        await self._text(msg)

    async def _text(self, message: str) -> None:
        await publish_outbound_message(self._platform, self._user_id, [message])


def _is_blank_tab(url: str | None) -> bool:
    """The pre-navigation empty tab — nothing worth showing the user yet."""
    return not url or url.startswith("about:") or url == "chrome://newtab/"


def _step_caption(index: int, goal: str | None, action: str | None) -> str:
    """A short, human caption for a step photo — what the agent is doing, in plain
    language (its goal), falling back to a clean action label; never a raw URL or
    an action's parameter dump."""
    label = (goal or "").strip().rstrip(".") or caption_from_action_summary(action)
    if len(label) > _CAPTION_MAX_CHARS:
        label = label[: _CAPTION_MAX_CHARS - 1].rstrip() + "…"
    return f"Step {index} · {label}" if label else f"Step {index}"
