"""Tests for bot progress delivery — session/step/handoff/result and helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.constants.browser import HandoffStatus, SensitiveCategory
from app.models.chat_models import ConversationSource
from app.schemas.browser import (
    BrowserAction,
    BrowserHandoffSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
)
from app.services.browser import bot_delivery as bot_delivery_mod
from app.services.browser.bot_delivery import (
    BotProgressDelivery,
    _is_blank_tab,
    _step_caption,
)
from app.services.outbound_delivery import OutboundResult
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit


@pytest.fixture
def delivery():
    return BotProgressDelivery(
        platform=ConversationSource.TELEGRAM,
        user_id="user-1",
        stream_screenshots=True,
    )


@pytest.fixture
def delivery_no_screenshots():
    return BotProgressDelivery(
        platform=ConversationSource.TELEGRAM,
        user_id="user-1",
        stream_screenshots=False,
    )


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


class TestBotProgressDeliverySession:
    async def test_session_is_silent_link_comes_at_handoff(self, delivery):
        snapshot = BrowserSessionSnapshot(
            task="do thing",
            status="running",
            session_id="sess-1",
        )
        with (
            patch(
                "app.services.browser.bot_delivery.create_live_view_link",
                new=AsyncMock(),
            ) as mock_link,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message",
                new=AsyncMock(),
            ) as mock_pub,
        ):
            await delivery.session(snapshot)
            mock_link.assert_not_awaited()
            mock_pub.assert_not_awaited()

    async def test_no_session_id_does_nothing(self, delivery):
        snapshot = BrowserSessionSnapshot(task="t", status="running", session_id=None)
        with (
            patch(
                "app.services.browser.bot_delivery.create_live_view_link", new=AsyncMock()
            ) as mock_link,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mock_pub,
        ):
            await delivery.session(snapshot)
            mock_link.assert_not_awaited()
            mock_pub.assert_not_awaited()

    async def test_empty_session_id_does_nothing(self, delivery):
        snapshot = BrowserSessionSnapshot(task="t", status="running", session_id="")
        with (
            patch("app.services.browser.bot_delivery.create_live_view_link", new=AsyncMock()) as ml,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mp,
        ):
            await delivery.session(snapshot)
            ml.assert_not_awaited()
            mp.assert_not_awaited()


class TestBotProgressDeliveryStep:
    async def test_blank_tab_sends_label_as_text_not_photo(self, delivery):
        snap = BrowserStepSnapshot(
            index=1, goal="Open", url="about:blank", screenshot="https://cdn/1.png"
        )
        with (
            patch(
                "app.services.browser.bot_delivery.publish_outbound_photo", new=AsyncMock()
            ) as mp,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mm,
        ):
            await delivery.step(snap)
            mp.assert_not_awaited()
            mm.assert_awaited_once()
            assert mm.call_args[0][2] == ["Step 1 · Open"]

    async def test_blank_tab_label_text(self, delivery):
        snap = BrowserStepSnapshot(index=1, goal="Open", url=None, screenshot="https://cdn/1.png")
        with (
            patch(
                "app.services.browser.bot_delivery.publish_outbound_photo", new=AsyncMock()
            ) as mp,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mm,
        ):
            await delivery.step(snap)
            mp.assert_not_awaited()
            mm.assert_awaited_once()
            assert mm.call_args[0][2] == ["Step 1 · Open"]

    async def test_photo_sent_when_eligible(self, delivery):
        snap = BrowserStepSnapshot(
            index=2,
            goal="Clicking",
            url="https://example.com",
            screenshot="https://cdn.example.com/shot.png",
        )
        with (
            patch(
                "app.services.browser.bot_delivery.publish_outbound_photo",
                new=AsyncMock(return_value=True),
            ) as mock_photo,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mock_text,
        ):
            await delivery.step(snap)
            mock_photo.assert_awaited_once_with(
                ConversationSource.TELEGRAM,
                "user-1",
                "https://cdn.example.com/shot.png",
                filename="browser-step-1.png",
                caption="Step 1 · Clicking",
            )
            mock_text.assert_not_awaited()

    async def test_photo_fallback_to_text_when_not_sent(self, delivery):
        snap = BrowserStepSnapshot(
            index=2, goal="Clicking", url="https://example.com", screenshot="https://cdn/shot.png"
        )
        with (
            patch(
                "app.services.browser.bot_delivery.publish_outbound_photo",
                new=AsyncMock(return_value=False),
            ) as mock_photo,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mock_text,
        ):
            await delivery.step(snap)
            mock_photo.assert_awaited_once()
            mock_text.assert_awaited_once()
            text_msg = mock_text.call_args[0][2][0]
            assert text_msg == "Step 1 · Clicking"

    async def test_inline_data_url_falls_back_to_text(self, delivery):
        snap = BrowserStepSnapshot(
            index=1, goal="Open", url="https://example.com", screenshot="data:image/png;base64,abc"
        )
        with (
            patch(
                "app.services.browser.bot_delivery.publish_outbound_photo", new=AsyncMock()
            ) as mp,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mm,
        ):
            await delivery.step(snap)
            mp.assert_not_awaited()
            mm.assert_awaited_once()
            assert mm.call_args[0][2][0] == "Step 1 · Open"

    async def test_long_goal_photo_caption_is_whole(self, delivery):
        goal = 'Typing "hi sent using gaia browser use from telegram" into the post composer box on the x.com homepage timeline view area near the very top of the main feed column on the left hand side'
        snap = BrowserStepSnapshot(
            index=2, goal=goal, url="https://x.com/compose", screenshot="https://cdn/shot.png"
        )
        with (
            patch(
                "app.services.browser.bot_delivery.publish_outbound_photo",
                new=AsyncMock(return_value=True),
            ) as mock_photo,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mm,
        ):
            await delivery.step(snap)
            mock_photo.assert_awaited_once()
            mm.assert_not_awaited()
            assert mock_photo.call_args.kwargs["caption"] == f"Step 1 · {goal}"

    async def test_long_goal_text_fallback_is_whole(self, delivery):
        goal = 'Typing "hi sent using gaia browser use from telegram" into the post composer box on the x.com homepage timeline view area near the very top of the main feed column on the left hand side'
        snap = BrowserStepSnapshot(
            index=2, goal=goal, url="https://x.com/compose", screenshot="https://cdn/shot.png"
        )
        with (
            patch(
                "app.services.browser.bot_delivery.publish_outbound_photo",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mm,
        ):
            await delivery.step(snap)
            mm.assert_awaited_once()
            assert mm.call_args[0][2][0] == f"Step 1 · {goal}"

    async def test_no_screenshot_falls_back_to_text(self, delivery):
        snap = BrowserStepSnapshot(index=1, goal="Open", url="https://example.com", screenshot=None)
        with (
            patch(
                "app.services.browser.bot_delivery.publish_outbound_photo", new=AsyncMock()
            ) as mp,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mm,
        ):
            await delivery.step(snap)
            mp.assert_not_awaited()
            mm.assert_awaited_once()
            assert mm.call_args[0][2][0] == "Step 1 · Open"

    async def test_empty_goal_uses_snapshot_actions_for_caption(self, delivery):
        """goal="" must still caption from the snapshot's own actions, not an empty list."""
        snap = BrowserStepSnapshot(
            index=1,
            goal="",
            actions=[BrowserAction(name="click")],
            url="https://example.com",
            screenshot=None,
        )
        with (
            patch(
                "app.services.browser.bot_delivery.publish_outbound_photo", new=AsyncMock()
            ) as mp,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mm,
        ):
            await delivery.step(snap)
            mp.assert_not_awaited()
            mm.assert_awaited_once_with(
                ConversationSource.TELEGRAM, "user-1", ["Step 1 · Clicking"]
            )

    async def test_stream_screenshots_disabled_always_text(self, delivery_no_screenshots):
        snap = BrowserStepSnapshot(
            index=1, goal="Open", url="https://example.com", screenshot="https://cdn/shot.png"
        )
        with (
            patch(
                "app.services.browser.bot_delivery.publish_outbound_photo", new=AsyncMock()
            ) as mp,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mm,
        ):
            await delivery_no_screenshots.step(snap)
            mp.assert_not_awaited()
            mm.assert_awaited_once()
            assert mm.call_args[0][2][0] == "Step 1 · Open"

    async def test_chrome_newtab_label_text(self, delivery):
        snap = BrowserStepSnapshot(
            index=1, goal="Open", url="chrome://newtab/", screenshot="https://cdn/shot.png"
        )
        with (
            patch(
                "app.services.browser.bot_delivery.publish_outbound_photo", new=AsyncMock()
            ) as mp,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mm,
        ):
            await delivery.step(snap)
            mp.assert_not_awaited()
            mm.assert_awaited_once()
            assert mm.call_args[0][2] == ["Step 1 · Open"]


