"""Link completion's side effects: whatever GAIA says after a link goes through the outbox.

A one-tap onboarding link hands over its first contact; any other new link gets the connected confirmation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.chat_models import ConversationSource
from app.models.platform_models import PlatformLinkResult
from app.services.outbox.models import NoticeReport, ProducerKind, SubjectKind
from app.services.outbox.prerendered import PrerenderedKind
from app.services.platform_link_completion import (
    PostLinkSideEffectError,
    complete_platform_link,
)
from app.services.platform_link_service import AccountHasDifferentPlatformError
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import IntegrationConnected

pytestmark = pytest.mark.usefixtures("onboarding_finish_on_link")

MODULE = "app.services.platform_link_completion"
USER_ID = "507f1f77bcf86cd799439011"
BUBBLES = ["Hey Aryan, I'm with you on WhatsApp now.", "Tell me one thing off your plate."]
CONNECTED_AT = "2026-09-08T00:00:00Z"


def _linked(is_new_link: bool = True, platform: str = "whatsapp") -> PlatformLinkResult:
    return PlatformLinkResult(
        status="linked",
        platform=platform,
        platform_user_id="wa-1",
        connected_at=CONNECTED_AT,
        is_new_link=is_new_link,
    )


def _only_report(submit: AsyncMock) -> NoticeReport:
    submit.assert_awaited_once()
    report = submit.await_args.args[0]
    assert isinstance(report, NoticeReport)
    return report


@pytest.fixture
def side_effects():
    submit = AsyncMock()
    link = AsyncMock(return_value=_linked())
    with (
        patch(f"{MODULE}.PlatformLinkService.link_account", link),
        patch(f"{MODULE}.submit", submit),
        patch(f"{MODULE}.schedule_account_sync", MagicMock()),
        patch(f"{MODULE}.capture", MagicMock()),
    ):
        yield submit, link


class TestPostLinkMessage:
    async def test_a_new_link_without_a_first_contact_gets_the_connected_confirmation(
        self, side_effects
    ) -> None:
        submit, _ = side_effects
        await complete_platform_link(USER_ID, "whatsapp", "wa-1")
        report = _only_report(submit)
        assert report.prerendered is not None
        assert (report.prerendered.kind, report.prerendered.platform) == (
            PrerenderedKind.ACCOUNT_LINKED,
            "WhatsApp",
        )
        assert (report.producer, report.subject.kind) == (ProducerKind.ACCOUNT, SubjectKind.ACCOUNT)

    async def test_the_message_is_pinned_to_the_chat_app_just_linked(self, side_effects) -> None:
        """The user is on the web when they link: without the pin the router would answer them in the app."""
        submit, _ = side_effects
        await complete_platform_link(USER_ID, "whatsapp", "wa-1")
        assert _only_report(submit).delivery_policy.channel is ConversationSource.WHATSAPP

    async def test_a_repeat_link_without_a_first_contact_says_nothing(self, side_effects) -> None:
        submit, link = side_effects
        link.return_value = _linked(is_new_link=False)
        await complete_platform_link(USER_ID, "whatsapp", "wa-1")
        submit.assert_not_awaited()

    async def test_a_platform_with_no_outbound_queue_is_not_told(self, side_effects) -> None:
        submit, link = side_effects
        link.return_value = _linked(platform="web")
        await complete_platform_link(USER_ID, "web", "w-1")
        submit.assert_not_awaited()

    async def test_a_first_contact_goes_to_the_outbox_instead_of_the_confirmation(
        self, side_effects
    ) -> None:
        submit, _ = side_effects
        result = await complete_platform_link(USER_ID, "whatsapp", "wa-1", first_contact=BUBBLES)
        report = _only_report(submit)
        assert report.prerendered is not None
        assert (report.prerendered.kind, report.prerendered.bubbles) == (
            PrerenderedKind.FIRST_CONTACT,
            BUBBLES,
        )
        assert result.first_contact_delivered is True

    async def test_each_occurrence_of_a_link_is_its_own_report(self, side_effects) -> None:
        """A relink is a new fact: the outbox's dedupe must not swallow its greeting."""
        submit, _ = side_effects
        await complete_platform_link(USER_ID, "whatsapp", "wa-1")
        assert _only_report(submit).report_id == f"account_linked:whatsapp:{CONNECTED_AT}"

    async def test_a_link_with_nothing_to_say_reports_first_contact_as_delivered(
        self, side_effects
    ) -> None:
        """No first contact means nothing failed to arrive; a False here would make the caller resend it."""
        result = await complete_platform_link(USER_ID, "whatsapp", "wa-1")
        assert result.first_contact_delivered is True

    async def test_a_first_contact_is_sent_even_when_the_link_already_existed(
        self, side_effects
    ) -> None:
        """Tapping the link twice still answers the tap."""
        submit, link = side_effects
        link.return_value = _linked(is_new_link=False)
        await complete_platform_link(USER_ID, "whatsapp", "wa-1", first_contact=BUBBLES)
        submit.assert_awaited_once()

    async def test_a_first_contact_with_no_queue_to_carry_it_is_handed_back_loudly_and_keeps_the_link(
        self, side_effects
    ) -> None:
        submit, link = side_effects
        link.return_value = _linked(platform="web")
        with patch(f"{MODULE}.log") as mock_log:
            result = await complete_platform_link(USER_ID, "web", "w-1", first_contact=BUBBLES)
        assert result.link.is_new_link is True
        assert result.first_contact_delivered is False
        submit.assert_not_awaited()
        mock_log.warning.assert_called_once_with(
            "first contact has no outbound queue after a one-tap link",
            platform="web",
            user_id=USER_ID,
        )


