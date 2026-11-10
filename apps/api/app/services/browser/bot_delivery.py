"""Hand a browser run's progress to the outbox, for the users who follow it in a messaging bot.

A step is a progress notice carrying its screenshot by reference: told only to a user
watching live, superseded by the next step, never sent into a group. A handoff needs the
user and is told whether they are watching or not, until the handoff times out. The
outbox decides where each goes; nothing here publishes to a bot.
"""

from datetime import datetime, timedelta

from pydantic import ValidationError

from app.config.settings import settings
from app.constants.browser import (
    BROWSER_CREDENTIALS_SAVED_NOTE,
    BROWSER_HANDOFF_REPLY_PROMPT,
    HandoffStatus,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import (
    BrowserAction,
    BrowserHandoffSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
)
from app.schemas.outbound import OutboundAttachment
from app.services.browser.captions import caption_from_action_list
from app.services.browser.live_view import create_live_view_link
from app.services.browser.shot_store import SHOT_SUFFIX
from app.services.outbox.intake import submit
from app.services.outbox.models import (
    Initiative,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    Subject,
    SubjectKind,
    SubjectMerge,
)
from app.utils import clock
from shared.py.wide_events import log

_SUBJECT_LABEL = "Browser task"


class BotProgressDelivery:
    """Submits browser card snapshots to the outbox, owned by the conversation that asked for the run."""

    def __init__(
        self,
        *,
        job_id: str,
        user_id: str,
        conversation_id: str,
        stream_screenshots: bool,
    ) -> None:
        self._job_id = job_id
        self._user_id = user_id
        self._conversation_id = conversation_id
        self._stream_screenshots = stream_screenshots
        self._steps_shown = 0
        self._reports_submitted = 0
        #: The page and frame of the last step sent; a step showing the same again sends none.
        # Equivalent mutant: "" equals no (address, frame) pair, exactly like None.
        self._last_frame: tuple[str | None, str] | None = None  # pragma: no mutate

    async def session(self, _snapshot: BrowserSessionSnapshot) -> None:
        """Session lifecycle event: deliberately silent.

        Screenshots already stream per step, so an auto-injected "watch live"
        line is noise, not orientation. The live-view link is handed over at
        the handoff instead — the one moment the user actually needs it.
        """
        return

    async def step(self, snapshot: BrowserStepSnapshot) -> None:
        """Submit a per-step progress notice, with the step's screenshot when there is one worth sending."""
        # The pre-navigation blank tab has no photo worth sending (empty white
        # page), but its label still says where the run is headed: send that
        # as text so step 1 is never silence.
        if _is_blank_tab(snapshot.url):
            label = _step_label(snapshot.goal, snapshot.actions)
            if label:
                self._steps_shown += 1
                await self.note(f"Step {self._steps_shown} · {label}")
            return
        # The page did not change (scrolling past the end of a list): the photo
        # already sent shows it. Only the same address showing an identical frame is skipped.
        frame = (snapshot.url, snapshot.frame_digest) if snapshot.frame_digest else None
        if frame is not None and frame == self._last_frame:
            return
        self._last_frame = frame
        # Numbered by what this user was shown: the run's index counts the blank tab and repeats.
        self._steps_shown += 1
        caption = _step_caption(self._steps_shown, snapshot.goal, snapshot.actions)
        photo = (
            self._photo_of(snapshot.screenshot, caption)
            if self._stream_screenshots and snapshot.screenshot
            else None
        )
        await self._submit_progress(caption, [photo] if photo is not None else [])

    async def handoff(self, snapshot: BrowserHandoffSnapshot) -> None:
        """Submit the user's turn: a live-view handoff, told until it times out."""
        # Only the PENDING snapshot needs a message: resolution is already acked
        # in-chat and the final result line closes the task.
        if snapshot.status != HandoffStatus.PENDING:
            return
        # The user may change the page in the live view: the next step is shown whatever it looks like.
        # Equivalent mutant: "" equals no (address, frame) pair, exactly like None.
        self._last_frame = None  # pragma: no mutate

        # The ask is the model's own words (request_human_takeover's reason);
        # the link and the reply instruction follow.
        facts = [snapshot.reason]
        if snapshot.saves_login:
            facts[0] += f"\n{BROWSER_CREDENTIALS_SAVED_NOTE}"
        if snapshot.session_id:
            # One link per handoff, revoked when it is settled: only one is ever open.
            link = await create_live_view_link(
                snapshot.session_id, self._user_id, snapshot.handoff_id
            )
            facts.append(f"Open the live browser: {link}")
        facts.append(BROWSER_HANDOFF_REPLY_PROMPT)
        await submit(
            self._notice(
                f"handoff:{snapshot.handoff_id}",
                NoticeOutcome.NEEDS_YOU,
                facts,
                subject_id=f"{self._job_id}:handoff:{snapshot.handoff_id}",
                valid_until=clock.now()
                + timedelta(seconds=settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS),
            )
        )

    async def result(self, snapshot: BrowserResultSnapshot) -> None:
        """Close out the progress with the run's recap link, and nothing else.

        The outcome itself is the assistant's to say, once: the executor run
        its ending lands in tells it. A canned "Done"/"Stopped" line here made
        every outcome arrive twice.
        """
        if snapshot.replay_url:
            await submit(
                self._notice(
                    "recap",
                    NoticeOutcome.INFO,
                    [f"Here's a recap of the run: {snapshot.replay_url}"],
                    subject_id=f"{self._job_id}:recap",
                )
            )

    async def note(self, message: str) -> None:
        """Submit one plain progress line."""
        await self._submit_progress(message, [])

    async def _submit_progress(self, text: str, artifacts: list[OutboundAttachment]) -> None:
        """Submit progress of the run, which supersedes the progress before it."""
        self._reports_submitted += 1
        await submit(
            self._notice(
                f"progress:{self._reports_submitted}",
                NoticeOutcome.PROGRESS,
                [text],
                subject_id=self._job_id,
                artifacts=artifacts,
            )
        )

    def _notice(
        self,
        report_key: str,
        outcome: NoticeOutcome,
        facts: list[str],
        *,
        subject_id: str,
        artifacts: list[OutboundAttachment] | None = None,
        valid_until: datetime | None = None,
    ) -> NoticeReport:
        return NoticeReport(
            report_id=f"browser:{self._job_id}:{report_key}",
            recipient=self._user_id,
            producer=ProducerKind.BROWSER,
            subject=Subject(
                kind=SubjectKind.BROWSER_JOB,
                id=subject_id,
                owner_conversation_id=self._conversation_id,
                label=_SUBJECT_LABEL,
                merge=SubjectMerge.REPLACE,
            ),
            occurred_at=clock.now(),
            initiative=Initiative.ASKED,
            outcome=outcome,
            facts=facts,
            artifacts=artifacts or [],
            valid_until=valid_until,
        )

    def _photo_of(self, url: str, caption: str) -> OutboundAttachment | None:
        """Return the step's screenshot as an attachment, or None when its URL may not be sent (the caption then goes alone)."""
        try:
            return OutboundAttachment(
                url=url, filename=f"browser-step-{self._steps_shown}{SHOT_SUFFIX}", caption=caption
            )
        except ValidationError:
            log.warning(
                f"{LogTag.BROWSER} Step screenshot URL rejected; sending its caption alone",
                user_id=self._user_id,
                job_id=self._job_id,
            )
            return None


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