class TestBotProgressDeliveryHandoff:
    async def test_reply_hint_uses_plain_quotes_not_markdown_emphasis(self, delivery):
        """*done*/*stop* rendered as literal <i>done</i> text on Telegram (no markdown parse mode on this send) -- plain quotes read correctly on every platform."""
        snap = BrowserHandoffSnapshot(
            handoff_id="h1", reason="Need creds", session_id=None, status=HandoffStatus.PENDING
        )
        with (
            patch("app.services.browser.bot_delivery.create_live_view_link", new=AsyncMock()),
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mp,
        ):
            await delivery.handoff(snap)
            msg = mp.call_args[0][2][0]
            assert "*done*" not in msg
            assert "*stop*" not in msg
            assert "<i>" not in msg
            assert '"done"' in msg
            assert '"stop"' in msg

    async def test_pending_with_session_includes_link(self, delivery):
        snap = BrowserHandoffSnapshot(
            handoff_id="h1",
            reason="Payment needed",
            session_id="sess-1",
            status=HandoffStatus.PENDING,
        )
        with (
            patch(
                "app.services.browser.bot_delivery.create_live_view_link",
                new=AsyncMock(return_value="https://live.example.com/link"),
            ) as mock_link,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mock_pub,
        ):
            await delivery.handoff(snap)
            mock_link.assert_awaited_once_with("sess-1", "user-1")
            msg = mock_pub.call_args[0][2][0]
            assert msg == (
                "Payment needed"
                "<NEW_MESSAGE_BREAK>"
                "Open the live browser: https://live.example.com/link"
                "<NEW_MESSAGE_BREAK>"
                'Reply "done" when you\'ve finished, or "stop" to cancel.'
            )

    async def test_handoff_is_one_delivery_call_with_token_bubbles(self, delivery):
        """The bot splitter turns each token block into its own bubble: ask, link and reply instruction arrive as three readable messages, still in a single delivery call."""
        from app.constants.browser import SensitiveCategory

        snap = BrowserHandoffSnapshot(
            handoff_id="h1",
            reason="Sign in to your Reddit account to continue.",
            session_id="sess-1",
            status=HandoffStatus.PENDING,
            category=SensitiveCategory.CREDENTIALS,
        )
        with (
            patch(
                "app.services.browser.bot_delivery.create_live_view_link",
                new=AsyncMock(return_value="https://live/x"),
            ),
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mp,
        ):
            await delivery.handoff(snap)
            mp.assert_awaited_once()
            text_parts = mp.call_args[0][2]
            assert len(text_parts) == 1
            assert text_parts[0].count("<NEW_MESSAGE_BREAK>") == 2

    async def test_credentials_handoff_reassures_the_login_is_saved(self, delivery):
        """A sign-in handoff tells the user the session will be saved encrypted — it is true (storage_persistence.py) and it is what makes a login worth doing once."""
        from app.constants.browser import BROWSER_CREDENTIALS_SAVED_NOTE, SensitiveCategory

        snap = BrowserHandoffSnapshot(
            handoff_id="h1",
            reason="Enter your password and click Sign in.",
            session_id="sess-1",
            status=HandoffStatus.PENDING,
            category=SensitiveCategory.CREDENTIALS,
        )
        with (
            patch(
                "app.services.browser.bot_delivery.create_live_view_link",
                new=AsyncMock(return_value="https://live/x"),
            ),
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mp,
        ):
            await delivery.handoff(snap)
            assert BROWSER_CREDENTIALS_SAVED_NOTE in mp.call_args[0][2][0]

    async def test_credentials_note_is_appended_not_substituted(self, delivery):
        """The saved-login note is an addition to the takeover request, never a replacement — a sign-in handoff that dropped the reason and the done/stop instructions would leave the user with reassurance and no idea what to do."""
        from app.constants.browser import BROWSER_CREDENTIALS_SAVED_NOTE, SensitiveCategory

        snap = BrowserHandoffSnapshot(
            handoff_id="h1",
            reason="Enter your password and click Sign in.",
            session_id="sess-1",
            status=HandoffStatus.PENDING,
            category=SensitiveCategory.CREDENTIALS,
        )
        with (
            patch(
                "app.services.browser.bot_delivery.create_live_view_link",
                new=AsyncMock(return_value="https://live/x"),
            ),
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mp,
        ):
            await delivery.handoff(snap)
            assert mp.call_args[0][2][0] == (
                "Enter your password and click Sign in.\n"
                f"{BROWSER_CREDENTIALS_SAVED_NOTE}"
                "<NEW_MESSAGE_BREAK>"
                "Open the live browser: https://live/x"
                "<NEW_MESSAGE_BREAK>"
                'Reply "done" when you\'ve finished, or "stop" to cancel.'
            )

    async def test_non_credentials_handoff_omits_the_saved_note(self, delivery):
        """A payment handoff must NOT promise to store anything — nothing is saved for a payment, so the note would be a false reassurance."""
        from app.constants.browser import BROWSER_CREDENTIALS_SAVED_NOTE, SensitiveCategory

        snap = BrowserHandoffSnapshot(
            handoff_id="h1",
            reason="Complete the payment.",
            session_id="sess-1",
            status=HandoffStatus.PENDING,
            category=SensitiveCategory.PAYMENT,
        )
        with (
            patch(
                "app.services.browser.bot_delivery.create_live_view_link",
                new=AsyncMock(return_value="https://live/x"),
            ),
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mp,
        ):
            await delivery.handoff(snap)
            assert BROWSER_CREDENTIALS_SAVED_NOTE not in mp.call_args[0][2][0]

    async def test_pending_without_session_no_link(self, delivery):
        snap = BrowserHandoffSnapshot(
            handoff_id="h1", reason="Need creds", session_id=None, status=HandoffStatus.PENDING
        )
        with (
            patch("app.services.browser.bot_delivery.create_live_view_link", new=AsyncMock()) as ml,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
            ) as mp,
        ):
            await delivery.handoff(snap)
            ml.assert_not_awaited()
            msg = mp.call_args[0][2][0]
            assert msg == (
                "Need creds"
                "<NEW_MESSAGE_BREAK>"
                'Reply "done" when you\'ve finished, or "stop" to cancel.'
            )

    async def test_non_pending_does_nothing(self, delivery):
        for status in (HandoffStatus.COMPLETED, HandoffStatus.CANCELLED, HandoffStatus.TIMEOUT):
            snap = BrowserHandoffSnapshot(
                handoff_id="h1", reason="x", session_id="s1", status=status
            )
            with (
                patch(
                    "app.services.browser.bot_delivery.create_live_view_link", new=AsyncMock()
                ) as ml,
                patch(
                    "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
                ) as mp,
            ):
                await delivery.handoff(snap)
                ml.assert_not_awaited()
                mp.assert_not_awaited()


