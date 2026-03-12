"""Unit tests for the mail service (app/services/mail/mail_service.py)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# All public symbols imported directly from the module under test.
# Deleting mail_service.py will break every test in this file.
# ---------------------------------------------------------------------------
from app.services.mail.mail_service import (
    get_gmail_tool,
    invoke_gmail_tool,
    send_email,
    fetch_detailed_messages,
    modify_message_labels,
    mark_messages_as_read,
    mark_messages_as_unread,
    star_messages,
    unstar_messages,
    trash_messages,
    untrash_messages,
    archive_messages,
    move_to_inbox,
    fetch_thread,
    search_messages,
    create_label,
    update_label,
    delete_label,
    apply_labels,
    remove_labels,
    create_draft,
    list_drafts,
    get_draft,
    update_draft,
    delete_draft,
    send_draft,
    list_labels,
    get_email_by_id,
    get_contact_list,
    _process_attachments,
)


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
    """Patch transform_gmail_message to return its input unchanged."""
    with patch(
        "app.services.mail.mail_service.transform_gmail_message",
        side_effect=lambda m: m,
    ) as mock_fn:
        yield mock_fn


# ---------------------------------------------------------------------------
# get_gmail_tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
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
            user_id=USER_ID,
        )

    def test_returns_none_on_exception(self, mock_composio_service):
        mock_composio_service.get_tool.side_effect = RuntimeError("service down")

        result = get_gmail_tool("GMAIL_SEND_EMAIL", USER_ID)

        assert result is None


# ---------------------------------------------------------------------------
# invoke_gmail_tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInvokeGmailTool:
    async def test_invokes_tool_and_returns_result(self, mock_composio_service):
        fake_tool = AsyncMock()
        fake_tool.ainvoke = AsyncMock(return_value={"successful": True, "id": "msg1"})
        mock_composio_service.get_tool.return_value = fake_tool

        result = await invoke_gmail_tool(USER_ID, "GMAIL_SEND_EMAIL", {"subject": "Hi"})

        assert result == {"successful": True, "id": "msg1"}
        fake_tool.ainvoke.assert_awaited_once_with({"subject": "Hi"})

    async def test_returns_error_dict_when_tool_not_found(self, mock_composio_service):
        mock_composio_service.get_tool.return_value = None

        result = await invoke_gmail_tool(USER_ID, "GMAIL_NONEXISTENT", {})

        assert result["successful"] is False
        assert "GMAIL_NONEXISTENT" in result["error"]

    async def test_returns_error_dict_on_exception(self, mock_composio_service):
        fake_tool = AsyncMock()
        fake_tool.ainvoke = AsyncMock(side_effect=Exception("network timeout"))
        mock_composio_service.get_tool.return_value = fake_tool

        result = await invoke_gmail_tool(USER_ID, "GMAIL_SEND_EMAIL", {})

        assert result["successful"] is False
        assert "network timeout" in result["error"]


# ---------------------------------------------------------------------------
# _process_attachments  (pure function – no mocking needed)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessAttachments:
    def test_converts_upload_files_to_dicts(self):
        import io

        upload = MagicMock()
        upload.filename = "report.pdf"
        upload.content_type = "application/pdf"
        upload.file = io.BytesIO(b"PDF content")

        result = _process_attachments([upload])

        assert len(result) == 1
        assert result[0]["filename"] == "report.pdf"
        assert result[0]["content"] == b"PDF content"
        assert result[0]["content_type"] == "application/pdf"

    def test_resets_file_pointer_after_read(self):
        upload = MagicMock()
        upload.filename = "file.txt"
        upload.content_type = "text/plain"
        upload.file = MagicMock()
        upload.file.read.return_value = b"hello"

        _process_attachments([upload])

        # seek(0) should have been called on the mock's file attribute
        upload.file.seek.assert_called_once_with(0)

    def test_handles_empty_list(self):
        result = _process_attachments([])
        assert result == []


# ---------------------------------------------------------------------------
# send_email
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSendEmail:
    async def test_new_email_uses_gmail_send_email_tool(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True, "messageId": "abc"}

        result = await send_email(
            user_id=USER_ID,
            to="bob@example.com",
            subject="Hello",
            body="Test body",
        )

        assert result == {"successful": True, "messageId": "abc"}
        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_SEND_EMAIL"
        params = args[2]
        assert params["recipient_email"] == "bob@example.com"
        assert params["subject"] == "Hello"
        assert params["body"] == "Test body"
        assert "thread_id" not in params

    async def test_reply_uses_gmail_reply_to_thread_tool(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True}

        await send_email(
            user_id=USER_ID,
            to="bob@example.com",
            subject="Re: Hello",
            body="Reply body",
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
        mock_invoke_gmail_tool.return_value = {"successful": True}

        await send_email(
            user_id=USER_ID,
            to="bob@example.com",
            subject="Hi",
            body="Body",
            cc_list=["cc@example.com"],
            bcc_list=["bcc@example.com"],
        )

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert params["cc"] == ["cc@example.com"]
        assert params["bcc"] == ["bcc@example.com"]

    async def test_omits_cc_bcc_when_not_provided(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True}

        await send_email(
            user_id=USER_ID,
            to="bob@example.com",
            subject="Hi",
            body="Body",
        )

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert "cc" not in params
        assert "bcc" not in params

    async def test_returns_error_dict_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("quota exceeded")

        result = await send_email(
            user_id=USER_ID, to="bob@example.com", subject="Hi", body="Body"
        )

        assert result["successful"] is False
        assert "quota exceeded" in result["error"]

    async def test_sends_attachments_when_provided(self, mock_invoke_gmail_tool):
        import io

        mock_invoke_gmail_tool.return_value = {"successful": True}
        upload = MagicMock()
        upload.filename = "doc.pdf"
        upload.content_type = "application/pdf"
        upload.file = io.BytesIO(b"data")

        await send_email(
            user_id=USER_ID,
            to="bob@example.com",
            subject="Hi",
            body="Body",
            attachments=[upload],
        )

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert "attachments" in params
        assert len(params["attachments"]) == 1


# ---------------------------------------------------------------------------
# fetch_detailed_messages
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchDetailedMessages:
    async def test_fetches_all_messages_by_id(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True, "id": "msg1"}

        messages = [{"id": "msg1"}, {"id": "msg2"}]
        with patch("app.services.mail.mail_service.time.sleep"):
            result = await fetch_detailed_messages(USER_ID, messages, batch_size=20)

        assert len(result) == 2
        assert mock_invoke_gmail_tool.call_count == 2
        # Both calls should use GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID
        for c in mock_invoke_gmail_tool.call_args_list:
            assert c[0][1] == "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID"

    async def test_skips_messages_without_id(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True}

        messages = [{"id": "msg1"}, {"no_id_key": "oops"}, {"id": "msg3"}]
        with patch("app.services.mail.mail_service.time.sleep"):
            await fetch_detailed_messages(USER_ID, messages, batch_size=20)

        # Only 2 valid messages were fetched
        assert mock_invoke_gmail_tool.call_count == 2

    async def test_omits_failed_messages_from_result(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {
            "successful": False,
            "error": "not found",
        }

        messages = [{"id": "bad_msg"}]
        with patch("app.services.mail.mail_service.time.sleep"):
            result = await fetch_detailed_messages(USER_ID, messages)

        assert result == []

    async def test_sleeps_between_batches(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True}

        # 3 messages with batch_size=2 → 2 batches → 1 sleep call
        messages = [{"id": f"msg{i}"} for i in range(3)]
        with patch("app.services.mail.mail_service.time.sleep") as mock_sleep:
            await fetch_detailed_messages(USER_ID, messages, batch_size=2, delay=1.5)

        mock_sleep.assert_called_once_with(1.5)

    async def test_no_sleep_when_single_batch(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True}

        messages = [{"id": "msg1"}, {"id": "msg2"}]
        with patch("app.services.mail.mail_service.time.sleep") as mock_sleep:
            await fetch_detailed_messages(USER_ID, messages, batch_size=20)

        mock_sleep.assert_not_called()

    async def test_returns_empty_list_for_empty_input(self, mock_invoke_gmail_tool):
        result = await fetch_detailed_messages(USER_ID, [])
        assert result == []
        mock_invoke_gmail_tool.assert_not_called()


# ---------------------------------------------------------------------------
# modify_message_labels
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModifyMessageLabels:
    async def test_returns_empty_list_when_no_labels_given(
        self, mock_invoke_gmail_tool
    ):
        result = await modify_message_labels(USER_ID, ["msg1"])
        assert result == []
        mock_invoke_gmail_tool.assert_not_called()

    async def test_adds_labels_via_correct_tool(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {
            "successful": True,
            "messages": [{"id": "msg1"}],
        }

        result = await modify_message_labels(
            USER_ID, ["msg1"], add_labels=["IMPORTANT"]
        )

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_ADD_LABEL_TO_EMAIL"
        assert args[2]["label_ids"] == ["IMPORTANT"]
        assert result == [{"id": "msg1"}]

    async def test_removes_labels_via_correct_tool(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {
            "successful": True,
            "messages": [{"id": "msg1"}],
        }

        result = await modify_message_labels(
            USER_ID, ["msg1"], remove_labels=["UNREAD"]
        )

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_REMOVE_LABEL"
        assert args[2]["label_ids"] == ["UNREAD"]
        assert result == [{"id": "msg1"}]

    async def test_both_add_and_remove_labels(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {
            "successful": True,
            "messages": [{"id": "msg1"}],
        }

        await modify_message_labels(
            USER_ID, ["msg1"], add_labels=["STARRED"], remove_labels=["UNREAD"]
        )

        # Should have been called twice: once for add, once for remove
        assert mock_invoke_gmail_tool.call_count == 2

        add_call, remove_call = mock_invoke_gmail_tool.call_args_list

        # First call must be the add-labels operation
        assert add_call[0][1] == "GMAIL_ADD_LABEL_TO_EMAIL"
        assert add_call[0][2]["label_ids"] == ["STARRED"]
        assert add_call[0][2]["message_ids"] == ["msg1"]

        # Second call must be the remove-labels operation
        assert remove_call[0][1] == "GMAIL_REMOVE_LABEL"
        assert remove_call[0][2]["label_ids"] == ["UNREAD"]
        assert remove_call[0][2]["message_ids"] == ["msg1"]

    async def test_gracefully_handles_tool_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("transient error")

        # Should not propagate - returns empty list
        result = await modify_message_labels(USER_ID, ["msg1"], add_labels=["STARRED"])

        assert result == []


# ---------------------------------------------------------------------------
# mark_messages_as_read / mark_messages_as_unread
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMarkReadUnread:
    async def test_mark_as_read_removes_unread_label(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True, "messages": []}

        await mark_messages_as_read(USER_ID, ["msg1", "msg2"])

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_REMOVE_LABEL"
        assert "UNREAD" in args[2]["label_ids"]

    async def test_mark_as_unread_adds_unread_label(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True, "messages": []}

        await mark_messages_as_unread(USER_ID, ["msg1"])

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_ADD_LABEL_TO_EMAIL"
        assert "UNREAD" in args[2]["label_ids"]


# ---------------------------------------------------------------------------
# star_messages / unstar_messages
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStarUnstar:
    async def test_star_adds_starred_label(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True, "messages": []}

        await star_messages(USER_ID, ["msg1"])

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_ADD_LABEL_TO_EMAIL"
        assert "STARRED" in args[2]["label_ids"]

    async def test_unstar_removes_starred_label(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True, "messages": []}

        await unstar_messages(USER_ID, ["msg1"])

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_REMOVE_LABEL"
        assert "STARRED" in args[2]["label_ids"]


# ---------------------------------------------------------------------------
# trash_messages / untrash_messages
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTrashUntrash:
    async def test_trash_calls_gmail_trash_per_message(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True}

        await trash_messages(USER_ID, ["msg1", "msg2"])

        assert mock_invoke_gmail_tool.call_count == 2
        tool_names = [c[0][1] for c in mock_invoke_gmail_tool.call_args_list]
        assert all(n == "GMAIL_TRASH_MESSAGE" for n in tool_names)

    async def test_trash_excludes_failed_messages_from_result(
        self, mock_invoke_gmail_tool
    ):
        mock_invoke_gmail_tool.return_value = {"successful": False, "error": "403"}

        result = await trash_messages(USER_ID, ["msg1"])

        assert result == []

    async def test_untrash_calls_gmail_untrash_per_message(
        self, mock_invoke_gmail_tool
    ):
        mock_invoke_gmail_tool.return_value = {"successful": True}

        await untrash_messages(USER_ID, ["msg1", "msg2"])

        assert mock_invoke_gmail_tool.call_count == 2
        tool_names = [c[0][1] for c in mock_invoke_gmail_tool.call_args_list]
        assert all(n == "GMAIL_UNTRASH_MESSAGE" for n in tool_names)

    async def test_trash_handles_exception_per_message(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("server error")

        # Should not raise; failed messages are simply skipped
        result = await trash_messages(USER_ID, ["msg1"])

        assert result == []


# ---------------------------------------------------------------------------
# archive_messages / move_to_inbox
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestArchiveMoveToInbox:
    async def test_archive_removes_inbox_label(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True, "messages": []}

        await archive_messages(USER_ID, ["msg1"])

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_REMOVE_LABEL"
        assert "INBOX" in args[2]["label_ids"]

    async def test_move_to_inbox_adds_inbox_label(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True, "messages": []}

        await move_to_inbox(USER_ID, ["msg1"])

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_ADD_LABEL_TO_EMAIL"
        assert "INBOX" in args[2]["label_ids"]


# ---------------------------------------------------------------------------
# fetch_thread
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchThread:
    async def test_returns_thread_with_transformed_messages(
        self, mock_invoke_gmail_tool, mock_transform
    ):
        mock_invoke_gmail_tool.return_value = {
            "successful": True,
            "messages": [
                {"internalDate": "2000", "subject": "Hi"},
                {"internalDate": "1000", "subject": "Hey"},
            ],
        }

        result = await fetch_thread(USER_ID, "thread_abc")

        # transform_gmail_message should have been called for each message
        assert mock_transform.call_count == 2
        # Messages should be sorted oldest first
        assert result["messages"][0]["internalDate"] == "1000"
        assert result["messages"][1]["internalDate"] == "2000"

    async def test_returns_empty_messages_on_failure(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": False, "error": "404"}

        result = await fetch_thread(USER_ID, "thread_abc")

        assert result == {"messages": []}

    async def test_returns_empty_messages_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("network error")

        result = await fetch_thread(USER_ID, "thread_abc")

        assert result == {"messages": []}

    async def test_calls_correct_tool_with_thread_id(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True, "messages": []}

        await fetch_thread(USER_ID, "thread_xyz")

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_FETCH_MESSAGE_BY_THREAD_ID"
        assert args[2]["thread_id"] == "thread_xyz"


# ---------------------------------------------------------------------------
# search_messages
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchMessages:
    async def test_returns_transformed_messages_and_next_token(
        self, mock_invoke_gmail_tool, mock_transform
    ):
        mock_invoke_gmail_tool.return_value = {
            "successful": True,
            "data": {
                "messages": [{"id": "m1"}, {"id": "m2"}],
                "nextPageToken": "tok123",
            },
        }

        result = await search_messages(USER_ID, query="is:unread", max_results=10)

        assert len(result["messages"]) == 2
        assert result["nextPageToken"] == "tok123"
        assert mock_transform.call_count == 2

    async def test_includes_page_token_when_provided(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {
            "successful": True,
            "data": {"messages": [], "nextPageToken": None},
        }

        await search_messages(USER_ID, query="test", page_token="prev_tok")

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert params["page_token"] == "prev_tok"

    async def test_returns_empty_result_on_failure(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": False, "error": "auth"}

        result = await search_messages(USER_ID)

        assert result == {"messages": [], "nextPageToken": None}

    async def test_returns_empty_result_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("503")

        result = await search_messages(USER_ID)

        assert result == {"messages": [], "nextPageToken": None}

    async def test_uses_empty_string_for_missing_query(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {
            "successful": True,
            "data": {"messages": [], "nextPageToken": None},
        }

        await search_messages(USER_ID)

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert params["query"] == ""


# ---------------------------------------------------------------------------
# create_label
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateLabel:
    async def test_creates_label_with_required_fields(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True, "id": "label1"}

        result = await create_label(USER_ID, name="Work")

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_CREATE_LABEL"
        assert args[2]["name"] == "Work"
        assert result == {"successful": True, "id": "label1"}

    async def test_includes_color_as_json_string_when_provided(
        self, mock_invoke_gmail_tool
    ):
        import json

        mock_invoke_gmail_tool.return_value = {"successful": True}

        await create_label(
            USER_ID, name="Work", background_color="#ff0000", text_color="#ffffff"
        )

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert "color" in params
        color = json.loads(params["color"])
        assert color["background_color"] == "#ff0000"
        assert color["text_color"] == "#ffffff"

    async def test_omits_color_when_not_provided(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True}

        await create_label(USER_ID, name="Personal")

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert "color" not in params

    async def test_returns_error_dict_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("label exists")

        result = await create_label(USER_ID, name="Work")

        assert result["successful"] is False
        assert "label exists" in result["error"]


# ---------------------------------------------------------------------------
# update_label
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateLabel:
    async def test_updates_label_with_provided_fields(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True}

        await update_label(USER_ID, label_id="lbl1", name="Updated Name")

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_PATCH_LABEL"
        params = args[2]
        assert params["label_id"] == "lbl1"
        assert params["name"] == "Updated Name"

    async def test_omits_optional_fields_not_provided(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True}

        await update_label(USER_ID, label_id="lbl1")

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert "name" not in params
        assert "color" not in params

    async def test_returns_error_dict_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("label not found")

        result = await update_label(USER_ID, label_id="lbl1")

        assert result["successful"] is False


# ---------------------------------------------------------------------------
# delete_label
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteLabel:
    async def test_returns_true_on_success(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True}

        result = await delete_label(USER_ID, "lbl1")

        assert result is True
        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_DELETE_LABEL"
        assert args[2]["label_id"] == "lbl1"

    async def test_returns_false_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("permission denied")

        result = await delete_label(USER_ID, "lbl1")

        assert result is False


# ---------------------------------------------------------------------------
# apply_labels / remove_labels
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApplyRemoveLabels:
    async def test_apply_labels_delegates_to_add(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True, "messages": []}

        await apply_labels(USER_ID, ["msg1"], ["IMPORTANT", "WORK"])

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_ADD_LABEL_TO_EMAIL"
        assert set(args[2]["label_ids"]) == {"IMPORTANT", "WORK"}

    async def test_remove_labels_delegates_to_remove(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True, "messages": []}

        await remove_labels(USER_ID, ["msg1"], ["INBOX"])

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_REMOVE_LABEL"
        assert "INBOX" in args[2]["label_ids"]


# ---------------------------------------------------------------------------
# create_draft
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateDraft:
    async def test_creates_draft_with_required_fields(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True, "id": "draft1"}

        result = await create_draft(
            user_id=USER_ID,
            sender="me@example.com",
            to_list=["bob@example.com"],
            subject="Draft subject",
            body="Draft body",
        )

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_CREATE_EMAIL_DRAFT"
        params = args[2]
        assert params["to"] == ["bob@example.com"]
        assert params["subject"] == "Draft subject"
        assert result == {"successful": True, "id": "draft1"}

    async def test_includes_cc_bcc_when_provided(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True}

        await create_draft(
            user_id=USER_ID,
            sender="me@example.com",
            to_list=["bob@example.com"],
            subject="Hi",
            body="Body",
            cc_list=["cc@example.com"],
            bcc_list=["bcc@example.com"],
        )

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert params["cc"] == ["cc@example.com"]
        assert params["bcc"] == ["bcc@example.com"]

    async def test_sets_html_flag_when_is_html_true(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True}

        await create_draft(
            user_id=USER_ID,
            sender="me@example.com",
            to_list=["bob@example.com"],
            subject="Hi",
            body="<b>HTML</b>",
            is_html=True,
        )

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert params.get("html") is True

    async def test_returns_error_dict_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("quota exceeded")

        result = await create_draft(
            user_id=USER_ID,
            sender="me@example.com",
            to_list=["bob@example.com"],
            subject="Hi",
            body="Body",
        )

        assert result["successful"] is False


# ---------------------------------------------------------------------------
# list_drafts
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListDrafts:
    async def test_returns_drafts_with_transformed_messages(
        self, mock_invoke_gmail_tool, mock_transform
    ):
        mock_invoke_gmail_tool.return_value = {
            "successful": True,
            "drafts": [
                {"id": "d1", "message": {"id": "m1", "subject": "Test"}},
            ],
            "nextPageToken": "tok",
        }

        result = await list_drafts(USER_ID, max_results=5)

        assert len(result["drafts"]) == 1
        assert result["nextPageToken"] == "tok"
        mock_transform.assert_called_once()

    async def test_includes_page_token_when_provided(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {
            "successful": True,
            "drafts": [],
            "nextPageToken": None,
        }

        await list_drafts(USER_ID, page_token="prev_tok")

        params = mock_invoke_gmail_tool.call_args[0][2]
        assert params["page_token"] == "prev_tok"

    async def test_returns_empty_on_failure(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": False, "error": "auth"}

        result = await list_drafts(USER_ID)

        assert result == {"drafts": [], "nextPageToken": None}

    async def test_returns_empty_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("timeout")

        result = await list_drafts(USER_ID)

        assert result == {"drafts": [], "nextPageToken": None}


# ---------------------------------------------------------------------------
# get_draft
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDraft:
    async def test_returns_draft_with_transformed_message(
        self, mock_invoke_gmail_tool, mock_transform
    ):
        mock_invoke_gmail_tool.return_value = {
            "successful": True,
            "id": "draft1",
            "message": {"id": "m1"},
        }

        result = await get_draft(USER_ID, "draft1")

        mock_transform.assert_called_once()
        assert "message" in result

    async def test_returns_error_on_failure(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {
            "successful": False,
            "error": "not found",
        }

        result = await get_draft(USER_ID, "draft1")

        assert result["successful"] is False

    async def test_returns_error_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("server error")

        result = await get_draft(USER_ID, "draft1")

        assert result["successful"] is False


# ---------------------------------------------------------------------------
# update_draft
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateDraft:
    async def test_updates_draft_with_correct_params(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True}

        await update_draft(
            user_id=USER_ID,
            draft_id="draft1",
            sender="me@example.com",
            to_list=["bob@example.com"],
            subject="Updated Subject",
            body="Updated body",
        )

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_UPDATE_DRAFT"
        params = args[2]
        assert params["draft_id"] == "draft1"
        assert params["subject"] == "Updated Subject"

    async def test_returns_error_on_failure(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": False, "error": "locked"}

        result = await update_draft(
            user_id=USER_ID,
            draft_id="draft1",
            sender="me@example.com",
            to_list=["bob@example.com"],
            subject="Hi",
            body="Body",
        )

        assert result["successful"] is False


# ---------------------------------------------------------------------------
# delete_draft
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteDraft:
    async def test_returns_true_on_success(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True}

        result = await delete_draft(USER_ID, "draft1")

        assert result is True
        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_DELETE_DRAFT"

    async def test_returns_false_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("not found")

        result = await delete_draft(USER_ID, "draft1")

        assert result is False


# ---------------------------------------------------------------------------
# send_draft
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSendDraft:
    async def test_sends_draft_via_correct_tool(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {"successful": True, "messageId": "msg1"}

        result = await send_draft(USER_ID, "draft1")

        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_SEND_DRAFT"
        assert args[2]["draft_id"] == "draft1"
        assert result == {"successful": True, "messageId": "msg1"}

    async def test_returns_error_on_failure(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {
            "successful": False,
            "error": "draft not found",
        }

        result = await send_draft(USER_ID, "draft1")

        assert result["successful"] is False

    async def test_returns_error_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("timeout")

        result = await send_draft(USER_ID, "draft1")

        assert result["successful"] is False


# ---------------------------------------------------------------------------
# list_labels
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListLabels:
    async def test_returns_labels_with_count(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {
            "successful": True,
            "labels": [
                {"id": "INBOX", "name": "INBOX"},
                {"id": "lbl1", "name": "Work"},
            ],
        }

        result = await list_labels(USER_ID)

        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["labels"]) == 2
        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_LIST_LABELS"

    async def test_returns_failure_on_tool_error(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {
            "successful": False,
            "error": "auth error",
        }

        result = await list_labels(USER_ID)

        assert result["success"] is False
        assert result["labels"] == []

    async def test_returns_failure_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("service unavailable")

        result = await list_labels(USER_ID)

        assert result["success"] is False
        assert result["labels"] == []


# ---------------------------------------------------------------------------
# get_email_by_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetEmailById:
    async def test_returns_transformed_message_on_success(
        self, mock_invoke_gmail_tool, mock_transform
    ):
        mock_invoke_gmail_tool.return_value = {
            "successful": True,
            "id": "msg1",
            "subject": "Hello",
        }

        result = await get_email_by_id(USER_ID, "msg1")

        assert result["success"] is True
        assert "message" in result
        mock_transform.assert_called_once()
        args, _ = mock_invoke_gmail_tool.call_args
        assert args[1] == "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID"
        assert args[2]["message_id"] == "msg1"

    async def test_returns_failure_on_tool_error(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {
            "successful": False,
            "error": "not found",
        }

        result = await get_email_by_id(USER_ID, "msg1")

        assert result["success"] is False
        assert result["message"] is None

    async def test_returns_failure_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("network failure")

        result = await get_email_by_id(USER_ID, "msg1")

        assert result["success"] is False
        assert result["message"] is None


# ---------------------------------------------------------------------------
# get_contact_list
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetContactList:
    async def test_extracts_contacts_from_message_headers(self, mock_invoke_gmail_tool):
        # First call: GMAIL_FETCH_EMAILS (search)
        # Second call: GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID (details)
        mock_invoke_gmail_tool.side_effect = [
            {"successful": True, "messages": [{"id": "msg1"}]},
            {
                "successful": True,
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Alice <alice@example.com>"},
                        {"name": "To", "value": "Bob <bob@example.com>"},
                    ]
                },
            },
        ]

        result = await get_contact_list(USER_ID)

        assert len(result) == 2
        emails = {c["email"] for c in result}
        assert "alice@example.com" in emails
        assert "bob@example.com" in emails

    async def test_parses_bare_email_addresses(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = [
            {"successful": True, "messages": [{"id": "msg1"}]},
            {
                "successful": True,
                "payload": {
                    "headers": [
                        {"name": "From", "value": "raw@example.com"},
                    ]
                },
            },
        ]

        result = await get_contact_list(USER_ID)

        assert len(result) == 1
        assert result[0]["email"] == "raw@example.com"
        assert result[0]["name"] == ""

    async def test_deduplicates_contacts(self, mock_invoke_gmail_tool):
        # Same address appears in two messages
        msg_detail = {
            "successful": True,
            "payload": {
                "headers": [
                    {"name": "From", "value": "Alice <alice@example.com>"},
                ]
            },
        }
        mock_invoke_gmail_tool.side_effect = [
            {"successful": True, "messages": [{"id": "msg1"}, {"id": "msg2"}]},
            msg_detail,
            msg_detail,
        ]

        result = await get_contact_list(USER_ID)

        assert len(result) == 1
        assert result[0]["email"] == "alice@example.com"

    async def test_returns_empty_list_on_search_failure(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {
            "successful": False,
            "error": "auth failed",
        }

        result = await get_contact_list(USER_ID)

        assert result == []

    async def test_returns_empty_list_on_exception(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = Exception("crash")

        result = await get_contact_list(USER_ID)

        assert result == []

    async def test_skips_messages_without_id(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.return_value = {
            "successful": True,
            "messages": [{"no_id": "value"}],
        }

        result = await get_contact_list(USER_ID)

        # Only one tool call was made (the search), no detail fetches
        assert mock_invoke_gmail_tool.call_count == 1
        assert result == []

    async def test_returns_contacts_sorted_by_name(self, mock_invoke_gmail_tool):
        mock_invoke_gmail_tool.side_effect = [
            {
                "successful": True,
                "messages": [{"id": "msg1"}, {"id": "msg2"}],
            },
            {
                "successful": True,
                "payload": {
                    "headers": [{"name": "From", "value": "Zoe <zoe@example.com>"}]
                },
            },
            {
                "successful": True,
                "payload": {
                    "headers": [{"name": "From", "value": "Alice <alice@example.com>"}]
                },
            },
        ]

        result = await get_contact_list(USER_ID)

        assert result[0]["name"] == "Alice"
        assert result[1]["name"] == "Zoe"

    async def test_extracts_contacts_from_to_and_cc_headers(
        self, mock_invoke_gmail_tool
    ):
        """All of From, To, and Cc addresses must appear in the result."""
        mock_invoke_gmail_tool.side_effect = [
            {"successful": True, "messages": [{"id": "msg1"}]},
            {
                "successful": True,
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Alice <alice@example.com>"},
                        {"name": "To", "value": "Bob <bob@example.com>"},
                        {"name": "Cc", "value": "Carol <carol@example.com>"},
                    ]
                },
            },
        ]

        result = await get_contact_list(USER_ID)

        emails = {c["email"] for c in result}
        assert emails == {
            "alice@example.com",
            "bob@example.com",
            "carol@example.com",
        }

    async def test_deduplicates_contacts_by_email_address(self, mock_invoke_gmail_tool):
        """The same email address in both To and Cc should appear only once."""
        mock_invoke_gmail_tool.side_effect = [
            {"successful": True, "messages": [{"id": "msg1"}]},
            {
                "successful": True,
                "payload": {
                    "headers": [
                        {"name": "To", "value": "Bob <bob@example.com>"},
                        {"name": "Cc", "value": "Bob <bob@example.com>"},
                    ]
                },
            },
        ]

        result = await get_contact_list(USER_ID)

        assert len(result) == 1
        assert result[0]["email"] == "bob@example.com"

    async def test_does_not_exclude_user_own_email(self, mock_invoke_gmail_tool):
        """Production code has no self-filtering; the caller's address is kept."""
        mock_invoke_gmail_tool.side_effect = [
            {"successful": True, "messages": [{"id": "msg1"}]},
            {
                "successful": True,
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Me <me@example.com>"},
                        {"name": "To", "value": "Other <other@example.com>"},
                    ]
                },
            },
        ]

        result = await get_contact_list(USER_ID)

        emails = {c["email"] for c in result}
        # The user's own address is NOT filtered out by the production code
        assert "me@example.com" in emails
        assert "other@example.com" in emails

    async def test_extracts_reply_to_header(self, mock_invoke_gmail_tool):
        """Reply-To addresses should also be collected."""
        mock_invoke_gmail_tool.side_effect = [
            {"successful": True, "messages": [{"id": "msg1"}]},
            {
                "successful": True,
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Sender <sender@example.com>"},
                        {
                            "name": "Reply-To",
                            "value": "replies@example.com",
                        },
                    ]
                },
            },
        ]

        result = await get_contact_list(USER_ID)

        emails = {c["email"] for c in result}
        assert "replies@example.com" in emails

    async def test_skips_detail_fetch_on_failure(self, mock_invoke_gmail_tool):
        """Messages whose detail fetch returns successful=False are silently skipped."""
        mock_invoke_gmail_tool.side_effect = [
            {"successful": True, "messages": [{"id": "msg1"}, {"id": "msg2"}]},
            {"successful": False, "error": "not found"},
            {
                "successful": True,
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Bob <bob@example.com>"},
                    ]
                },
            },
        ]

        result = await get_contact_list(USER_ID)

        # Only the second message yielded a contact
        assert len(result) == 1
        assert result[0]["email"] == "bob@example.com"

    async def test_ignores_addresses_without_at_sign(self, mock_invoke_gmail_tool):
        """Strings that are not valid email addresses must not appear in result."""
        mock_invoke_gmail_tool.side_effect = [
            {"successful": True, "messages": [{"id": "msg1"}]},
            {
                "successful": True,
                "payload": {
                    "headers": [
                        {"name": "From", "value": "not-an-email"},
                        {"name": "To", "value": "real@example.com"},
                    ]
                },
            },
        ]

        result = await get_contact_list(USER_ID)

        assert len(result) == 1
        assert result[0]["email"] == "real@example.com"

    async def test_handles_multiple_addresses_in_single_header(
        self, mock_invoke_gmail_tool
    ):
        """Comma-separated addresses in a single header are each extracted."""
        mock_invoke_gmail_tool.side_effect = [
            {"successful": True, "messages": [{"id": "msg1"}]},
            {
                "successful": True,
                "payload": {
                    "headers": [
                        {
                            "name": "To",
                            "value": "Alice <alice@example.com>, Bob <bob@example.com>",
                        },
                    ]
                },
            },
        ]

        result = await get_contact_list(USER_ID)

        emails = {c["email"] for c in result}
        assert "alice@example.com" in emails
        assert "bob@example.com" in emails
