"""Unit tests for platform email senders (app/services/email).

Tests cover:
- Async email functions: send_welcome_email, add_marketing_contact, send_inactive_user_email
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.rate_limits import derive_pro_benefits, get_feature_info
from app.config.settings import settings
from app.constants.email import CONTACT_EMAIL, FOUNDER_SENDER
from app.services.email import (
    add_marketing_contact,
    send_inactive_user_email,
    send_welcome_email,
)
from app.services.email.senders import (
    LIMIT_EMAIL_WINDOW,
    send_limit_reached_email,
    send_workflows_paused_email,
)

SENDERS = "app.services.email.senders"
RESEND_PROVIDER = "app.services.email.providers.resend_provider"

# ===========================================================================
# Async: send_welcome_email
# ===========================================================================


class TestSendWelcomeEmail:
    @patch(f"{SENDERS}.send_email")
    @patch(f"{SENDERS}.render_email_template", return_value="<h1>Welcome</h1>")
    async def test_success(self, mock_render, mock_send):
        await send_welcome_email("user@example.com", "Alice")

        assert mock_render.call_args[0][0] == "welcome.html"
        assert mock_render.call_args[1]["user_name"] == "Alice"
        mock_send.assert_awaited_once()
        message = mock_send.call_args[0][0]
        assert message.to == ["user@example.com"]
        assert message.subject == "From the founder of GAIA, personally"
        assert message.html == "<h1>Welcome</h1>"

    @patch(f"{SENDERS}.send_email", side_effect=Exception("API error"))
    @patch(f"{SENDERS}.render_email_template", return_value="<h1>ok</h1>")
    async def test_propagates_send_exception(self, mock_render, mock_send):
        with pytest.raises(Exception, match="API error"):
            await send_welcome_email("user@example.com")

    @patch(f"{SENDERS}.send_email")
    @patch(f"{SENDERS}.render_email_template", return_value="<h1>Hi</h1>")
    async def test_no_name_passed_through(self, mock_render, mock_send):
        await send_welcome_email("user@example.com")
        assert mock_render.call_args[1]["user_name"] is None


# ===========================================================================
# Async: add_marketing_contact
# ===========================================================================


class TestAddMarketingContact:
    # add_contact exits early when RESEND_AUDIENCE_ID is empty (not configured).
    # All tests must patch settings so the guard passes and the real logic runs.

    @patch(f"{RESEND_PROVIDER}.settings")
    @patch(f"{RESEND_PROVIDER}.resend.Contacts.create")
    async def test_with_full_name(self, mock_create, mock_settings):
        mock_settings.RESEND_AUDIENCE_ID = "aud-test"  # pragma: allowlist secret
        await add_marketing_contact("alice@example.com", "Alice Smith")

        mock_create.assert_called_once()
        params = mock_create.call_args[0][0]
        assert params["email"] == "alice@example.com"
        assert params["first_name"] == "Alice"
        assert params["last_name"] == "Smith"
        assert params["unsubscribed"] is False

    @patch(f"{RESEND_PROVIDER}.settings")
    @patch(f"{RESEND_PROVIDER}.resend.Contacts.create")
    async def test_without_name(self, mock_create, mock_settings):
        mock_settings.RESEND_AUDIENCE_ID = "aud-test"  # pragma: allowlist secret
        await add_marketing_contact("bob@example.com")

        params = mock_create.call_args[0][0]
        assert params["first_name"] == ""
        assert params["last_name"] == ""

    @patch(f"{RESEND_PROVIDER}.settings")
    @patch(f"{RESEND_PROVIDER}.resend.Contacts.create")
    async def test_single_word_name(self, mock_create, mock_settings):
        mock_settings.RESEND_AUDIENCE_ID = "aud-test"  # pragma: allowlist secret
        await add_marketing_contact("user@example.com", "Alice")

        params = mock_create.call_args[0][0]
        assert params["first_name"] == "Alice"
        assert params["last_name"] == ""

    @patch(f"{RESEND_PROVIDER}.settings")
    @patch(f"{RESEND_PROVIDER}.resend.Contacts.create")
    async def test_three_word_name(self, mock_create, mock_settings):
        mock_settings.RESEND_AUDIENCE_ID = "aud-test"  # pragma: allowlist secret
        await add_marketing_contact("user@example.com", "Alice Marie Smith")

        params = mock_create.call_args[0][0]
        assert params["first_name"] == "Alice"
        assert params["last_name"] == "Marie Smith"

    @patch(f"{RESEND_PROVIDER}.settings")
    @patch(
        f"{RESEND_PROVIDER}.resend.Contacts.create",
        side_effect=Exception("network error"),
    )
    async def test_exception_swallowed(self, mock_create, mock_settings):
        """add_marketing_contact swallows exceptions so user creation still succeeds."""
        mock_settings.RESEND_AUDIENCE_ID = "aud-test"  # pragma: allowlist secret
        # Should NOT raise
        await add_marketing_contact("user@example.com", "Alice")

    @patch(f"{RESEND_PROVIDER}.settings")
    @patch(f"{RESEND_PROVIDER}.resend.Contacts.create")
    async def test_whitespace_name_trimmed(self, mock_create, mock_settings):
        mock_settings.RESEND_AUDIENCE_ID = "aud-test"  # pragma: allowlist secret
        await add_marketing_contact("user@example.com", "  Alice  ")

        params = mock_create.call_args[0][0]
        assert params["first_name"] == "Alice"
        assert params["last_name"] == ""

    @patch(f"{RESEND_PROVIDER}.settings")
    @patch(f"{RESEND_PROVIDER}.resend.Contacts.create")
    async def test_empty_string_name(self, mock_create, mock_settings):
        """An empty string name is falsy, so first/last should be empty."""
        mock_settings.RESEND_AUDIENCE_ID = "aud-test"  # pragma: allowlist secret
        await add_marketing_contact("user@example.com", "")

        params = mock_create.call_args[0][0]
        assert params["first_name"] == ""
        assert params["last_name"] == ""


# ===========================================================================
# Async: send_inactive_user_email
# ===========================================================================


class TestSendInactiveUserEmail:
    # Throttle policy lives in the check_inactive_users worker task, not here —
    # see tests/unit/workers/test_user_tasks.py.

    @patch(f"{SENDERS}.build_unsubscribe_headers", return_value={"List-Unsubscribe": "<url>"})
    @patch(f"{SENDERS}.build_unsubscribe_url", return_value="https://unsub")
    @patch(f"{SENDERS}.send_email")
    @patch(f"{SENDERS}.render_email_template", return_value="<h1>Miss you</h1>")
    async def test_success(self, mock_render, mock_send, mock_unsub_url, mock_unsub_headers):
        await send_inactive_user_email("user@example.com", "user-123", "Alice")

        assert mock_render.call_args[0][0] == "inactive.html"
        assert mock_render.call_args[1]["user_name"] == "Alice"
        mock_send.assert_awaited_once()
        message = mock_send.call_args[0][0]
        assert message.to == ["user@example.com"]
        assert message.html == "<h1>Miss you</h1>"
        assert message.headers == {"List-Unsubscribe": "<url>"}

    @patch(f"{SENDERS}.build_unsubscribe_headers", return_value={})
    @patch(f"{SENDERS}.build_unsubscribe_url", return_value="https://unsub")
    @patch(f"{SENDERS}.send_email", side_effect=Exception("send failed"))
    @patch(f"{SENDERS}.render_email_template", return_value="<h1>ok</h1>")
    async def test_propagates_exception(
        self, mock_render, mock_send, mock_unsub_url, mock_unsub_headers
    ):
        with pytest.raises(Exception, match="send failed"):
            await send_inactive_user_email("user@example.com", "user-123")


# ===========================================================================
# Async: send_workflows_paused_email (shares weekly dedupe with the upsell)
# ===========================================================================


def _limit_email_user(last_sent=None):
    user = MagicMock()
    user.email = "user@example.com"
    user.name = "Alice"
    user.last_limit_email_sent = last_sent
    return user


class TestSendWorkflowsPausedEmail:
    @patch(f"{SENDERS}.send_email")
    @patch(f"{SENDERS}.render_email_template", return_value="<h1>Paused</h1>")
    async def test_sends_and_records(self, mock_render, mock_send):
        with (
            patch(f"{SENDERS}.user_repository.get", new_callable=AsyncMock) as get,
            patch(
                f"{SENDERS}.user_repository.claim_limit_email_slot", new_callable=AsyncMock
            ) as claim,
        ):
            get.return_value = _limit_email_user()
            sent = await send_workflows_paused_email("user-1")

        assert sent is True
        get.assert_awaited_once_with("user-1")
        assert mock_render.call_args[0][0] == "workflows_paused.html"
        assert mock_render.call_args[1] == {
            "user_name": "Alice",
            "workflows_url": f"{settings.FRONTEND_URL}/workflows",
            "pricing_url": f"{settings.FRONTEND_URL}/pricing",
            "contact_email": CONTACT_EMAIL,
        }
        message = mock_send.call_args[0][0]
        assert message.sender == FOUNDER_SENDER
        assert message.to == ["user@example.com"]
        assert message.subject == "GAIA is taking a break until tomorrow"
        assert message.html == "<h1>Paused</h1>"
        assert message.reply_to == CONTACT_EMAIL
        claim.assert_awaited_once()

    @patch(f"{SENDERS}.send_email")
    async def test_weekly_dedupe_blocks_send(self, mock_send):
        with (
            patch(f"{SENDERS}.user_repository.get", new_callable=AsyncMock) as get,
            patch(
                f"{SENDERS}.user_repository.claim_limit_email_slot",
                new_callable=AsyncMock,
                return_value=None,  # the window is already held
            ),
        ):
            get.return_value = _limit_email_user(datetime.now(UTC) - timedelta(days=2))
            sent = await send_workflows_paused_email("user-1")

        assert sent is False
        mock_send.assert_not_called()

    @patch(f"{SENDERS}.send_email")
    async def test_dedupe_is_shared_with_upsell_email(self, mock_send):
        """One limit email of either kind per week: a recent send blocks both."""
        with (
            patch(f"{SENDERS}.user_repository.get", new_callable=AsyncMock) as get,
            patch(
                f"{SENDERS}.user_repository.claim_limit_email_slot",
                new_callable=AsyncMock,
                return_value=None,  # the window is already held
            ),
        ):
            get.return_value = _limit_email_user(datetime.now(UTC) - timedelta(days=2))
            sent = await send_limit_reached_email("user-1", "chat_messages")

        assert sent is False
        mock_send.assert_not_called()


# ===========================================================================
# Async: send_limit_reached_email
# ===========================================================================


class TestSendLimitReachedEmail:
    @patch(f"{SENDERS}.send_email")
    @patch(f"{SENDERS}.render_email_template", return_value="<h1>Upsell</h1>")
    async def test_sends_and_records(self, mock_render, mock_send):
        with (
            patch(f"{SENDERS}.user_repository.get", new_callable=AsyncMock) as get,
            patch(
                f"{SENDERS}.user_repository.claim_limit_email_slot", new_callable=AsyncMock
            ) as claim,
        ):
            get.return_value = _limit_email_user()
            sent = await send_limit_reached_email("user-1", "chat_messages")

        assert sent is True
        get.assert_awaited_once_with("user-1")
        assert mock_render.call_args[0][0] == "limit_reached.html"
        assert mock_render.call_args[1] == {
            "user_name": "Alice",
            "hit_feature_title": get_feature_info("chat_messages").title,
            "benefits": derive_pro_benefits("chat_messages"),
            "pricing_url": f"{settings.FRONTEND_URL}/pricing",
            "contact_email": CONTACT_EMAIL,
        }
        message = mock_send.call_args[0][0]
        assert message.sender == FOUNDER_SENDER
        assert message.to == ["user@example.com"]
        assert message.subject == "You hit your GAIA limit today — here's what Pro unlocks"
        assert message.html == "<h1>Upsell</h1>"
        assert message.reply_to == CONTACT_EMAIL
        claim.assert_awaited_once()


class TestTheWeeklyWindowIsClaimedNotJustRead:
    """The dedupe has to survive two limit hits landing at once.

    Reading eligibility and stamping it after the send straddled a network
    send, so both callers passed the check and the user got two emails in a
    week the copy promises will have one.
    """

    @patch(f"{SENDERS}.send_email")
    @patch(f"{SENDERS}.render_email_template", return_value="<h1>Upsell</h1>")
    async def test_the_loser_of_a_concurrent_claim_sends_nothing(
        self, _mock_render, mock_send
    ) -> None:
        # One winner, one loser — what the conditional update returns to two
        # callers racing for the same weekly slot.
        with (
            patch(f"{SENDERS}.user_repository.get", new_callable=AsyncMock) as get,
            patch(
                f"{SENDERS}.user_repository.claim_limit_email_slot",
                new_callable=AsyncMock,
                side_effect=[_limit_email_user(), None],
            ),
        ):
            get.return_value = _limit_email_user()
            first = await send_limit_reached_email("user-1", "chat_messages")
            second = await send_limit_reached_email("user-1", "chat_messages")

        assert (first, second) == (True, False)
        assert mock_send.call_count == 1

    @patch(f"{SENDERS}.send_email")
    @patch(f"{SENDERS}.render_email_template", return_value="<h1>Upsell</h1>")
    async def test_the_claim_names_the_user_and_a_window_that_has_passed(
        self, _mock_render, _mock_send
    ) -> None:
        """The claim's arguments ARE the dedupe. A stale_before in the future
        makes every user look eligible and mails them daily; the wrong id
        claims someone else's window."""
        with (
            patch(f"{SENDERS}.user_repository.get", new_callable=AsyncMock) as get,
            patch(
                f"{SENDERS}.user_repository.claim_limit_email_slot",
                new_callable=AsyncMock,
                return_value=_limit_email_user(),
            ) as claim,
        ):
            get.return_value = _limit_email_user()
            before = datetime.now(UTC)
            await send_limit_reached_email("user-1", "chat_messages")

        assert claim.await_args.args == ("user-1",)
        stale_before = claim.await_args.kwargs["stale_before"]
        # Exactly one window in the PAST, not the future.
        assert before - LIMIT_EMAIL_WINDOW - timedelta(seconds=5) <= stale_before
        assert stale_before <= datetime.now(UTC) - LIMIT_EMAIL_WINDOW

    @patch(f"{SENDERS}.render_email_template", return_value="<h1>Paused</h1>")
    async def test_the_paused_email_also_hands_its_slot_back(self, _mock_render) -> None:
        """Both senders share the window, so both must release it on failure."""
        previously = datetime.now(UTC) - timedelta(days=30)
        with (
            patch(f"{SENDERS}.user_repository.get", new_callable=AsyncMock) as get,
            patch(
                f"{SENDERS}.user_repository.claim_limit_email_slot",
                new_callable=AsyncMock,
                return_value=_limit_email_user(previously),
            ),
            patch(
                f"{SENDERS}.user_repository.release_limit_email_slot", new_callable=AsyncMock
            ) as release,
            patch(f"{SENDERS}.send_email", side_effect=RuntimeError("smtp down")),
        ):
            get.return_value = _limit_email_user(previously)
            with pytest.raises(RuntimeError):
                await send_workflows_paused_email("user-1")

        release.assert_awaited_once_with("user-1", previously)

    @patch(f"{SENDERS}.render_email_template", return_value="<h1>Upsell</h1>")
    async def test_a_failed_send_hands_the_slot_back(self, _mock_render) -> None:
        """Otherwise a failed send burns the whole week: the marker claims an
        email went out when none did, and the user hears nothing for 7 days."""
        previously = datetime.now(UTC) - timedelta(days=30)
        with (
            patch(f"{SENDERS}.user_repository.get", new_callable=AsyncMock) as get,
            patch(
                f"{SENDERS}.user_repository.claim_limit_email_slot",
                new_callable=AsyncMock,
                return_value=_limit_email_user(previously),
            ),
            patch(
                f"{SENDERS}.user_repository.release_limit_email_slot", new_callable=AsyncMock
            ) as release,
            patch(f"{SENDERS}.send_email", side_effect=RuntimeError("smtp down")),
        ):
            get.return_value = _limit_email_user(previously)
            with pytest.raises(RuntimeError):
                await send_limit_reached_email("user-1", "chat_messages")

        release.assert_awaited_once_with("user-1", previously)