#: One run of every outcome the result used to voice its own line for.
_OUTCOMES = (
    ("completed", True, "Posted the tweet with exactly the requested text"),
    ("failed", False, "Browser task failed: Failed to establish CDP connection"),
    ("cancelled", False, "Browser task was cancelled."),
    ("failed", False, "Stopped: nobody finished the step in the live browser in time."),
)


class TestBotProgressDeliveryResult:
    """The outcome is the assistant's to voice once; the progress channel sends only the recap link."""

    @pytest.mark.parametrize(("status", "success", "summary"), _OUTCOMES)
    async def test_a_run_with_a_recap_sends_exactly_the_recap_line(
        self, delivery, status, success, summary
    ):
        """A canned "Done"/"Stopped"/"Couldn't finish" line here made every outcome arrive twice."""
        snap = BrowserResultSnapshot(
            status=status,
            success=success,
            summary=summary,
            steps=2,
            replay_url="https://cdn.example.com/replay",
        )
        with patch(
            "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
        ) as mp:
            await delivery.result(snap)
        mp.assert_awaited_once()
        assert mp.call_args[0][2] == ["📽 Here's a recap of the run: https://cdn.example.com/replay"]

    @pytest.mark.parametrize(("status", "success", "summary"), _OUTCOMES)
    async def test_a_run_without_a_recap_sends_nothing(self, delivery, status, success, summary):
        snap = BrowserResultSnapshot(status=status, success=success, summary=summary, steps=2)
        with patch(
            "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
        ) as mp:
            await delivery.result(snap)
        mp.assert_not_awaited()


