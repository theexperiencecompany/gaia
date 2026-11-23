"""Unit tests for mail (Gmail) API endpoints.

Tests the Gmail endpoints with mocked service layer and integration
dependency to verify routing, status codes, response bodies, and validation.

Gmail endpoints use require_integration("gmail") which internally calls
check_integration_status.  We patch that function to return True so
the dependency passes without a real Composio/Redis connection.
"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.api.v1.endpoints.mail import _build_gmail_query
from app.models.mail_models import (
    GmailMessagesResponse,
    GmailMessageSummary,
    GmailSearchFilters,
    GmailToolResult,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.mail import EmailReplied, EmailSent
from tests.conftest import FAKE_USER

MAIL_BASE = "/api/v1"
ANALYTICS_PATCH = "app.api.v1.endpoints.mail.capture"


@pytest.fixture(autouse=True)
def _noop_analytics():
    """Neutralize capture for every test in this module.

    The test app runs a no-op lifespan, so the PostHog provider is never
    registered; a bare capture call would raise KeyError on the
    missing provider. Tests that assert on captures patch the call site again
    and assert on their own mock.
    """
    with patch(ANALYTICS_PATCH):
        yield


# All tests in this module need the integration check to pass.
pytestmark = [
    pytest.mark.usefixtures("_bypass_integration_check"),
]


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/search
# ---------------------------------------------------------------------------


class TestSearchEmails:
    @patch(
        "app.api.v1.endpoints.mail.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_emails_returns_200(self, mock_search: AsyncMock, client: AsyncClient):
        mock_search.return_value = GmailMessagesResponse(messages=[GmailMessageSummary(id="msg-1")])
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


class TestMailAnalytics:
    """Analytics captures on mail endpoints."""

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
            UserId(FAKE_USER.user_id),
            EmailReplied(has_attachments=False, attachment_count=0),
        )

    @patch(
        "app.api.v1.endpoints.mail.send_email",
        new_callable=AsyncMock,
    )
    async def test_a_reply_with_an_attachment_reports_it(
        self, mock_send: AsyncMock, client: AsyncClient
    ):
        mock_send.return_value = GmailToolResult.model_validate(
            {"data": {"id": "sent-005"}, "error": None, "successful": True}
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
                files={"attachments": ("note.txt", b"hello", "text/plain")},
            )

        assert response.status_code == 200
        mock_capture.assert_called_once_with(
            UserId(FAKE_USER.user_id),
            EmailReplied(has_attachments=True, attachment_count=1),
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
            UserId(FAKE_USER.user_id),
            EmailSent(has_attachments=False, attachment_count=0),
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
            UserId(FAKE_USER.user_id),
            EmailSent(has_attachments=True, attachment_count=1),
        )
        final_set = mock_log.set.call_args_list[-1]
        assert final_set.kwargs == {
            "operation": "send_email",
            "thread_id": None,
            "has_attachment": True,
            "attachments_count": 1,
            "outcome": "success",
        }


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
        mock_capture.assert_called_once_with(UserId(FAKE_USER.user_id), EmailSent())
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
        mock_search.return_value = GmailMessagesResponse(
            messages=[GmailMessageSummary(id="m-1"), GmailMessageSummary(id="m-2")]
        )
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
        assert response.json()["message"] == "quota exceeded"
