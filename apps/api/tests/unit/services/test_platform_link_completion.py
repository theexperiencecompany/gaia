"""Link completion's side effects: whatever GAIA says after a link is sent from here.

A one-tap onboarding link hands over its composed first contact; any other new link gets the generic connected text.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.outbound import OUTBOUND_TTL_SECONDS_GREETING
from app.models.chat_models import ConversationSource
from app.models.platform_models import PlatformLinkResult
from app.services.analytics_service import AnalyticsEvents
from app.services.outbound_delivery import OutboundResult
from app.services.platform_link_completion import (
    PostLinkSideEffectError,
    complete_platform_link,
)
from app.services.platform_link_service import AccountHasDifferentPlatformError
from app.utils.errors import AppError

MODULE = "app.services.platform_link_completion"
BUBBLES = ["Hey Aryan, I'm with you on WhatsApp now.", "Tell me one thing off your plate."]


def _linked(is_new_link: bool = True) -> PlatformLinkResult:
    return PlatformLinkResult(
        status="linked",
        platform="whatsapp",
        platform_user_id="wa-1",
        connected_at="2026-09-08T00:00:00Z",
        is_new_link=is_new_link,
    )


@pytest.fixture
def side_effects():
    notify = AsyncMock()
    publish = AsyncMock(return_value=OutboundResult.PUBLISHED)
    link = AsyncMock(return_value=_linked())
    with (
        patch(f"{MODULE}.PlatformLinkService.link_account", link),
        patch(f"{MODULE}.notify_account_linked", notify),
        patch(f"{MODULE}.publish_outbound_message", publish),
        patch(f"{MODULE}.schedule_account_sync", MagicMock()),
        patch(f"{MODULE}.capture_event", MagicMock()),
    ):
        yield notify, publish, link


class TestPostLinkMessage:
    async def test_a_new_link_without_a_first_contact_gets_the_generic_text(
        self, side_effects
    ) -> None:
        notify, publish, _ = side_effects
        await complete_platform_link("u1", "whatsapp", "wa-1")
        notify.assert_awaited_once_with("whatsapp", "u1")
        publish.assert_not_awaited()

    async def test_a_repeat_link_without_a_first_contact_says_nothing(self, side_effects) -> None:
        notify, publish, link = side_effects
        link.return_value = _linked(is_new_link=False)
        await complete_platform_link("u1", "whatsapp", "wa-1")
        notify.assert_not_awaited()
        publish.assert_not_awaited()

    async def test_a_first_contact_is_delivered_on_the_outbound_queue_instead(
        self, side_effects
    ) -> None:
        notify, publish, _ = side_effects
        result = await complete_platform_link("u1", "whatsapp", "wa-1", first_contact=BUBBLES)
        publish.assert_awaited_once_with(
            ConversationSource.WHATSAPP, "u1", BUBBLES, ttl_seconds=OUTBOUND_TTL_SECONDS_GREETING
        )
        notify.assert_not_awaited()
        # Reported back as delivered: the caller has the bot resend otherwise.
        assert result.first_contact_delivered is True

    async def test_a_link_with_nothing_to_say_reports_first_contact_as_delivered(
        self, side_effects
    ) -> None:
        """No first contact means nothing failed to arrive; a False here would make the caller resend it."""
        result = await complete_platform_link("u1", "whatsapp", "wa-1")
        assert result.first_contact_delivered is True

    async def test_a_first_contact_is_delivered_even_when_the_link_already_existed(
        self, side_effects
    ) -> None:
        """Tapping the link twice still answers the tap."""
        _, publish, link = side_effects
        link.return_value = _linked(is_new_link=False)
        await complete_platform_link("u1", "whatsapp", "wa-1", first_contact=BUBBLES)
        publish.assert_awaited_once()

    async def test_an_undelivered_first_contact_is_logged_loudly_but_keeps_the_link(
        self, side_effects
    ) -> None:
        _, publish, _ = side_effects
        publish.return_value = OutboundResult.FAILED
        with patch(f"{MODULE}.log") as mock_log:
            result = await complete_platform_link("u1", "whatsapp", "wa-1", first_contact=BUBBLES)
        assert result.link.is_new_link is True
        assert result.first_contact_delivered is False
        mock_log.warning.assert_called_once_with(
            "first contact was not delivered after a one-tap link",
            platform="whatsapp",
            user_id="u1",
            outcome="failed",
        )


class TestPostCommitFailures:
    """A failure after the link is written is a different animal from a refusal.

    The link exists; a caller holding a single-use credential must spend it
    rather than hand it back, or the retry re-runs the greeting against a link
    that is already there. Reported, never swallowed.
    """

    async def test_a_broken_first_contact_publish_says_the_link_was_already_written(
        self, side_effects
    ) -> None:
        _, publish, _ = side_effects
        broker_down = RuntimeError("could not resolve the outbound destination")
        publish.side_effect = broker_down

        # The message is the only place the platform and the underlying failure
        # reach the operator: the caller re-raises it as-is.
        with pytest.raises(
            PostLinkSideEffectError,
            match="the whatsapp link was written but its follow-through failed: "
            "could not resolve the outbound destination",
        ) as excinfo:
            await complete_platform_link("u1", "whatsapp", "wa-1", first_contact=BUBBLES)

        assert excinfo.value.__cause__ is broker_down

    async def test_a_refused_link_is_not_dressed_as_a_post_commit_failure(
        self, side_effects
    ) -> None:
        """Nothing was written, so the caller's credential is still good."""
        _, _, link = side_effects
        link.side_effect = AccountHasDifferentPlatformError("already has a different account")

        with pytest.raises(AppError) as excinfo:
            await complete_platform_link("u1", "whatsapp", "wa-2")

        assert not isinstance(excinfo.value, PostLinkSideEffectError)


