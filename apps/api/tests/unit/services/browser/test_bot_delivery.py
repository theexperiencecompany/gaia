"""Tests for bot progress delivery — session/step/handoff/result and helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.constants.browser import HandoffStatus
from app.models.chat_models import ConversationSource
from app.schemas.browser import (
    BrowserAction,
    BrowserHandoffSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
)
from app.services.browser.bot_delivery import BotProgressDelivery, _is_blank_tab, _step_caption

pytestmark = pytest.mark.unit


@pytest.fixture
def delivery():
    return BotProgressDelivery(
        platform=ConversationSource.TELEGRAM,
        user_id="user-1",
        conversation_id="conv-1",
        stream_screenshots=True,
    )


@pytest.fixture
def delivery_no_screenshots():
    return BotProgressDelivery(
        platform=ConversationSource.TELEGRAM,
        user_id="user-1",
        conversation_id="conv-1",
        stream_screenshots=False,
    )


class TestBotProgressDeliveryInit:
    def test_stores_all_constructor_args_verbatim(self):
        delivery = BotProgressDelivery(
            platform=ConversationSource.WHATSAPP,
            user_id="user-42",
            conversation_id="conv-99",
            stream_screenshots=True,
        )
        assert delivery._platform == ConversationSource.WHATSAPP
        assert delivery._user_id == "user-42"
        assert delivery._conversation_id == "conv-99"
        assert delivery._stream_screenshots is True

    def test_stream_screenshots_false_is_stored_as_false(self):
        delivery = BotProgressDelivery(
            platform=ConversationSource.TELEGRAM,
            user_id="user-1",
            conversation_id="conv-1",
            stream_screenshots=False,
        )
        assert delivery._stream_screenshots is False


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

    def test_truncates_at_90(self):
        long_goal = "A" * 100
        result = _step_caption(2, long_goal, [])
        # _CAPTION_MAX_CHARS is 90, truncated to 89 + ellipsis
        assert result.startswith("Step 2 · ")
        label = result.split(" · ", 1)[1]
        assert len(label) == 90
        assert label.endswith("…")

    def test_exactly_90_not_truncated(self):
        goal = "A" * 90
        result = _step_caption(1, goal, [])
        assert result == f"Step 1 · {goal}"

    def test_91_truncated(self):
        goal = "A" * 91
        result = _step_caption(1, goal, [])
        assert result.endswith("…")
        # label should be 90 chars
        label = result.split(" · ", 1)[1]
        assert len(label) == 90

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

    def test_truncation_rstrips_trailing_space_before_ellipsis(self):
        # 88 "A"s then a space then filler — the 90-char slice cuts right after
        # the space, so the truncated label must have it trimmed before the
        # ellipsis is appended, not "A"*88 + " …".
        goal = "A" * 88 + " " + "B" * 20
        result = _step_caption(1, goal, [])
        label = result.split(" · ", 1)[1]
        assert label == "A" * 88 + "…"
        assert len(label) == 89


class TestBotProgressDeliverySession:
    async def test_emits_live_view_link(self, delivery):
        snapshot = BrowserSessionSnapshot(
            task="do thing",
            status="running",
            session_id="sess-1",
        )
        with (
            patch(
                "app.services.browser.bot_delivery.create_live_view_link",
                new=AsyncMock(return_value="https://live.example.com/abc"),
            ) as mock_link,
            patch(
                "app.services.browser.bot_delivery.publish_outbound_message",
                new=AsyncMock(return_value="published"),
            ) as mock_pub,
        ):
            await delivery.session(snapshot)
            mock_link.assert_awaited_once_with("sess-1", "user-1")
            mock_pub.assert_awaited_once()
            args = mock_pub.call_args
            assert "https://live.example.com/abc" in args[0][2][0]

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
    async def test_blank_tab_skipped(self, delivery):
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
            mm.assert_not_awaited()

    async def test_none_url_skipped(self, delivery):
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
            mm.assert_not_awaited()

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
                filename="browser-step-2.jpg",
                caption="Step 2 · Clicking",
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
            assert text_msg == "Step 2 · Clicking"

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
        # goal="" forces the caption to fall back to the *snapshot's own*
        # actions — an arg-drop mutant that passes [] instead of
        # snapshot.actions here would silently lose the action entirely and
        # caption to "Step 1" instead of "Step 1 · Clicking".
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

    async def test_chrome_newtab_skipped(self, delivery):
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
            mm.assert_not_awaited()


class TestBotProgressDeliveryText:
    async def test_forwards_platform_user_and_message_as_single_part_list(self, delivery):
        with patch(
            "app.services.browser.bot_delivery.publish_outbound_message",
            new=AsyncMock(return_value="published"),
        ) as mp:
            await delivery._text("hello there")
            mp.assert_awaited_once_with(ConversationSource.TELEGRAM, "user-1", ["hello there"])


class TestBotProgressDeliveryHandoff:
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
                "I need you to take over for this step:\nPayment needed\n\n"
                "Reply *done* when you've finished, or *stop* to cancel."
                "\n\nOpen the live browser: https://live.example.com/link"
            )

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
                "I need you to take over for this step:\nNeed creds\n\n"
                "Reply *done* when you've finished, or *stop* to cancel."
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


class TestBotProgressDeliveryResult:
    async def test_success_message(self, delivery):
        snap = BrowserResultSnapshot(status="completed", success=True, summary="Done", steps=3)
        with patch(
            "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
        ) as mp:
            await delivery.result(snap)
            msg = mp.call_args[0][2][0]
            assert msg == "✅ Done."

    async def test_failure_message(self, delivery):
        snap = BrowserResultSnapshot(status="failed", success=False, summary="Failed", steps=2)
        with patch(
            "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
        ) as mp:
            await delivery.result(snap)
            msg = mp.call_args[0][2][0]
            assert msg == "⚠️ The browser task didn't fully complete."

    async def test_with_replay_url_appended(self, delivery):
        snap = BrowserResultSnapshot(
            status="completed",
            success=True,
            summary="Done",
            steps=1,
            replay_url="https://cdn.example.com/replay",
        )
        with patch(
            "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
        ) as mp:
            await delivery.result(snap)
            msg = mp.call_args[0][2][0]
            assert msg == (
                "✅ Done.\n\n📽 Here's a recap you can watch: https://cdn.example.com/replay"
            )

    async def test_without_replay_url_no_extra(self, delivery):
        snap = BrowserResultSnapshot(status="completed", success=True, summary="Done", steps=1)
        with patch(
            "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
        ) as mp:
            await delivery.result(snap)
            msg = mp.call_args[0][2][0]
            assert msg == "✅ Done."

    async def test_failed_with_replay_url(self, delivery):
        snap = BrowserResultSnapshot(
            status="failed",
            success=False,
            summary="Fail",
            steps=1,
            replay_url="https://cdn/replay",
        )
        with patch(
            "app.services.browser.bot_delivery.publish_outbound_message", new=AsyncMock()
        ) as mp:
            await delivery.result(snap)
            msg = mp.call_args[0][2][0]
            assert msg == (
                "⚠️ The browser task didn't fully complete."
                "\n\n📽 Here's a recap you can watch: https://cdn/replay"
            )