class TestOneLinkPerRun:
    async def test_the_handoff_reuses_the_link_the_run_already_sent(self, delivery):
        """Two links to one browser leaves the user guessing which tab is the real one."""
        codes = iter(["https://live.example.com/first", "https://live.example.com/second"])
        with (
            patch(
                "app.services.browser.bot_delivery.create_live_view_link",
                new=AsyncMock(side_effect=lambda *_: next(codes)),
            ) as mock_link,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message",
                new=AsyncMock(return_value="published"),
            ) as mock_pub,
        ):
            await delivery.session(
                BrowserSessionSnapshot(task="sign in", status="running", session_id="sess-1")
            )
            await delivery.handoff(
                BrowserHandoffSnapshot(
                    handoff_id="h1",
                    status=HandoffStatus.PENDING,
                    reason="Enter your password and sign in",
                    category=SensitiveCategory.CREDENTIALS,
                    session_id="sess-1",
                )
            )

        assert mock_link.await_count == 1
        sent = [call[0][2][0] for call in mock_pub.await_args_list]
        assert all("https://live.example.com/first" in message for message in sent)
        assert not any("second" in message for message in sent)


async def test_the_first_step_the_user_sees_is_step_one(delivery, monkeypatch) -> None:
    """The blank-tab navigate sends its label as text (no photo to show), so numbering still opens at Step 1."""
    sent: list[str] = []

    async def _message(platform, user_id, blocks) -> bool:
        sent.extend(blocks)
        return True

    monkeypatch.setattr(bot_delivery_mod, "publish_outbound_message", _message)
    monkeypatch.setattr(bot_delivery_mod, "publish_outbound_photo", AsyncMock(return_value=False))

    await delivery.step(BrowserStepSnapshot(index=1, goal="Opening the site", url="about:blank"))
    await delivery.step(BrowserStepSnapshot(index=2, goal="Searching", url="https://example.com"))
    await delivery.step(BrowserStepSnapshot(index=3, goal="Reading", url="https://example.com/a"))

    assert [line.split(" · ")[0] for line in sent] == ["Step 1", "Step 2", "Step 3"]


