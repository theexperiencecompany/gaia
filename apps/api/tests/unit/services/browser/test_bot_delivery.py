"""Browser progress handed to the outbox: what each card snapshot becomes, and what it never becomes."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.config.settings import settings
from app.constants.browser import (
    BROWSER_CREDENTIALS_SAVED_NOTE,
    BROWSER_HANDOFF_REPLY_PROMPT,
    BrowserSessionStatus,
    HandoffStatus,
    SensitiveCategory,
)
from app.schemas.browser import (
    BrowserAction,
    BrowserHandoffSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
)
from app.services.browser.bot_delivery import (
    BotProgressDelivery,
    _is_blank_tab,
    _step_caption,
)
from app.services.outbox.models import (
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    SubjectKind,
    SubjectMerge,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
SUBMIT = "app.services.browser.bot_delivery.submit"
LIVE_LINK = "https://live.example.com/link"


def _delivery(*, stream_screenshots: bool = True) -> BotProgressDelivery:
    return BotProgressDelivery(
        job_id="job-1",
        user_id="user-1",
        conversation_id="conv-1",
        stream_screenshots=stream_screenshots,
    )


@pytest.fixture
def delivery() -> BotProgressDelivery:
    return _delivery()


@pytest.fixture
def delivery_no_screenshots() -> BotProgressDelivery:
    return _delivery(stream_screenshots=False)


@pytest.fixture
def submitted() -> Iterator[list[NoticeReport]]:
    """Every report handed to the outbox, in order; the clock and the live-view link are fixed."""
    reports: list[NoticeReport] = []

    async def capture_report(report: NoticeReport) -> None:
        reports.append(report)

    with (
        patch(SUBMIT, capture_report),
        patch("app.services.browser.bot_delivery.clock.now", return_value=NOW),
        patch(
            "app.services.browser.bot_delivery.create_live_view_link",
            new=AsyncMock(return_value=LIVE_LINK),
        ),
    ):
        yield reports


def _step(index: int = 2, **overrides: object) -> BrowserStepSnapshot:
    fields: dict[str, object] = {
        "index": index,
        "goal": "Clicking",
        "url": "https://example.com",
        "screenshot": "https://cdn.example.com/shot.png",
    }
    return BrowserStepSnapshot.model_validate({**fields, **overrides})


def _handoff(**overrides: object) -> BrowserHandoffSnapshot:
    fields: dict[str, object] = {
        "handoff_id": "h1",
        "reason": "Payment needed",
        "session_id": "sess-1",
        "status": HandoffStatus.PENDING,
    }
    return BrowserHandoffSnapshot.model_validate({**fields, **overrides})


class TestIsBlankTab:
    def test_none_is_blank(self):
        assert _is_blank_tab(None) is True

    def test_empty_is_blank(self):
        assert _is_blank_tab("") is True

    def test_about_blank(self):
        assert _is_blank_tab("about:blank") is True
        assert _is_blank_tab("about:srcdoc") is True

    def test_chrome_newtab(self):
        assert _is_blank_tab("chrome://newtab/") is True

    def test_real_url_not_blank(self):
        assert _is_blank_tab("https://example.com") is False
        assert _is_blank_tab("http://localhost:3000") is False

    def test_chrome_without_trailing_slash_not_blank(self):
        # exact match required for chrome://newtab/
        assert _is_blank_tab("chrome://newtab") is False


class TestStepCaption:
    def test_with_goal(self):
        assert (
            _step_caption(1, "Opening the page", [BrowserAction(name="click")])
            == "Step 1 · Opening the page"
        )

    def test_strips_trailing_dot(self):
        assert _step_caption(1, "Opening the page.", []) == "Step 1 · Opening the page"

    def test_long_goal_never_truncated(self):
        goal = "A" * 300
        result = _step_caption(1, goal, [])
        assert result == f"Step 1 · {goal}"

    def test_falls_back_to_the_actions(self):
        # goal empty → uses caption_from_action_summary
        result = _step_caption(3, "", [BrowserAction(name="click"), BrowserAction(name="scroll")])
        assert result == "Step 3 · Clicking, Scrolling"

    def test_falls_back_when_goal_whitespace(self):
        result = _step_caption(1, "   ", [BrowserAction(name="click")])
        assert result == "Step 1 · Clicking"

    def test_no_label_returns_step_only(self):
        assert _step_caption(5, None, []) == "Step 5"
        assert _step_caption(5, "", "") == "Step 5"

    def test_goal_stripped(self):
        assert _step_caption(1, "  Hello world  ", []) == "Step 1 · Hello world"

    def test_only_trailing_dot_is_stripped_not_letter_x(self):
        # rstrip(".") must strip only a trailing period — a padding mutant that
        # widens the strip set (e.g. to "XX.XX") would also eat a trailing "X",
        # which a real caption text like "Click X" must never lose.
        assert _step_caption(1, "Click X", []) == "Step 1 · Click X"

    def test_long_goal_with_space_never_truncated(self):
        goal = "A" * 178 + " " + "B" * 20
        result = _step_caption(1, goal, [])
        assert result == f"Step 1 · {goal}"


class TestSessionIsSilent:
    async def test_a_session_snapshot_submits_nothing_and_mints_no_link(
        self, delivery, submitted
    ) -> None:
        snapshot = BrowserSessionSnapshot(
            task="t", status=BrowserSessionStatus.RUNNING, session_id="sess-1"
        )
        with patch("app.services.browser.bot_delivery.create_live_view_link") as mint:
            await delivery.session(snapshot)
        mint.assert_not_called()
        assert submitted == []


class TestStepIsProgressThatSupersedes:
    async def test_a_step_is_a_progress_notice_of_the_browser_job_owned_by_the_asking_chat(
        self, delivery, submitted
    ) -> None:
        await delivery.step(_step())
        [report] = submitted
        assert report.outcome is NoticeOutcome.PROGRESS
        assert report.producer is ProducerKind.BROWSER
        assert (report.recipient, report.subject.owner_conversation_id) == ("user-1", "conv-1")
        assert (report.subject.kind, report.subject.id) == (SubjectKind.BROWSER_JOB, "job-1")
        assert report.subject.merge is SubjectMerge.REPLACE
        assert report.valid_until is None

    async def test_every_step_of_a_run_is_a_distinct_report_of_one_subject(
        self, delivery, submitted
    ) -> None:
        await delivery.step(_step(1, frame_digest="a"))
        await delivery.step(_step(2, frame_digest="b"))
        first, second = submitted
        assert first.report_id != second.report_id
        assert first.subject.id == second.subject.id

    async def test_a_step_carries_its_photo_by_url_with_the_caption(
        self, delivery, submitted
    ) -> None:
        await delivery.step(_step())
        [report] = submitted
        [photo] = report.artifacts
        assert (photo.url, photo.filename, photo.caption) == (
            "https://cdn.example.com/shot.png",
            "browser-step-1.jpg",
            "Step 1 · Clicking",
        )
        assert report.facts == ["Step 1 · Clicking"]

    async def test_a_long_goal_is_never_clipped(self, delivery, submitted) -> None:
        goal = "Typing " + "a very long goal " * 12
        await delivery.step(_step(goal=goal))
        assert submitted[0].artifacts[0].caption == f"Step 1 · {goal.strip()}"

    @pytest.mark.parametrize(
        "overrides", [{"screenshot": None}, {"screenshot": "http://cdn.example.com/shot.png"}]
    )
    async def test_a_step_with_no_sendable_photo_goes_as_its_caption_alone(
        self, delivery, submitted, overrides
    ) -> None:
        """A rejected (non-https) URL degrades to the caption, never to silence."""
        await delivery.step(_step(**overrides))
        [report] = submitted
        assert report.artifacts == []
        assert report.facts == ["Step 1 · Clicking"]

    async def test_a_rejected_screenshot_url_is_a_warning_naming_the_job(
        self, delivery, submitted
    ) -> None:
        with patch("app.services.browser.bot_delivery.log") as log:
            await delivery.step(_step(screenshot="http://cdn.example.com/shot.png"))
        log.warning.assert_called_once()
        assert log.warning.call_args.kwargs["job_id"] == "job-1"

    async def test_screenshots_turned_off_send_only_the_caption(
        self, delivery_no_screenshots, submitted
    ) -> None:
        await delivery_no_screenshots.step(_step())
        assert submitted[0].artifacts == []

    @pytest.mark.parametrize("url", [None, "about:blank", "chrome://newtab/"])
    async def test_the_blank_tab_says_where_the_run_is_headed_without_a_photo(
        self, delivery, submitted, url
    ) -> None:
        await delivery.step(_step(1, goal="Open", url=url))
        [report] = submitted
        assert (report.facts, report.artifacts) == (["Step 1 · Open"], [])

    async def test_a_blank_tab_with_no_label_is_silent(self, delivery, submitted) -> None:
        await delivery.step(_step(1, goal="", url="about:blank"))
        assert submitted == []

    async def test_a_blank_tab_with_no_goal_is_named_by_its_action(
        self, delivery, submitted
    ) -> None:
        await delivery.step(
            _step(1, goal="", url="about:blank", actions=[BrowserAction(name="click")])
        )
        assert submitted[0].facts == ["Step 1 · Clicking"]

    async def test_numbering_counts_what_the_user_was_shown(self, delivery, submitted) -> None:
        await delivery.step(_step(1, goal="Open", url="about:blank"))
        await delivery.step(_step(3, goal="Read", frame_digest="a"))
        await delivery.step(_step(4, goal="Mid-run blank", url="about:blank"))
        assert [report.facts[0] for report in submitted] == [
            "Step 1 · Open",
            "Step 2 · Read",
            "Step 3 · Mid-run blank",
        ]


class TestRepeatedFrames:
    """A list scrolled past its end shows the same page again and again; the user is sent it once."""

    @staticmethod
    def _frame(
        index: int, digest: str, url: str = "https://example.com/list"
    ) -> BrowserStepSnapshot:
        return _step(
            index,
            goal="Scrolling",
            url=url,
            screenshot=f"https://cdn.example.com/{index}.jpg",
            frame_digest=digest,
        )

    async def test_only_a_frame_identical_to_the_last_one_sent_is_skipped(
        self, delivery, submitted
    ) -> None:
        await delivery.step(self._frame(1, "a"))
        await delivery.step(self._frame(2, "a"))
        await delivery.step(self._frame(3, "b"))
        await delivery.step(self._frame(4, "a"))
        # The same picture at another address is another page.
        await delivery.step(self._frame(5, "a", url="https://example.com/list?page=2"))
        await delivery.handoff(_handoff(session_id=None))
        # The user may have changed the page in the live view: shown again.
        await delivery.step(self._frame(6, "a", url="https://example.com/list?page=2"))

        photos = [r.artifacts[0] for r in submitted if r.outcome is NoticeOutcome.PROGRESS]
        assert [(p.url, p.caption) for p in photos] == [
            ("https://cdn.example.com/1.jpg", "Step 1 · Scrolling"),
            ("https://cdn.example.com/3.jpg", "Step 2 · Scrolling"),
            ("https://cdn.example.com/4.jpg", "Step 3 · Scrolling"),
            ("https://cdn.example.com/5.jpg", "Step 4 · Scrolling"),
            ("https://cdn.example.com/6.jpg", "Step 5 · Scrolling"),
        ]


class TestHandoffNeedsTheUser:
    async def test_a_pending_handoff_is_a_needs_you_notice_valid_until_the_handoff_times_out(
        self, delivery, submitted
    ) -> None:
        await delivery.handoff(_handoff())
        [report] = submitted
        assert report.outcome is NoticeOutcome.NEEDS_YOU
        assert report.valid_until == NOW + timedelta(
            seconds=settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS
        )

    async def test_it_says_the_ask_then_the_one_link_then_how_to_reply(
        self, delivery, submitted
    ) -> None:
        await delivery.handoff(_handoff())
        assert submitted[0].facts == [
            "Payment needed",
            f"Open the live browser: {LIVE_LINK}",
            BROWSER_HANDOFF_REPLY_PROMPT,
        ]

    async def test_the_link_is_minted_once_for_this_user_and_handoff(
        self, delivery, submitted
    ) -> None:
        with patch(
            "app.services.browser.bot_delivery.create_live_view_link",
            new=AsyncMock(return_value=LIVE_LINK),
        ) as mint:
            await delivery.handoff(_handoff())
        mint.assert_awaited_once_with("sess-1", "user-1", "h1")

    async def test_a_handoff_is_its_own_subject_so_a_later_step_cannot_supersede_it(
        self, delivery, submitted
    ) -> None:
        await delivery.step(_step())
        await delivery.handoff(_handoff())
        step, handoff = submitted
        assert handoff.subject.id != step.subject.id
        assert handoff.report_id == "browser:job-1:handoff:h1"

    async def test_a_credentials_handoff_reassures_the_login_is_saved_in_the_first_line(
        self, delivery, submitted
    ) -> None:
        await delivery.handoff(
            _handoff(
                reason="Sign in to your Reddit account to continue.",
                category=SensitiveCategory.CREDENTIALS,
                saves_login=True,
            )
        )
        first = submitted[0].facts[0]
        assert first.startswith("Sign in to your Reddit account to continue.")
        assert first.endswith(BROWSER_CREDENTIALS_SAVED_NOTE)

    async def test_a_handoff_that_saves_no_login_promises_none(self, delivery, submitted) -> None:
        await delivery.handoff(_handoff(saves_login=False))
        assert BROWSER_CREDENTIALS_SAVED_NOTE not in submitted[0].facts[0]

    async def test_a_handoff_without_a_session_has_no_link(self, delivery, submitted) -> None:
        await delivery.handoff(_handoff(session_id=None))
        assert submitted[0].facts == ["Payment needed", BROWSER_HANDOFF_REPLY_PROMPT]

    @pytest.mark.parametrize("status", [s for s in HandoffStatus if s is not HandoffStatus.PENDING])
    async def test_a_settled_handoff_says_nothing(self, delivery, submitted, status) -> None:
        await delivery.handoff(_handoff(status=status))
        assert submitted == []


_OUTCOMES = (
    (BrowserSessionStatus.COMPLETED, True, "Done."),
    (BrowserSessionStatus.COMPLETED, False, "Couldn't finish."),
    (BrowserSessionStatus.FAILED, False, "Stopped: nobody finished the step in time."),
)


class TestResultIsOnlyTheRecap:
    """The outcome is the assistant's to voice once, in the executor's report; this sends only the recap link."""

    @pytest.mark.parametrize(("status", "success", "summary"), _OUTCOMES)
    async def test_a_run_with_a_recap_submits_exactly_the_recap(
        self, delivery, submitted, status, success, summary
    ) -> None:
        await delivery.result(
            BrowserResultSnapshot(
                status=status,
                success=success,
                summary=summary,
                steps=2,
                replay_url="https://cdn.example.com/replay",
            )
        )
        [report] = submitted
        assert report.outcome is NoticeOutcome.INFO
        assert report.facts == ["Here's a recap of the run: https://cdn.example.com/replay"]

    @pytest.mark.parametrize(("status", "success", "summary"), _OUTCOMES)
    async def test_a_run_without_a_recap_submits_nothing(
        self, delivery, submitted, status, success, summary
    ) -> None:
        await delivery.result(
            BrowserResultSnapshot(status=status, success=success, summary=summary, steps=2)
        )
        assert submitted == []


class TestNote:
    async def test_a_plain_line_is_progress_of_the_run(self, delivery, submitted) -> None:
        await delivery.note("Still waiting on the page to load.")
        [report] = submitted
        assert report.outcome is NoticeOutcome.PROGRESS
        assert report.facts == ["Still waiting on the page to load."]

    async def test_an_outbox_that_cannot_take_it_raises_to_the_caller(self, delivery) -> None:
        """The job runner's mirror logs the failure and goes on; the producer never hides it."""
        with (
            patch(SUBMIT, AsyncMock(side_effect=ConnectionError("redis down"))),
            pytest.raises(ConnectionError),
        ):
            await delivery.note("x")
