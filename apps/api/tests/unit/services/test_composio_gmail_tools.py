"""Unit tests for Gmail custom tools (post-Composio-proxy migration).

Each tool routes provider API calls through `proxy_request_sync` instead of
raw httpx. Tests patch that helper and assert on the request shape.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.models.common_models import GatherContextInput
from app.services.composio.custom_tools.gmail_tools import (
    ArchiveEmailInput,
    GetContactListInput,
    GetUnreadCountInput,
    MarkAsReadInput,
    MarkAsUnreadInput,
    ScheduleSendInput,
    SnoozeEmailInput,
    StarEmailInput,
    register_gmail_custom_tools,
)

AUTH_CREDS: dict[str, Any] = {"user_id": "user_test_123"}
PROXY_PATH = "app.services.composio.custom_tools.gmail_tools.proxy_request_sync"


@pytest.fixture
def mock_proxy():
    with patch(PROXY_PATH) as proxy:
        proxy.return_value = {}
        yield proxy


def _register_and_get_tools() -> dict[str, Any]:
    """Register tools on a mock Composio client and return the tool functions."""
    tools: dict[str, Any] = {}
    mock_composio = MagicMock()

    def custom_tool_decorator(**_kwargs):
        def decorator(fn):
            tools[fn.__name__] = fn
            return fn

        return decorator

    mock_composio.tools.custom_tool = MagicMock(side_effect=custom_tool_decorator)
    register_gmail_custom_tools(mock_composio)
    return tools


# ---------------------------------------------------------------------------
# Pydantic input models
# ---------------------------------------------------------------------------


class TestInputModels:
    def test_mark_as_read(self):
        m = MarkAsReadInput(message_ids=["m1", "m2"])
        assert m.message_ids == ["m1", "m2"]

    def test_mark_as_unread(self):
        assert MarkAsUnreadInput(message_ids=["x"]).message_ids == ["x"]

    def test_archive_email(self):
        assert ArchiveEmailInput(message_ids=["x"]).message_ids == ["x"]

    def test_star_email_default_unstar_false(self):
        m = StarEmailInput(message_ids=["x"])
        assert m.unstar is False

    def test_get_unread_count_defaults(self):
        m = GetUnreadCountInput()
        assert m.label_ids is None
        assert m.query is None
        assert m.include_spam_trash is False

    def test_get_contact_list_default_max_results(self):
        m = GetContactListInput(query="foo")
        assert m.max_results == 30

    def test_schedule_send_required_fields(self):
        m = ScheduleSendInput(
            recipient_email="a@b.c",
            subject="s",
            body="b",
            send_at="2025-01-01T10:00:00Z",
        )
        assert m.cc is None

    def test_snooze_email(self):
        m = SnoozeEmailInput(message_ids=["x"], snooze_until="2025-01-01T10:00:00Z")
        assert m.message_ids == ["x"]


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_returns_expected_tool_names(self):
        mock_composio = MagicMock()
        mock_composio.tools.custom_tool = MagicMock(side_effect=lambda **_kw: lambda fn: fn)
        names = register_gmail_custom_tools(mock_composio)
        assert names == [
            "GMAIL_MARK_AS_READ",
            "GMAIL_MARK_AS_UNREAD",
            "GMAIL_ARCHIVE_EMAIL",
            "GMAIL_STAR_EMAIL",
            "GMAIL_GET_UNREAD_COUNT",
            "GMAIL_GET_CONTACT_LIST",
            "GMAIL_CUSTOM_GATHER_CONTEXT",
        ]


# ---------------------------------------------------------------------------
# Label-modifying tools
# ---------------------------------------------------------------------------


class TestMarkAsRead:
    def test_calls_batch_modify_with_remove_unread(self, mock_proxy):
        tools = _register_and_get_tools()
        tools["MARK_AS_READ"](
            request=MarkAsReadInput(message_ids=["m1", "m2"]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        kwargs = mock_proxy.call_args.kwargs
        assert kwargs["toolkit"] == "GMAIL"
        assert kwargs["method"] == "POST"
        assert kwargs["endpoint"].endswith("/users/me/messages/batchModify")
        assert kwargs["body"] == {
            "ids": ["m1", "m2"],
            "removeLabelIds": ["UNREAD"],
        }

    def test_missing_user_id_raises(self):
        tools = _register_and_get_tools()
        with pytest.raises(ValueError):
            tools["MARK_AS_READ"](
                request=MarkAsReadInput(message_ids=["m1"]),
                execute_request=MagicMock(),
                auth_credentials={},
            )


class TestMarkAsUnread:
    def test_adds_unread_label(self, mock_proxy):
        tools = _register_and_get_tools()
        tools["MARK_AS_UNREAD"](
            request=MarkAsUnreadInput(message_ids=["m1"]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert mock_proxy.call_args.kwargs["body"] == {
            "ids": ["m1"],
            "addLabelIds": ["UNREAD"],
        }


class TestArchive:
    def test_removes_inbox_label(self, mock_proxy):
        tools = _register_and_get_tools()
        tools["ARCHIVE_EMAIL"](
            request=ArchiveEmailInput(message_ids=["m1"]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert mock_proxy.call_args.kwargs["body"] == {
            "ids": ["m1"],
            "removeLabelIds": ["INBOX"],
        }


class TestStar:
    def test_star_adds_starred_label(self, mock_proxy):
        tools = _register_and_get_tools()
        result = tools["STAR_EMAIL"](
            request=StarEmailInput(message_ids=["m1"]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result == {"action": "starred"}
        assert mock_proxy.call_args.kwargs["body"]["addLabelIds"] == ["STARRED"]

    def test_unstar_removes_starred_label(self, mock_proxy):
        tools = _register_and_get_tools()
        result = tools["STAR_EMAIL"](
            request=StarEmailInput(message_ids=["m1"], unstar=True),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result == {"action": "unstarred"}
        assert mock_proxy.call_args.kwargs["body"]["removeLabelIds"] == ["STARRED"]


# ---------------------------------------------------------------------------
# GET_UNREAD_COUNT
# ---------------------------------------------------------------------------


class TestGetUnreadCount:
    def test_label_mode_returns_per_label_counts(self, mock_proxy):
        tools = _register_and_get_tools()
        mock_proxy.return_value = {
            "name": "INBOX",
            "messagesUnread": 7,
            "messagesTotal": 100,
        }
        result = tools["GET_UNREAD_COUNT"](
            request=GetUnreadCountInput(),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["unreadCount"] == 7
        assert result["totalCount"] == 100
        assert result["label_id"] == "INBOX"

    def test_query_mode_returns_total_and_unread_estimates(self, mock_proxy):
        tools = _register_and_get_tools()
        mock_proxy.side_effect = [
            {"resultSizeEstimate": 50},
            {"resultSizeEstimate": 12},
        ]
        result = tools["GET_UNREAD_COUNT"](
            request=GetUnreadCountInput(query="from:boss"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["totalCount"] == 50
        assert result["unreadCount"] == 12
        assert result["is_estimate"] is True


# ---------------------------------------------------------------------------
# GET_CONTACT_LIST
# ---------------------------------------------------------------------------


class TestGetContactList:
    def test_extracts_contacts_from_messages(self, mock_proxy):
        tools = _register_and_get_tools()
        mock_proxy.side_effect = [
            {"messages": [{"id": "m1"}]},
            {
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Boss <boss@example.com>"},
                    ]
                }
            },
        ]
        result = tools["GET_CONTACT_LIST"](
            request=GetContactListInput(query="boss"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["count"] == 1
        assert result["contacts"][0]["email"] == "boss@example.com"
        assert result["contacts"][0]["name"] == "Boss"


# ---------------------------------------------------------------------------
# CUSTOM_GATHER_CONTEXT
# ---------------------------------------------------------------------------


class TestGatherContext:
    def test_returns_profile_inbox_and_recent_ids(self, mock_proxy):
        tools = _register_and_get_tools()
        mock_proxy.side_effect = [
            {
                "emailAddress": "u@x.com",
                "messagesTotal": 1000,
                "threadsTotal": 500,
            },
            {"messagesUnread": 3, "messagesTotal": 100},
            {"messages": [{"id": "m1"}, {"id": "m2"}]},
        ]
        result = tools["CUSTOM_GATHER_CONTEXT"](
            request=GatherContextInput(),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["user"]["email"] == "u@x.com"
        assert result["inbox"]["unread_count"] == 3
        assert result["recent_message_ids"] == ["m1", "m2"]
