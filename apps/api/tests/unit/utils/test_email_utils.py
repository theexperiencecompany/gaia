"""Unit tests for email utility functions.

Tests cover:
- Pure extraction helpers: extract_subject, extract_sender, extract_date, extract_labels
- Content parsing: extract_string_content, _parse_mail_parts
- Format conversion: convert_composio_to_gmail_format
- Async email functions: send_welcome_email, add_contact_to_resend, send_inactive_user_email
"""

import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.utils.email_utils import (
    _parse_mail_parts,
    add_contact_to_resend,
    convert_composio_to_gmail_format,
    extract_date,
    extract_labels,
    extract_sender,
    extract_string_content,
    extract_subject,
    send_inactive_user_email,
    send_welcome_email,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64(text: str) -> str:
    """URL-safe base64-encode a plain string (no padding fix needed)."""
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def _gmail_msg(
    mime_type: str = "text/plain",
    headers: list[dict] | None = None,
    body_data: str = "",
    parts: list[dict] | None = None,
    label_ids: list[str] | None = None,
    message_text: str | None = None,
) -> dict:
    """Build a minimal Gmail-like message dict for testing."""
    msg: dict = {
        "payload": {
            "mimeType": mime_type,
            "headers": headers or [],
            "body": {"data": body_data},
            "parts": parts or [],
        },
    }
    if label_ids is not None:
        msg["labelIds"] = label_ids
    if message_text is not None:
        msg["message_text"] = message_text
    return msg


# ===========================================================================
# Pure logic: extract_subject
# ===========================================================================


@pytest.mark.unit
class TestExtractSubject:
    def test_returns_subject_when_present(self):
        msg = _gmail_msg(headers=[{"name": "Subject", "value": "Hello World"}])
        assert extract_subject(msg) == "Hello World"

    def test_returns_empty_when_no_subject_header(self):
        msg = _gmail_msg(headers=[{"name": "From", "value": "a@b.com"}])
        assert extract_subject(msg) == ""

    def test_returns_empty_for_empty_headers_list(self):
        msg = _gmail_msg(headers=[])
        assert extract_subject(msg) == ""

    def test_returns_empty_when_payload_missing(self):
        assert extract_subject({}) == ""

    def test_returns_empty_when_headers_key_missing(self):
        assert extract_subject({"payload": {}}) == ""

    def test_subject_with_empty_value(self):
        msg = _gmail_msg(headers=[{"name": "Subject", "value": ""}])
        assert extract_subject(msg) == ""

    def test_picks_first_subject_header(self):
        msg = _gmail_msg(
            headers=[
                {"name": "Subject", "value": "First"},
                {"name": "Subject", "value": "Second"},
            ]
        )
        assert extract_subject(msg) == "First"


# ===========================================================================
# Pure logic: extract_sender
# ===========================================================================


@pytest.mark.unit
class TestExtractSender:
    def test_returns_from_when_present(self):
        msg = _gmail_msg(headers=[{"name": "From", "value": "alice@example.com"}])
        assert extract_sender(msg) == "alice@example.com"

    def test_returns_empty_when_no_from_header(self):
        msg = _gmail_msg(headers=[{"name": "Subject", "value": "Hi"}])
        assert extract_sender(msg) == ""

    def test_returns_empty_for_empty_headers(self):
        msg = _gmail_msg(headers=[])
        assert extract_sender(msg) == ""

    def test_returns_empty_when_payload_missing(self):
        assert extract_sender({}) == ""

    def test_from_with_display_name(self):
        msg = _gmail_msg(
            headers=[{"name": "From", "value": "Alice <alice@example.com>"}]
        )
        assert extract_sender(msg) == "Alice <alice@example.com>"


# ===========================================================================
# Pure logic: extract_date
# ===========================================================================


@pytest.mark.unit
class TestExtractDate:
    def test_returns_date_when_present(self):
        msg = _gmail_msg(
            headers=[{"name": "Date", "value": "Mon, 1 Jan 2024 12:00:00 +0000"}]
        )
        assert extract_date(msg) == "Mon, 1 Jan 2024 12:00:00 +0000"

    def test_returns_empty_when_no_date_header(self):
        msg = _gmail_msg(headers=[{"name": "From", "value": "a@b.com"}])
        assert extract_date(msg) == ""

    def test_returns_empty_for_empty_headers(self):
        msg = _gmail_msg(headers=[])
        assert extract_date(msg) == ""

    def test_returns_empty_when_payload_missing(self):
        assert extract_date({}) == ""


# ===========================================================================
# Pure logic: extract_labels
# ===========================================================================


@pytest.mark.unit
class TestExtractLabels:
    def test_returns_labels_when_present(self):
        msg = _gmail_msg(label_ids=["INBOX", "UNREAD"])
        assert extract_labels(msg) == ["INBOX", "UNREAD"]

    def test_returns_empty_list_when_no_label_ids(self):
        msg = _gmail_msg()
        assert extract_labels(msg) == []

    def test_returns_empty_list_for_empty_dict(self):
        assert extract_labels({}) == []

    def test_returns_single_label(self):
        msg = _gmail_msg(label_ids=["STARRED"])
        assert extract_labels(msg) == ["STARRED"]

    def test_preserves_order(self):
        labels = ["SENT", "IMPORTANT", "CATEGORY_PERSONAL"]
        msg = _gmail_msg(label_ids=labels)
        assert extract_labels(msg) == labels


# ===========================================================================
# Pure logic: _parse_mail_parts
# ===========================================================================


@pytest.mark.unit
class TestParseMailParts:
    def test_plain_text_part(self):
        parts = [
            {
                "mimeType": "text/plain",
                "body": {"data": _b64("Hello plain text")},
            }
        ]
        assert _parse_mail_parts(parts) == "Hello plain text"

    def test_html_part_strips_tags(self):
        html = "<html><body><p>Hello <b>HTML</b></p></body></html>"
        parts = [
            {
                "mimeType": "text/html",
                "body": {"data": _b64(html)},
            }
        ]
        result = _parse_mail_parts(parts)
        assert "Hello" in result
        assert "HTML" in result
        assert "<p>" not in result

    def test_recursive_multipart(self):
        inner_parts = [
            {
                "mimeType": "text/plain",
                "body": {"data": _b64("nested content")},
            }
        ]
        parts = [
            {
                "mimeType": "multipart/alternative",
                "parts": inner_parts,
            }
        ]
        assert _parse_mail_parts(parts) == "nested content"

    def test_empty_data_skipped(self):
        parts = [
            {
                "mimeType": "text/plain",
                "body": {"data": ""},
            }
        ]
        assert _parse_mail_parts(parts) == ""

    def test_empty_parts_list(self):
        assert _parse_mail_parts([]) == ""

    def test_multiple_parts_concatenated(self):
        parts = [
            {
                "mimeType": "text/plain",
                "body": {"data": _b64("Part one. ")},
            },
            {
                "mimeType": "text/plain",
                "body": {"data": _b64("Part two.")},
            },
        ]
        result = _parse_mail_parts(parts)
        assert "Part one." in result
        assert "Part two." in result

    def test_unknown_mime_type_ignored(self):
        parts = [
            {
                "mimeType": "image/png",
                "body": {"data": _b64("not text")},
            }
        ]
        assert _parse_mail_parts(parts) == ""

    def test_missing_body_key(self):
        parts = [{"mimeType": "text/plain"}]
        assert _parse_mail_parts(parts) == ""


# ===========================================================================
# Pure logic: extract_string_content
# ===========================================================================


@pytest.mark.unit
class TestExtractStringContent:
    # --- Composio format (message_text) ---

    def test_composio_plain_text(self):
        msg = _gmail_msg(message_text="Hello from Composio")
        assert extract_string_content(msg) == "Hello from Composio"

    def test_composio_html_text_stripped(self):
        msg = _gmail_msg(message_text="<p>Hello <b>bold</b></p>")
        result = extract_string_content(msg)
        assert "Hello" in result
        assert "bold" in result
        assert "<p>" not in result

    def test_composio_empty_message_text(self):
        msg = _gmail_msg(message_text="")
        assert extract_string_content(msg) == ""

    # --- Gmail plain text ---
    # NOTE: The production code has a heuristic for the top-level text/plain
    # and text/html paths: if body.data is a string that does NOT start with
    # "=", it is treated as already-decoded (from Composio conversion).
    # Actual base64 decoding only triggers when data starts with "=".
    # The multipart path (_parse_mail_parts) always base64-decodes.

    def test_gmail_plain_already_decoded(self):
        """Data that doesn't start with '=' is treated as already-decoded text."""
        msg = _gmail_msg(mime_type="text/plain", body_data="Already decoded text")
        assert extract_string_content(msg) == "Already decoded text"

    def test_gmail_plain_preserves_content(self):
        msg = _gmail_msg(mime_type="text/plain", body_data="Simple email body")
        assert extract_string_content(msg) == "Simple email body"

    def test_gmail_plain_empty_body(self):
        msg = _gmail_msg(mime_type="text/plain", body_data="")
        assert extract_string_content(msg) == ""

    # --- Gmail HTML (already decoded path) ---

    def test_gmail_html_already_decoded(self):
        html = "<div>Decoded HTML</div>"
        msg = _gmail_msg(mime_type="text/html", body_data=html)
        result = extract_string_content(msg)
        assert "Decoded HTML" in result
        assert "<div>" not in result

    def test_gmail_html_strips_nested_tags(self):
        html = "<html><body><p>HTML <b>email</b></p></body></html>"
        msg = _gmail_msg(mime_type="text/html", body_data=html)
        result = extract_string_content(msg)
        assert "HTML" in result
        assert "email" in result
        assert "<p>" not in result

    def test_gmail_html_empty_body(self):
        msg = _gmail_msg(mime_type="text/html", body_data="")
        assert extract_string_content(msg) == ""

    def test_gmail_html_entities_decoded(self):
        html = "<p>5 &gt; 3 &amp; 2 &lt; 4</p>"
        msg = _gmail_msg(mime_type="text/html", body_data=html)
        result = extract_string_content(msg)
        assert "5 > 3 & 2 < 4" in result

    # --- Multipart (delegates to _parse_mail_parts which always base64-decodes) ---

    def test_multipart_delegates_to_parse_mail_parts(self):
        parts = [
            {
                "mimeType": "text/plain",
                "body": {"data": _b64("multipart content")},
            }
        ]
        msg = _gmail_msg(mime_type="multipart/mixed", parts=parts)
        assert extract_string_content(msg) == "multipart content"

    def test_multipart_alternative(self):
        parts = [
            {
                "mimeType": "text/plain",
                "body": {"data": _b64("plain version")},
            },
            {
                "mimeType": "text/html",
                "body": {"data": _b64("<p>html version</p>")},
            },
        ]
        msg = _gmail_msg(mime_type="multipart/alternative", parts=parts)
        result = extract_string_content(msg)
        assert "plain version" in result
        assert "html version" in result

    def test_multipart_empty_parts(self):
        msg = _gmail_msg(mime_type="multipart/mixed", parts=[])
        assert extract_string_content(msg) == ""

    # --- Unknown mime type ---

    def test_unknown_mime_type_returns_empty(self):
        msg = _gmail_msg(mime_type="application/pdf", body_data="binary stuff")
        assert extract_string_content(msg) == ""

    # --- Whitespace stripping ---

    def test_strips_whitespace(self):
        msg = _gmail_msg(mime_type="text/plain", body_data="  padded  ")
        assert extract_string_content(msg) == "padded"


# ===========================================================================
# Pure logic: convert_composio_to_gmail_format
# ===========================================================================


@pytest.mark.unit
class TestConvertComposioToGmailFormat:
    def test_all_fields_present(self):
        composio_data = {
            "subject": "Test Subject",
            "sender": "alice@example.com",
            "message_timestamp": "2024-01-01T00:00:00Z",
            "message_id": "msg-123",
            "thread_id": "thread-456",
            "label_ids": ["INBOX", "UNREAD"],
            "message_text": "Hello world",
            "payload": {
                "mimeType": "text/plain",
                "headers": [{"name": "X-Custom", "value": "custom-val"}],
                "parts": [],
            },
        }

        result = convert_composio_to_gmail_format(composio_data)

        assert result["id"] == "msg-123"
        assert result["threadId"] == "thread-456"
        assert result["labelIds"] == ["INBOX", "UNREAD"]
        assert result["payload"]["mimeType"] == "text/plain"
        assert result["payload"]["body"]["data"] == "Hello world"

        # Standard headers mapped
        headers = result["payload"]["headers"]
        subject_headers = [h for h in headers if h["name"] == "Subject"]
        from_headers = [h for h in headers if h["name"] == "From"]
        date_headers = [h for h in headers if h["name"] == "Date"]
        custom_headers = [h for h in headers if h["name"] == "X-Custom"]

        assert len(subject_headers) == 1
        assert subject_headers[0]["value"] == "Test Subject"
        assert len(from_headers) == 1
        assert from_headers[0]["value"] == "alice@example.com"
        assert len(date_headers) == 1
        assert date_headers[0]["value"] == "2024-01-01T00:00:00Z"
        assert len(custom_headers) == 1
        assert custom_headers[0]["value"] == "custom-val"

    def test_missing_optional_fields(self):
        composio_data: dict = {"payload": {}}
        result = convert_composio_to_gmail_format(composio_data)

        assert result["id"] == ""
        assert result["threadId"] == ""
        assert result["labelIds"] == []
        assert result["payload"]["mimeType"] == "text/plain"
        assert result["payload"]["body"]["data"] == ""
        assert result["payload"]["headers"] == []
        assert result["payload"]["parts"] == []

    def test_non_list_headers_ignored(self):
        """When payload.headers is not a list, additional headers should not be added."""
        composio_data = {
            "subject": "Test",
            "payload": {
                "headers": "not-a-list",  # Invalid type
            },
        }
        result = convert_composio_to_gmail_format(composio_data)

        # Should still have the Subject header from the top-level field
        headers = result["payload"]["headers"]
        assert any(h["name"] == "Subject" for h in headers)
        # But should NOT crash or include the non-list value
        for h in headers:
            assert isinstance(h, dict)

    def test_no_subject_no_sender_no_timestamp(self):
        """When top-level fields are absent, those headers should not appear."""
        composio_data: dict = {"payload": {"headers": []}}
        result = convert_composio_to_gmail_format(composio_data)
        headers = result["payload"]["headers"]
        header_names = [h["name"] for h in headers]
        assert "Subject" not in header_names
        assert "From" not in header_names
        assert "Date" not in header_names

    def test_empty_input(self):
        result = convert_composio_to_gmail_format({})
        assert result["id"] == ""
        assert result["threadId"] == ""
        assert result["payload"]["mimeType"] == "text/plain"


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

    @patch(
        "app.utils.email_utils.resend.Emails.send", side_effect=Exception("API error")
    )
    @patch(
        "app.utils.email_utils.generate_welcome_email_html", return_value="<h1>ok</h1>"
    )
    async def test_propagates_send_exception(self, mock_gen_html, mock_send):
        with pytest.raises(Exception, match="API error"):
            await send_welcome_email("user@example.com")

    @patch("app.utils.email_utils.resend.Emails.send")
    @patch(
        "app.utils.email_utils.generate_welcome_email_html", return_value="<h1>Hi</h1>"
    )
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
    async def test_user_not_found_returns_false(
        self, mock_gen_html, mock_send, mock_users
    ):
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
        now = datetime.now(timezone.utc)
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
    async def test_no_last_active_returns_false(
        self, mock_gen_html, mock_send, mock_users
    ):
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
    async def test_email_sent_recently_returns_false(
        self, mock_gen_html, mock_send, mock_users
    ):
        """If an inactive email was sent less than 7 days ago, skip."""
        now = datetime.now(timezone.utc)
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
        now = datetime.now(timezone.utc)
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
    async def test_max_2_emails_stops_after_14_days(
        self, mock_gen_html, mock_send, mock_users
    ):
        """After 14+ days inactive with a previous email sent, stop sending."""
        now = datetime.now(timezone.utc)
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
        now = datetime.now(timezone.utc)
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
        now = datetime.now(timezone.utc)
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

    @patch(
        "app.utils.email_utils.resend.Emails.send", side_effect=Exception("send failed")
    )
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
    async def test_naive_last_email_sent_handled(
        self, mock_gen_html, mock_send, mock_users
    ):
        """Naive last_inactive_email_sent datetime should be handled."""
        now = datetime.now(timezone.utc)
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