async def test_a_run_of_identical_steps_reaches_the_user_once(delivery, monkeypatch) -> None:
    """Reading a long list sent 24 photos in a row captioned "Scrolling", one a second."""
    sent: list[str] = []

    async def _message(platform, user_id, blocks) -> bool:
        sent.extend(blocks)
        return True

    monkeypatch.setattr(bot_delivery_mod, "publish_outbound_message", _message)
    monkeypatch.setattr(bot_delivery_mod, "publish_outbound_photo", AsyncMock(return_value=False))
    url = "https://example.com/list"

    await delivery.step(BrowserStepSnapshot(index=1, goal="Opening the list", url=url))
    for index in range(2, 6):
        await delivery.step(BrowserStepSnapshot(index=index, goal="Scrolling", url=url))
    await delivery.step(BrowserStepSnapshot(index=6, goal="Reading the last row", url=url))
    await delivery.step(BrowserStepSnapshot(index=7, goal="Scrolling", url=url))

    assert sent == [
        "Step 1 · Opening the list",
        "Step 2 · Scrolling",
        "Step 3 · Reading the last row",
        "Step 4 · Scrolling",
    ]


async def test_a_blank_tab_with_no_goal_is_named_by_its_action(delivery, monkeypatch) -> None:
    sent: list[str] = []

    async def _message(platform, user_id, blocks) -> OutboundResult:
        sent.extend(blocks)
        return OutboundResult.PUBLISHED

    monkeypatch.setattr(bot_delivery_mod, "publish_outbound_message", _message)

    await delivery.step(
        BrowserStepSnapshot(
            index=1,
            goal="",
            url="about:blank",
            actions=[BrowserAction(name="navigate", inputs={"url": "https://www.example.com/a"})],
        )
    )

    assert sent == ["Step 1 · Opening example.com"]


async def test_a_blank_tab_opened_mid_run_continues_the_numbering(delivery, monkeypatch) -> None:
    sent: list[str] = []

    async def _message(platform, user_id, blocks) -> OutboundResult:
        sent.extend(blocks)
        return OutboundResult.PUBLISHED

    monkeypatch.setattr(bot_delivery_mod, "publish_outbound_message", _message)
    monkeypatch.setattr(bot_delivery_mod, "publish_outbound_photo", AsyncMock(return_value=False))

    await delivery.step(BrowserStepSnapshot(index=1, goal="Searching", url="https://example.com"))
    await delivery.step(BrowserStepSnapshot(index=2, goal="Opening a new tab", url="about:blank"))

    assert sent == ["Step 1 · Searching", "Step 2 · Opening a new tab"]


@pytest.mark.parametrize("outcome", [OutboundResult.SKIPPED, OutboundResult.FAILED])
async def test_a_message_the_bot_never_got_is_a_warning_naming_who_missed_it(
    delivery, monkeypatch, outcome
) -> None:
    monkeypatch.setattr(
        bot_delivery_mod, "publish_outbound_message", AsyncMock(return_value=outcome)
    )

    async with captured_wide_event() as event:
        await delivery.note("Step 1 · Searching")

    [warning] = event["warnings"]
    assert "not sent to the bot" in warning["msg"]
    assert warning["outbound_result"] is outcome
    assert warning["platform"] == ConversationSource.TELEGRAM
    assert warning["user_id"] == "user-1"


async def test_a_delivered_message_raises_no_warning(delivery, monkeypatch) -> None:
    monkeypatch.setattr(
        bot_delivery_mod,
        "publish_outbound_message",
        AsyncMock(return_value=OutboundResult.PUBLISHED),
    )

    async with captured_wide_event() as event:
        await delivery.note("Step 1 · Searching")

    assert "warnings" not in event
