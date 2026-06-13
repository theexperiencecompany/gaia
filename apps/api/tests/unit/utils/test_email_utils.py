"""Unit tests for email utility functions.

Tests cover:
- Async email functions: send_welcome_email, add_contact_to_resend, send_inactive_user_email
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.utils.email_utils import (
    add_contact_to_resend,
    send_inactive_user_email,
    send_welcome_email,
)

# ===========================================================================
# Async: send_welcome_email
# ===========================================================================


@pytest.mark.unit
class TestSendWelcomeEmail:
    @patch("app.utils.email_utils.resend.Emails.send")
    @patch(
        "app.utils.email_utils.generate_welcome_email_html",
        return_value="<h1>Welcome</h1>",
    )
    async def test_success(self, mock_gen_html, mock_send):
        await send_welcome_email("user@example.com", "Alice")

        mock_gen_html.assert_called_once_with("Alice")
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert call_args["to"] == ["user@example.com"]
        assert call_args["subject"] == "From the founder of GAIA, personally"
        assert call_args["html"] == "<h1>Welcome</h1>"

    @patch("app.utils.email_utils.resend.Emails.send")
    @patch("app.utils.email_utils.generate_welcome_email_html", return_value=None)
    async def test_raises_when_html_is_none(self, mock_gen_html, mock_send):
        with pytest.raises(ValueError, match="Failed to generate email HTML content"):
            await send_welcome_email("user@example.com")

        mock_send.assert_not_called()

    @patch("app.utils.email_utils.resend.Emails.send", side_effect=Exception("API error"))
    @patch("app.utils.email_utils.generate_welcome_email_html", return_value="<h1>ok</h1>")
    async def test_propagates_send_exception(self, mock_gen_html, mock_send):
        with pytest.raises(Exception, match="API error"):
            await send_welcome_email("user@example.com")

    @patch("app.utils.email_utils.resend.Emails.send")
    @patch("app.utils.email_utils.generate_welcome_email_html", return_value="<h1>Hi</h1>")
    async def test_no_name_passed_through(self, mock_gen_html, mock_send):
        await send_welcome_email("user@example.com")
        mock_gen_html.assert_called_once_with(None)


# ===========================================================================
# Async: add_contact_to_resend
# ===========================================================================


@pytest.mark.unit
class TestAddContactToResend:
    @patch("app.utils.email_utils.resend.Contacts.create")
    async def test_with_full_name(self, mock_create):
        await add_contact_to_resend("alice@example.com", "Alice Smith")

        mock_create.assert_called_once()
        params = mock_create.call_args[0][0]
        assert params["email"] == "alice@example.com"
        assert params["first_name"] == "Alice"
        assert params["last_name"] == "Smith"
        assert params["unsubscribed"] is False

    @patch("app.utils.email_utils.resend.Contacts.create")
    async def test_without_name(self, mock_create):
        await add_contact_to_resend("bob@example.com")

        params = mock_create.call_args[0][0]
        assert params["first_name"] == ""
        assert params["last_name"] == ""

    @patch("app.utils.email_utils.resend.Contacts.create")
    async def test_single_word_name(self, mock_create):
        await add_contact_to_resend("user@example.com", "Alice")

        params = mock_create.call_args[0][0]
        assert params["first_name"] == "Alice"
        assert params["last_name"] == ""

    @patch("app.utils.email_utils.resend.Contacts.create")
    async def test_three_word_name(self, mock_create):
        await add_contact_to_resend("user@example.com", "Alice Marie Smith")

        params = mock_create.call_args[0][0]
        assert params["first_name"] == "Alice"
        assert params["last_name"] == "Marie Smith"

    @patch(
        "app.utils.email_utils.resend.Contacts.create",
        side_effect=Exception("network error"),
    )
    async def test_exception_swallowed(self, mock_create):
        """add_contact_to_resend swallows exceptions so user creation still succeeds."""
        # Should NOT raise
        await add_contact_to_resend("user@example.com", "Alice")

    @patch("app.utils.email_utils.resend.Contacts.create")
    async def test_whitespace_name_trimmed(self, mock_create):
        await add_contact_to_resend("user@example.com", "  Alice  ")

        params = mock_create.call_args[0][0]
        assert params["first_name"] == "Alice"
        assert params["last_name"] == ""

    @patch("app.utils.email_utils.resend.Contacts.create")
    async def test_empty_string_name(self, mock_create):
        """An empty string name is falsy, so first/last should be empty."""
        await add_contact_to_resend("user@example.com", "")

        params = mock_create.call_args[0][0]
        assert params["first_name"] == ""
        assert params["last_name"] == ""


# ===========================================================================
# Async: send_inactive_user_email
# ===========================================================================


@pytest.mark.unit
class TestSendInactiveUserEmail:
    """Tests for send_inactive_user_email which has complex branching:
    - No user_id: sends directly without DB checks
    - With user_id: looks up user, checks inactivity duration, email cooldown, max emails
    """

    @patch("app.utils.email_utils.resend.Emails.send")
    @patch(
        "app.utils.email_utils.generate_inactive_user_email_html",
        return_value="<h1>Miss you</h1>",
    )
    async def test_no_user_id_sends_directly(self, mock_gen_html, mock_send):
        result = await send_inactive_user_email("user@example.com", "Alice")

        assert result is True
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert call_args["to"] == ["user@example.com"]
        mock_gen_html.assert_called_once_with("Alice")

    @patch("app.utils.email_utils.users_collection")
    @patch("app.utils.email_utils.resend.Emails.send")
    @patch(
        "app.utils.email_utils.generate_inactive_user_email_html",
        return_value="<h1>ok</h1>",
    )
    async def test_user_not_found_returns_false(self, mock_gen_html, mock_send, mock_users):
        mock_users.find_one = AsyncMock(return_value=None)

        result = await send_inactive_user_email(
            "user@example.com", "Alice", user_id="507f1f77bcf86cd799439011"
        )

        assert result is False
        mock_send.assert_not_called()

    @patch("app.utils.email_utils.users_collection")
    @patch("app.utils.email_utils.resend.Emails.send")
    @patch(
        "app.utils.email_utils.generate_inactive_user_email_html",
        return_value="<h1>ok</h1>",
    )
    async def test_less_than_7_days_inactive_returns_false(
        self, mock_gen_html, mock_send, mock_users
    ):
        """User active 3 days ago should NOT receive an inactive email."""
        now = datetime.now(UTC)
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": "507f1f77bcf86cd799439011",
                "last_active_at": now - timedelta(days=3),
                "last_inactive_email_sent": None,
            }
        )

        result = await send_inactive_user_email(
            "user@example.com", "Alice", user_id="507f1f77bcf86cd799439011"
        )

        assert result is False
        mock_send.assert_not_called()

    @patch("app.utils.email_utils.users_collection")
    @patch("app.utils.email_utils.resend.Emails.send")
    @patch(
        "app.utils.email_utils.generate_inactive_user_email_html",
        return_value="<h1>ok</h1>",
    )
    async def test_no_last_active_returns_false(self, mock_gen_html, mock_send, mock_users):
        """If user has no last_active_at field at all, skip."""
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": "507f1f77bcf86cd799439011",
                "last_inactive_email_sent": None,
            }
        )

        result = await send_inactive_user_email(
            "user@example.com", "Alice", user_id="507f1f77bcf86cd799439011"
        )

        assert result is False
        mock_send.assert_not_called()

    @patch("app.utils.email_utils.users_collection")
    @patch("app.utils.email_utils.resend.Emails.send")
    @patch(
        "app.utils.email_utils.generate_inactive_user_email_html",
        return_value="<h1>ok</h1>",
    )
    async def test_email_sent_recently_returns_false(self, mock_gen_html, mock_send, mock_users):
        """If an inactive email was sent less than 7 days ago, skip."""
        now = datetime.now(UTC)
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": "507f1f77bcf86cd799439011",
                "last_active_at": now - timedelta(days=10),
                "last_inactive_email_sent": now - timedelta(days=2),
            }
        )

        result = await send_inactive_user_email(
            "user@example.com", "Alice", user_id="507f1f77bcf86cd799439011"
        )

        assert result is False
        mock_send.assert_not_called()

    @patch("app.utils.email_utils.users_collection")
    @patch("app.utils.email_utils.resend.Emails.send")
    @patch(
        "app.utils.email_utils.generate_inactive_user_email_html",
        return_value="<h1>ok</h1>",
    )
    async def test_success_with_user_id(self, mock_gen_html, mock_send, mock_users):
        """User inactive 10 days, never emailed -> should send and update DB."""
        now = datetime.now(UTC)
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": "507f1f77bcf86cd799439011",
                "last_active_at": now - timedelta(days=10),
                "last_inactive_email_sent": None,
            }
        )
        mock_users.update_one = AsyncMock()

        result = await send_inactive_user_email(
            "user@example.com", "Alice", user_id="507f1f77bcf86cd799439011"
        )

        assert result is True
        mock_send.assert_called_once()
        mock_users.update_one.assert_called_once()

    @patch("app.utils.email_utils.users_collection")
    @patch("app.utils.email_utils.resend.Emails.send")
    @patch(
        "app.utils.email_utils.generate_inactive_user_email_html",
        return_value="<h1>ok</h1>",
    )
    async def test_max_2_emails_stops_after_14_days(self, mock_gen_html, mock_send, mock_users):
        """After 14+ days inactive with a previous email sent, stop sending."""
        now = datetime.now(UTC)
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": "507f1f77bcf86cd799439011",
                "last_active_at": now - timedelta(days=15),
                "last_inactive_email_sent": now - timedelta(days=8),
            }
        )

        result = await send_inactive_user_email(
            "user@example.com", "Alice", user_id="507f1f77bcf86cd799439011"
        )

        assert result is False
        mock_send.assert_not_called()

    @patch("app.utils.email_utils.users_collection")
    @patch("app.utils.email_utils.resend.Emails.send")
    @patch(
        "app.utils.email_utils.generate_inactive_user_email_html",
        return_value="<h1>ok</h1>",
    )
    async def test_second_email_sent_between_7_and_14_days(
        self, mock_gen_html, mock_send, mock_users
    ):
        """User inactive 12 days, first email sent 8 days ago -> eligible for second email."""
        now = datetime.now(UTC)
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": "507f1f77bcf86cd799439011",
                "last_active_at": now - timedelta(days=12),
                "last_inactive_email_sent": now - timedelta(days=8),
            }
        )
        mock_users.update_one = AsyncMock()

        result = await send_inactive_user_email(
            "user@example.com", "Alice", user_id="507f1f77bcf86cd799439011"
        )

        assert result is True
        mock_send.assert_called_once()

    @patch("app.utils.email_utils.users_collection")
    @patch("app.utils.email_utils.resend.Emails.send")
    @patch(
        "app.utils.email_utils.generate_inactive_user_email_html",
        return_value="<h1>ok</h1>",
    )
    async def test_naive_datetimes_handled(self, mock_gen_html, mock_send, mock_users):
        """MongoDB may return naive datetimes; the function should handle them."""
        now = datetime.now(UTC)
        # Naive datetimes (no tzinfo) — function adds timezone.utc
        naive_last_active = (now - timedelta(days=10)).replace(tzinfo=None)
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": "507f1f77bcf86cd799439011",
                "last_active_at": naive_last_active,
                "last_inactive_email_sent": None,
            }
        )
        mock_users.update_one = AsyncMock()

        result = await send_inactive_user_email(
            "user@example.com", "Alice", user_id="507f1f77bcf86cd799439011"
        )

        assert result is True
        mock_send.assert_called_once()

    @patch("app.utils.email_utils.resend.Emails.send", side_effect=Exception("send failed"))
    @patch(
        "app.utils.email_utils.generate_inactive_user_email_html",
        return_value="<h1>ok</h1>",
    )
    async def test_propagates_exception(self, mock_gen_html, mock_send):
        with pytest.raises(Exception, match="send failed"):
            await send_inactive_user_email("user@example.com")

    @patch("app.utils.email_utils.users_collection")
    @patch("app.utils.email_utils.resend.Emails.send")
    @patch(
        "app.utils.email_utils.generate_inactive_user_email_html",
        return_value="<h1>ok</h1>",
    )
    async def test_naive_last_email_sent_handled(self, mock_gen_html, mock_send, mock_users):
        """Naive last_inactive_email_sent datetime should be handled."""
        now = datetime.now(UTC)
        naive_last_email = (now - timedelta(days=2)).replace(tzinfo=None)
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": "507f1f77bcf86cd799439011",
                "last_active_at": now - timedelta(days=10),
                "last_inactive_email_sent": naive_last_email,
            }
        )

        result = await send_inactive_user_email(
            "user@example.com", "Alice", user_id="507f1f77bcf86cd799439011"
        )

        # Email sent 2 days ago -> less than 7 -> should skip
        assert result is False
        mock_send.assert_not_called()
