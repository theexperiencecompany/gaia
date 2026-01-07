"""
Gmail custom tool tests using pytest.

Tests Gmail tools:
- GMAIL_GET_UNREAD_COUNT (read-only)
- GMAIL_CREATE_EMAIL_DRAFT (setup)
- GMAIL_MARK_AS_READ
- GMAIL_MARK_AS_UNREAD
- GMAIL_STAR_EMAIL
- GMAIL_SNOOZE_EMAIL
- GMAIL_ARCHIVE_EMAIL
- GMAIL_DELETE_DRAFT (cleanup)

Creates a draft email, performs operations, then cleans up.

Usage:
    python -m tests.composio_tools.run_tests gmail
    pytest tests/composio_tools/test_gmail.py -v --user-id USER_ID
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Generator

import pytest
from pytest_check import check

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

    Expected GMAIL_CREATE_EMAIL_DRAFT output:
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
        "GMAIL_CREATE_EMAIL_DRAFT",
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
        Test GET_UNREAD_COUNT returns unread count for inbox.

        Expected output schema:
        {
          "data": {
            "unreadCount": 2135,
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
            assert isinstance(data.get("unreadCount"), int), "unreadCount should be int"
            assert data.get("unreadCount") >= 0, "unreadCount should be non-negative"


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

    def test_snooze_email(self, composio_client, user_id, test_email):
        """
        Test SNOOZE_EMAIL snoozes the test email.

        Expected output schema:
        {
          "data": {
            "snooze_until": "2026-01-01T18:25:26.969995Z",
            "snoozed_label_id": "Label_1"
          },
          "error": null,
          "successful": true
        }
        """
        # Use timezone-aware datetime
        snooze_until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        result = execute_tool(
            composio_client,
            "GMAIL_SNOOZE_EMAIL",
            {
                "message_ids": [test_email["message_id"]],
                "snooze_until": snooze_until,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = parse_data(result)
        assert data.get("snooze_until"), "Should have snooze_until timestamp"
        assert data.get("snoozed_label_id"), "Should have snoozed_label_id"

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
