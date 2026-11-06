"""Unit tests for the mail service (app/services/mail/mail_service.py)."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from composio.utils.shared import json_schema_to_model
from langchain_core.tools import StructuredTool
import pytest

from app.constants.log_tags import LogTag
from app.models.mail_models import (
    GmailMessagesResponse,
    GmailMessageSummary,
    GmailToolResult,
)
from app.services.mail.mail_service import (
    EmailContent,
    MessageFetchOptions,
    _process_attachments,
    get_gmail_tool,
    invoke_gmail_tool,
    search_messages,
    send_draft,
    send_email,
)
from app.utils.composio_hooks.registry import master_schema_modifier
from shared.py.wide_events import MailContext

# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

USER_ID = "user_test_123"


@pytest.fixture
def mock_composio_service():
    """Patch get_composio_service and return a controllable mock."""
    with patch("app.services.mail.mail_service.get_composio_service") as mock_factory:
        mock_service = MagicMock()
        mock_factory.return_value = mock_service
        yield mock_service


@pytest.fixture
def mock_invoke_gmail_tool():
    """Patch invoke_gmail_tool at the module level."""
    with patch("app.services.mail.mail_service.invoke_gmail_tool") as mock_fn:
        yield mock_fn


@pytest.fixture
def mock_transform():
    """Patch transform_gmail_message to wrap its input unchanged."""
    with patch(
        "app.services.mail.mail_service.transform_gmail_message",
        side_effect=lambda m: GmailMessageSummary.model_validate({"id": "", **m}),
    ) as mock_fn:
        yield mock_fn


# ---------------------------------------------------------------------------
# get_gmail_tool
# ---------------------------------------------------------------------------


class TestGetGmailTool:
    def test_returns_tool_from_composio_service(self, mock_composio_service):
        fake_tool = MagicMock()
        mock_composio_service.get_tool.return_value = fake_tool

        result = get_gmail_tool("GMAIL_SEND_EMAIL", USER_ID)

        assert result is fake_tool
        mock_composio_service.get_tool.assert_called_once_with(
            "GMAIL_SEND_EMAIL",
            use_before_hook=False,
            use_after_hook=False,
            use_schema_modifier=True,
            user_id=USER_ID,
        )

    def test_native_schema_is_requested_when_asked(self, mock_composio_service):
        get_gmail_tool("GMAIL_SEND_EMAIL", USER_ID, use_schema_modifier=False)

        assert mock_composio_service.get_tool.call_args.kwargs["use_schema_modifier"] is False

    def test_returns_none_on_exception(self, mock_composio_service):
        mock_composio_service.get_tool.side_effect = RuntimeError("service down")

        result = get_gmail_tool("GMAIL_SEND_EMAIL", USER_ID)

        assert result is None


# ---------------------------------------------------------------------------
# invoke_gmail_tool
# ---------------------------------------------------------------------------


class TestInvokeGmailTool:
    async def test_invokes_tool_and_returns_result(self, mock_composio_service):
        fake_tool = AsyncMock()
        fake_tool.ainvoke = AsyncMock(return_value={"successful": True, "id": "msg1"})
        mock_composio_service.get_tool.return_value = fake_tool

        result = await invoke_gmail_tool(USER_ID, "GMAIL_SEND_EMAIL", {"subject": "Hi"})

        assert result.model_dump(exclude_unset=True, by_alias=True) == {
            "successful": True,
            "id": "msg1",
        }
        fake_tool.ainvoke.assert_awaited_once_with({"subject": "Hi"})
        # The tool is fetched for this user, by name, with the agent-facing
        # schema — a wrong value here silently sends the call to another
        # mailbox or strips arguments off it.
        assert mock_composio_service.get_tool.call_args.args == ("GMAIL_SEND_EMAIL",)
        assert mock_composio_service.get_tool.call_args.kwargs == {
            "use_before_hook": False,
            "use_after_hook": False,
            "use_schema_modifier": True,
            "user_id": USER_ID,
        }

    async def test_native_schema_request_reaches_the_tool_fetch(self, mock_composio_service):
        fake_tool = AsyncMock()
        fake_tool.ainvoke = AsyncMock(return_value={"successful": True})
        mock_composio_service.get_tool.return_value = fake_tool

        await invoke_gmail_tool(
            USER_ID, "GMAIL_SEND_EMAIL", {"subject": "Hi"}, use_schema_modifier=False
        )

        assert mock_composio_service.get_tool.call_args.kwargs["use_schema_modifier"] is False

    async def test_returns_error_dict_when_tool_not_found(self, mock_composio_service):
        mock_composio_service.get_tool.return_value = None

        result = await invoke_gmail_tool(USER_ID, "GMAIL_NONEXISTENT", {})

        assert result.successful is False
        assert result.error is not None
        assert "GMAIL_NONEXISTENT" in result.error

    async def test_returns_error_dict_on_exception(self, mock_composio_service):
        fake_tool = AsyncMock()
        fake_tool.ainvoke = AsyncMock(side_effect=Exception("network timeout"))
        mock_composio_service.get_tool.return_value = fake_tool

        result = await invoke_gmail_tool(USER_ID, "GMAIL_SEND_EMAIL", {})

        assert result.successful is False
        assert result.error is not None
        assert "network timeout" in result.error


# ---------------------------------------------------------------------------
# _process_attachments  (pure function – no mocking needed)
# ---------------------------------------------------------------------------


class TestProcessAttachments:
    def test_uploads_upload_files_to_composio(self):
        import io

        upload = MagicMock()
        upload.filename = "report.pdf"
        upload.content_type = "application/pdf"
        upload.file = io.BytesIO(b"PDF content")

        with patch(
            "app.services.mail.mail_service.upload_bytes_sync",
            return_value={"name": "report.pdf", "mimetype": "application/pdf", "s3key": "k/1"},
        ) as mock_upload:
            result = _process_attachments([upload], "GMAIL_SEND_EMAIL")

        # Raw bytes + filename + content-type are handed to the Composio uploader,
        # scoped to the invoking tool/toolkit.
        assert mock_upload.call_args.args == (b"PDF content", "report.pdf", "application/pdf")
        assert mock_upload.call_args.kwargs == {"tool": "GMAIL_SEND_EMAIL", "toolkit": "gmail"}
        assert result == [{"name": "report.pdf", "mimetype": "application/pdf", "s3key": "k/1"}]

    def test_falls_back_to_generic_name_when_filename_missing(self):
        import io

        upload = MagicMock()
        upload.filename = None
        upload.content_type = "application/octet-stream"
        upload.file = io.BytesIO(b"x")

        with patch(
            "app.services.mail.mail_service.upload_bytes_sync",
            return_value={
                "name": "attachment",
                "mimetype": "application/octet-stream",
                "s3key": "k",
            },
        ) as mock_upload:
            _process_attachments([upload], "GMAIL_SEND_EMAIL")

        # A missing filename becomes the literal "attachment".
        assert mock_upload.call_args.args[1] == "attachment"

    def test_resets_file_pointer_after_read(self):
        upload = MagicMock()
        upload.filename = "file.txt"
        upload.content_type = "text/plain"
        upload.file = MagicMock()
        upload.file.read.return_value = b"hello"

        with patch(
            "app.services.mail.mail_service.upload_bytes_sync",
            return_value={"name": "file.txt", "mimetype": "text/plain", "s3key": "k/2"},
        ):
            _process_attachments([upload], "GMAIL_SEND_EMAIL")

        # seek(0) should have been called on the mock's file attribute
        upload.file.seek.assert_called_once_with(0)

    def test_handles_empty_list(self):
        result = _process_attachments([], "GMAIL_SEND_EMAIL")
        assert result == []


# ---------------------------------------------------------------------------
# send_email
# ---------------------------------------------------------------------------


class TestSendEmail:
    async def test_new_email_uses_gmail_send_email_tool(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate(
            {"successful": True, "messageId": "abc"}
        )

        result = await send_email(
            user_id=USER_ID,
            to="bob@example.com",
            content=EmailContent(subject="Hello", body="Test body"),
        )

        assert result.model_dump(exclude_unset=True, by_alias=True) == {
            "successful": True,
            "messageId": "abc",
        }
        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_SEND_EMAIL"
        params = args[2]
        assert params["recipient_email"] == "bob@example.com"
        assert params["subject"] == "Hello"
        assert params["body"] == "Test body"
        assert "thread_id" not in params

    async def test_reply_uses_gmail_reply_to_thread_tool(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate({"successful": True})

        await send_email(
            user_id=USER_ID,
            to="bob@example.com",
            content=EmailContent(subject="Re: Hello", body="Reply body"),
            thread_id="thread_xyz",
        )

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_REPLY_TO_THREAD"
        params = args[2]
        assert params["thread_id"] == "thread_xyz"
        # reply uses message_body not body
        assert "message_body" in params
        assert "body" not in params

    async def test_includes_cc_and_bcc_when_provided(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate({"successful": True})

        await send_email(
            user_id=USER_ID,
            to="bob@example.com",
            content=EmailContent(
                subject="Hi", body="Body", cc_list=["cc@example.com"], bcc_list=["bcc@example.com"]
            ),
        )

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert params["cc"] == ["cc@example.com"]
        assert params["bcc"] == ["bcc@example.com"]

    async def test_omits_cc_bcc_when_not_provided(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate({"successful": True})

        await send_email(
            user_id=USER_ID,
            to="bob@example.com",
            content=EmailContent(subject="Hi", body="Body"),
        )

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert "cc" not in params
        assert "bcc" not in params

    async def test_returns_error_dict_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("quota exceeded")

        result = await send_email(
            user_id=USER_ID, to="bob@example.com", content=EmailContent(subject="Hi", body="Body")
        )

        assert result.successful is False
        assert result.error is not None
        assert "quota exceeded" in result.error

    async def test_sends_attachments_when_provided(self, mock_invoke_gmail_tool):
        import io

        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate({"successful": True})
        upload = MagicMock()
        upload.filename = "doc.pdf"
        upload.content_type = "application/pdf"
        upload.file = io.BytesIO(b"data")

        # Composio's Gmail tools take a singular attachment of {name, mimetype,
        # s3key} (a pre-uploaded file), not a plural attachments of raw bytes.
        with patch(
            "app.services.mail.mail_service.upload_bytes_sync",
            return_value={"name": "doc.pdf", "mimetype": "application/pdf", "s3key": "k/1"},
        ) as mock_upload:
            await send_email(
                user_id=USER_ID,
                to="bob@example.com",
                content=EmailContent(subject="Hi", body="Body"),
                attachments=[upload],
            )

        # The bytes read off the UploadFile are handed to the Composio uploader,
        # scoped to the send tool so the upload lands in the right toolkit namespace.
        assert mock_upload.call_args.args[0] == b"data"
        assert mock_upload.call_args.kwargs["tool"] == "GMAIL_SEND_EMAIL"
        params = mock_invoke_gmail_tool.call_args[0][2]
        assert "attachments" not in params
        # One file -> a single FileUploadable object (the pinned Gmail toolkit
        # version rejects a list), not a one-element list.
        assert params["attachment"] == {
            "name": "doc.pdf",
            "mimetype": "application/pdf",
            "s3key": "k/1",
        }

    async def test_rejects_multiple_attachments_without_uploading(self, mock_invoke_gmail_tool):
        import io

        uploads = []
        for name in ("a.pdf", "b.pdf"):
            up = MagicMock()
            up.filename, up.content_type, up.file = name, "application/pdf", io.BytesIO(b"x")
            uploads.append(up)

        with patch("app.services.mail.mail_service.upload_bytes_sync") as mock_upload:
            result = await send_email(
                user_id=USER_ID,
                to="bob@example.com",
                content=EmailContent(subject="Hi", body="Body"),
                attachments=uploads,
            )

        # Composio types Gmail's `attachment` as a single object, so a second file
        # is rejected up front — nothing is uploaded and no send is attempted.
        assert result.successful is False
        assert "one attachment" in (result.error or "")
        mock_upload.assert_not_called()
        mock_invoke_gmail_tool.assert_not_called()


class TestAttachmentsSurviveArgumentValidation:
    """attachment is Gmail's own param, and only the tool's own schema has it.

    Shaping the parameter correctly is not enough: LangChain validates the call
    against the schema the tool was bound with and silently drops anything that
    schema does not declare. Under the agent-facing schema — where the modifier
    has replaced attachment with the reference-based attachments — the
    file is dropped between here and Composio and the mail sends without it.
    """

    def _gmail_send_schema(self) -> SimpleNamespace:
        # The native shape: FileUploadable emits `file_uploadable` onto its own
        # schema node, alongside the s3key object it stands for.
        return SimpleNamespace(
            description="Send an email",
            input_parameters={
                "title": "GmailSendEmail",
                "properties": {
                    "recipient_email": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "attachment": {
                        "type": "object",
                        "file_uploadable": True,
                        "properties": {
                            "name": {"type": "string"},
                            "mimetype": {"type": "string"},
                            "s3key": {"type": "string"},
                        },
                    },
                },
                "required": [],
            },
        )

    def _args_reaching_the_tool(self, schema: SimpleNamespace, call: dict) -> dict:
        """Return what Composio's executor receives, through the real LangChain plumbing."""
        received: dict = {}

        def _execute(**kwargs: object) -> str:
            received.update(kwargs)
            return "ok"

        tool = StructuredTool.from_function(
            name="GMAIL_SEND_EMAIL",
            description="Send an email",
            args_schema=json_schema_to_model(schema.input_parameters),
            func=_execute,
        )
        tool.invoke(call)
        return received

    def test_agent_facing_schema_drops_the_attachment_argument(self):
        call = {
            "recipient_email": "bob@example.com",
            "subject": "Hi",
            "body": "Body",
            "attachment": {"name": "doc.pdf", "mimetype": "application/pdf", "s3key": "k/1"},
        }
        native = self._gmail_send_schema()
        # Composio coerces the object into its generated model; the s3key — the
        # only part that identifies the uploaded file — arrives intact.
        delivered = self._args_reaching_the_tool(native, call)["attachment"]
        assert delivered.s3key == "k/1"

        agent_facing = master_schema_modifier(
            "GMAIL_SEND_EMAIL", "gmail", self._gmail_send_schema()
        )
        assert "attachment" not in self._args_reaching_the_tool(agent_facing, call)

    async def test_send_with_attachments_asks_for_the_native_schema(self, mock_invoke_gmail_tool):
        import io

        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate({"successful": True})
        upload = MagicMock()
        upload.filename, upload.content_type, upload.file = (
            "d.pdf",
            "application/pdf",
            io.BytesIO(b"x"),
        )

        with patch(
            "app.services.mail.mail_service.upload_bytes_sync",
            return_value={"name": "d.pdf", "mimetype": "application/pdf", "s3key": "k/1"},
        ):
            await send_email(
                user_id=USER_ID,
                to="bob@example.com",
                content=EmailContent(subject="Hi", body="Body"),
                attachments=[upload],
            )

        assert mock_invoke_gmail_tool.call_args.kwargs["use_schema_modifier"] is False

    async def test_send_without_attachments_keeps_the_agent_facing_schema(
        self, mock_invoke_gmail_tool
    ):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate({"successful": True})

        await send_email(
            user_id=USER_ID,
            to="bob@example.com",
            content=EmailContent(subject="Hi", body="Body"),
        )

        assert mock_invoke_gmail_tool.call_args.kwargs["use_schema_modifier"] is True


