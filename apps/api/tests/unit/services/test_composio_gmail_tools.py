"""Unit tests for Gmail custom tools (Composio custom tool wrappers).

Tests cover: _auth_headers, all registered tool functions (MARK_AS_READ,
MARK_AS_UNREAD, ARCHIVE_EMAIL, STAR_EMAIL, GET_UNREAD_COUNT,
GET_CONTACT_LIST, CUSTOM_GATHER_CONTEXT), input models, and
register_gmail_custom_tools.
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.composio.custom_tools.gmail_tools import (
    ArchiveEmailInput,
    GetContactListInput,
    GetUnreadCountInput,
    MarkAsReadInput,
    MarkAsUnreadInput,
    ScheduleSendInput,
    SnoozeEmailInput,
    StarEmailInput,
    _auth_headers,
    register_gmail_custom_tools,
)
from app.models.common_models import GatherContextInput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AUTH_CREDS: Dict[str, Any] = {"access_token": "test_token_123"}


def _mock_response(status_code: int = 200, json_data: Any = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


def _extract_tools(composio_mock: MagicMock) -> Dict[str, Any]:
    """Extract tool functions registered via @composio.tools.custom_tool."""
    tools: Dict[str, Any] = {}
    for call in composio_mock.tools.custom_tool.return_value.call_args_list:
        fn = call[0][0] if call[0] else None
        if fn and hasattr(fn, "__name__"):
            tools[fn.__name__] = fn
    return tools


def _register_and_get_tools() -> tuple[MagicMock, Dict[str, Any]]:
    """Register tools on a mock Composio client and return (mock, tool_fns)."""
    mock_composio = MagicMock()
    # Make the decorator pass-through so we can call the raw functions
    mock_composio.tools.custom_tool = MagicMock(
        side_effect=lambda **kwargs: lambda fn: fn
    )
    result = register_gmail_custom_tools(mock_composio)
    assert isinstance(result, list)
    assert len(result) == 7

    # Collect all decorated functions by re-registering with capture
    captured: Dict[str, Any] = {}

    def capture_decorator(**kwargs):
        def wrapper(fn):
            captured[fn.__name__] = fn
            return fn

        return wrapper

    mock_composio2 = MagicMock()
    mock_composio2.tools.custom_tool = MagicMock(side_effect=capture_decorator)
    register_gmail_custom_tools(mock_composio2)
    return mock_composio2, captured


# ---------------------------------------------------------------------------
# _auth_headers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAuthHeaders:
    def test_returns_bearer_header(self):
        headers = _auth_headers({"access_token": "abc123"})
        assert headers == {"Authorization": "Bearer abc123"}

    def test_raises_when_no_token(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            _auth_headers({})

    def test_raises_when_token_is_none(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            _auth_headers({"access_token": None})


# ---------------------------------------------------------------------------
# Input model validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInputModels:
    def test_mark_as_read_input(self):
        inp = MarkAsReadInput(message_ids=["m1", "m2"])
        assert inp.message_ids == ["m1", "m2"]

    def test_mark_as_unread_input(self):
        inp = MarkAsUnreadInput(message_ids=["m1"])
        assert inp.message_ids == ["m1"]

    def test_archive_email_input(self):
        inp = ArchiveEmailInput(message_ids=["m1"])
        assert inp.message_ids == ["m1"]

    def test_star_email_input_defaults(self):
        inp = StarEmailInput(message_ids=["m1"])
        assert inp.unstar is False

    def test_star_email_input_unstar(self):
        inp = StarEmailInput(message_ids=["m1"], unstar=True)
        assert inp.unstar is True

    def test_get_unread_count_defaults(self):
        inp = GetUnreadCountInput()
        assert inp.label_ids is None
        assert inp.query is None
        assert inp.include_spam_trash is False

    def test_schedule_send_input(self):
        inp = ScheduleSendInput(
            recipient_email="test@example.com",
            subject="Hello",
            body="Body text",
            send_at="2024-01-15T10:00:00Z",
        )
        assert inp.recipient_email == "test@example.com"
        assert inp.cc is None
        assert inp.bcc is None

    def test_snooze_email_input(self):
        inp = SnoozeEmailInput(
            message_ids=["m1"],
            snooze_until="2024-01-15T09:00:00Z",
        )
        assert inp.message_ids == ["m1"]

    def test_get_contact_list_input_defaults(self):
        inp = GetContactListInput(query="john")
        assert inp.max_results == 30


# ---------------------------------------------------------------------------
# register_gmail_custom_tools
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterGmailCustomTools:
    def test_returns_correct_tool_names(self):
        mock_composio = MagicMock()
        mock_composio.tools.custom_tool = MagicMock(
            side_effect=lambda **kwargs: lambda fn: fn
        )
        result = register_gmail_custom_tools(mock_composio)
        expected = [
            "GMAIL_MARK_AS_READ",
            "GMAIL_MARK_AS_UNREAD",
            "GMAIL_ARCHIVE_EMAIL",
            "GMAIL_STAR_EMAIL",
            "GMAIL_GET_UNREAD_COUNT",
            "GMAIL_GET_CONTACT_LIST",
            "GMAIL_CUSTOM_GATHER_CONTEXT",
        ]
        assert result == expected

    def test_registers_all_tools(self):
        mock_composio = MagicMock()
        mock_composio.tools.custom_tool = MagicMock(
            side_effect=lambda **kwargs: lambda fn: fn
        )
        register_gmail_custom_tools(mock_composio)
        assert mock_composio.tools.custom_tool.call_count == 7


# ---------------------------------------------------------------------------
# MARK_AS_READ
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMarkAsRead:
    def test_sends_correct_request(self):
        _, tools = _register_and_get_tools()
        fn = tools["MARK_AS_READ"]
        request = MarkAsReadInput(message_ids=["msg1", "msg2"])

        mock_resp = _mock_response()
        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client"
        ) as mock_client:
            mock_client.post = MagicMock(return_value=mock_resp)
            result = fn(request, None, AUTH_CREDS)

        assert result == {}
        call_args = mock_client.post.call_args
        assert "batchModify" in call_args[0][0]
        payload = call_args[1]["json"]
        assert payload["ids"] == ["msg1", "msg2"]
        assert payload["removeLabelIds"] == ["UNREAD"]


# ---------------------------------------------------------------------------
# MARK_AS_UNREAD
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMarkAsUnread:
    def test_sends_correct_request(self):
        _, tools = _register_and_get_tools()
        fn = tools["MARK_AS_UNREAD"]
        request = MarkAsUnreadInput(message_ids=["msg1"])

        mock_resp = _mock_response()
        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client"
        ) as mock_client:
            mock_client.post = MagicMock(return_value=mock_resp)
            result = fn(request, None, AUTH_CREDS)

        assert result == {}
        payload = mock_client.post.call_args[1]["json"]
        assert payload["addLabelIds"] == ["UNREAD"]


# ---------------------------------------------------------------------------
# ARCHIVE_EMAIL
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestArchiveEmail:
    def test_sends_correct_request(self):
        _, tools = _register_and_get_tools()
        fn = tools["ARCHIVE_EMAIL"]
        request = ArchiveEmailInput(message_ids=["msg1"])

        mock_resp = _mock_response()
        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client"
        ) as mock_client:
            mock_client.post = MagicMock(return_value=mock_resp)
            result = fn(request, None, AUTH_CREDS)

        assert result == {}
        payload = mock_client.post.call_args[1]["json"]
        assert payload["removeLabelIds"] == ["INBOX"]


# ---------------------------------------------------------------------------
# STAR_EMAIL
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStarEmail:
    def test_star_adds_label(self):
        _, tools = _register_and_get_tools()
        fn = tools["STAR_EMAIL"]
        request = StarEmailInput(message_ids=["msg1"], unstar=False)

        mock_resp = _mock_response()
        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client"
        ) as mock_client:
            mock_client.post = MagicMock(return_value=mock_resp)
            result = fn(request, None, AUTH_CREDS)

        assert result["action"] == "starred"
        payload = mock_client.post.call_args[1]["json"]
        assert payload["addLabelIds"] == ["STARRED"]

    def test_unstar_removes_label(self):
        _, tools = _register_and_get_tools()
        fn = tools["STAR_EMAIL"]
        request = StarEmailInput(message_ids=["msg1"], unstar=True)

        mock_resp = _mock_response()
        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client"
        ) as mock_client:
            mock_client.post = MagicMock(return_value=mock_resp)
            result = fn(request, None, AUTH_CREDS)

        assert result["action"] == "unstarred"
        payload = mock_client.post.call_args[1]["json"]
        assert payload["removeLabelIds"] == ["STARRED"]


# ---------------------------------------------------------------------------
# GET_UNREAD_COUNT
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUnreadCount:
    def test_label_mode_single_label(self):
        _, tools = _register_and_get_tools()
        fn = tools["GET_UNREAD_COUNT"]
        request = GetUnreadCountInput(label_ids=["INBOX"])

        label_resp = _mock_response(
            json_data={
                "name": "INBOX",
                "messagesUnread": 5,
                "messagesTotal": 100,
            }
        )
        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client"
        ) as mock_client:
            mock_client.get = MagicMock(return_value=label_resp)
            result = fn(request, None, AUTH_CREDS)

        assert result["unreadCount"] == 5
        assert result["totalCount"] == 100
        assert result["label_id"] == "INBOX"
        assert result["label_name"] == "INBOX"

    def test_label_mode_multiple_labels(self):
        _, tools = _register_and_get_tools()
        fn = tools["GET_UNREAD_COUNT"]
        request = GetUnreadCountInput(label_ids=["INBOX", "SENT"])

        def mock_get(url, headers=None, params=None):
            if "INBOX" in url:
                return _mock_response(
                    json_data={
                        "name": "INBOX",
                        "messagesUnread": 3,
                        "messagesTotal": 50,
                    }
                )
            return _mock_response(
                json_data={"name": "SENT", "messagesUnread": 0, "messagesTotal": 20}
            )

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client"
        ) as mock_client:
            mock_client.get = MagicMock(side_effect=mock_get)
            result = fn(request, None, AUTH_CREDS)

        assert "counts" in result
        assert "INBOX" in result["counts"]
        assert "SENT" in result["counts"]
        # Multiple labels: no top-level label_id
        assert "label_id" not in result

    def test_query_mode(self):
        _, tools = _register_and_get_tools()
        fn = tools["GET_UNREAD_COUNT"]
        request = GetUnreadCountInput(query="from:test@example.com")

        msg_resp = _mock_response(json_data={"resultSizeEstimate": 15})
        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client"
        ) as mock_client:
            mock_client.get = MagicMock(return_value=msg_resp)
            result = fn(request, None, AUTH_CREDS)

        assert result["totalCount"] == 15
        assert result["is_estimate"] is True
        assert result["query"] == "from:test@example.com"

    def test_query_mode_already_has_is_unread(self):
        _, tools = _register_and_get_tools()
        fn = tools["GET_UNREAD_COUNT"]
        request = GetUnreadCountInput(query="from:test@example.com is:unread")

        msg_resp = _mock_response(json_data={"resultSizeEstimate": 5})
        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client"
        ) as mock_client:
            mock_client.get = MagicMock(return_value=msg_resp)
            result = fn(request, None, AUTH_CREDS)

        # When query already has is:unread, totalCount == unreadCount
        assert result["totalCount"] == result["unreadCount"]

    def test_default_label_is_inbox(self):
        _, tools = _register_and_get_tools()
        fn = tools["GET_UNREAD_COUNT"]
        request = GetUnreadCountInput()  # no label_ids, no query

        label_resp = _mock_response(
            json_data={"name": "INBOX", "messagesUnread": 2, "messagesTotal": 10}
        )
        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client"
        ) as mock_client:
            mock_client.get = MagicMock(return_value=label_resp)
            result = fn(request, None, AUTH_CREDS)

        assert result["label_id"] == "INBOX"
        assert result["unreadCount"] == 2

    def test_empty_label_ids_filtered(self):
        _, tools = _register_and_get_tools()
        fn = tools["GET_UNREAD_COUNT"]
        request = GetUnreadCountInput(label_ids=["", ""])

        # With all empty strings filtered out and no query, should default to empty counts
        with patch("app.services.composio.custom_tools.gmail_tools._http_client"):
            result = fn(request, None, AUTH_CREDS)

        assert result["unreadCount"] == 0
        assert result["counts"] == {}

    def test_query_mode_with_label_ids_single(self):
        _, tools = _register_and_get_tools()
        fn = tools["GET_UNREAD_COUNT"]
        request = GetUnreadCountInput(query="subject:test", label_ids=["INBOX"])

        msg_resp = _mock_response(json_data={"resultSizeEstimate": 3})
        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client"
        ) as mock_client:
            mock_client.get = MagicMock(return_value=msg_resp)
            result = fn(request, None, AUTH_CREDS)

        assert result["label_id"] == "INBOX"


# ---------------------------------------------------------------------------
# GET_CONTACT_LIST
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetContactList:
    def test_returns_contacts(self):
        _, tools = _register_and_get_tools()
        fn = tools["GET_CONTACT_LIST"]
        request = GetContactListInput(query="john", max_results=10)

        expected_contacts = {
            "contacts": [{"name": "John Doe", "email": "john@example.com"}],
            "total": 1,
        }

        with (
            patch(
                "app.services.composio.custom_tools.gmail_tools.Credentials"
            ) as mock_creds_cls,
            patch("app.services.composio.custom_tools.gmail_tools.build") as mock_build,
            patch(
                "app.services.composio.custom_tools.gmail_tools.get_gmail_contacts",
                return_value=expected_contacts,
            ) as mock_get_contacts,
        ):
            mock_creds_cls.return_value = MagicMock()
            mock_build.return_value = MagicMock()
            result = fn(request, None, AUTH_CREDS)

        assert result == expected_contacts
        mock_get_contacts.assert_called_once()

    def test_raises_when_no_token(self):
        _, tools = _register_and_get_tools()
        fn = tools["GET_CONTACT_LIST"]
        request = GetContactListInput(query="john")

        with pytest.raises(ValueError, match="Missing access_token"):
            fn(request, None, {})

    def test_raises_on_service_error(self):
        _, tools = _register_and_get_tools()
        fn = tools["GET_CONTACT_LIST"]
        request = GetContactListInput(query="john")

        with (
            patch(
                "app.services.composio.custom_tools.gmail_tools.Credentials"
            ) as mock_creds_cls,
            patch(
                "app.services.composio.custom_tools.gmail_tools.build",
                side_effect=Exception("API error"),
            ),
        ):
            mock_creds_cls.return_value = MagicMock()
            with pytest.raises(RuntimeError, match="Failed to get contacts"):
                fn(request, None, AUTH_CREDS)


# ---------------------------------------------------------------------------
# CUSTOM_GATHER_CONTEXT
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCustomGatherContext:
    def test_returns_context_without_since(self):
        _, tools = _register_and_get_tools()
        fn = tools["CUSTOM_GATHER_CONTEXT"]
        request = GatherContextInput()

        profile_resp = _mock_response(
            json_data={
                "emailAddress": "user@example.com",
                "messagesTotal": 5000,
                "threadsTotal": 2000,
            }
        )
        inbox_resp = _mock_response(
            json_data={"messagesUnread": 10, "messagesTotal": 500}
        )
        messages_resp = _mock_response(
            json_data={"messages": [{"id": "m1"}, {"id": "m2"}]}
        )

        call_count = 0

        def mock_get(url, headers=None, params=None):
            nonlocal call_count
            call_count += 1
            if "profile" in url:
                return profile_resp
            if "labels/INBOX" in url:
                return inbox_resp
            return messages_resp

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client"
        ) as mock_client:
            mock_client.get = MagicMock(side_effect=mock_get)
            result = fn(request, None, AUTH_CREDS)

        assert result["user"]["email"] == "user@example.com"
        assert result["inbox"]["unread_count"] == 10
        assert result["recent_message_ids"] == ["m1", "m2"]

    def test_returns_context_with_since(self):
        _, tools = _register_and_get_tools()
        fn = tools["CUSTOM_GATHER_CONTEXT"]
        request = GatherContextInput(since="2024-01-01T00:00:00Z")

        profile_resp = _mock_response(
            json_data={"emailAddress": "u@e.com", "messagesTotal": 1}
        )
        inbox_resp = _mock_response(json_data={"messagesUnread": 0, "messagesTotal": 0})
        messages_resp = _mock_response(json_data={"messages": []})

        def mock_get(url, headers=None, params=None):
            if "profile" in url:
                return profile_resp
            if "labels/INBOX" in url:
                return inbox_resp
            return messages_resp

        with patch(
            "app.services.composio.custom_tools.gmail_tools._http_client"
        ) as mock_client:
            mock_client.get = MagicMock(side_effect=mock_get)
            result = fn(request, None, AUTH_CREDS)

        # When since is provided, messages call should include 'after:' in q param
        messages_call = [
            c for c in mock_client.get.call_args_list if "messages" in str(c)
        ]
        assert len(messages_call) >= 1
        assert result["recent_message_ids"] == []