class TestLinkAnalytics:
    """integration_connected counts connections, not taps."""

    async def test_a_new_link_is_captured_once(self, side_effects) -> None:
        with patch(f"{MODULE}.capture_event") as capture:
            await complete_platform_link("u1", "whatsapp", "wa-1")
        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": "whatsapp", "is_new_link": True},
        )

    async def test_a_repeat_link_is_not_captured_again(self, side_effects) -> None:
        """A re-link used to count as a fresh integration_connected, inflating the connection count with every tap."""
        _, _, link = side_effects
        link.return_value = _linked(is_new_link=False)
        with patch(f"{MODULE}.capture_event") as capture:
            await complete_platform_link("u1", "whatsapp", "wa-1")
        capture.assert_not_called()


class TestLinkConflicts:
    """The two 409s are not interchangeable.

    PlatformAccountTakenError is proved end to end through the route in
    tests/unit/api/test_platform_links_endpoint.py::test_link_conflict; this
    is its sibling, where the conflict is on the GAIA side and the fix is the
    opposite one. The bots pick the message they show from code alone
    (libs/shared/ts/src/bots/link-codes.ts::classifyLinkFailure), so the
    exact body is a cross-language contract, not a message anyone may reword.
    """

    async def test_a_second_account_on_the_same_platform_names_the_conflict_the_user_owns(
        self, side_effects
    ) -> None:
        _, _, link = side_effects
        conflict = AccountHasDifferentPlatformError(
            "Your account already has a different whatsapp account linked"
        )
        link.side_effect = conflict

        with patch(f"{MODULE}.log") as mock_log, pytest.raises(AppError) as excinfo:
            await complete_platform_link("u1", "whatsapp", "wa-2")

        error = excinfo.value
        assert error.status_code == 409
        assert error.to_dict() == {
            "message": "Your account already has a different whatsapp account linked",
            "why": "this GAIA account already has a different account on this platform",
            "fix": "disconnect the one you already have in settings, then link this one",
            # Not "platform_account_taken": telling this person to free the
            # account on the other GAIA account sends them after one that does
            # not exist.
            "code": "account_has_other_platform_account",
        }
        assert error.__cause__ is conflict
        # The audit line has to say WHICH conflict fired; both 409s share this
        # call site, and a bare ValueError name cannot tell them apart.
        mock_log.audit.assert_called_once_with(
            "platform account link rejected",
            actor="u1",
            resource="wa-2",
            provider="whatsapp",
            error_type="AccountHasDifferentPlatformError",
            error="Your account already has a different whatsapp account linked",
        )
