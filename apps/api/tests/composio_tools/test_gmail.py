"""
Gmail custom tool tests using pytest.

Tests Gmail tools:
- GMAIL_GET_UNREAD_COUNT (read-only)
- GMAIL_CUSTOM_CREATE_DRAFT (setup)
- GMAIL_MARK_AS_READ
- GMAIL_MARK_AS_UNREAD
- GMAIL_STAR_EMAIL
- GMAIL_ARCHIVE_EMAIL
- GMAIL_GET_CONTACT_LIST
- GMAIL_DELETE_DRAFT (cleanup)

Creates a draft email, performs operations, then cleans up.

Usage:
    python -m tests.composio_tools.run_tests gmail
    pytest tests/composio_tools/test_gmail.py -v --user-id USER_ID
"""

import json
from datetime import datetime
from typing import Any, Dict, Generator

import pytest
from pytest_check.context_manager import check

from tests.composio_tools.config_utils import get_integration_config
from tests.composio_tools.conftest import execute_tool


def parse_data(result: Dict[str, Any]) -> Dict[str, Any]:
    """Parse result data, handling string JSON responses."""
    data = result.get("data", {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            pass
    return data if isinstance(data, dict) else {}


@pytest.fixture(scope="class")
def test_email(composio_client, user_id) -> Generator[Dict[str, Any], None, None]:
    """
    Create a test draft email for Gmail testing.

    Expected GMAIL_CUSTOM_CREATE_DRAFT output:
    {
      "data": {
        "id": "r-...",  # draft_id
        "message": {
          "id": "...",  # message_id
          "labelIds": ["DRAFT"],
          "threadId": "..."
        }
      },
      "error": null,
      "successful": true
    }
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    subject = f"[PYTEST] Test Email {timestamp}"

    result = execute_tool(
        composio_client,
        "GMAIL_CUSTOM_CREATE_DRAFT",
        {
            "to": "test@example.com",
            "subject": subject,
            "body": f"This is a test draft created by pytest at {timestamp}.",
        },
        user_id,
    )

    if not result.get("successful"):
        pytest.skip(f"Could not create test draft: {result.get('error')}")

    data = parse_data(result)

    # Schema: data.id is draft_id, data.message.id is message_id
    draft_id = data.get("id") or data.get("draft_id") or data.get("draftId")
    message_data = data.get("message", {})
    message_id = message_data.get("id") or data.get("message_id")

    if not message_id and not draft_id:
        pytest.skip("Could not get message ID or draft ID from create response")

    # Use draft_id as message_id if message_id not found
    if not message_id:
        message_id = draft_id

    email_info = {
        "message_id": message_id,
        "draft_id": draft_id,
        "subject": subject,
    }

    yield email_info

    # Cleanup: Delete the draft
    # Expected output: {"data": {"success": true}, "error": null, "successful": true}
    if draft_id:
        try:
            execute_tool(
                composio_client,
                "GMAIL_DELETE_DRAFT",
                {"draft_id": draft_id},
                user_id,
            )
        except Exception:
            pass  # Best effort cleanup


class TestGmailReadOperations:
    """Tests for read-only Gmail operations."""

    def test_get_unread_count(self, composio_client, user_id):
        """
        Test GET_UNREAD_COUNT returns unread + total counts for inbox.

        Expected output schema:
        {
          "data": {
            "unreadCount": 2135,
            "totalCount": 9876,
            "label_id": "INBOX"
          },
          "error": null,
          "successful": true
        }
        """
        result = execute_tool(
            composio_client,
            "GMAIL_GET_UNREAD_COUNT",
            {"label_id": "INBOX"},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = parse_data(result)

        with check:
            assert "unreadCount" in data, "Should have 'unreadCount' field"
            unread_count = data.get("unreadCount")
            assert isinstance(unread_count, int), "unreadCount should be int"
            assert unread_count >= 0, "unreadCount should be non-negative"
            assert "totalCount" in data, "Should have 'totalCount' field"
            total_count = data.get("totalCount")
            assert isinstance(total_count, int), "totalCount should be int"
            assert total_count >= unread_count, "totalCount should be >= unreadCount"

    def test_get_unread_count_with_query(self, composio_client, user_id):
        """
        Test GET_UNREAD_COUNT supports query-based counting.

        Expected output schema:
        {
          "data": {
            "query": "is:unread",
            "unreadCount": 123,
            "totalCount": 123,
            "is_estimate": true
          },
          "error": null,
          "successful": true
        }
        """
        result = execute_tool(
            composio_client,
            "GMAIL_GET_UNREAD_COUNT",
            {"query": "is:unread", "label_ids": ["INBOX"]},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = parse_data(result)

        with check:
            assert data.get("query") == "is:unread", "Should echo query"
            assert "unreadCount" in data, "Should have unreadCount"
            assert "totalCount" in data, "Should have totalCount"
            unread_count = data.get("unreadCount")
            total_count = data.get("totalCount")
            assert isinstance(unread_count, int), "unreadCount should be int"
            assert isinstance(total_count, int), "totalCount should be int"
            assert unread_count >= 0, "unreadCount should be non-negative"
            assert total_count >= unread_count, "totalCount should be >= unreadCount"


class TestGmailMessageOperations:
    """Tests for Gmail message operations using draft email."""

    def test_mark_as_read(self, composio_client, user_id, test_email):
        """
        Test MARK_AS_READ marks the test email as read.

        Expected output schema:
        {"data": {}, "error": null, "successful": true}
        """
        result = execute_tool(
            composio_client,
            "GMAIL_MARK_AS_READ",
            {"message_ids": [test_email["message_id"]]},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

    def test_mark_as_unread(self, composio_client, user_id, test_email):
        """
        Test MARK_AS_UNREAD marks the test email as unread.

        Expected output schema:
        {"data": {}, "error": null, "successful": true}
        """
        result = execute_tool(
            composio_client,
            "GMAIL_MARK_AS_UNREAD",
            {"message_ids": [test_email["message_id"]]},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

    def test_star_email(self, composio_client, user_id, test_email):
        """
        Test STAR_EMAIL adds star to the test email.

        Expected output schema:
        {"data": {"action": "starred"}, "error": null, "successful": true}
        """
        result = execute_tool(
            composio_client,
            "GMAIL_STAR_EMAIL",
            {
                "message_ids": [test_email["message_id"]],
                "unstar": False,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = parse_data(result)
        assert data.get("action") == "starred", "Should report action as 'starred'"

    def test_unstar_email(self, composio_client, user_id, test_email):
        """
        Test STAR_EMAIL with unstar=True removes star.

        Expected output schema:
        {"data": {"action": "unstarred"}, "error": null, "successful": true}
        """
        result = execute_tool(
            composio_client,
            "GMAIL_STAR_EMAIL",
            {
                "message_ids": [test_email["message_id"]],
                "unstar": True,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = parse_data(result)
        assert data.get("action") == "unstarred", "Should report action as 'unstarred'"

    def test_archive_email(self, composio_client, user_id, test_email):
        """
        Test ARCHIVE_EMAIL archives the test email (run last).

        Expected output schema:
        {"data": {}, "error": null, "successful": true}
        """
        result = execute_tool(
            composio_client,
            "GMAIL_ARCHIVE_EMAIL",
            {"message_ids": [test_email["message_id"]]},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"


class TestGmailContactList:
    """Tests for Gmail contact list extraction."""

    def test_get_contact_list_with_query(self, composio_client, user_id):
        """
        Test GET_CONTACT_LIST returns contacts matching a query.

        Expected output schema:
        {
          "data": {
            "success": true,
            "contacts": [{"name": "...", "email": "..."}],
            "count": 5
          },
          "error": null,
          "successful": true
        }
        """
        result = execute_tool(
            composio_client,
            "GMAIL_GET_CONTACT_LIST",
            {"query": "test", "max_results": 10},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = parse_data(result)

        assert data.get("success") is True, "Should return success"
        assert "contacts" in data, "Should have contacts field"
        assert isinstance(data.get("contacts"), list), "contacts should be a list"
        assert "count" in data, "Should have count field"
        assert data.get("count") == len(data.get("contacts", [])), (
            "count should match contacts length"
        )

    def test_get_contact_list_with_email_domain(self, composio_client, user_id):
        """
        Test GET_CONTACT_LIST filters by email domain.

        Expected output schema:
        {
          "data": {
            "success": true,
            "contacts": [{"name": "...", "email": "..."}],
            "count": N
          },
          "error": null,
          "successful": true
        }
        """
        result = execute_tool(
            composio_client,
            "GMAIL_GET_CONTACT_LIST",
            {"query": "gmail.com", "max_results": 10},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = parse_data(result)

        assert data.get("success") is True, "Should return success"
        assert "contacts" in data, "Should have contacts field"
        assert isinstance(data.get("contacts"), list), "contacts should be a list"

    def test_get_contact_list_empty_results(self, composio_client, user_id):
        """
        Test GET_CONTACT_LIST handles no results gracefully.

        Expected output schema:
        {
          "data": {
            "success": true,
            "contacts": [],
            "count": 0,
            "message": "No messages found matching query: ..."
          },
          "error": null,
          "successful": true
        }
        """
        result = execute_tool(
            composio_client,
            "GMAIL_GET_CONTACT_LIST",
            {"query": "xyzqwerty123456789nonexistent", "max_results": 5},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = parse_data(result)

        assert data.get("success") is True, "Should return success even with no results"
        assert "contacts" in data, "Should have contacts field"
        assert data.get("count") == 0, "count should be 0 for no results"
        assert len(data.get("contacts", [])) == 0, "contacts should be empty list"


class TestGmailSendEmailDestructive:
    """Live send-email tests that send real emails via Composio."""

    @pytest.fixture(scope="class")
    def target_email(self) -> str:
        """Load recipient email from integration config/env."""
        config = get_integration_config("gmail")
        recipient_obj: object = config.get("test_recipient_email") or config.get(
            "share_email"
        )
        if not isinstance(recipient_obj, str):
            pytest.skip(
                "No gmail test recipient configured. "
                "Set gmail.test_recipient_email or TEST_SHARE_EMAIL."
            )
        assert isinstance(recipient_obj, str)
        recipient = recipient_obj.strip()
        if not recipient:
            pytest.skip(
                "No gmail test recipient configured. "
                "Set gmail.test_recipient_email or TEST_SHARE_EMAIL."
            )
        return recipient

    def test_send_email_plain_text_with_empty_cc_bcc(
        self,
        composio_client,
        user_id,
        target_email,
        skip_destructive,
        confirm_action,
    ):
        """
        Validate the reported failing payload against GMAIL_SEND_EMAIL.

        Sends a real email via Composio with:
        - subject
        - body
        - cc=[]
        - bcc=[]
        - is_html=False
        - user_id='me'
        """
        if skip_destructive:
            pytest.skip("Skipped destructive send-email test (--skip-destructive)")

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = f"[PYTEST][GMAIL_SEND_EMAIL] Payload Validation {timestamp}"
        body = (
            "This is a live Composio Gmail send-email test.\n\n"
            f"Timestamp: {timestamp}\n"
            "Case: subject/body + cc=[] + bcc=[] + is_html=false + user_id=me"
        )

        confirm_action(
            f"About to SEND a real email via GMAIL_SEND_EMAIL to {target_email}."
        )

        result = execute_tool(
            composio_client,
            "GMAIL_SEND_EMAIL",
            {
                "recipient_email": target_email,
                "subject": subject,
                "body": body,
                "cc": [],
                "bcc": [],
                "is_html": False,
                "user_id": "me",
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

        data = parse_data(result)
        with check:
            assert isinstance(data, dict), "data should be a dict"
            assert data != {}, "send response data should not be empty"

    def test_send_email_html_with_empty_cc_bcc(
        self,
        composio_client,
        user_id,
        target_email,
        skip_destructive,
        confirm_action,
    ):
        """Validate GMAIL_SEND_EMAIL with is_html=True on a live send."""
        if skip_destructive:
            pytest.skip("Skipped destructive send-email test (--skip-destructive)")

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = f"[PYTEST][GMAIL_SEND_EMAIL][HTML] Payload Validation {timestamp}"
        body = (
            "<p>This is a <strong>live Composio Gmail send-email HTML test.</strong></p>"
            f"<p>Timestamp: {timestamp}</p>"
            "<p>Case: subject/body + cc=[] + bcc=[] + is_html=true + user_id=me</p>"
        )

        confirm_action(
            f"About to SEND a real HTML email via GMAIL_SEND_EMAIL to {target_email}."
        )

        result = execute_tool(
            composio_client,
            "GMAIL_SEND_EMAIL",
            {
                "recipient_email": target_email,
                "subject": subject,
                "body": body,
                "cc": [],
                "bcc": [],
                "is_html": True,
                "user_id": "me",
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

        data = parse_data(result)
        with check:
            assert isinstance(data, dict), "data should be a dict"
            assert data != {}, "send response data should not be empty"
