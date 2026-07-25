"""E2E test: sending an email through the real GAIA Gmail send path.

Starts from the API call the web mail composer actually makes
(``POST /api/v1/gmail/send-json`` and ``POST /api/v1/gmail/send``) and asserts
on the response the user sees. Everything between is real production code:

- ``app.api.v1.endpoints.mail.send_email_json`` / ``send_email_route``
- ``app.services.mail.mail_service.send_email`` (tool selection, parameter build)
- ``app.services.mail.mail_service.invoke_gmail_tool``
- ``app.services.composio.langchain_composio_service.LangchainProvider`` — the
  real Composio→LangChain tool wrapper, including its pydantic argument schema

The only fake is Composio's remote execution call (``execute_tool``), which is
where the request would leave the process for Gmail. It returns recorded
``ToolExecutionResponse`` payloads (``{"data", "error", "successful"}``).
"""

from typing import Any

from composio.types import Tool
import pytest

from app.services.composio.langchain_composio_service import LangchainProvider

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("_bypass_integration_check")]

MAIL_BASE = "/api/v1"

# Minimal but real Composio tool descriptors. Slugs and parameter names match
# what mail_service builds, so a rename on either side breaks these tests.
_TOOL_SCHEMAS = {
    "GMAIL_SEND_EMAIL": {
        "title": "SendEmailRequest",
        "type": "object",
        "properties": {
            "recipient_email": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "extra_recipients": {"type": "array", "items": {"type": "string"}},
            "cc": {"type": "array", "items": {"type": "string"}},
            "bcc": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["recipient_email"],
    },
    "GMAIL_REPLY_TO_THREAD": {
        "title": "ReplyToThreadRequest",
        "type": "object",
        "properties": {
            "recipient_email": {"type": "string"},
            "subject": {"type": "string"},
            "message_body": {"type": "string"},
            "thread_id": {"type": "string"},
            "extra_recipients": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["recipient_email", "thread_id"],
    },
}


def _composio_tool(slug: str) -> Tool:
    return Tool.model_validate(
        {
            "available_versions": ["latest"],
            "deprecated": {
                "available_versions": ["latest"],
                "displayName": slug,
                "is_deprecated": False,
                "toolkit": {"logo": ""},
                "version": "latest",
            },
            "description": f"{slug} (test descriptor)",
            "input_parameters": _TOOL_SCHEMAS[slug],
            "is_deprecated": False,
            "name": slug,
            "no_auth": False,
            "output_parameters": {
                "title": f"{slug}Response",
                "type": "object",
                "properties": {},
            },
            "scopes": [],
            "slug": slug,
            "tags": [],
            "toolkit": {"logo": "", "name": "gmail", "slug": "gmail"},
            "version": "latest",
        }
    )


class FakeGmail:
    """Stands in for Composio's remote tool execution — the network boundary.

    Records every outbound call so tests can assert what would have been sent to
    Gmail, and replays a caller-supplied ``ToolExecutionResponse``.
    """

    def __init__(self, response: dict[str, Any] | None, known_tools: set[str] | None = None):
        self.response = response
        self.known_tools = known_tools if known_tools is not None else set(_TOOL_SCHEMAS)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_tool(self, tool_name: str, **_kwargs: Any):
        if tool_name not in self.known_tools:
            return None
        return LangchainProvider().wrap_tool(_composio_tool(tool_name), self._execute)

    def _execute(self, slug: str, arguments: dict[Any, Any]) -> dict[Any, Any]:
        self.calls.append((slug, arguments))
        assert self.response is not None
        return self.response

    @property
    def last_params(self) -> dict[str, Any]:
        return self.calls[-1][1]


@pytest.fixture
def _bypass_integration_check():
    """require_integration("gmail") must pass without a live Composio connection."""
    from unittest.mock import AsyncMock, patch

    with patch(
        "app.api.v1.dependencies.google_scope_dependencies.check_integration_status",
        new_callable=AsyncMock,
        return_value=True,
    ):
        yield


@pytest.fixture
def gmail_boundary(monkeypatch):
    """Install a FakeGmail as the Composio service mail_service resolves."""

    def _install(response: dict[str, Any] | None, known_tools: set[str] | None = None) -> FakeGmail:
        fake = FakeGmail(response, known_tools)
        monkeypatch.setattr(
            "app.services.mail.mail_service.get_composio_service", lambda: fake, raising=True
        )
        return fake

    return _install


class TestSendEmailFlow:
    async def test_send_returns_gmail_message_id_and_addresses_all_recipients(
        self, client, gmail_boundary
    ):
        """A successful send returns Gmail's message id and mails every recipient.

        ``to[0]`` becomes ``recipient_email`` and the remainder ``extra_recipients``
        (route logic); the id lives under the Composio response envelope's ``data``.
        """
        fake = gmail_boundary(
            {
                "data": {"id": "gmail-msg-9001", "threadId": "gmail-thread-42"},
                "error": None,
                "successful": True,
            }
        )

        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={
                "to": ["alice@example.com", "bob@example.com"],
                "subject": "Q3 numbers",
                "body": "Attached below.",
                "cc": ["carol@example.com"],
            },
        )

        assert response.status_code == 200, response.text
        assert response.json() == {
            "message_id": "gmail-msg-9001",
            "status": "Email sent successfully",
        }

        slug, params = fake.calls[0]
        assert slug == "GMAIL_SEND_EMAIL"
        assert params["recipient_email"] == "alice@example.com"
        assert params["extra_recipients"] == ["bob@example.com"]
        assert params["cc"] == ["carol@example.com"]
        assert params["subject"] == "Q3 numbers"
        assert params["body"] == "Attached below."

    async def test_send_reports_failure_instead_of_claiming_success(self, client, gmail_boundary):
        """A Gmail rejection must NOT come back as "Email sent successfully".

        Composio signals failure with ``successful: False`` and an ``error``. If
        the route ignores that, the composer tells the user the mail went out
        when nothing was delivered.
        """
        gmail_boundary(
            {
                "data": {},
                "error": "Request had insufficient authentication scopes.",
                "successful": False,
            }
        )

        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={"to": ["alice@example.com"], "subject": "Q3 numbers", "body": "Attached."},
        )

        assert response.status_code == 500, response.text
        body = response.json()
        assert "successfully" not in str(body).lower(), (
            f"Gmail rejected the send but the API reported success: {body}"
        )
        assert "insufficient authentication scopes" in str(body), (
            f"The Gmail error must reach the user, got: {body}"
        )

    async def test_send_reports_failure_when_gmail_tool_is_unavailable(
        self, client, gmail_boundary
    ):
        """An unresolvable GMAIL_SEND_EMAIL tool is a failure, not a silent success."""
        gmail_boundary(None, known_tools=set())

        response = await client.post(
            f"{MAIL_BASE}/gmail/send-json",
            json={"to": ["alice@example.com"], "subject": "Hi", "body": "There."},
        )

        assert response.status_code == 500, response.text
        assert "successfully" not in str(response.json()).lower()
        assert "GMAIL_SEND_EMAIL" in str(response.json())

    async def test_form_send_route_reports_failure_instead_of_claiming_success(
        self, client, gmail_boundary
    ):
        """The multipart send route (attachments path) must fail loud too."""
        gmail_boundary(
            {"data": {}, "error": "Recipient address rejected", "successful": False},
        )

        response = await client.post(
            f"{MAIL_BASE}/gmail/send",
            data={
                "to": "alice@example.com",
                "subject": "Q3 numbers",
                "body": "Attached.",
            },
        )

        assert response.status_code == 500, response.text
        assert "successfully" not in str(response.json()).lower()
        assert "Recipient address rejected" in str(response.json())

    async def test_reply_uses_thread_tool_and_returns_message_id(self, client, gmail_boundary):
        """A send with thread_id replies on the thread instead of starting a new one."""
        fake = gmail_boundary(
            {"data": {"id": "gmail-msg-9002"}, "error": None, "successful": True},
        )

        response = await client.post(
            f"{MAIL_BASE}/gmail/send",
            data={
                "to": "alice@example.com",
                "subject": "Re: Q3 numbers",
                "body": "Sounds good.",
                "thread_id": "gmail-thread-42",
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["message_id"] == "gmail-msg-9002"

        slug, params = fake.calls[0]
        assert slug == "GMAIL_REPLY_TO_THREAD"
        assert params["thread_id"] == "gmail-thread-42"
        assert params["message_body"] == "Sounds good."
