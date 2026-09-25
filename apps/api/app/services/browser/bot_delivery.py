"""Mirror browser progress to messaging bots (Telegram/WhatsApp/etc).

Bots consume backend-pushed messages over RabbitMQ, not the SSE stream. Step
screenshots are already uploaded to the CDN as signed URLs (see
screenshots.py), so a bot step is delivered as a real photo, the same
artifact the web card renders, through the platform's native image message
instead of a pasted link.
"""

from app.constants.browser import (
    BROWSER_CREDENTIALS_SAVED_NOTE,
    HandoffStatus,
    SensitiveCategory,
)
from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.log_tags import LogTag
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
from app.services.outbound_delivery import (
    OutboundResult,
    publish_outbound_message,
    publish_outbound_photo,
)
from shared.py.wide_events import log


class BotProgressDelivery:
    """Delivers browser card snapshots to the requester's DM, even for a run asked for in a group."""

    def __init__(
        self,
        *,
        platform: ConversationSource,
        user_id: str,
        stream_screenshots: bool,
    ) -> None:
        self._platform = platform
        self._user_id = user_id
        self._stream_screenshots = stream_screenshots
        self._links: dict[str, str] = {}
        self._steps_shown = 0
        self._last_label = ""  # pragma: no mutate — only compared to a non-empty label

    async def session(self, _snapshot: BrowserSessionSnapshot) -> None:
        """Session lifecycle event: deliberately silent.

        Screenshots already stream per step, so an auto-injected "watch live"
        line is noise, not orientation. The live-view link is handed over at
        the handoff instead — the one moment the user actually needs it.
        """
        return

    async def _link(self, session_id: str) -> str:
        """One live-view link per session: every mint is a different code for the same browser, and a second link reads as a second browser."""
        if session_id not in self._links:
            self._links[session_id] = await create_live_view_link(session_id, self._user_id)
        return self._links[session_id]

    async def step(self, snapshot: BrowserStepSnapshot) -> None:
        """Emit a per-step progress event to the conversation."""
        # The pre-navigation blank tab has no photo worth sending (empty white
        # page), but its label still says where the run is headed: send that
        # as text so step 1 is never silence.
        if _is_blank_tab(snapshot.url):
            label = _step_label(snapshot.goal, snapshot.actions)
            if label:
                self._steps_shown += 1
                await self.note(f"Step {self._steps_shown} · {label}")
            return
        # A run of identical steps (scrolling a long list) is one update, not a
        # photo a second; the first of the run already told the user what is going on.
        label = _step_label(snapshot.goal, snapshot.actions)
        if label and label == self._last_label:
            return
        self._last_label = label
        # Numbered by what this user was shown: the run's index counts the blank
        # tab and the repeats skipped above.
        self._steps_shown += 1
        caption = _step_caption(self._steps_shown, snapshot.goal, snapshot.actions)
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
                filename=f"browser-step-{self._steps_shown}.png",
                caption=caption,
            )
            if sent:
                return
        await self.note(_step_caption(self._steps_shown, snapshot.goal, snapshot.actions))

    async def handoff(self, snapshot: BrowserHandoffSnapshot) -> None:
        """Emit a live-view handoff event to the conversation."""
        # Only the PENDING snapshot needs a message: resolution is already acked
        # in-chat and the final result line closes the task.
        if snapshot.status != HandoffStatus.PENDING:
            return

        # The ask is the model's own words (request_human_takeover's reason),
        # shown verbatim as the first bubble; link and reply instruction follow.
        blocks = [snapshot.reason]
        if snapshot.category == SensitiveCategory.CREDENTIALS:
            blocks[0] += f"\n{BROWSER_CREDENTIALS_SAVED_NOTE}"
        if snapshot.session_id:
            blocks.append(f"Open the live browser: {await self._link(snapshot.session_id)}")
        blocks.append('Reply "done" when you\'ve finished, or "stop" to cancel.')
        await self.note(NEW_MESSAGE_BREAKER.join(blocks))

    async def result(self, snapshot: BrowserResultSnapshot) -> None:
        """Close out the progress with the run's recap link, and nothing else.

        The outcome itself is the assistant's to say, once: the joined turn
        narrates it, or the worker's follow-up does when nobody is joined. A
        canned "Done"/"Stopped" line here made every outcome arrive twice.
        """
        if snapshot.replay_url:
            await self.note(f"📽 Here's a recap of the run: {snapshot.replay_url}")

    async def note(self, message: str) -> None:
        """Send one plain message to the user."""
        result = await publish_outbound_message(self._platform, self._user_id, [message])
        if result is not OutboundResult.PUBLISHED:
            log.warning(
                f"{LogTag.BROWSER} Browser progress not sent to the bot",
                outbound_result=result,
                platform=self._platform,
                user_id=self._user_id,
            )


def _is_blank_tab(url: str | None) -> bool:
    """Return whether url is the pre-navigation empty tab (nothing worth showing yet)."""
    return not url or url.startswith("about:") or url == "chrome://newtab/"


def _step_label(goal: str | None, actions: list[BrowserAction]) -> str:
    """Say what the agent is doing this step in plain language: its goal, else a clean action label; never a raw URL or a parameter dump. Never clipped."""
    return (goal or "").strip().rstrip(".") or caption_from_action_list(actions)


def _step_caption(index: int, goal: str | None, actions: list[BrowserAction]) -> str:
    """Return the numbered caption a step carries, in full."""
    label = _step_label(goal, actions)
    return f"Step {index} · {label}" if label else f"Step {index}"
