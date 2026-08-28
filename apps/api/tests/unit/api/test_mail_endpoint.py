"""Unit tests for mail (Gmail) API endpoints.

Tests the Gmail endpoints with mocked service layer and integration
dependency to verify routing, status codes, response bodies, and validation.

Gmail endpoints use ``require_integration("gmail")`` which internally calls
``check_integration_status``.  We patch that function to return ``True`` so
the dependency passes without a real Composio/Redis connection.
"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.api.v1.endpoints.mail import _build_gmail_query
from app.models.mail_models import (
    BulkEmailImportanceSummariesResponse,
    EmailImportanceSummariesResponse,
    EmailImportanceSummaryResponse,
    GmailDraftsResponse,
    GmailEmailResult,
    GmailLabelsResult,
    GmailMessageResource,
    GmailMessagesResponse,
    GmailSearchFilters,
    GmailToolResult,
)
from app.services.analytics_service import AnalyticsEvents

MAIL_BASE = "/api/v1"
ANALYTICS_PATCH = "app.api.v1.endpoints.mail.capture_context_event"


@pytest.fixture(autouse=True)
def _noop_analytics():
    """Neutralize capture_context_event for every test in this module.

    The test app runs a no-op lifespan, so the PostHog provider is never
    registered; a bare capture_context_event call would raise KeyError on the
    missing provider. Tests that assert on captures patch the call site again
    and assert on their own mock.
    """
    with patch(ANALYTICS_PATCH):
        yield


# All tests in this module need the integration check to pass.
pytestmark = [
    pytest.mark.usefixtures("_bypass_integration_check"),
]


@pytest.fixture(autouse=True)
async def _bypass_integration_check():
    """Patch check_integration_status so require_integration("gmail") passes."""
    with patch(
        "app.api.v1.dependencies.google_scope_dependencies.check_integration_status",
        new_callable=AsyncMock,
        return_value=True,
    ):
        yield


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/labels
# ---------------------------------------------------------------------------


class TestListLabels:
    @patch(
        "app.api.v1.endpoints.mail.list_labels_service",
        new_callable=AsyncMock,
    )
    async def test_list_labels_returns_200(self, mock_labels: AsyncMock, client: AsyncClient):
        mock_labels.return_value = GmailLabelsResult(
            success=True,
            labels=[{"id": "INBOX", "name": "INBOX"}],
            count=1,
        )
        response = await client.get(f"{MAIL_BASE}/gmail/labels")
        assert response.status_code == 200
        data = response.json()
        assert "labels" in data
        assert data["count"] == 1

    @patch(
        "app.api.v1.endpoints.mail.list_labels_service",
        new_callable=AsyncMock,
    )
    async def test_list_labels_service_failure_returns_500(
        self, mock_labels: AsyncMock, client: AsyncClient
    ):
        mock_labels.return_value = GmailLabelsResult(success=False, error="API error")
        response = await client.get(f"{MAIL_BASE}/gmail/labels")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/messages
# ---------------------------------------------------------------------------


class TestListMessages:
    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_list_messages_returns_200(self, mock_search: AsyncMock, client: AsyncClient):
        mock_search.return_value = GmailMessagesResponse(
            messages=[{"id": "msg-1", "snippet": "Hello"}]
        )
        response = await client.get(f"{MAIL_BASE}/gmail/messages")
        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 1
        assert data["nextPageToken"] is None

    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_list_messages_with_pagination(self, mock_search: AsyncMock, client: AsyncClient):
        mock_search.return_value = GmailMessagesResponse(
            messages=[{"id": "msg-2"}], next_page_token="token-abc"
        )
        response = await client.get(
            f"{MAIL_BASE}/gmail/messages",
            params={"max_results": 10, "pageToken": "prev-token"},
        )
        assert response.status_code == 200
        assert response.json()["nextPageToken"] == "token-abc"

    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_list_messages_service_error_returns_500(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.side_effect = Exception("Gmail API error")
        response = await client.get(f"{MAIL_BASE}/gmail/messages")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/message/{message_id}
# ---------------------------------------------------------------------------


class TestGetEmailById:
    @patch(
        "app.api.v1.endpoints.mail.get_email_by_id_service",
        new_callable=AsyncMock,
    )
    async def test_get_email_returns_200(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.return_value = GmailEmailResult(
            success=True,
            message={"id": "msg-1", "subject": "Test"},
        )
        response = await client.get(f"{MAIL_BASE}/gmail/message/msg-1")
        assert response.status_code == 200
        data = response.json()
        assert data["message"]["id"] == "msg-1"
        assert data["status"] == "Message retrieved successfully"

    @patch(
        "app.api.v1.endpoints.mail.get_email_by_id_service",
        new_callable=AsyncMock,
    )
    async def test_get_email_not_found_returns_404(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.return_value = GmailEmailResult(
            success=False,
            error="Message not found",
        )
        response = await client.get(f"{MAIL_BASE}/gmail/message/nonexistent")
        assert response.status_code == 404

    @patch(
        "app.api.v1.endpoints.mail.get_email_by_id_service",
        new_callable=AsyncMock,
    )
    async def test_get_email_service_failure_returns_500(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.return_value = {
            "success": False,
            "error": "Internal failure",
        }
        response = await client.get(f"{MAIL_BASE}/gmail/message/msg-1")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/search
# ---------------------------------------------------------------------------


class TestSearchEmails:
    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_emails_returns_200(self, mock_search: AsyncMock, client: AsyncClient):
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "msg-1"}])
        response = await client.get(f"{MAIL_BASE}/gmail/search", params={"query": "invoice"})
        assert response.status_code == 200

    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_emails_with_filters(self, mock_search: AsyncMock, client: AsyncClient):
        mock_search.return_value = GmailMessagesResponse(messages=[])
        response = await client.get(
            f"{MAIL_BASE}/gmail/search",
            params={
                "sender": "boss@company.com",
                "has_attachment": True,
                "is_read": False,
                "max_results": 5,
            },
        )
        assert response.status_code == 200
        # Verify the query was constructed with filters
        call_kwargs = mock_search.call_args.kwargs
        assert "from:boss@company.com" in call_kwargs["query"]
        assert "has:attachment" in call_kwargs["query"]
        assert "is:unread" in call_kwargs["query"]

    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_emails_caps_max_results_at_20(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.return_value = GmailMessagesResponse(messages=[])
        await client.get(
            f"{MAIL_BASE}/gmail/search",
            params={"query": "test", "max_results": 100},
        )
        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs["max_results"] == 20


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/send-json
# ---------------------------------------------------------------------------


class TestSendEmailJson:
    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_email_json_returns_200(self, mock_send: AsyncMock, client: AsyncClient):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": {"id": "sent-001"}, "error": None, "successful": True}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={
                "to": ["recipient@example.com"],
                "subject": "Hello",
                "body": "Test email body",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["message_id"] == "sent-001"
        assert data["status"] == "Email sent successfully"


class TestMailAnalytics:
    """Analytics captures on mail endpoints."""

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_json_captures_email_sent(self, mock_send: AsyncMock, client: AsyncClient):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": {"id": "sent-001"}, "error": None, "successful": True}
        )
        with patch(ANALYTICS_PATCH) as mock_capture:
            response = await client.post(
                f"{MAIL_BASE}/gmail/send-json",
                json={
                    "to": ["recipient@example.com"],
                    "subject": "Hello",
                    "body": "Test email body",
                },
            )

        assert response.status_code == 200
        mock_capture.assert_called_once_with(AnalyticsEvents.EMAIL_SENT, {"recipient_count": 1})

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_with_thread_captures_email_replied(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": {"id": "sent-002"}, "error": None, "successful": True}
        )
        with patch(ANALYTICS_PATCH) as mock_capture:
            response = await client.post(
                f"{MAIL_BASE}/gmail/send",
                data={
                    "to": "recipient@example.com",
                    "subject": "Hello",
                    "body": "Test email body",
                    "thread_id": "thread-1",
                },
            )

        assert response.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.EMAIL_REPLIED,
            {"has_attachments": False, "attachment_count": 0},
        )

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_without_thread_captures_email_sent(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        """No thread id -> the capture names EMAIL_SENT, not EMAIL_REPLIED."""
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": {"id": "sent-003"}, "error": None, "successful": True}
        )
        with patch(ANALYTICS_PATCH) as mock_capture:
            response = await client.post(
                f"{MAIL_BASE}/gmail/send",
                data={
                    "to": "recipient@example.com",
                    "subject": "Hello",
                    "body": "Test email body",
                },
            )

        assert response.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.EMAIL_SENT,
            {"has_attachments": False, "attachment_count": 0},
        )

    @patch("app.api.v1.endpoints.mail.log")
    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_with_attachments_captures_attachment_count(
        self, mock_send: AsyncMock, mock_log: AsyncMock, client: AsyncClient
    ):
        """Attachments are reported truthfully in the capture payload."""
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": {"id": "sent-004"}, "error": None, "successful": True}
        )
        with patch(ANALYTICS_PATCH) as mock_capture:
            response = await client.post(
                f"{MAIL_BASE}/gmail/send",
                data={
                    "to": "recipient@example.com",
                    "subject": "Hello",
                    "body": "Test email body",
                },
                files={
                    "attachments": (
                        "note.txt",
                        b"hello",
                        "text/plain",
                    )
                },
            )

        assert response.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.EMAIL_SENT,
            {"has_attachments": True, "attachment_count": 1},
        )
        final_set = mock_log.set.call_args_list[-1]
        assert final_set.kwargs == {
            "operation": "send_email",
            "thread_id": None,
            "has_attachment": True,
            "attachments_count": 1,
            "outcome": "success",
        }

    @patch(
        "app.api.v1.endpoints.mail.ainvoke_structured",
        new_callable=AsyncMock,
    )
    async def test_ai_compose_captures_email_composed(
        self, mock_invoke: AsyncMock, client: AsyncClient
    ):
        mock_invoke.return_value = {"subject": "Hi", "body": "Hello there"}
        with (
            patch(
                "app.api.v1.endpoints.mail.search_notes_by_similarity",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            response = await client.post(
                f"{MAIL_BASE}/mail/ai/compose",
                json={"prompt": "Write a follow up"},
            )

        assert response.status_code == 200
        mock_capture.assert_called_once_with(AnalyticsEvents.EMAIL_COMPOSED)

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_email_json_with_cc_bcc(self, mock_send: AsyncMock, client: AsyncClient):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": {"id": "sent-002"}, "error": None, "successful": True}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={
                "to": ["a@test.com"],
                "subject": "CC Test",
                "body": "Body",
                "cc": ["cc@test.com"],
                "bcc": ["bcc@test.com"],
            },
        )
        assert response.status_code == 200

    async def test_send_email_json_missing_to_returns_422(self, client: AsyncClient):
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={"subject": "Test", "body": "Body"},
        )
        assert response.status_code == 422

    async def test_send_email_json_missing_subject_returns_422(self, client: AsyncClient):
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={"to": ["a@test.com"], "body": "Body"},
        )
        assert response.status_code == 422

    async def test_send_email_json_missing_body_returns_422(self, client: AsyncClient):
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={"to": ["a@test.com"], "subject": "Test"},
        )
        assert response.status_code == 422

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_email_json_service_error_returns_500(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.side_effect = Exception("SMTP error")
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={
                "to": ["a@test.com"],
                "subject": "Test",
                "body": "Body",
            },
        )
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/mark-as-read
# ---------------------------------------------------------------------------


class TestMarkAsRead:
    @patch(
        "app.api.v1.endpoints.mail.mark_messages_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_returns_200(self, mock_mark: AsyncMock, client: AsyncClient):
        mock_mark.return_value = [
            GmailMessageResource(id="msg-1"),
            GmailMessageResource(id="msg-2"),
        ]
        response = await client.post(
            f"{MAIL_BASE}/gmail/mark-as-read",
            json={"message_ids": ["msg-1", "msg-2"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["count"] == 2
        assert "msg-1" in data["marked_as_read"]

    async def test_mark_as_read_missing_ids_returns_422(self, client: AsyncClient):
        response = await client.post(f"{MAIL_BASE}/gmail/mark-as-read", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/mark-as-unread
# ---------------------------------------------------------------------------


class TestMarkAsUnread:
    @patch(
        "app.api.v1.endpoints.mail.mark_messages_as_unread",
        new_callable=AsyncMock,
    )
    async def test_mark_as_unread_returns_200(self, mock_mark: AsyncMock, client: AsyncClient):
        mock_mark.return_value = [GmailMessageResource(id="msg-1")]
        response = await client.post(
            f"{MAIL_BASE}/gmail/mark-as-unread",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["count"] == 1


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/star
# ---------------------------------------------------------------------------


class TestStarEmails:
    @patch(
        "app.api.v1.endpoints.mail.star_messages",
        new_callable=AsyncMock,
    )
    async def test_star_emails_returns_200(self, mock_star: AsyncMock, client: AsyncClient):
        mock_star.return_value = [GmailMessageResource(id="msg-1")]
        response = await client.post(
            f"{MAIL_BASE}/gmail/star",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "msg-1" in data["starred"]

    @patch(
        "app.api.v1.endpoints.mail.star_messages",
        new_callable=AsyncMock,
    )
    async def test_star_emails_service_error_returns_500(
        self, mock_star: AsyncMock, client: AsyncClient
    ):
        mock_star.side_effect = Exception("API error")
        response = await client.post(
            f"{MAIL_BASE}/gmail/star",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/unstar
# ---------------------------------------------------------------------------


class TestUnstarEmails:
    @patch(
        "app.api.v1.endpoints.mail.unstar_messages",
        new_callable=AsyncMock,
    )
    async def test_unstar_emails_returns_200(self, mock_unstar: AsyncMock, client: AsyncClient):
        mock_unstar.return_value = [GmailMessageResource(id="msg-1")]
        response = await client.post(
            f"{MAIL_BASE}/gmail/unstar",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/trash
# ---------------------------------------------------------------------------


class TestTrashEmails:
    @patch(
        "app.api.v1.endpoints.mail.trash_messages",
        new_callable=AsyncMock,
    )
    async def test_trash_returns_200(self, mock_trash: AsyncMock, client: AsyncClient):
        mock_trash.return_value = [{"id": "msg-1"}]
        response = await client.post(
            f"{MAIL_BASE}/gmail/trash",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert "msg-1" in response.json()["trashed"]


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/untrash
# ---------------------------------------------------------------------------


class TestUntrashEmails:
    @patch(
        "app.api.v1.endpoints.mail.untrash_messages",
        new_callable=AsyncMock,
    )
    async def test_untrash_returns_200(self, mock_untrash: AsyncMock, client: AsyncClient):
        mock_untrash.return_value = [{"id": "msg-1"}]
        response = await client.post(
            f"{MAIL_BASE}/gmail/untrash",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert "msg-1" in response.json()["restored"]


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/archive
# ---------------------------------------------------------------------------


class TestArchiveEmails:
    @patch(
        "app.api.v1.endpoints.mail.archive_messages",
        new_callable=AsyncMock,
    )
    async def test_archive_returns_200(self, mock_archive: AsyncMock, client: AsyncClient):
        mock_archive.return_value = [GmailMessageResource(id="msg-1")]
        response = await client.post(
            f"{MAIL_BASE}/gmail/archive",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert "msg-1" in response.json()["archived"]


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/move-to-inbox
# ---------------------------------------------------------------------------


class TestMoveToInbox:
    @patch(
        "app.api.v1.endpoints.mail.move_to_inbox",
        new_callable=AsyncMock,
    )
    async def test_move_to_inbox_returns_200(self, mock_move: AsyncMock, client: AsyncClient):
        mock_move.return_value = [GmailMessageResource(id="msg-1")]
        response = await client.post(
            f"{MAIL_BASE}/gmail/move-to-inbox",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert "msg-1" in response.json()["moved_to_inbox"]


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/thread/{thread_id}
# ---------------------------------------------------------------------------


class TestGetThread:
    @patch(
        "app.api.v1.endpoints.mail.fetch_thread",
        new_callable=AsyncMock,
    )
    async def test_get_thread_returns_200(self, mock_fetch: AsyncMock, client: AsyncClient):
        mock_fetch.return_value = GmailToolResult(
            messages=[
                {"id": "msg-1", "threadId": "thread-1"},
                {"id": "msg-2", "threadId": "thread-1"},
            ]
        )
        response = await client.get(f"{MAIL_BASE}/gmail/thread/thread-1")
        assert response.status_code == 200
        data = response.json()
        assert data["thread_id"] == "thread-1"
        assert data["messages_count"] == 2

    @patch(
        "app.api.v1.endpoints.mail.fetch_thread",
        new_callable=AsyncMock,
    )
    async def test_get_thread_service_error_returns_500(
        self, mock_fetch: AsyncMock, client: AsyncClient
    ):
        mock_fetch.side_effect = Exception("Thread not found")
        response = await client.get(f"{MAIL_BASE}/gmail/thread/bad-id")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/labels (create)
# ---------------------------------------------------------------------------


class TestCreateLabel:
    @patch(
        "app.api.v1.endpoints.mail.create_label",
        new_callable=AsyncMock,
    )
    async def test_create_label_returns_200(self, mock_create: AsyncMock, client: AsyncClient):
        mock_create.return_value = GmailToolResult.model_validate(
            {"id": "Label_1", "name": "Important"}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/labels",
            json={"name": "Important"},
        )
        assert response.status_code == 200
        assert response.json()["id"] == "Label_1"

    async def test_create_label_missing_name_returns_422(self, client: AsyncClient):
        response = await client.post(f"{MAIL_BASE}/gmail/labels", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/v1/gmail/labels/{label_id}
# ---------------------------------------------------------------------------


class TestUpdateLabel:
    @patch(
        "app.api.v1.endpoints.mail.update_label_service",
        new_callable=AsyncMock,
    )
    async def test_update_label_returns_200(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.return_value = GmailToolResult.model_validate(
            {"id": "Label_1", "name": "Renamed"}
        )
        response = await client.put(
            f"{MAIL_BASE}/gmail/labels/Label_1",
            json={"name": "Renamed"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Renamed"


# ---------------------------------------------------------------------------
# DELETE /api/v1/gmail/labels/{label_id}
# ---------------------------------------------------------------------------


class TestDeleteLabel:
    @patch(
        "app.api.v1.endpoints.mail.delete_label",
        new_callable=AsyncMock,
    )
    async def test_delete_label_success(self, mock_delete: AsyncMock, client: AsyncClient):
        mock_delete.return_value = True
        response = await client.delete(f"{MAIL_BASE}/gmail/labels/Label_1")
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch(
        "app.api.v1.endpoints.mail.delete_label",
        new_callable=AsyncMock,
    )
    async def test_delete_label_failure(self, mock_delete: AsyncMock, client: AsyncClient):
        mock_delete.return_value = False
        response = await client.delete(f"{MAIL_BASE}/gmail/labels/Label_1")
        assert response.status_code == 200
        assert response.json()["status"] == "error"


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/messages/apply-label
# ---------------------------------------------------------------------------


class TestApplyLabels:
    @patch(
        "app.api.v1.endpoints.mail.apply_labels",
        new_callable=AsyncMock,
    )
    async def test_apply_labels_returns_200(self, mock_apply: AsyncMock, client: AsyncClient):
        mock_apply.return_value = [GmailMessageResource(id="msg-1")]
        response = await client.post(
            f"{MAIL_BASE}/gmail/messages/apply-label",
            json={"message_ids": ["msg-1"], "label_ids": ["Label_1"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    async def test_apply_labels_missing_fields_returns_422(self, client: AsyncClient):
        response = await client.post(
            f"{MAIL_BASE}/gmail/messages/apply-label",
            json={"message_ids": ["msg-1"]},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/messages/remove-label
# ---------------------------------------------------------------------------


class TestRemoveLabels:
    @patch(
        "app.api.v1.endpoints.mail.remove_labels",
        new_callable=AsyncMock,
    )
    async def test_remove_labels_returns_200(self, mock_remove: AsyncMock, client: AsyncClient):
        mock_remove.return_value = [GmailMessageResource(id="msg-1")]
        response = await client.post(
            f"{MAIL_BASE}/gmail/messages/remove-label",
            json={"message_ids": ["msg-1"], "label_ids": ["Label_1"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/drafts (create)
# ---------------------------------------------------------------------------


class TestCreateDraft:
    @patch(
        "app.api.v1.endpoints.mail.create_draft",
        new_callable=AsyncMock,
    )
    async def test_create_draft_returns_200(self, mock_create: AsyncMock, client: AsyncClient):
        mock_create.return_value = GmailToolResult.model_validate(
            {"id": "draft-001", "message": {"id": "msg-draft-001"}}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/drafts",
            json={
                "to": ["recipient@test.com"],
                "subject": "Draft Subject",
                "body": "Draft Body",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["draft_id"] == "draft-001"
        assert data["status"] == "Draft created successfully"

    async def test_create_draft_missing_to_returns_422(self, client: AsyncClient):
        response = await client.post(
            f"{MAIL_BASE}/gmail/drafts",
            json={"subject": "Test", "body": "Body"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/drafts
# ---------------------------------------------------------------------------


class TestListDrafts:
    @patch(
        "app.api.v1.endpoints.mail.list_drafts",
        new_callable=AsyncMock,
    )
    async def test_list_drafts_returns_200(self, mock_list: AsyncMock, client: AsyncClient):
        mock_list.return_value = GmailDraftsResponse(drafts=[{"id": "draft-001"}])
        response = await client.get(f"{MAIL_BASE}/gmail/drafts")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/drafts/{draft_id}
# ---------------------------------------------------------------------------


class TestGetDraft:
    @patch(
        "app.api.v1.endpoints.mail.get_draft",
        new_callable=AsyncMock,
    )
    async def test_get_draft_returns_200(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.return_value = GmailToolResult.model_validate(
            {"id": "draft-001", "message": {"id": "msg-001"}}
        )
        response = await client.get(f"{MAIL_BASE}/gmail/drafts/draft-001")
        assert response.status_code == 200

    @patch(
        "app.api.v1.endpoints.mail.get_draft",
        new_callable=AsyncMock,
    )
    async def test_get_draft_error_returns_500(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.side_effect = Exception("Not found")
        response = await client.get(f"{MAIL_BASE}/gmail/drafts/bad-id")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# PUT /api/v1/gmail/drafts/{draft_id}
# ---------------------------------------------------------------------------


class TestUpdateDraft:
    @patch(
        "app.api.v1.endpoints.mail.update_draft",
        new_callable=AsyncMock,
    )
    async def test_update_draft_returns_200(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.return_value = GmailToolResult.model_validate(
            {"id": "draft-001", "message": {"id": "msg-updated"}}
        )
        response = await client.put(
            f"{MAIL_BASE}/gmail/drafts/draft-001",
            json={
                "to": ["new@test.com"],
                "subject": "Updated",
                "body": "Updated body",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "Draft updated successfully"


# ---------------------------------------------------------------------------
# DELETE /api/v1/gmail/drafts/{draft_id}
# ---------------------------------------------------------------------------


class TestDeleteDraft:
    @patch(
        "app.api.v1.endpoints.mail.delete_draft",
        new_callable=AsyncMock,
    )
    async def test_delete_draft_success(self, mock_delete: AsyncMock, client: AsyncClient):
        mock_delete.return_value = True
        response = await client.delete(f"{MAIL_BASE}/gmail/drafts/draft-001")
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch(
        "app.api.v1.endpoints.mail.delete_draft",
        new_callable=AsyncMock,
    )
    async def test_delete_draft_failure(self, mock_delete: AsyncMock, client: AsyncClient):
        mock_delete.return_value = False
        response = await client.delete(f"{MAIL_BASE}/gmail/drafts/draft-001")
        assert response.status_code == 200
        assert response.json()["status"] == "error"


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/drafts/{draft_id}/send
# ---------------------------------------------------------------------------


class TestSendDraft:
    @patch(
        "app.api.v1.endpoints.mail.send_draft",
        new_callable=AsyncMock,
    )
    async def test_send_draft_returns_200(self, mock_send: AsyncMock, client: AsyncClient):
        mock_send.return_value = GmailToolResult.model_validate(
            {"successful": True, "id": "sent-001", "threadId": "thread-001"}
        )
        with patch(ANALYTICS_PATCH) as mock_capture:
            response = await client.post(f"{MAIL_BASE}/gmail/drafts/draft-001/send")
        mock_capture.assert_called_once_with(AnalyticsEvents.EMAIL_SENT)
        assert response.status_code == 200
        data = response.json()
        assert data["successful"] is True
        assert data["status"] == "Draft sent successfully"

    @patch(
        "app.api.v1.endpoints.mail.send_draft",
        new_callable=AsyncMock,
    )
    async def test_send_draft_failure_returns_500(self, mock_send: AsyncMock, client: AsyncClient):
        mock_send.return_value = GmailToolResult.model_validate(
            {"successful": False, "error": "Draft expired"}
        )
        response = await client.post(f"{MAIL_BASE}/gmail/drafts/draft-001/send")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/importance-summaries
# ---------------------------------------------------------------------------


class TestGetImportanceSummaries:
    @patch(
        "app.api.v1.endpoints.mail.get_importance_summaries_service",
        new_callable=AsyncMock,
    )
    async def test_returns_200(self, mock_svc: AsyncMock, client: AsyncClient):
        mock_svc.return_value = EmailImportanceSummariesResponse(
            status="success", emails=[], count=0, filtered_by_importance=False
        )
        response = await client.get(f"{MAIL_BASE}/gmail/importance-summaries")
        assert response.status_code == 200
        # Asserted against a literal, not the model: this is the wire contract
        # the web client reads, and it must not move when the service's return
        # type does.
        assert response.json() == {
            "status": "success",
            "emails": [],
            "count": 0,
            "filtered_by_importance": False,
        }

    @patch(
        "app.api.v1.endpoints.mail.get_importance_summaries_service",
        new_callable=AsyncMock,
    )
    async def test_with_params(self, mock_svc: AsyncMock, client: AsyncClient):
        mock_svc.return_value = EmailImportanceSummariesResponse(
            status="success", emails=[], count=0, filtered_by_importance=True
        )
        response = await client.get(
            f"{MAIL_BASE}/gmail/importance-summaries",
            params={"limit": 10, "important_only": True},
        )
        assert response.status_code == 200
        assert response.json() == {
            "status": "success",
            "emails": [],
            "count": 0,
            "filtered_by_importance": True,
        }


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/importance-summary/{message_id}
# ---------------------------------------------------------------------------


class TestGetSingleImportanceSummary:
    @patch(
        "app.api.v1.endpoints.mail.get_single_importance_summary_service",
        new_callable=AsyncMock,
    )
    async def test_returns_200(self, mock_svc: AsyncMock, client: AsyncClient):
        mock_svc.return_value = EmailImportanceSummaryResponse(
            status="success",
            email={
                "is_important": True,
                "importance_level": "HIGH",
                "summary": "Action required",
            },
        )
        response = await client.get(f"{MAIL_BASE}/gmail/importance-summary/msg-1")
        assert response.status_code == 200
        assert response.json() == {
            "status": "success",
            "email": {
                "is_important": True,
                "importance_level": "HIGH",
                "summary": "Action required",
            },
        }

    @patch(
        "app.api.v1.endpoints.mail.get_single_importance_summary_service",
        new_callable=AsyncMock,
    )
    async def test_not_found_returns_404(self, mock_svc: AsyncMock, client: AsyncClient):
        mock_svc.return_value = None
        response = await client.get(f"{MAIL_BASE}/gmail/importance-summary/nonexistent")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/importance-summaries/bulk
# ---------------------------------------------------------------------------


class TestBulkImportanceSummaries:
    @patch(
        "app.api.v1.endpoints.mail.get_bulk_importance_summaries_service",
        new_callable=AsyncMock,
    )
    async def test_returns_200(self, mock_svc: AsyncMock, client: AsyncClient):
        mock_svc.return_value = BulkEmailImportanceSummariesResponse(
            status="success",
            emails={},
            found_count=0,
            missing_count=2,
            found_message_ids=[],
            missing_message_ids=["msg-1", "msg-2"],
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/importance-summaries/bulk",
            json={"message_ids": ["msg-1", "msg-2"]},
        )
        assert response.status_code == 200
        assert response.json() == {
            "status": "success",
            "emails": {},
            "found_count": 0,
            "missing_count": 2,
            "found_message_ids": [],
            "missing_message_ids": ["msg-1", "msg-2"],
        }

    async def test_missing_message_ids_returns_422(self, client: AsyncClient):
        response = await client.post(
            f"{MAIL_BASE}/gmail/importance-summaries/bulk",
            json={},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# _build_gmail_query (pure helper behind GET /gmail/search)
# ---------------------------------------------------------------------------


class TestBuildGmailQuery:
    def test_query_only(self) -> None:
        assert _build_gmail_query(GmailSearchFilters(query="invoice")) == "invoice"

    def test_all_prefixed_filters_joined_in_order(self) -> None:
        filters = GmailSearchFilters(
            query="report",
            sender="boss@company.com",
            recipient="me@company.com",
            subject="Q3",
            attachment_type="pdf",
            date_from="2026/01/01",
            date_to="2026/02/01",
            label="Work",
        )
        assert (
            _build_gmail_query(filters) == "report"
            " from:boss@company.com"
            " to:me@company.com"
            " subject:Q3"
            " filename:pdf"
            " after:2026/01/01"
            " before:2026/02/01"
            " label:Work"
        )

    @pytest.mark.parametrize(
        ("has_attachment", "expected"),
        [(True, "has:attachment"), (False, "-has:attachment")],
    )
    def test_has_attachment_flag(self, has_attachment: bool, expected: str) -> None:
        assert _build_gmail_query(GmailSearchFilters(has_attachment=has_attachment)) == expected

    def test_has_attachment_none_omits_flag(self) -> None:
        assert _build_gmail_query(GmailSearchFilters(has_attachment=None)) == ""

    @pytest.mark.parametrize(
        ("is_read", "expected"),
        [(True, "is:read"), (False, "is:unread")],
    )
    def test_read_flag(self, is_read: bool, expected: str) -> None:
        assert _build_gmail_query(GmailSearchFilters(is_read=is_read)) == expected

    def test_no_filters_yields_empty_string(self) -> None:
        assert _build_gmail_query(GmailSearchFilters()) == ""


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/search — service-call contract
# ---------------------------------------------------------------------------


class TestSearchEmailsQueryContract:
    @patch("app.api.v1.endpoints.mail.log")
    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_passes_built_query_and_capped_results(
        self, mock_search: AsyncMock, mock_log: AsyncMock, client: AsyncClient
    ):
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "m-1"}, {"id": "m-2"}])
        response = await client.get(
            f"{MAIL_BASE}/gmail/search",
            params={
                "query": "invoice",
                "sender": "boss@company.com",
                "label": "Work",
                "max_results": 100,
                "page_token": "tok-1",
            },
        )
        assert response.status_code == 200
        kwargs = mock_search.call_args.kwargs
        assert kwargs["query"] == "invoice from:boss@company.com label:Work"
        assert kwargs["max_results"] == 20
        assert kwargs["page_token"] == "tok-1"

        first_set = mock_log.set.call_args_list[0]
        assert first_set.kwargs["operation"] == "search_emails"
        assert first_set.kwargs["user"]["id"]

        final_set = mock_log.set.call_args_list[-1]
        assert final_set.kwargs == {
            "operation": "search_emails",
            "result_count": 2,
            "has_attachment": None,
            "label": "Work",
            "outcome": "success",
        }

    @patch("app.api.v1.endpoints.mail.log")
    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_passes_max_results_through_under_cap(
        self, mock_search: AsyncMock, mock_log: AsyncMock, client: AsyncClient
    ):
        mock_search.return_value = GmailMessagesResponse(messages=[])
        response = await client.get(
            f"{MAIL_BASE}/gmail/search",
            params={"query": "test", "max_results": 5},
        )
        assert response.status_code == 200
        kwargs = mock_search.call_args.kwargs
        assert kwargs["max_results"] == 5
        assert kwargs["page_token"] is None

        final_set = mock_log.set.call_args_list[-1]
        assert final_set.kwargs["result_count"] == 0


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/send — form-parsing and service-call contract
# ---------------------------------------------------------------------------


class TestSendEmailRouteContract:
    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_splits_recipients_and_forwards_form_fields(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": {"id": "sent-100"}, "error": None, "successful": True}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/send",
            data={
                "to": "a@x.com, b@x.com ,c@x.com",
                "subject": "Hello",
                "body": "Body",
                "cc": "cc1@x.com, cc2@x.com",
                "bcc": "bcc1@x.com, bcc2@x.com",
                "thread_id": "thread-42",
            },
            files={"attachments": ("note.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 200
        assert response.json() == {
            "message_id": "sent-100",
            "status": "Email sent successfully",
            "attachments_count": 1,
        }
        kwargs = mock_send.call_args.kwargs
        assert kwargs["to"] == "a@x.com"
        content = kwargs["content"]
        assert content.subject == "Hello"
        assert content.body == "Body"
        assert content.extra_recipients == ["b@x.com", "c@x.com"]
        assert content.cc_list == ["cc1@x.com", "cc2@x.com"]
        assert content.bcc_list == ["bcc1@x.com", "bcc2@x.com"]
        assert len(kwargs["attachments"]) == 1
        assert kwargs["thread_id"] == "thread-42"

    @patch("app.api.v1.endpoints.mail.log")
    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_without_cc_bcc_thread_attachments_passes_none(
        self, mock_send: AsyncMock, mock_log: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": {"id": "sent-101"}, "error": None, "successful": True}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/send",
            data={"to": "solo@x.com", "subject": "Hi", "body": "Body"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "message_id": "sent-101",
            "status": "Email sent successfully",
            "attachments_count": 0,
        }
        kwargs = mock_send.call_args.kwargs
        content = kwargs["content"]
        assert content.extra_recipients == []
        assert content.cc_list is None
        assert content.bcc_list is None
        assert kwargs["attachments"] is None
        assert kwargs["thread_id"] is None

        final_set = mock_log.set.call_args_list[-1]
        assert final_set.kwargs == {
            "operation": "send_email",
            "thread_id": None,
            "has_attachment": False,
            "attachments_count": 0,
            "outcome": "success",
        }

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_unsuccessful_result_returns_error_detail(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": None, "error": "quota exceeded", "successful": False}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/send",
            data={"to": "a@x.com", "subject": "Hi", "body": "Body"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "quota exceeded"


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/send-json — request-mapping and failure contract
# ---------------------------------------------------------------------------


class TestSendEmailJsonContract:
    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_json_send_maps_request_fields_exactly(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": {"id": "sent-200"}, "error": None, "successful": True}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={
                "to": ["first@t.com", "second@t.com"],
                "subject": "S",
                "body": "B",
                "cc": ["cc@t.com"],
                "bcc": ["bcc@t.com"],
            },
        )
        assert response.status_code == 200
        kwargs = mock_send.call_args.kwargs
        assert kwargs["to"] == "first@t.com"
        content = kwargs["content"]
        assert content.subject == "S"
        assert content.body == "B"
        assert content.extra_recipients == ["second@t.com"]
        assert content.cc_list == ["cc@t.com"]
        assert content.bcc_list == ["bcc@t.com"]

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_json_send_unsuccessful_returns_error_detail(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": None, "error": "invalid recipient", "successful": False}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={"to": ["a@t.com"], "subject": "S", "body": "B"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "invalid recipient"


# ---------------------------------------------------------------------------
# PUT /api/v1/gmail/labels/{label_id} — service-call contract
# ---------------------------------------------------------------------------


class TestUpdateLabelRouteContract:
    @patch(
        "app.api.v1.endpoints.mail.update_label_service",
        new_callable=AsyncMock,
    )
    async def test_update_label_forwards_label_id_and_changes(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        payload = {
            "id": "Label_9",
            "name": "Renamed",
            "labelListVisibility": "labelHide",
            "messageListVisibility": "hide",
            "color": {"backgroundColor": "#fb4c2f", "textColor": "#000000"},
        }
        mock_update.return_value = GmailToolResult.model_validate(payload)
        response = await client.put(
            f"{MAIL_BASE}/gmail/labels/Label_9",
            json={
                "name": "Renamed",
                "label_list_visibility": "labelHide",
                "message_list_visibility": "hide",
                "background_color": "#fb4c2f",
                "text_color": "#000000",
            },
        )
        assert response.status_code == 200
        assert response.json() == payload
        mock_update.assert_called_once()
        kwargs = mock_update.call_args.kwargs
        assert kwargs["label_id"] == "Label_9"
        changes = kwargs["changes"]
        assert changes.name == "Renamed"
        assert changes.label_list_visibility == "labelHide"
        assert changes.message_list_visibility == "hide"
        assert changes.background_color == "#fb4c2f"
        assert changes.text_color == "#000000"


# ---------------------------------------------------------------------------
# PUT /api/v1/gmail/drafts/{draft_id} — service-call contract
# ---------------------------------------------------------------------------


class TestUpdateDraftRouteContract:
    @patch(
        "app.api.v1.endpoints.mail.update_draft",
        new_callable=AsyncMock,
    )
    async def test_update_draft_forwards_request_fields(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        mock_update.return_value = GmailToolResult.model_validate(
            {"id": "draft-77", "message": {"id": "msg-77"}}
        )
        response = await client.put(
            f"{MAIL_BASE}/gmail/drafts/draft-77",
            json={
                "to": ["new1@t.com", "new2@t.com"],
                "subject": "Updated S",
                "body": "Updated B",
                "cc": ["dcc@t.com"],
                "bcc": ["dbcc@t.com"],
            },
        )
        assert response.status_code == 200
        assert response.json() == {
            "draft_id": "draft-77",
            "message_id": "msg-77",
            "status": "Draft updated successfully",
        }
        mock_update.assert_called_once()
        kwargs = mock_update.call_args.kwargs
        assert kwargs["draft_id"] == "draft-77"
        assert kwargs["to_list"] == ["new1@t.com", "new2@t.com"]
        content = kwargs["content"]
        assert content.subject == "Updated S"
        assert content.body == "Updated B"
        assert content.cc_list == ["dcc@t.com"]
        assert content.bcc_list == ["dbcc@t.com"]
