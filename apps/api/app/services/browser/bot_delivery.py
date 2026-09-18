"""Mirror browser progress to messaging bots (Telegram/WhatsApp/etc).

Bots consume backend-pushed messages over RabbitMQ, not the SSE stream. Step
screenshots are already uploaded to the CDN as signed URLs (see
screenshots.py), so a bot step is delivered as a real photo, the same
artifact the web card renders, through the platform's native image message
instead of a pasted link.
"""

from app.constants.browser import (
    BROWSER_CREDENTIALS_SAVED_NOTE,
    BROWSER_TASK_FAILED_PREFIX,
    BrowserSessionStatus,
    HandoffStatus,
    SensitiveCategory,
)
from app.models.chat_models import ConversationSource
from app.schemas.browser import (
    BrowserAction,
    BrowserHandoffSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
)
from app.services.browser.captions import caption_from_action_list
from app.services.browser.live_view import create_live_view_link
from app.services.outbound_delivery import publish_outbound_message, publish_outbound_photo

# A photo caption should be a glanceable phrase, not a paragraph of the agent's goal.
_CAPTION_MAX_CHARS = 90

# The runner's failure summary is written for logs, not chat — clip it so a raw
# error dump never floods the conversation.
_FAILURE_REASON_MAX_CHARS = 160


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
        self._links: dict[str, str] = {}

    async def session(self, snapshot: BrowserSessionSnapshot) -> None:
        """Emit a session lifecycle event to the conversation."""
        # Surface the live-view link up front so the user can watch the run as it
        # happens, and is already oriented if a handoff comes later. The link
        # only exists once the session is allocated, which is exactly now.
        if not snapshot.session_id:
            return
        await self._text(f"On it. Watch along live here:\n{await self._link(snapshot.session_id)}")

    async def _link(self, session_id: str) -> str:
        """One live-view link per session: every mint is a different code for the same browser, and a second link reads as a second browser."""
        if session_id not in self._links:
            self._links[session_id] = await create_live_view_link(session_id, self._user_id)
        return self._links[session_id]

    async def step(self, snapshot: BrowserStepSnapshot) -> None:
        """Emit a per-step progress event to the conversation."""
        # Skip the pre-navigation blank tab: its screenshot is an empty white
        # page and "Empty Tab" tells the user nothing.
        if _is_blank_tab(snapshot.url):
            return
        # Caption with what the agent is DOING this step (its goal), not the page
        # URL — a raw link reads as noise and invites a mis-click.
        caption = _step_caption(snapshot.index, snapshot.goal, snapshot.actions)
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
                filename=f"browser-step-{snapshot.index}.png",
                caption=caption,
            )
            if sent:
                return
        await self._text(caption)

    async def handoff(self, snapshot: BrowserHandoffSnapshot) -> None:
        # Only PENDING needs a message: resolution is already acked in-chat and
        # the final result line closes the task, so a "handoff completed"
        # message here would be redundant noise.
        """Emit a live-view handoff event to the conversation."""
        # Only the PENDING snapshot needs a message: resolution is already acked
        # in-chat and the final result line closes the task.
        if snapshot.status != HandoffStatus.PENDING:
            return

        msg = (
            f"I need you to take over for this step:\n{snapshot.reason}\n\n"
            "Reply *done* when you've finished, or *stop* to cancel."
        )
        if snapshot.category == SensitiveCategory.CREDENTIALS:
            msg += f"\n\n{BROWSER_CREDENTIALS_SAVED_NOTE}"
        if snapshot.session_id:
            msg += f"\n\nOpen the live browser: {await self._link(snapshot.session_id)}"
        await self._text(msg)

    async def result(self, snapshot: BrowserResultSnapshot) -> None:
        """Emit the final task result to the conversation."""
        # Don't echo Browser-Use's raw final text: the assistant sends the
        # user-facing summary right after. This just closes out the progress.
        if snapshot.success:
            msg = "✅ Done."
        elif snapshot.status is BrowserSessionStatus.CANCELLED:
            # The user stopped this themselves, so telling them it could not be
            # finished reads as a failure they did not cause.
            msg = "🛑 Stopped."
        else:
            reason = _failure_reason(snapshot.summary)
            msg = f"⚠️ Couldn't finish that: {reason}" if reason else "⚠️ Couldn't finish that."
        if snapshot.replay_url:
            msg += f"\n\n📽 Here's a recap of the run: {snapshot.replay_url}"
        await self._text(msg)

    async def _text(self, message: str) -> None:
        await publish_outbound_message(self._platform, self._user_id, [message])


def _failure_reason(summary: str) -> str:
    """Collapse a runner failure summary to one clipped line, or "" when it carried none."""
    reason = " ".join(summary.removeprefix(BROWSER_TASK_FAILED_PREFIX).split())
    if len(reason) > _FAILURE_REASON_MAX_CHARS:
        reason = reason[: _FAILURE_REASON_MAX_CHARS - 1].rstrip() + "…"
    return reason


def _is_blank_tab(url: str | None) -> bool:
    """Return whether url is the pre-navigation empty tab (nothing worth showing yet)."""
    return not url or url.startswith("about:") or url == "chrome://newtab/"


def _step_caption(index: int, goal: str | None, actions: list[BrowserAction]) -> str:
    """Return a short, human caption for a step photo — what the agent is doing, in plain language (its goal), falling back to a clean action label; never a raw URL or an action's parameter dump."""
    label = (goal or "").strip().rstrip(".") or caption_from_action_list(actions)
    if len(label) > _CAPTION_MAX_CHARS:
        label = label[: _CAPTION_MAX_CHARS - 1].rstrip() + "…"
    return f"Step {index} · {label}" if label else f"Step {index}"