# ---------------------------------------------------------------------------
# search_messages
# ---------------------------------------------------------------------------


class TestSearchMessages:
    async def test_returns_transformed_messages_and_next_token(
        self, mock_invoke_gmail_tool, mock_transform
    ):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate(
            {
                "successful": True,
                "data": {
                    "messages": [{"id": "m1"}, {"id": "m2"}],
                    "nextPageToken": "tok123",
                },
            }
        )

        result = await search_messages(USER_ID, query="is:unread", max_results=10)

        assert len(result.messages) == 2
        assert result.next_page_token == "tok123"
        assert mock_transform.call_count == 2

    async def test_last_page_empty_token_means_no_next_page(self, mock_invoke_gmail_tool):
        """Regression: Composio's "" end-of-results token made the dashboard refetch page 1 (2 unread shown as 8)."""
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate(
            {
                "successful": True,
                "error": None,
                "data": {
                    "messages": [
                        {
                            "messageId": "1a0ce452407833e5",
                            "threadId": "1a0ce452407833e5",
                            "sender": "Aryan from GAIA <aryan@heygaia.io>",
                            "subject": "Welcome to GAIA Pro!",
                            "messageTimestamp": "2026-09-23T12:37:12Z",
                            "labelIds": ["UNREAD", "CATEGORY_PERSONAL", "INBOX"],
                            "preview": {"subject": "Welcome to GAIA Pro!", "body": "Thanks for"},
                        },
                        {
                            "messageId": "1a0ce3bab478825b",
                            "threadId": "1a0ce3bab478825b",
                            "sender": "Google <noreply-accounts@google.com>",
                            "subject": "You shared some Google Account data with Hey GAIA",
                            "messageTimestamp": "2026-09-23T12:26:51Z",
                            "labelIds": ["UNREAD", "CATEGORY_UPDATES", "INBOX"],
                            "preview": {"subject": "You shared some", "body": "Hey GAIA"},
                        },
                    ],
                    "nextPageToken": "",
                    "resultSizeEstimate": 2,
                },
            }
        )

        result = await search_messages(USER_ID, query="is:unread", max_results=10)

        assert [m.id for m in result.messages] == ["1a0ce452407833e5", "1a0ce3bab478825b"]
        assert result.next_page_token is None
        assert json.loads(result.model_dump_json(by_alias=True))["nextPageToken"] is None

    async def test_includes_page_token_when_provided(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate(
            {
                "successful": True,
                "data": {"messages": [], "nextPageToken": None},
            }
        )

        await search_messages(USER_ID, query="test", page_token="prev_tok")

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert params["page_token"] == "prev_tok"

    async def test_returns_empty_result_on_failure(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate(
            {"successful": False, "error": "auth"}
        )

        result = await search_messages(USER_ID)

        assert result == GmailMessagesResponse(messages=[])

    async def test_exception_propagates(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("503")

        with pytest.raises(Exception, match="503"):
            await search_messages(USER_ID)

    async def test_uses_empty_string_for_missing_query(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate(
            {
                "successful": True,
                "data": {"messages": [], "nextPageToken": None},
            }
        )

        await search_messages(USER_ID)

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert params["query"] == ""

    async def test_forwards_message_format_to_gmail(self, mock_invoke_gmail_tool):
        """output_format="metadata" must reach the Gmail tool as format="metadata", or it silently full-fetches."""
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate(
            {
                "successful": True,
                "data": {"messages": [], "nextPageToken": None},
            }
        )

        await search_messages(
            USER_ID,
            query="test",
            options=MessageFetchOptions(
                output_format="metadata", include_payload=False, verbose=False
            ),
        )

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert params["format"] == "metadata"
        assert params["include_payload"] is False
        assert params["verbose"] is False


# ---------------------------------------------------------------------------
# send_draft
# ---------------------------------------------------------------------------


class TestSendDraft:
    async def test_sends_draft_via_correct_tool(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate(
            {"successful": True, "messageId": "msg1"}
        )

        result = await send_draft(USER_ID, "draft1")

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_SEND_DRAFT"
        assert args[2]["draft_id"] == "draft1"
        assert result.model_dump(exclude_unset=True, by_alias=True) == {
            "successful": True,
            "messageId": "msg1",
        }

    async def test_returns_error_on_failure(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate(
            {
                "successful": False,
                "error": "draft not found",
            }
        )

        result = await send_draft(USER_ID, "draft1")

        assert result.successful is False

    async def test_returns_error_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("timeout")

        result = await send_draft(USER_ID, "draft1")

        assert result.successful is False


class TestSendEmailParamPins:
    async def test_log_context_is_exact(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate({"successful": True})
        with patch("app.services.mail.mail_service.log") as log:
            await send_email(
                USER_ID,
                "bob@example.com",
                EmailContent(subject="Hi", body="Body"),
            )
        log.set.assert_called_once_with(
            user={"id": USER_ID},
            mail=MailContext(operation="send", provider="gmail"),
        )
        log.set_ns.assert_called_once_with("mail", success=True)

    async def test_new_email_parameters_are_exact(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate({"successful": True})
        await send_email(
            USER_ID,
            "bob@example.com",
            EmailContent(
                subject="Hi",
                body="Body",
                extra_recipients=["carol@example.com"],
                cc_list=["cc@example.com"],
                bcc_list=["bcc@example.com"],
            ),
        )
        args, _ = mock_invoke_gmail_tool.await_args
        assert args[0] == USER_ID
        assert args[1] == "GMAIL_SEND_EMAIL"
        assert args[2] == {
            "recipient_email": "bob@example.com",
            "extra_recipients": ["carol@example.com"],
            "body": "Body",
            "subject": "Hi",
            "cc": ["cc@example.com"],
            "bcc": ["bcc@example.com"],
        }

    async def test_reply_parameters_are_exact(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate({"successful": True})
        await send_email(
            USER_ID,
            "bob@example.com",
            EmailContent(subject="Re", body="Body"),
            thread_id="thread_1",
        )
        args, _ = mock_invoke_gmail_tool.await_args
        assert args[1] == "GMAIL_REPLY_TO_THREAD"
        assert args[2] == {
            "recipient_email": "bob@example.com",
            "extra_recipients": [],
            "message_body": "Body",
            "subject": "Re",
            "thread_id": "thread_1",
        }

    async def test_failed_tool_result_logs_error_and_is_returned_verbatim(
        self, mock_invoke_gmail_tool
    ):
        failed = GmailToolResult.model_validate({"successful": False, "error": "quota"})
        mock_invoke_gmail_tool.return_value = failed
        with patch("app.services.mail.mail_service.log") as log:
            result = await send_email(
                USER_ID, "bob@example.com", EmailContent(subject="Hi", body="Body")
            )
        assert result is not None and result.successful is False
        assert result.error == "quota"
        log.error.assert_called_once_with(
            f"{LogTag.MAIL} Error from tool",
            tool_name="GMAIL_SEND_EMAIL",
            error="quota",
        )
        log.set_ns.assert_called_once_with("mail", success=False)

    async def test_exception_returns_failed_result_with_exact_fields(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = RuntimeError("composio down")
        with patch("app.services.mail.mail_service.log") as log:
            result = await send_email(
                USER_ID, "bob@example.com", EmailContent(subject="Hi", body="Body")
            )
        assert result.successful is False
        assert result.error == "composio down"
        log.error.assert_called_once_with(
            f"{LogTag.MAIL} Error sending email for user",
            user_id=USER_ID,
            error="composio down",
            error_type="RuntimeError",
        )
        log.set_ns.assert_called_once_with("mail", success=False)


class TestSearchMessagesParamPins:
    async def test_default_parameters_are_exact(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate(
            {"successful": True, "data": {"messages": [], "nextPageToken": None}}
        )
        await search_messages(USER_ID)
        args, _ = mock_invoke_gmail_tool.await_args
        assert args[0] == USER_ID
        assert args[1] == "GMAIL_FETCH_EMAILS"
        assert args[2] == {"query": "", "max_results": 20}

    async def test_all_parameters_are_forwarded_exactly(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate(
            {"successful": True, "data": {"messages": [], "nextPageToken": "tok"}}
        )
        response = await search_messages(
            USER_ID,
            query="is:unread",
            max_results=7,
            page_token="prev",
            options=MessageFetchOptions(output_format="metadata", include_payload=False),
        )
        args, _ = mock_invoke_gmail_tool.await_args
        assert args[2] == {
            "query": "is:unread",
            "max_results": 7,
            "page_token": "prev",
            "format": "metadata",
            "include_payload": False,
        }
        assert response.next_page_token == "tok"

    async def test_verbose_option_is_forwarded(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate(
            {"successful": True, "data": {"messages": [], "nextPageToken": None}}
        )
        await search_messages(USER_ID, options=MessageFetchOptions(verbose=True))
        args, _ = mock_invoke_gmail_tool.await_args
        assert args[2]["verbose"] is True

    async def test_failure_returns_empty_response_and_sets_ns(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = GmailToolResult.model_validate({"successful": False})
        with patch("app.services.mail.mail_service.log") as log:
            response = await search_messages(USER_ID, query="q")
        assert response.messages == []
        log.set_ns.assert_called_once_with("mail", success=False)

    async def test_exception_propagates_after_setting_ns(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = RuntimeError("down")
        with patch("app.services.mail.mail_service.log") as log:
            with pytest.raises(RuntimeError, match="down"):
                await search_messages(USER_ID, query="q")
        log.set_ns.assert_called_once_with("mail", success=False)
