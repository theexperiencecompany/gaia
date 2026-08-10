"""Unit tests for mail (Gmail) API endpoints.

Tests the Gmail endpoints with mocked service layer and integration
dependency to verify routing, status codes, response bodies, and validation.

Every assertion is made against a literal, not the model that produced it:
the wire contract the web client reads must not move when the service's
return type does. Success paths assert the exact JSON body, the exact
arguments the endpoint forwards to the mocked service, and the exact wide
event the endpoint records; failure paths assert the exact status code and
detail string. Together those three assertions pin the whole behaviour of
each thin endpoint.

Gmail endpoints use ``require_integration("gmail")`` which internally calls
``check_integration_status``.  We patch that function to return ``True`` so
the dependency passes without a real Composio/Redis connection.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from httpx import AsyncClient
import pytest

from app.agents.prompts.mail_prompts import EMAIL_COMPOSER
from app.api.v1.endpoints.mail import (
    get_bulk_email_importance_summaries,
    get_email_importance_summaries,
    get_single_email_importance_summary,
    list_drafts_route,
    list_messages,
    process_email,
    search_emails,
    send_email_route,
)
from app.constants.log_tags import LogTag
from app.models.mail_models import (
    BulkEmailImportanceSummariesResponse,
    ComposedEmailOutput,
    EmailActionRequest,
    EmailImportanceSummariesResponse,
    EmailImportanceSummaryResponse,
    EmailRequest,
    GmailDraftsResponse,
    GmailEmailResult,
    GmailLabelsResult,
    GmailMessageResource,
    GmailMessagesResponse,
    GmailToolResult,
)

MAIL_BASE = "/api/v1"

USER_ID = "507f1f77bcf86cd799439011"

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


@pytest.fixture
def mock_mail_log() -> MagicMock:
    """Capture the endpoint's wide-event writes (``log.set``/``log.error``).

    The wide event fields are part of the observable contract (LogQL queries
    read them), so the tests pin the exact ``log.set`` call each endpoint
    makes. Patching the module binding only — the middleware and the rate
    limiter keep their own bindings.
    """
    with patch("app.api.v1.endpoints.mail.log") as mock_log:
        yield mock_log


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/labels
# ---------------------------------------------------------------------------


class TestListLabels:
    @patch(
        "app.api.v1.endpoints.mail.list_labels_service",
        new_callable=AsyncMock,
    )
    async def test_list_labels_returns_200(
        self, mock_labels: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_labels.return_value = GmailLabelsResult(
            success=True,
            labels=[{"id": "INBOX", "name": "INBOX"}],
            count=1,
        )
        response = await client.get(f"{MAIL_BASE}/gmail/labels")

        assert response.status_code == 200
        assert response.json() == {
            "labels": [{"id": "INBOX", "name": "INBOX"}],
            "count": 1,
        }
        mock_labels.assert_awaited_once_with(user_id=USER_ID)
        mock_mail_log.set.assert_any_call(operation="get_labels")
        mock_mail_log.set.assert_any_call(
            operation="get_labels", result_count=1, outcome="success"
        )

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
        assert response.json() == {"detail": "API error"}

    @patch(
        "app.api.v1.endpoints.mail.list_labels_service",
        new_callable=AsyncMock,
    )
    async def test_list_labels_failure_without_error_uses_default_detail(
        self, mock_labels: AsyncMock, client: AsyncClient
    ):
        mock_labels.return_value = GmailLabelsResult(success=False, error=None)
        response = await client.get(f"{MAIL_BASE}/gmail/labels")

        assert response.status_code == 500
        assert response.json() == {"detail": "Failed to list labels"}

    @patch(
        "app.api.v1.endpoints.mail.list_labels_service",
        new_callable=AsyncMock,
    )
    async def test_list_labels_exception_returns_500(
        self, mock_labels: AsyncMock, client: AsyncClient
    ):
        mock_labels.side_effect = Exception("boom")
        response = await client.get(f"{MAIL_BASE}/gmail/labels")

        assert response.status_code == 500
        assert response.json() == {"detail": "boom"}


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/messages
# ---------------------------------------------------------------------------


class TestListMessages:
    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_list_messages_returns_200(
        self, mock_search: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_search.return_value = GmailMessagesResponse(
            messages=[{"id": "msg-1", "snippet": "Hello"}]
        )
        response = await client.get(f"{MAIL_BASE}/gmail/messages")

        assert response.status_code == 200
        assert response.json() == {
            "messages": [{"id": "msg-1", "snippet": "Hello"}],
            "nextPageToken": None,
        }
        mock_search.assert_awaited_once_with(
            user_id=USER_ID, query="in:inbox", max_results=20, page_token=None
        )
        mock_mail_log.set.assert_any_call(
            operation="list_emails",
            result_count=1,
            folder="inbox",
            outcome="success",
        )

    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_list_messages_with_pagination(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.return_value = GmailMessagesResponse(
            messages=[{"id": "msg-2"}], next_page_token="token-abc"
        )
        response = await client.get(
            f"{MAIL_BASE}/gmail/messages",
            params={"max_results": 10, "pageToken": "prev-token"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "messages": [{"id": "msg-2"}],
            "nextPageToken": "token-abc",
        }
        mock_search.assert_awaited_once_with(
            user_id=USER_ID, query="in:inbox", max_results=10, page_token="prev-token"
        )

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
        assert response.json() == {"detail": "Gmail API error"}

    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_list_messages_default_max_results_is_20(
        self, mock_search: AsyncMock
    ) -> None:
        # Direct call: FastAPI reflects the route signature at decoration time,
        # so an HTTP request can never see the function's own defaults. This
        # pins the function contract for non-route callers.
        mock_search.return_value = GmailMessagesResponse(messages=[])
        await list_messages(user_id=USER_ID)

        mock_search.assert_awaited_once_with(
            user_id=USER_ID, query="in:inbox", max_results=20, page_token=None
        )


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/message/{message_id}
# ---------------------------------------------------------------------------


class TestGetEmailById:
    @patch(
        "app.api.v1.endpoints.mail.get_email_by_id_service",
        new_callable=AsyncMock,
    )
    async def test_get_email_returns_200(
        self, mock_get: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_get.return_value = GmailEmailResult(
            success=True,
            message={"id": "msg-1", "subject": "Test"},
        )
        response = await client.get(f"{MAIL_BASE}/gmail/message/msg-1")

        assert response.status_code == 200
        assert response.json() == {
            "message": {"id": "msg-1", "subject": "Test"},
            "status": "Message retrieved successfully",
        }
        mock_get.assert_awaited_once_with(user_id=USER_ID, message_id="msg-1")
        mock_mail_log.set.assert_any_call(operation="get_email", email_id="msg-1")
        mock_mail_log.set.assert_any_call(
            operation="get_email", email_id="msg-1", outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.get_email_by_id_service",
        new_callable=AsyncMock,
    )
    async def test_get_email_not_found_returns_404(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.return_value = GmailEmailResult(
            success=False,
            error="Message not found",
        )
        response = await client.get(f"{MAIL_BASE}/gmail/message/nonexistent")

        assert response.status_code == 404
        assert response.json() == {"detail": "Message not found"}

    @patch(
        "app.api.v1.endpoints.mail.get_email_by_id_service",
        new_callable=AsyncMock,
    )
    async def test_get_email_other_error_returns_500(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.return_value = GmailEmailResult(
            success=False,
            error="Internal failure",
        )
        response = await client.get(f"{MAIL_BASE}/gmail/message/msg-1")

        assert response.status_code == 500
        assert response.json() == {"detail": "Internal failure"}

    @patch(
        "app.api.v1.endpoints.mail.get_email_by_id_service",
        new_callable=AsyncMock,
    )
    async def test_get_email_failure_without_error_uses_default_detail(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.return_value = GmailEmailResult(success=False, error=None)
        response = await client.get(f"{MAIL_BASE}/gmail/message/msg-1")

        assert response.status_code == 500
        assert response.json() == {"detail": "Failed to retrieve message"}

    @patch(
        "app.api.v1.endpoints.mail.get_email_by_id_service",
        new_callable=AsyncMock,
    )
    async def test_get_email_service_failure_returns_500(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.side_effect = Exception("Internal failure")
        response = await client.get(f"{MAIL_BASE}/gmail/message/msg-1")

        assert response.status_code == 500
        assert response.json() == {"detail": "Internal failure"}


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/search
# ---------------------------------------------------------------------------


class TestSearchEmails:
    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_emails_builds_full_query(
        self, mock_search: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_search.return_value = GmailMessagesResponse(
            messages=[{"id": "msg-1", "snippet": "invoice"}],
            next_page_token="tok",
        )
        response = await client.get(
            f"{MAIL_BASE}/gmail/search",
            params={
                "query": "invoice",
                "sender": "boss@company.com",
                "recipient": "me@company.com",
                "subject": "Quarterly",
                "has_attachment": True,
                "attachment_type": "pdf",
                "date_from": "2024/01/01",
                "date_to": "2024/12/31",
                "label": "Work",
                "is_read": True,
                "max_results": 5,
                "page_token": "next",
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "messages": [{"id": "msg-1", "snippet": "invoice"}],
            "nextPageToken": "tok",
        }
        mock_search.assert_awaited_once_with(
            user_id=USER_ID,
            query=(
                "invoice from:boss@company.com to:me@company.com subject:Quarterly "
                "has:attachment filename:pdf after:2024/01/01 before:2024/12/31 "
                "label:Work is:read"
            ),
            max_results=5,
            page_token="next",
        )
        mock_mail_log.set.assert_any_call(
            operation="search_emails",
            result_count=1,
            has_attachment=True,
            label="Work",
            outcome="success",
        )

    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_emails_negated_filters(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.return_value = GmailMessagesResponse(messages=[])
        response = await client.get(
            f"{MAIL_BASE}/gmail/search",
            params={"has_attachment": False, "is_read": False},
        )

        assert response.status_code == 200
        mock_search.assert_awaited_once_with(
            user_id=USER_ID,
            query="-has:attachment is:unread",
            max_results=20,
            page_token=None,
        )

    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_emails_without_filters_uses_empty_query(
        self, mock_search: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_search.return_value = GmailMessagesResponse(messages=[])
        response = await client.get(f"{MAIL_BASE}/gmail/search")

        assert response.status_code == 200
        mock_search.assert_awaited_once_with(
            user_id=USER_ID, query="", max_results=20, page_token=None
        )
        mock_mail_log.set.assert_any_call(
            operation="search_emails",
            result_count=0,
            has_attachment=None,
            label=None,
            outcome="success",
        )

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

    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_emails_default_max_results_is_20(
        self, mock_search: AsyncMock
    ) -> None:
        # Direct call: FastAPI reflects the route signature at decoration time,
        # so an HTTP request can never see the function's own defaults. This
        # pins the function contract for non-route callers.
        mock_search.return_value = GmailMessagesResponse(messages=[])
        await search_emails(user_id=USER_ID)

        mock_search.assert_awaited_once_with(
            user_id=USER_ID, query="", max_results=20, page_token=None
        )

    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_emails_service_error_returns_500(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.side_effect = Exception("Gmail API error")
        response = await client.get(f"{MAIL_BASE}/gmail/search", params={"query": "x"})

        assert response.status_code == 500
        assert response.json() == {"detail": "Gmail API error"}


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/send (multipart form)
# ---------------------------------------------------------------------------


class TestSendEmailRoute:
    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_route_returns_200_with_attachments(
        self, mock_send: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": {"id": "sent-001"}, "error": None, "successful": True}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/send",
            data={
                "to": "a@test.com, b@test.com",
                "subject": "Subject",
                "body": "Body",
                "thread_id": "thread-1",
                "cc": "cc1@test.com, cc2@test.com",
                "bcc": "bcc1@test.com, bcc2@test.com",
            },
            files=[
                ("attachments", ("a.txt", b"data-a", "text/plain")),
                ("attachments", ("b.txt", b"data-b", "text/plain")),
            ],
        )

        assert response.status_code == 200
        assert response.json() == {
            "message_id": "sent-001",
            "status": "Email sent successfully",
            "attachments_count": 2,
        }
        mock_send.assert_awaited_once()
        call_kwargs = mock_send.await_args.kwargs
        assert call_kwargs["user_id"] == USER_ID
        assert call_kwargs["to"] == "a@test.com"
        assert call_kwargs["extra_recipients"] == ["b@test.com"]
        assert call_kwargs["subject"] == "Subject"
        assert call_kwargs["body"] == "Body"
        assert call_kwargs["cc_list"] == ["cc1@test.com", "cc2@test.com"]
        assert call_kwargs["bcc_list"] == ["bcc1@test.com", "bcc2@test.com"]
        assert call_kwargs["thread_id"] == "thread-1"
        attachments = call_kwargs["attachments"]
        assert [attachment.filename for attachment in attachments] == ["a.txt", "b.txt"]
        mock_mail_log.set.assert_any_call(
            operation="send_email",
            thread_id="thread-1",
            has_attachment=True,
            attachments_count=2,
            outcome="success",
        )

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_route_single_recipient_uses_defaults(
        self, mock_send: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": {"id": "sent-002"}, "error": None, "successful": True}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/send",
            data={"to": "a@test.com", "subject": "Subject", "body": "Body"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "message_id": "sent-002",
            "status": "Email sent successfully",
            "attachments_count": 0,
        }
        mock_send.assert_awaited_once_with(
            user_id=USER_ID,
            to="a@test.com",
            extra_recipients=[],
            subject="Subject",
            body="Body",
            cc_list=None,
            bcc_list=None,
            attachments=None,
            thread_id=None,
        )
        mock_mail_log.set.assert_any_call(
            operation="send_email",
            thread_id=None,
            has_attachment=False,
            attachments_count=0,
            outcome="success",
        )

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_route_strips_whitespace_and_empty_segments(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": {"id": "sent-003"}, "error": None, "successful": True}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/send",
            data={
                "to": "a@test.com, , b@test.com ,",
                "subject": "Subject",
                "body": "Body",
            },
        )

        assert response.status_code == 200
        mock_send.assert_awaited_once_with(
            user_id=USER_ID,
            to="a@test.com",
            extra_recipients=["b@test.com"],
            subject="Subject",
            body="Body",
            cc_list=None,
            bcc_list=None,
            attachments=None,
            thread_id=None,
        )

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_route_service_failure_returns_500(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": None, "error": "Gmail rejected", "successful": False}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/send",
            data={"to": "a@test.com", "subject": "Subject", "body": "Body"},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Gmail rejected"}

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_route_failure_without_error_uses_default_detail(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": None, "error": None, "successful": False}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/send",
            data={"to": "a@test.com", "subject": "Subject", "body": "Body"},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Failed to send email"}

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_route_service_error_returns_500(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.side_effect = Exception("SMTP down")
        response = await client.post(
            f"{MAIL_BASE}/gmail/send",
            data={"to": "a@test.com", "subject": "Subject", "body": "Body"},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Failed to send email: SMTP down"}

    async def test_send_route_missing_to_returns_422(self, client: AsyncClient):
        response = await client.post(
            f"{MAIL_BASE}/gmail/send",
            data={"subject": "Subject", "body": "Body"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/send-json
# ---------------------------------------------------------------------------


class TestSendEmailJson:
    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_email_json_returns_200(
        self, mock_send: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": {"id": "sent-001"}, "error": None, "successful": True}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={
                "to": ["a@test.com", "b@test.com"],
                "subject": "Hello",
                "body": "Test email body",
                "cc": ["cc@test.com"],
                "bcc": ["bcc@test.com"],
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "message_id": "sent-001",
            "status": "Email sent successfully",
        }
        mock_send.assert_awaited_once_with(
            user_id=USER_ID,
            to="a@test.com",
            extra_recipients=["b@test.com"],
            subject="Hello",
            body="Test email body",
            cc_list=["cc@test.com"],
            bcc_list=["bcc@test.com"],
            attachments=None,
        )
        mock_mail_log.set.assert_any_call(
            operation="send_email", has_attachment=False, outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_email_json_service_failure_returns_500(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": None, "error": "Gmail rejected", "successful": False}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={"to": ["a@test.com"], "subject": "Test", "body": "Body"},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Gmail rejected"}

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_send_email_json_failure_without_error_uses_default_detail(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": None, "error": None, "successful": False}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={"to": ["a@test.com"], "subject": "Test", "body": "Body"},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Failed to send email"}

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
            json={"to": ["a@test.com"], "subject": "Test", "body": "Body"},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Failed to send email: SMTP error"}

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


# ---------------------------------------------------------------------------
# POST /api/v1/mail/ai/compose
# ---------------------------------------------------------------------------


class TestProcessEmail:
    @patch(
        "app.api.v1.endpoints.mail.search_notes_by_similarity",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mail.ainvoke_structured",
        new_callable=AsyncMock,
    )
    async def test_compose_returns_200_with_full_prompt(
        self,
        mock_invoke: AsyncMock,
        mock_notes: AsyncMock,
        mock_mail_log: MagicMock,
        client: AsyncClient,
    ):
        mock_notes.return_value = []
        mock_invoke.return_value = ComposedEmailOutput(
            subject="Re: invoice", body="Here is the email body"
        )
        response = await client.post(
            f"{MAIL_BASE}/mail/ai/compose",
            json={
                "prompt": "Write an email about invoices",
                "subject": "Old subject",
                "body": "Old body",
                "writingStyle": "Friendly",
                "contentLength": "Shorten",
                "clarityOption": "Simplify",
            },
        )

        assert response.status_code == 200
        assert response.json() == {"subject": "Re: invoice", "body": "Here is the email body"}
        mock_notes.assert_awaited_once_with(
            input_text="Write an email about invoices", user_id=USER_ID
        )
        # FAKE_USER carries no onboarding block, so the learned-style slot is
        # empty; the exact prompt pins every value the endpoint formats in.
        expected_prompt = EMAIL_COMPOSER.format(
            sender_name="Test User",
            subject="Old subject",
            body="Old body",
            writing_style="Friendly",
            content_length="Shorten",
            clarity_option="Simplify",
            notes="No relevant notes found.",
            prompt="Write an email about invoices",
            learned_writing_style="",
        )
        mock_invoke.assert_awaited_once_with(
            ComposedEmailOutput,
            expected_prompt,
            label="mail_compose",
            config={"configurable": {"user_id": USER_ID}},
        )
        mock_mail_log.set.assert_any_call(mail={"operation": "compose"})
        mock_mail_log.set.assert_any_call(user={"id": USER_ID})

    @patch(
        "app.api.v1.endpoints.mail.search_notes_by_similarity",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mail.ainvoke_structured",
        new_callable=AsyncMock,
    )
    async def test_compose_uses_defaults_for_missing_fields(
        self,
        mock_invoke: AsyncMock,
        mock_notes: AsyncMock,
        client: AsyncClient,
    ):
        mock_notes.return_value = []
        mock_invoke.return_value = ComposedEmailOutput(subject="S", body="B")
        response = await client.post(
            f"{MAIL_BASE}/mail/ai/compose", json={"prompt": "Write an email"}
        )

        assert response.status_code == 200
        expected_prompt = EMAIL_COMPOSER.format(
            sender_name="Test User",
            subject="empty",
            body="empty",
            writing_style="Professional",
            content_length="None",
            clarity_option="None",
            notes="No relevant notes found.",
            prompt="Write an email",
            learned_writing_style="",
        )
        mock_invoke.assert_awaited_once_with(
            ComposedEmailOutput,
            expected_prompt,
            label="mail_compose",
            config={"configurable": {"user_id": USER_ID}},
        )

    @patch(
        "app.api.v1.endpoints.mail.search_notes_by_similarity",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mail.ainvoke_structured",
        new_callable=AsyncMock,
    )
    async def test_compose_joins_notes_into_prompt(
        self,
        mock_invoke: AsyncMock,
        mock_notes: AsyncMock,
        client: AsyncClient,
    ):
        # The second note has no "content" key: the endpoint must fall back to
        # the empty string rather than crashing the join.
        mock_notes.return_value = [{"content": "note one"}, {"title": "no content"}]
        mock_invoke.return_value = ComposedEmailOutput(subject="S", body="B")
        response = await client.post(
            f"{MAIL_BASE}/mail/ai/compose", json={"prompt": "Write an email"}
        )

        assert response.status_code == 200
        expected_prompt = EMAIL_COMPOSER.format(
            sender_name="Test User",
            subject="empty",
            body="empty",
            writing_style="Professional",
            content_length="None",
            clarity_option="None",
            notes="note one- ",
            prompt="Write an email",
            learned_writing_style="",
        )
        mock_invoke.assert_awaited_once_with(
            ComposedEmailOutput,
            expected_prompt,
            label="mail_compose",
            config={"configurable": {"user_id": USER_ID}},
        )

    @patch(
        "app.api.v1.endpoints.mail.search_notes_by_similarity",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mail.ainvoke_structured",
        new_callable=AsyncMock,
    )
    async def test_compose_formats_learned_writing_style_block(
        self,
        mock_invoke: AsyncMock,
        mock_notes: AsyncMock,
        client: AsyncClient,
    ):
        mock_notes.return_value = []
        mock_invoke.return_value = ComposedEmailOutput(subject="S", body="B")
        # Real format_writing_style_for_prompt: the exact block below is what it
        # renders for this onboarding payload, and the exact prompt pins that
        # the endpoint feeds the onboarding writing style through it.
        learned_block = (
            "Learned Writing Style (match this tone and voice when composing the email):\n"
            "  Style: Concise and direct\n"
            '  Example email in their voice:\n    "Hi\n\nShort paras.\n\nBest\nAda"'
        )

        result = await process_email(
            EmailRequest(prompt="Write an email"),
            current_user={
                "user_id": USER_ID,
                "name": "Ada",
                "onboarding": {
                    "writing_style": {
                        "user_edited_summary": "Concise and direct",
                        "example": {
                            "greeting": "Hi",
                            "body": ["Short paras."],
                            "signoff": "Best",
                            "name": "Ada",
                        },
                    }
                },
            },
        )

        assert result == ComposedEmailOutput(subject="S", body="B")
        expected_prompt = EMAIL_COMPOSER.format(
            sender_name="Ada",
            subject="empty",
            body="empty",
            writing_style="Professional",
            content_length="None",
            clarity_option="None",
            notes="No relevant notes found.",
            prompt="Write an email",
            learned_writing_style=learned_block,
        )
        mock_invoke.assert_awaited_once_with(
            ComposedEmailOutput,
            expected_prompt,
            label="mail_compose",
            config={"configurable": {"user_id": USER_ID}},
        )

    @patch(
        "app.api.v1.endpoints.mail.search_notes_by_similarity",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mail.ainvoke_structured",
        new_callable=AsyncMock,
    )
    async def test_compose_uses_none_sender_name_when_missing(
        self,
        mock_invoke: AsyncMock,
        mock_notes: AsyncMock,
    ) -> None:
        # No "name" key in the auth context: the endpoint must fall back to
        # the literal "none" in the prompt (the wire contract the composer
        # reads), not crash or substitute something else.
        mock_notes.return_value = []
        mock_invoke.return_value = ComposedEmailOutput(subject="S", body="B")

        result = await process_email(
            EmailRequest(prompt="Write an email"),
            current_user={"user_id": USER_ID},
        )

        assert result == ComposedEmailOutput(subject="S", body="B")
        expected_prompt = EMAIL_COMPOSER.format(
            sender_name="none",
            subject="empty",
            body="empty",
            writing_style="Professional",
            content_length="None",
            clarity_option="None",
            notes="No relevant notes found.",
            prompt="Write an email",
            learned_writing_style="",
        )
        mock_invoke.assert_awaited_once_with(
            ComposedEmailOutput,
            expected_prompt,
            label="mail_compose",
            config={"configurable": {"user_id": USER_ID}},
        )

    @patch(
        "app.api.v1.endpoints.mail.search_notes_by_similarity",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mail.ainvoke_structured",
        new_callable=AsyncMock,
    )
    async def test_compose_missing_user_id_is_wrapped_in_500(
        self, mock_invoke: AsyncMock, mock_notes: AsyncMock
    ) -> None:
        mock_notes.return_value = []
        mock_invoke.return_value = ComposedEmailOutput(subject="S", body="B")
        # Direct call: require_integration rejects a user without an id before
        # the handler runs over HTTP. The handler's own 401 guard sits inside
        # the try, and this route has no ``except HTTPException`` re-raise, so
        # the catch-all wraps it: str(HTTPException(401, ...)) is
        # "401: User ID is required" under a 500.
        with pytest.raises(HTTPException) as exc_info:
            await process_email(EmailRequest(prompt="Write an email"), current_user={})
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "401: User ID is required"

    @patch(
        "app.api.v1.endpoints.mail.search_notes_by_similarity",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mail.ainvoke_structured",
        new_callable=AsyncMock,
    )
    async def test_compose_llm_error_returns_500(
        self, mock_invoke: AsyncMock, mock_notes: AsyncMock, client: AsyncClient
    ):
        mock_notes.return_value = []
        mock_invoke.side_effect = Exception("LLM down")
        response = await client.post(
            f"{MAIL_BASE}/mail/ai/compose", json={"prompt": "Write an email"}
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "LLM down"}

    async def test_compose_missing_prompt_returns_422(self, client: AsyncClient):
        response = await client.post(f"{MAIL_BASE}/mail/ai/compose", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/mark-as-read
# ---------------------------------------------------------------------------


class TestMarkAsRead:
    @patch(
        "app.api.v1.endpoints.mail.mark_messages_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_returns_200(
        self, mock_mark: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_mark.return_value = [
            GmailMessageResource(id="msg-1"),
            GmailMessageResource(id="msg-2"),
        ]
        response = await client.post(
            f"{MAIL_BASE}/gmail/mark-as-read",
            json={"message_ids": ["msg-1", "msg-2"]},
        )

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "marked_as_read": ["msg-1", "msg-2"],
            "count": 2,
            "status": "Messages marked as read",
        }
        mock_mark.assert_awaited_once_with(
            user_id=USER_ID, message_ids=["msg-1", "msg-2"]
        )
        mock_mail_log.set.assert_any_call(
            operation="mark_read", result_count=2, outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.mark_messages_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_service_error_returns_500(
        self, mock_mark: AsyncMock, client: AsyncClient
    ):
        mock_mark.side_effect = Exception("API error")
        response = await client.post(
            f"{MAIL_BASE}/gmail/mark-as-read",
            json={"message_ids": ["msg-1"]},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Failed to mark messages as read: API error"}

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
    async def test_mark_as_unread_returns_200(
        self, mock_mark: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_mark.return_value = [
            GmailMessageResource(id="msg-1"),
            GmailMessageResource(id="msg-2"),
        ]
        response = await client.post(
            f"{MAIL_BASE}/gmail/mark-as-unread",
            json={"message_ids": ["msg-1", "msg-2"]},
        )

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "marked_as_unread": ["msg-1", "msg-2"],
            "count": 2,
            "status": "Messages marked as unread",
        }
        mock_mark.assert_awaited_once_with(
            user_id=USER_ID, message_ids=["msg-1", "msg-2"]
        )
        mock_mail_log.set.assert_any_call(
            operation="mark_unread", result_count=2, outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.mark_messages_as_unread",
        new_callable=AsyncMock,
    )
    async def test_mark_as_unread_service_error_returns_500(
        self, mock_mark: AsyncMock, client: AsyncClient
    ):
        mock_mark.side_effect = Exception("API error")
        response = await client.post(
            f"{MAIL_BASE}/gmail/mark-as-unread",
            json={"message_ids": ["msg-1"]},
        )

        assert response.status_code == 500
        assert response.json() == {
            "detail": "Failed to mark messages as unread: API error"
        }


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/star
# ---------------------------------------------------------------------------


class TestStarEmails:
    @patch(
        "app.api.v1.endpoints.mail.star_messages",
        new_callable=AsyncMock,
    )
    async def test_star_emails_returns_200(
        self, mock_star: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_star.return_value = [
            GmailMessageResource(id="msg-1"),
            GmailMessageResource(id="msg-2"),
        ]
        response = await client.post(
            f"{MAIL_BASE}/gmail/star",
            json={"message_ids": ["msg-1", "msg-2"]},
        )

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "starred": ["msg-1", "msg-2"],
            "count": 2,
            "status": "Messages starred",
        }
        mock_star.assert_awaited_once_with(
            user_id=USER_ID, message_ids=["msg-1", "msg-2"]
        )
        mock_mail_log.set.assert_any_call(
            operation="star_emails", result_count=2, outcome="success"
        )

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
        assert response.json() == {"detail": "Failed to star messages: API error"}


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/unstar
# ---------------------------------------------------------------------------


class TestUnstarEmails:
    @patch(
        "app.api.v1.endpoints.mail.unstar_messages",
        new_callable=AsyncMock,
    )
    async def test_unstar_emails_returns_200(
        self, mock_unstar: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_unstar.return_value = [
            GmailMessageResource(id="msg-1"),
            GmailMessageResource(id="msg-2"),
        ]
        response = await client.post(
            f"{MAIL_BASE}/gmail/unstar",
            json={"message_ids": ["msg-1", "msg-2"]},
        )

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "unstarred": ["msg-1", "msg-2"],
            "count": 2,
            "status": "Messages unstarred",
        }
        mock_unstar.assert_awaited_once_with(
            user_id=USER_ID, message_ids=["msg-1", "msg-2"]
        )
        mock_mail_log.set.assert_any_call(
            operation="unstar_emails", result_count=2, outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.unstar_messages",
        new_callable=AsyncMock,
    )
    async def test_unstar_emails_service_error_returns_500(
        self, mock_unstar: AsyncMock, client: AsyncClient
    ):
        mock_unstar.side_effect = Exception("API error")
        response = await client.post(
            f"{MAIL_BASE}/gmail/unstar",
            json={"message_ids": ["msg-1"]},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Failed to unstar messages: API error"}


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/trash
# ---------------------------------------------------------------------------


class TestTrashEmails:
    @patch(
        "app.api.v1.endpoints.mail.trash_messages",
        new_callable=AsyncMock,
    )
    async def test_trash_returns_200(
        self, mock_trash: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_trash.return_value = [{"id": "msg-1"}, {"id": "msg-2"}]
        response = await client.post(
            f"{MAIL_BASE}/gmail/trash",
            json={"message_ids": ["msg-1", "msg-2"]},
        )

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "trashed": ["msg-1", "msg-2"],
            "count": 2,
            "status": "Messages moved to trash",
        }
        mock_trash.assert_awaited_once_with(
            user_id=USER_ID, message_ids=["msg-1", "msg-2"]
        )
        mock_mail_log.set.assert_any_call(
            operation="delete_email", result_count=2, outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.trash_messages",
        new_callable=AsyncMock,
    )
    async def test_trash_service_error_returns_500(
        self, mock_trash: AsyncMock, client: AsyncClient
    ):
        mock_trash.side_effect = Exception("API error")
        response = await client.post(
            f"{MAIL_BASE}/gmail/trash",
            json={"message_ids": ["msg-1"]},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Failed to move messages to trash: API error"}


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/untrash
# ---------------------------------------------------------------------------


class TestUntrashEmails:
    @patch(
        "app.api.v1.endpoints.mail.untrash_messages",
        new_callable=AsyncMock,
    )
    async def test_untrash_returns_200(
        self, mock_untrash: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_untrash.return_value = [{"id": "msg-1"}, {"id": "msg-2"}]
        response = await client.post(
            f"{MAIL_BASE}/gmail/untrash",
            json={"message_ids": ["msg-1", "msg-2"]},
        )

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "restored": ["msg-1", "msg-2"],
            "count": 2,
            "status": "Messages restored from trash",
        }
        mock_untrash.assert_awaited_once_with(
            user_id=USER_ID, message_ids=["msg-1", "msg-2"]
        )
        mock_mail_log.set.assert_any_call(
            operation="untrash_emails", result_count=2, outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.untrash_messages",
        new_callable=AsyncMock,
    )
    async def test_untrash_service_error_returns_500(
        self, mock_untrash: AsyncMock, client: AsyncClient
    ):
        mock_untrash.side_effect = Exception("API error")
        response = await client.post(
            f"{MAIL_BASE}/gmail/untrash",
            json={"message_ids": ["msg-1"]},
        )

        assert response.status_code == 500
        assert response.json() == {
            "detail": "Failed to restore messages from trash: API error"
        }


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/archive
# ---------------------------------------------------------------------------


class TestArchiveEmails:
    @patch(
        "app.api.v1.endpoints.mail.archive_messages",
        new_callable=AsyncMock,
    )
    async def test_archive_returns_200(
        self, mock_archive: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_archive.return_value = [
            GmailMessageResource(id="msg-1"),
            GmailMessageResource(id="msg-2"),
        ]
        response = await client.post(
            f"{MAIL_BASE}/gmail/archive",
            json={"message_ids": ["msg-1", "msg-2"]},
        )

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "archived": ["msg-1", "msg-2"],
            "count": 2,
            "status": "Messages archived",
        }
        mock_archive.assert_awaited_once_with(
            user_id=USER_ID, message_ids=["msg-1", "msg-2"]
        )
        mock_mail_log.set.assert_any_call(
            operation="archive_email", result_count=2, outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.archive_messages",
        new_callable=AsyncMock,
    )
    async def test_archive_service_error_returns_500(
        self, mock_archive: AsyncMock, client: AsyncClient
    ):
        mock_archive.side_effect = Exception("API error")
        response = await client.post(
            f"{MAIL_BASE}/gmail/archive",
            json={"message_ids": ["msg-1"]},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Failed to archive messages: API error"}


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/move-to-inbox
# ---------------------------------------------------------------------------


class TestMoveToInbox:
    @patch(
        "app.api.v1.endpoints.mail.move_to_inbox",
        new_callable=AsyncMock,
    )
    async def test_move_to_inbox_returns_200(
        self, mock_move: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_move.return_value = [
            GmailMessageResource(id="msg-1"),
            GmailMessageResource(id="msg-2"),
        ]
        response = await client.post(
            f"{MAIL_BASE}/gmail/move-to-inbox",
            json={"message_ids": ["msg-1", "msg-2"]},
        )

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "moved_to_inbox": ["msg-1", "msg-2"],
            "count": 2,
            "status": "Messages moved to inbox",
        }
        mock_move.assert_awaited_once_with(
            user_id=USER_ID, message_ids=["msg-1", "msg-2"]
        )
        mock_mail_log.set.assert_any_call(
            operation="move_email",
            folder="inbox",
            result_count=2,
            outcome="success",
        )

    @patch(
        "app.api.v1.endpoints.mail.move_to_inbox",
        new_callable=AsyncMock,
    )
    async def test_move_to_inbox_service_error_returns_500(
        self, mock_move: AsyncMock, client: AsyncClient
    ):
        mock_move.side_effect = Exception("API error")
        response = await client.post(
            f"{MAIL_BASE}/gmail/move-to-inbox",
            json={"message_ids": ["msg-1"]},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Failed to move messages to inbox: API error"}


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/thread/{thread_id}
# ---------------------------------------------------------------------------


class TestGetThread:
    @patch(
        "app.api.v1.endpoints.mail.fetch_thread",
        new_callable=AsyncMock,
    )
    async def test_get_thread_returns_200(
        self, mock_fetch: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_fetch.return_value = GmailToolResult(
            messages=[
                {"id": "msg-1", "threadId": "thread-1"},
                {"id": "msg-2", "threadId": "thread-1"},
            ]
        )
        response = await client.get(f"{MAIL_BASE}/gmail/thread/thread-1")

        assert response.status_code == 200
        assert response.json() == {
            "thread_id": "thread-1",
            "messages_count": 2,
            "thread": {
                "messages": [
                    {"id": "msg-1", "threadId": "thread-1"},
                    {"id": "msg-2", "threadId": "thread-1"},
                ]
            },
        }
        mock_fetch.assert_awaited_once_with(user_id=USER_ID, thread_id="thread-1")
        mock_mail_log.set.assert_any_call(
            operation="get_thread",
            thread_id="thread-1",
            result_count=2,
            outcome="success",
        )

    @patch(
        "app.api.v1.endpoints.mail.fetch_thread",
        new_callable=AsyncMock,
    )
    async def test_get_thread_without_messages_counts_zero(
        self, mock_fetch: AsyncMock, client: AsyncClient
    ):
        mock_fetch.return_value = GmailToolResult(messages=None)
        response = await client.get(f"{MAIL_BASE}/gmail/thread/thread-1")

        assert response.status_code == 200
        assert response.json() == {
            "thread_id": "thread-1",
            "messages_count": 0,
            "thread": {"messages": None},
        }

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
        assert response.json() == {"detail": "Failed to fetch email thread: Thread not found"}


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/labels (create)
# ---------------------------------------------------------------------------


class TestCreateLabel:
    @patch(
        "app.api.v1.endpoints.mail.create_label",
        new_callable=AsyncMock,
    )
    async def test_create_label_uses_default_visibilities_when_null(
        self, mock_create: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_create.return_value = GmailToolResult.model_validate(
            {"id": "Label_1", "name": "Important"}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/labels",
            json={
                "name": "Important",
                "label_list_visibility": None,
                "message_list_visibility": None,
            },
        )

        assert response.status_code == 200
        assert response.json() == {"id": "Label_1", "name": "Important"}
        mock_create.assert_awaited_once_with(
            user_id=USER_ID,
            name="Important",
            label_list_visibility="labelShow",
            message_list_visibility="show",
        )
        mock_mail_log.set.assert_any_call(
            operation="create_label", label="Important", outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.create_label",
        new_callable=AsyncMock,
    )
    async def test_create_label_forwards_explicit_visibilities(
        self, mock_create: AsyncMock, client: AsyncClient
    ):
        mock_create.return_value = GmailToolResult.model_validate(
            {"id": "Label_1", "name": "Hidden"}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/labels",
            json={
                "name": "Hidden",
                "label_list_visibility": "labelHide",
                "message_list_visibility": "hide",
            },
        )

        assert response.status_code == 200
        mock_create.assert_awaited_once_with(
            user_id=USER_ID,
            name="Hidden",
            label_list_visibility="labelHide",
            message_list_visibility="hide",
        )

    @patch(
        "app.api.v1.endpoints.mail.create_label",
        new_callable=AsyncMock,
    )
    async def test_create_label_service_error_returns_500(
        self, mock_create: AsyncMock, client: AsyncClient
    ):
        mock_create.side_effect = Exception("boom")
        response = await client.post(
            f"{MAIL_BASE}/gmail/labels",
            json={"name": "Important"},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "boom"}

    async def test_create_label_missing_name_returns_422(self, client: AsyncClient):
        response = await client.post(f"{MAIL_BASE}/gmail/labels", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/v1/gmail/labels/{label_id}
# ---------------------------------------------------------------------------


class TestUpdateLabel:
    @patch(
        "app.api.v1.endpoints.mail.update_label",
        new_callable=AsyncMock,
    )
    async def test_update_label_returns_200(
        self, mock_update: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_update.return_value = GmailToolResult.model_validate(
            {"id": "Label_1", "name": "Renamed"}
        )
        response = await client.put(
            f"{MAIL_BASE}/gmail/labels/Label_1",
            json={
                "name": "Renamed",
                "label_list_visibility": "labelHide",
                "message_list_visibility": "hide",
            },
        )

        assert response.status_code == 200
        assert response.json() == {"id": "Label_1", "name": "Renamed"}
        mock_update.assert_awaited_once_with(
            user_id=USER_ID,
            label_id="Label_1",
            name="Renamed",
            label_list_visibility="labelHide",
            message_list_visibility="hide",
        )
        mock_mail_log.set.assert_any_call(
            operation="update_label", label="Label_1", outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.update_label",
        new_callable=AsyncMock,
    )
    async def test_update_label_service_error_returns_500(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        mock_update.side_effect = Exception("boom")
        response = await client.put(
            f"{MAIL_BASE}/gmail/labels/Label_1",
            json={"name": "Renamed"},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "boom"}


# ---------------------------------------------------------------------------
# DELETE /api/v1/gmail/labels/{label_id}
# ---------------------------------------------------------------------------


class TestDeleteLabel:
    @patch(
        "app.api.v1.endpoints.mail.delete_label",
        new_callable=AsyncMock,
    )
    async def test_delete_label_success(
        self, mock_delete: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_delete.return_value = True
        response = await client.delete(f"{MAIL_BASE}/gmail/labels/Label_1")

        assert response.status_code == 200
        assert response.json() == {
            "status": "success",
            "message": "Label deleted successfully",
        }
        mock_delete.assert_awaited_once_with(user_id=USER_ID, label_id="Label_1")
        mock_mail_log.set.assert_any_call(operation="delete_label", label="Label_1")
        mock_mail_log.set.assert_any_call(
            operation="delete_label", label="Label_1", outcome="success"
        )
        mock_mail_log.error.assert_not_called()

    @patch(
        "app.api.v1.endpoints.mail.delete_label",
        new_callable=AsyncMock,
    )
    async def test_delete_label_failure_still_returns_200_with_error(
        self, mock_delete: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_delete.return_value = False
        response = await client.delete(f"{MAIL_BASE}/gmail/labels/Label_1")

        assert response.status_code == 200
        assert response.json() == {
            "status": "error",
            "message": "Failed to delete label",
        }
        mock_delete.assert_awaited_once_with(user_id=USER_ID, label_id="Label_1")
        mock_mail_log.error.assert_called_once_with(
            f"{LogTag.MAIL} Label deletion reported failure", label="Label_1"
        )
        mock_mail_log.set.assert_any_call(operation="delete_label", label="Label_1")
        mock_mail_log.set.assert_any_call(outcome="failed")

    @patch(
        "app.api.v1.endpoints.mail.delete_label",
        new_callable=AsyncMock,
    )
    async def test_delete_label_service_error_returns_500(
        self, mock_delete: AsyncMock, client: AsyncClient
    ):
        mock_delete.side_effect = Exception("boom")
        response = await client.delete(f"{MAIL_BASE}/gmail/labels/Label_1")

        assert response.status_code == 500
        assert response.json() == {"detail": "boom"}


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/messages/apply-label
# ---------------------------------------------------------------------------


class TestApplyLabels:
    @patch(
        "app.api.v1.endpoints.mail.apply_labels",
        new_callable=AsyncMock,
    )
    async def test_apply_labels_returns_200(
        self, mock_apply: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_apply.return_value = [
            GmailMessageResource(id="msg-1"),
            GmailMessageResource(id="msg-2"),
        ]
        response = await client.post(
            f"{MAIL_BASE}/gmail/messages/apply-label",
            json={"message_ids": ["msg-1", "msg-2"], "label_ids": ["Label_1"]},
        )

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "modified_messages": ["msg-1", "msg-2"],
            "count": 2,
            "status": "Labels applied successfully",
        }
        mock_apply.assert_awaited_once_with(
            user_id=USER_ID,
            message_ids=["msg-1", "msg-2"],
            label_ids=["Label_1"],
        )
        mock_mail_log.set.assert_any_call(
            operation="apply_label", result_count=2, outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.apply_labels",
        new_callable=AsyncMock,
    )
    async def test_apply_labels_service_error_returns_500(
        self, mock_apply: AsyncMock, client: AsyncClient
    ):
        mock_apply.side_effect = Exception("boom")
        response = await client.post(
            f"{MAIL_BASE}/gmail/messages/apply-label",
            json={"message_ids": ["msg-1"], "label_ids": ["Label_1"]},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "boom"}

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
    async def test_remove_labels_returns_200(
        self, mock_remove: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_remove.return_value = [
            GmailMessageResource(id="msg-1"),
            GmailMessageResource(id="msg-2"),
        ]
        response = await client.post(
            f"{MAIL_BASE}/gmail/messages/remove-label",
            json={"message_ids": ["msg-1", "msg-2"], "label_ids": ["Label_1"]},
        )

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "modified_messages": ["msg-1", "msg-2"],
            "count": 2,
            "status": "Labels removed successfully",
        }
        mock_remove.assert_awaited_once_with(
            user_id=USER_ID,
            message_ids=["msg-1", "msg-2"],
            label_ids=["Label_1"],
        )
        mock_mail_log.set.assert_any_call(
            operation="remove_label", result_count=2, outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.remove_labels",
        new_callable=AsyncMock,
    )
    async def test_remove_labels_service_error_returns_500(
        self, mock_remove: AsyncMock, client: AsyncClient
    ):
        mock_remove.side_effect = Exception("boom")
        response = await client.post(
            f"{MAIL_BASE}/gmail/messages/remove-label",
            json={"message_ids": ["msg-1"], "label_ids": ["Label_1"]},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "boom"}


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/drafts (create)
# ---------------------------------------------------------------------------


class TestCreateDraft:
    @patch(
        "app.api.v1.endpoints.mail.create_draft",
        new_callable=AsyncMock,
    )
    async def test_create_draft_returns_200(
        self, mock_create: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_create.return_value = GmailToolResult.model_validate(
            {"id": "draft-001", "message": {"id": "msg-draft-001"}}
        )
        response = await client.post(
            f"{MAIL_BASE}/gmail/drafts",
            json={
                "to": ["recipient@test.com", "other@test.com"],
                "subject": "Draft Subject",
                "body": "Draft Body",
                "cc": ["cc@test.com"],
                "bcc": ["bcc@test.com"],
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "draft_id": "draft-001",
            "message_id": "msg-draft-001",
            "status": "Draft created successfully",
        }
        mock_create.assert_awaited_once_with(
            user_id=USER_ID,
            to_list=["recipient@test.com", "other@test.com"],
            subject="Draft Subject",
            body="Draft Body",
            cc_list=["cc@test.com"],
            bcc_list=["bcc@test.com"],
        )
        mock_mail_log.set.assert_any_call(
            operation="create_draft", email_id="msg-draft-001", outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.create_draft",
        new_callable=AsyncMock,
    )
    async def test_create_draft_without_message_has_null_message_id(
        self, mock_create: AsyncMock, client: AsyncClient
    ):
        mock_create.return_value = GmailToolResult.model_validate(
            {"id": "draft-001", "message": None}
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
        assert response.json() == {
            "draft_id": "draft-001",
            "message_id": None,
            "status": "Draft created successfully",
        }

    @patch(
        "app.api.v1.endpoints.mail.create_draft",
        new_callable=AsyncMock,
    )
    async def test_create_draft_service_error_returns_500(
        self, mock_create: AsyncMock, client: AsyncClient
    ):
        mock_create.side_effect = Exception("boom")
        response = await client.post(
            f"{MAIL_BASE}/gmail/drafts",
            json={
                "to": ["recipient@test.com"],
                "subject": "Draft Subject",
                "body": "Draft Body",
            },
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "boom"}

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
    async def test_list_drafts_uses_defaults(
        self, mock_list: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_list.return_value = GmailDraftsResponse(
            drafts=[{"id": "draft-001"}], next_page_token="tok"
        )
        response = await client.get(f"{MAIL_BASE}/gmail/drafts")

        assert response.status_code == 200
        assert response.json() == {
            "drafts": [{"id": "draft-001"}],
            "nextPageToken": "tok",
        }
        mock_list.assert_awaited_once_with(
            user_id=USER_ID, max_results=20, page_token=None
        )
        mock_mail_log.set.assert_any_call(
            operation="list_drafts", result_count=1, outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.list_drafts",
        new_callable=AsyncMock,
    )
    async def test_list_drafts_with_pagination(
        self, mock_list: AsyncMock, client: AsyncClient
    ):
        mock_list.return_value = GmailDraftsResponse(drafts=[], next_page_token=None)
        response = await client.get(
            f"{MAIL_BASE}/gmail/drafts",
            params={"max_results": 10, "page_token": "prev"},
        )

        assert response.status_code == 200
        assert response.json() == {"drafts": [], "nextPageToken": None}
        mock_list.assert_awaited_once_with(
            user_id=USER_ID, max_results=10, page_token="prev"
        )

    @patch(
        "app.api.v1.endpoints.mail.list_drafts",
        new_callable=AsyncMock,
    )
    async def test_list_drafts_service_error_returns_500(
        self, mock_list: AsyncMock, client: AsyncClient
    ):
        mock_list.side_effect = Exception("boom")
        response = await client.get(f"{MAIL_BASE}/gmail/drafts")

        assert response.status_code == 500
        assert response.json() == {"detail": "boom"}

    @patch(
        "app.api.v1.endpoints.mail.list_drafts",
        new_callable=AsyncMock,
    )
    async def test_list_drafts_default_max_results_is_20(
        self, mock_list: AsyncMock
    ) -> None:
        # Direct call: see test_list_messages_default_max_results_is_20.
        mock_list.return_value = GmailDraftsResponse(drafts=[], next_page_token=None)
        await list_drafts_route(user_id=USER_ID)

        mock_list.assert_awaited_once_with(
            user_id=USER_ID, max_results=20, page_token=None
        )


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/drafts/{draft_id}
# ---------------------------------------------------------------------------


class TestGetDraft:
    @patch(
        "app.api.v1.endpoints.mail.get_draft",
        new_callable=AsyncMock,
    )
    async def test_get_draft_returns_200(
        self, mock_get: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_get.return_value = GmailToolResult.model_validate(
            {"id": "draft-001", "message": {"id": "msg-001"}}
        )
        response = await client.get(f"{MAIL_BASE}/gmail/drafts/draft-001")

        assert response.status_code == 200
        assert response.json() == {"id": "draft-001", "message": {"id": "msg-001"}}
        mock_get.assert_awaited_once_with(user_id=USER_ID, draft_id="draft-001")
        mock_mail_log.set.assert_any_call(
            operation="get_draft", email_id="draft-001", outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.get_draft",
        new_callable=AsyncMock,
    )
    async def test_get_draft_error_returns_500(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.side_effect = Exception("Not found")
        response = await client.get(f"{MAIL_BASE}/gmail/drafts/bad-id")

        assert response.status_code == 500
        assert response.json() == {"detail": "Not found"}


# ---------------------------------------------------------------------------
# PUT /api/v1/gmail/drafts/{draft_id}
# ---------------------------------------------------------------------------


class TestUpdateDraft:
    @patch(
        "app.api.v1.endpoints.mail.update_draft",
        new_callable=AsyncMock,
    )
    async def test_update_draft_returns_200(
        self, mock_update: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_update.return_value = GmailToolResult.model_validate(
            {"id": "draft-001", "message": {"id": "msg-updated"}}
        )
        response = await client.put(
            f"{MAIL_BASE}/gmail/drafts/draft-001",
            json={
                "to": ["new@test.com", "other@test.com"],
                "subject": "Updated",
                "body": "Updated body",
                "cc": ["cc@test.com"],
                "bcc": ["bcc@test.com"],
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "draft_id": "draft-001",
            "message_id": "msg-updated",
            "status": "Draft updated successfully",
        }
        mock_update.assert_awaited_once_with(
            user_id=USER_ID,
            draft_id="draft-001",
            to_list=["new@test.com", "other@test.com"],
            subject="Updated",
            body="Updated body",
            cc_list=["cc@test.com"],
            bcc_list=["bcc@test.com"],
        )
        mock_mail_log.set.assert_any_call(
            operation="update_draft", email_id="draft-001", outcome="success"
        )

    @patch(
        "app.api.v1.endpoints.mail.update_draft",
        new_callable=AsyncMock,
    )
    async def test_update_draft_service_error_returns_500(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        mock_update.side_effect = Exception("boom")
        response = await client.put(
            f"{MAIL_BASE}/gmail/drafts/draft-001",
            json={
                "to": ["new@test.com"],
                "subject": "Updated",
                "body": "Updated body",
            },
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "boom"}


# ---------------------------------------------------------------------------
# DELETE /api/v1/gmail/drafts/{draft_id}
# ---------------------------------------------------------------------------


class TestDeleteDraft:
    @patch(
        "app.api.v1.endpoints.mail.delete_draft",
        new_callable=AsyncMock,
    )
    async def test_delete_draft_success(
        self, mock_delete: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_delete.return_value = True
        response = await client.delete(f"{MAIL_BASE}/gmail/drafts/draft-001")

        assert response.status_code == 200
        assert response.json() == {
            "status": "success",
            "message": "Draft deleted successfully",
        }
        mock_delete.assert_awaited_once_with(user_id=USER_ID, draft_id="draft-001")
        mock_mail_log.set.assert_any_call(operation="delete_draft", email_id="draft-001")
        mock_mail_log.set.assert_any_call(
            operation="delete_draft", email_id="draft-001", outcome="success"
        )
        mock_mail_log.error.assert_not_called()

    @patch(
        "app.api.v1.endpoints.mail.delete_draft",
        new_callable=AsyncMock,
    )
    async def test_delete_draft_failure_still_returns_200_with_error(
        self, mock_delete: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_delete.return_value = False
        response = await client.delete(f"{MAIL_BASE}/gmail/drafts/draft-001")

        assert response.status_code == 200
        assert response.json() == {
            "status": "error",
            "message": "Failed to delete draft",
        }
        mock_delete.assert_awaited_once_with(user_id=USER_ID, draft_id="draft-001")
        mock_mail_log.error.assert_called_once_with(
            f"{LogTag.MAIL} Draft deletion reported failure", email_id="draft-001"
        )
        mock_mail_log.set.assert_any_call(operation="delete_draft", email_id="draft-001")
        mock_mail_log.set.assert_any_call(outcome="failed")

    @patch(
        "app.api.v1.endpoints.mail.delete_draft",
        new_callable=AsyncMock,
    )
    async def test_delete_draft_service_error_returns_500(
        self, mock_delete: AsyncMock, client: AsyncClient
    ):
        mock_delete.side_effect = Exception("boom")
        response = await client.delete(f"{MAIL_BASE}/gmail/drafts/draft-001")

        assert response.status_code == 500
        assert response.json() == {"detail": "boom"}


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/drafts/{draft_id}/send
# ---------------------------------------------------------------------------


class TestSendDraft:
    @patch(
        "app.api.v1.endpoints.mail.send_draft",
        new_callable=AsyncMock,
    )
    async def test_send_draft_returns_200(
        self, mock_send: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"successful": True, "id": "sent-001", "threadId": "thread-001"}
        )
        response = await client.post(f"{MAIL_BASE}/gmail/drafts/draft-001/send")

        assert response.status_code == 200
        assert response.json() == {
            "message_id": "sent-001",
            "thread_id": "thread-001",
            "status": "Draft sent successfully",
            "successful": True,
        }
        mock_send.assert_awaited_once_with(user_id=USER_ID, draft_id="draft-001")
        mock_mail_log.set.assert_any_call(
            operation="send_draft", email_id="draft-001"
        )
        mock_mail_log.set.assert_any_call(
            operation="send_draft",
            email_id="draft-001",
            thread_id="thread-001",
            outcome="success",
        )

    @patch(
        "app.api.v1.endpoints.mail.send_draft",
        new_callable=AsyncMock,
    )
    async def test_send_draft_without_thread_uses_empty_strings(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"successful": True, "id": None, "threadId": None}
        )
        response = await client.post(f"{MAIL_BASE}/gmail/drafts/draft-001/send")

        assert response.status_code == 200
        assert response.json() == {
            "message_id": "",
            "thread_id": "",
            "status": "Draft sent successfully",
            "successful": True,
        }

    @patch(
        "app.api.v1.endpoints.mail.send_draft",
        new_callable=AsyncMock,
    )
    async def test_send_draft_failure_returns_500(
        self, mock_send: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"successful": False, "error": "Draft expired"}
        )
        response = await client.post(f"{MAIL_BASE}/gmail/drafts/draft-001/send")

        # The endpoint raises HTTPException(500, ...) inside the try and its own
        # catch-all re-wraps it via str(e), which is "500: Draft expired".
        assert response.status_code == 500
        assert response.json() == {"detail": "500: Draft expired"}
        mock_mail_log.set.assert_any_call(operation="send_draft", email_id="draft-001")
        mock_mail_log.set.assert_any_call(outcome="failed")

    @patch(
        "app.api.v1.endpoints.mail.send_draft",
        new_callable=AsyncMock,
    )
    async def test_send_draft_failure_without_error_uses_default_detail(
        self, mock_send: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"successful": False, "error": None}
        )
        response = await client.post(f"{MAIL_BASE}/gmail/drafts/draft-001/send")

        assert response.status_code == 500
        assert response.json() == {"detail": "500: Failed to send draft"}
        mock_mail_log.set.assert_any_call(outcome="failed")

    @patch(
        "app.api.v1.endpoints.mail.send_draft",
        new_callable=AsyncMock,
    )
    async def test_send_draft_service_error_returns_500(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.side_effect = Exception("boom")
        response = await client.post(f"{MAIL_BASE}/gmail/drafts/draft-001/send")

        assert response.status_code == 500
        assert response.json() == {"detail": "boom"}


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/importance-summaries
# ---------------------------------------------------------------------------


class TestGetImportanceSummaries:
    @patch(
        "app.api.v1.endpoints.mail.get_importance_summaries_service",
        new_callable=AsyncMock,
    )
    async def test_returns_200_with_defaults(
        self, mock_svc: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
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
        mock_svc.assert_awaited_once_with(USER_ID, 50, False)
        mock_mail_log.set.assert_any_call(
            operation="get_importance_summaries",
            important_only=False,
            outcome="success",
        )

    @patch(
        "app.api.v1.endpoints.mail.get_importance_summaries_service",
        new_callable=AsyncMock,
    )
    async def test_with_params(
        self, mock_svc: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
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
        mock_svc.assert_awaited_once_with(USER_ID, 10, True)
        mock_mail_log.set.assert_any_call(
            operation="get_importance_summaries",
            important_only=True,
            outcome="success",
        )

    @patch(
        "app.api.v1.endpoints.mail.get_importance_summaries_service",
        new_callable=AsyncMock,
    )
    async def test_service_error_returns_500(
        self, mock_svc: AsyncMock, client: AsyncClient
    ):
        mock_svc.side_effect = Exception("boom")
        response = await client.get(f"{MAIL_BASE}/gmail/importance-summaries")

        assert response.status_code == 500
        assert response.json() == {"detail": "Error retrieving email summaries: boom"}

    @patch(
        "app.api.v1.endpoints.mail.get_importance_summaries_service",
        new_callable=AsyncMock,
    )
    async def test_default_limit_and_important_only(
        self, mock_svc: AsyncMock
    ) -> None:
        # Direct call: see test_list_messages_default_max_results_is_20.
        mock_svc.return_value = EmailImportanceSummariesResponse(
            status="success", emails=[], count=0, filtered_by_importance=False
        )
        await get_email_importance_summaries(current_user={"user_id": USER_ID})

        mock_svc.assert_awaited_once_with(USER_ID, 50, False)

    async def test_missing_user_id_is_wrapped_in_500(self) -> None:
        # Called directly because require_integration rejects a user without an
        # id before the endpoint body runs. The endpoint's own guard raises 401
        # inside the try, but this route has no ``except HTTPException``
        # re-raise, so the catch-all wraps it: str(HTTPException(401, ...)) is
        # "401: User ID not found". That wrapped 500 is the wire behaviour.
        with pytest.raises(HTTPException) as exc_info:
            await get_email_importance_summaries(current_user={})
        assert exc_info.value.status_code == 500
        assert (
            exc_info.value.detail
            == "Error retrieving email summaries: 401: User ID not found"
        )


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/importance-summary/{message_id}
# ---------------------------------------------------------------------------


class TestGetSingleImportanceSummary:
    @patch(
        "app.api.v1.endpoints.mail.get_single_importance_summary_service",
        new_callable=AsyncMock,
    )
    async def test_returns_200(
        self, mock_svc: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
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
        mock_svc.assert_awaited_once_with(USER_ID, "msg-1")
        mock_mail_log.set.assert_any_call(
            operation="get_importance_summary",
            email_id="msg-1",
            outcome="success",
        )

    @patch(
        "app.api.v1.endpoints.mail.get_single_importance_summary_service",
        new_callable=AsyncMock,
    )
    async def test_not_found_returns_404(
        self, mock_svc: AsyncMock, client: AsyncClient
    ):
        mock_svc.return_value = None
        response = await client.get(f"{MAIL_BASE}/gmail/importance-summary/nonexistent")

        assert response.status_code == 404
        assert response.json() == {"detail": "Email summary not found"}

    @patch(
        "app.api.v1.endpoints.mail.get_single_importance_summary_service",
        new_callable=AsyncMock,
    )
    async def test_service_error_returns_500(
        self, mock_svc: AsyncMock, client: AsyncClient
    ):
        mock_svc.side_effect = Exception("boom")
        response = await client.get(f"{MAIL_BASE}/gmail/importance-summary/msg-1")

        assert response.status_code == 500
        assert response.json() == {"detail": "Error retrieving email summary: boom"}

    async def test_missing_user_id_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await get_single_email_importance_summary(
                message_id="msg-1", current_user={}
            )
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "User ID not found"


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/importance-summaries/bulk
# ---------------------------------------------------------------------------


class TestBulkImportanceSummaries:
    @patch(
        "app.api.v1.endpoints.mail.get_bulk_importance_summaries_service",
        new_callable=AsyncMock,
    )
    async def test_returns_200(
        self, mock_svc: AsyncMock, mock_mail_log: MagicMock, client: AsyncClient
    ):
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
        mock_svc.assert_awaited_once_with(USER_ID, ["msg-1", "msg-2"])
        mock_mail_log.set.assert_any_call(
            operation="get_bulk_importance_summaries",
            result_count=2,
            outcome="success",
        )

    @patch(
        "app.api.v1.endpoints.mail.get_bulk_importance_summaries_service",
        new_callable=AsyncMock,
    )
    async def test_service_error_returns_500(
        self, mock_svc: AsyncMock, client: AsyncClient
    ):
        mock_svc.side_effect = Exception("boom")
        response = await client.post(
            f"{MAIL_BASE}/gmail/importance-summaries/bulk",
            json={"message_ids": ["msg-1"]},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Error retrieving bulk email summaries: boom"}

    async def test_missing_message_ids_returns_422(self, client: AsyncClient):
        response = await client.post(
            f"{MAIL_BASE}/gmail/importance-summaries/bulk",
            json={},
        )
        assert response.status_code == 422

    async def test_missing_user_id_is_wrapped_in_500(self) -> None:
        # See TestGetImportanceSummaries.test_missing_user_id_is_wrapped_in_500:
        # same guard, same catch-all wrapping, same wire behaviour.
        with pytest.raises(HTTPException) as exc_info:
            await get_bulk_email_importance_summaries(
                EmailActionRequest(message_ids=["msg-1"]), current_user={}
            )
        assert exc_info.value.status_code == 500
        assert (
            exc_info.value.detail
            == "Error retrieving bulk email summaries: 401: User ID not found"
        )