class TestPostCommitFailures:
    """A failure after the link is written is a different animal from a refusal.

    The link exists; a caller holding a single-use credential must spend it
    rather than hand it back, or the retry re-runs the greeting against a link
    that is already there. Reported, never swallowed.
    """

    async def test_a_broken_first_contact_submit_says_the_link_was_already_written(
        self, side_effects
    ) -> None:
        submit, _ = side_effects
        broker_down = RuntimeError("could not resolve the outbound destination")
        submit.side_effect = broker_down

        # The message is the only place the platform and the underlying failure
        # reach the operator: the caller re-raises it as-is.
        with pytest.raises(
            PostLinkSideEffectError,
            match="the whatsapp link was written but its follow-through failed: "
            "could not resolve the outbound destination",
        ) as excinfo:
            await complete_platform_link(USER_ID, "whatsapp", "wa-1", first_contact=BUBBLES)

        assert excinfo.value.__cause__ is broker_down

    async def test_a_refused_link_is_not_dressed_as_a_post_commit_failure(
        self, side_effects
    ) -> None:
        """Nothing was written, so the caller's credential is still good."""
        _, link = side_effects
        link.side_effect = AccountHasDifferentPlatformError("already has a different account")

        with pytest.raises(AppError) as excinfo:
            await complete_platform_link(USER_ID, "whatsapp", "wa-2")

        assert not isinstance(excinfo.value, PostLinkSideEffectError)


class TestLinkAnalytics:
    """integration_connected counts connections, not taps."""

    async def test_a_new_link_is_captured_once(self, side_effects) -> None:
        with patch(f"{MODULE}.capture") as capture:
            await complete_platform_link(USER_ID, "whatsapp", "wa-1")
        capture.assert_called_once_with(
            UserId(USER_ID), IntegrationConnected(integration_id="whatsapp", is_new_link=True)
        )

    async def test_a_repeat_link_is_not_captured_again(self, side_effects) -> None:
        """A re-link used to count as a fresh integration_connected, inflating the connection count with every tap."""
        _, link = side_effects
        link.return_value = _linked(is_new_link=False)
        with patch(f"{MODULE}.capture") as capture:
            await complete_platform_link(USER_ID, "whatsapp", "wa-1")
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
        _, link = side_effects
        conflict = AccountHasDifferentPlatformError(
            "Your account already has a different whatsapp account linked"
        )
        link.side_effect = conflict

        with patch(f"{MODULE}.log") as mock_log, pytest.raises(AppError) as excinfo:
            await complete_platform_link(USER_ID, "whatsapp", "wa-2")

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
            actor=USER_ID,
            resource="wa-2",
            provider="whatsapp",
            error_type="AccountHasDifferentPlatformError",
            error="Your account already has a different whatsapp account linked",
        )


class TestOnboardingFinishesWithTheLink:
    """A user who taps Start in Telegram and never returns to the web tab still finishes onboarding."""

    async def test_a_new_link_finishes_onboarding_for_its_user(
        self, side_effects, onboarding_finish_on_link: AsyncMock
    ) -> None:
        await complete_platform_link(USER_ID, "whatsapp", "wa-1")
        onboarding_finish_on_link.assert_awaited_once_with(USER_ID)

    async def test_a_repeat_link_does_not(
        self, side_effects, onboarding_finish_on_link: AsyncMock
    ) -> None:
        _, link = side_effects
        link.return_value = _linked(is_new_link=False)
        await complete_platform_link(USER_ID, "whatsapp", "wa-1")
        onboarding_finish_on_link.assert_not_awaited()

    async def test_a_failed_finish_is_a_follow_through_failure(
        self, side_effects, onboarding_finish_on_link: AsyncMock
    ) -> None:
        """The link is already written, so the caller must spend its single-use credential."""
        onboarding_finish_on_link.side_effect = RuntimeError("mongo down")
        with pytest.raises(PostLinkSideEffectError):
            await complete_platform_link(USER_ID, "whatsapp", "wa-1")
