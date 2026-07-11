"""Unit tests for platform email senders (app/services/email).

Tests cover:
- Async email functions: send_welcome_email, add_marketing_contact, send_inactive_user_email
"""

from unittest.mock import patch

import pytest

from app.services.email import (
    add_marketing_contact,
    send_inactive_user_email,
    send_welcome_email,
)

SENDERS = "app.services.email.senders"
RESEND_PROVIDER = "app.services.email.providers.resend_provider"

# ===========================================================================
# Async: send_welcome_email
# ===========================================================================


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestSendInactiveUserEmail:
    # Throttle policy lives in the check_inactive_users worker task, not here —
    # see tests/unit/workers/test_user_tasks.py.

    @patch(f"{SENDERS}.send_email")
    @patch(f"{SENDERS}.render_email_template", return_value="<h1>Miss you</h1>")
    async def test_success(self, mock_render, mock_send):
        await send_inactive_user_email("user@example.com", "Alice")

        assert mock_render.call_args[0][0] == "inactive.html"
        assert mock_render.call_args[1]["user_name"] == "Alice"
        mock_send.assert_awaited_once()
        message = mock_send.call_args[0][0]
        assert message.to == ["user@example.com"]
        assert message.html == "<h1>Miss you</h1>"

    @patch(f"{SENDERS}.send_email", side_effect=Exception("send failed"))
    @patch(f"{SENDERS}.render_email_template", return_value="<h1>ok</h1>")
    async def test_propagates_exception(self, mock_render, mock_send):
        with pytest.raises(Exception, match="send failed"):
            await send_inactive_user_email("user@example.com")
