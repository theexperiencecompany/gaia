"""Unit tests for Gmail custom tools (post-Composio-proxy migration).

Each tool routes provider API calls through `proxy_request_sync` instead of
raw httpx. Tests patch that helper and assert on the request shape.
"""

import base64
import re
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.models.common_models import GatherContextInput
from app.models.composio_schemas.gmail import FetchInboxSummaryInput
from app.services.composio.custom_tools.gmail_tools import (
    ArchiveEmailInput,
    GetContactListInput,
    GetUnreadCountInput,
    MarkAsReadInput,
    MarkAsUnreadInput,
    StarEmailInput,
    _resolve_timeframe,
    _timeframe_clause,
    register_gmail_custom_tools,
)
from app.utils.timezone import Timezone

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
            "GMAIL_FETCH_INBOX_SUMMARY",
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


# ---------------------------------------------------------------------------
# FETCH_INBOX_SUMMARY — timeframe resolution
# ---------------------------------------------------------------------------


class TestResolveTimeframe:
    """Test the internal _resolve_timeframe + _timeframe_clause helpers."""

    def test_today_produces_after_before_same_day(self):
        tz = Timezone.parse("+05:30")
        clause = _timeframe_clause("today", tz)
        # Should look like "after:2024/06/18 before:2024/06/19"
        assert clause.startswith("after:")
        assert "before:" in clause
        # The two dates are exactly 1 day apart.
        after_date = clause.split("after:")[1].split(" ")[0]
        before_date = clause.split("before:")[1].strip()
        assert before_date > after_date

    def test_7d_default_max(self):
        combined, default_max = _resolve_timeframe("7d", None, Timezone.utc())
        assert default_max == 200
        assert combined.startswith("after:")

    def test_1m_default_max_500(self):
        combined, default_max = _resolve_timeframe("1m", None, Timezone.utc())
        assert default_max == 500
        assert combined.startswith("after:")

    def test_explicit_after_in_query_wins(self):
        combined, _ = _resolve_timeframe("today", "from:alice after:2024/01/01", Timezone.utc())
        assert "from:alice" in combined
        assert "after:2024/01/01" in combined
        # The timeframe's after:/before: is NOT added on top.
        assert combined.count("after:") == 1
        assert "before:" not in combined

    def test_query_only_no_timeframe(self):
        combined, _ = _resolve_timeframe(None, "is:unread", Timezone.utc())
        assert combined == "is:unread"

    def test_timeframe_only_no_query(self):
        combined, _ = _resolve_timeframe("today", None, Timezone.utc())
        assert combined.startswith("after:")
        assert "before:" in combined

    def test_timeframe_and_query_combined(self):
        combined, _ = _resolve_timeframe("today", "is:unread", Timezone.utc())
        assert combined.startswith("after:")
        assert combined.endswith("is:unread")


# ---------------------------------------------------------------------------
# FETCH_INBOX_SUMMARY — pagination, field shaping, offload
# ---------------------------------------------------------------------------


class TestFetchInboxSummary:
    """Tests for the GMAIL_FETCH_INBOX_SUMMARY custom tool."""

    @staticmethod
    def _make_message_response() -> dict[str, Any]:
        """Minimal Gmail API message shape for the loop to process."""
        return {
            "id": "x",
            "threadId": "t",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "a@b.com"},
                    {"name": "To", "value": "me@x.com"},
                    {"name": "Subject", "value": "Hi"},
                    {"name": "Date", "value": "Thu, 18 Jun 2026"},
                ],
                "body": {"data": ""},
            },
        }

    def test_pagination_loop_aggregates_until_token_null(self, mock_proxy):
        """Three pages of message IDs, no nextPageToken on the last → all 9 fetched."""
        tools = _register_and_get_tools()

        # 3 list responses (page1, page2, page3).
        list_responses = [
            {"messages": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}], "nextPageToken": "t1"},
            {"messages": [{"id": "m4"}, {"id": "m5"}, {"id": "m6"}], "nextPageToken": "t2"},
            {"messages": [{"id": "m7"}, {"id": "m8"}, {"id": "m9"}]},  # no token → done
        ]
        message_response = self._make_message_response()

        # Dispatch on the endpoint: list calls hit `.../messages`, message
        # calls hit `.../messages/{id}`. The two iterators are independent
        # so message fetches don't accidentally consume list responses.
        list_iter = iter(list_responses)
        message_iter = iter([message_response] * 9)

        def side_effect(*args, **kwargs):
            endpoint = kwargs.get("endpoint", "")
            # List call: exactly /users/me/messages (no id segment after).
            if re.match(r".+/users/me/messages/?$", endpoint):
                return next(list_iter)
            return next(message_iter)

        mock_proxy.side_effect = side_effect

        result = tools["FETCH_INBOX_SUMMARY"](
            request=FetchInboxSummaryInput(timeframe="today", per_page=3, body_processing="none"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert result["fetched_count"] == 9
        assert result["truncated"] is False
        assert len(result["messages"]) == 9

    def test_pagination_loop_respects_max_messages(self, mock_proxy):
        """Hit the cap before exhausting pages → truncated=True."""
        tools = _register_and_get_tools()

        list_responses = [
            {"messages": [{"id": f"m{i}"} for i in range(1, 4)], "nextPageToken": "t1"},
            {"messages": [{"id": f"m{i}"} for i in range(4, 7)], "nextPageToken": "t2"},
            {"messages": [{"id": f"m{i}"} for i in range(7, 10)]},
        ]
        message_response = self._make_message_response()

        list_iter = iter(list_responses)
        message_iter = iter([message_response] * 5)

        def side_effect(*args, **kwargs):
            endpoint = kwargs.get("endpoint", "")
            # List call: exactly /users/me/messages (no id segment after).
            if re.match(r".+/users/me/messages/?$", endpoint):
                return next(list_iter)
            return next(message_iter)

        mock_proxy.side_effect = side_effect

        result = tools["FETCH_INBOX_SUMMARY"](
            request=FetchInboxSummaryInput(
                timeframe="today",
                max_messages=5,
                per_page=3,
                body_processing="none",
            ),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert result["fetched_count"] == 5
        assert result["truncated"] is True

    def test_pagination_loop_stops_on_gmail_error(self, mock_proxy):
        """Mid-loop error → return partial + error, no crash."""
        tools = _register_and_get_tools()

        list_responses = [
            {
                "messages": [{"id": "m1"}, {"id": "m2"}],
                "nextPageToken": "t1",  # so the loop continues and hits the error on page 2
            },
        ]
        message_response = self._make_message_response()
        # State machine: list page 1 OK → list page 2 RAISE. Two messages
        # in between (m1, m2). Using a counter + raise so the mock
        # actually propagates the exception (returning it as a value would
        # not trigger the tool's error path).
        list_call_count = [0]

        def side_effect(*args, **kwargs):
            endpoint = kwargs.get("endpoint", "")
            # List call: exactly /users/me/messages (no id segment after).
            if re.match(r".+/users/me/messages/?$", endpoint):
                list_call_count[0] += 1
                if list_call_count[0] == 1:
                    return list_responses[0]
                raise RuntimeError("Gmail 503")
            return message_response

        mock_proxy.side_effect = side_effect

        result = tools["FETCH_INBOX_SUMMARY"](
            request=FetchInboxSummaryInput(
                timeframe="today",
                per_page=2,
                body_processing="none",
            ),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert result["partial"] is True
        assert result["truncated"] is True
        assert result["fetched_count"] == 2
        assert "Gmail 503" in result["error"]

    def test_default_fields_excludes_body(self, mock_proxy):
        """Default fields list must NOT contain body, cc, or bcc."""
        defaults = FetchInboxSummaryInput.model_fields["fields"].default_factory()
        assert "body" not in defaults
        assert "cc" not in defaults
        assert "bcc" not in defaults
        assert "id" in defaults
        assert "subject" in defaults
        assert "snippet" in defaults

    def test_aggregate_inline_when_small(self, mock_proxy):
        """Small result → no offload, full payload returned."""
        tools = _register_and_get_tools()

        list_resp = {"messages": [{"id": "m1"}]}
        msg_resp = {
            "id": "m1",
            "threadId": "t1",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [{"name": "From", "value": "a@b.com"}],
                "body": {"data": ""},
            },
        }
        list_iter = iter([list_resp])
        message_iter = iter([msg_resp])

        def side_effect(*args, **kwargs):
            endpoint = kwargs.get("endpoint", "")
            # List call: exactly /users/me/messages (no id segment after).
            if re.match(r".+/users/me/messages/?$", endpoint):
                return next(list_iter)
            return next(message_iter)

        mock_proxy.side_effect = side_effect

        result = tools["FETCH_INBOX_SUMMARY"](
            request=FetchInboxSummaryInput(
                timeframe="today",
                per_page=10,
                body_processing="none",
            ),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert "offloaded_to" not in result
        assert result["fetched_count"] == 1
        assert len(result["messages"]) == 1

    def test_offload_triggered_when_large(self, mock_proxy, tmp_path):
        """Response > 60KB chars → writes JSONL file and returns digest."""
        tools = _register_and_get_tools()

        # Build a synthetic list response with 5 messages; each message body
        # is large enough that the aggregate exceeds the 60KB inline limit.
        big_body = "x" * 20_000  # 20KB per message; 5 messages = 100KB+
        list_response = {"messages": [{"id": f"m{i}"} for i in range(5)]}
        message_response = {
            "id": "m",
            "threadId": "t",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [{"name": "From", "value": "a@b.com"}],
                "body": {"data": base64.urlsafe_b64encode(big_body.encode()).decode()},
            },
        }
        list_iter = iter([list_response])
        message_iter = iter([message_response] * 5)

        def side_effect(*args, **kwargs):
            endpoint = kwargs.get("endpoint", "")
            # List call: exactly /users/me/messages (no id segment after).
            if re.match(r".+/users/me/messages/?$", endpoint):
                return next(list_iter)
            return next(message_iter)

        mock_proxy.side_effect = side_effect

        with (
            patch(
                "app.services.composio.custom_tools.gmail_tools._write_session_file_sync"
            ) as write_mock,
            patch(
                "app.services.composio.custom_tools.gmail_tools.get_config",
                return_value={"configurable": {"vfs_session_id": "test"}},
            ),
        ):
            write_mock.return_value = (
                tmp_path / "fake.jsonl",
                "/workspace/sessions/test/fake.jsonl",
            )
            # Request "body" in fields so the aggregate is large enough to
            # trigger offload (default field set excludes body).
            fields_with_body = list(
                FetchInboxSummaryInput.model_fields["fields"].default_factory()
            ) + ["body"]
            result = tools["FETCH_INBOX_SUMMARY"](
                request=FetchInboxSummaryInput(
                    timeframe="today",
                    per_page=10,
                    fields=fields_with_body,
                    body_processing="raw",
                ),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        assert "offloaded_to" in result
        assert "inline_preview" in result
        assert len(result["inline_preview"]) <= 10
        assert "hint" in result
        assert "jq" in result["hint"]

    def test_offload_skipped_when_no_conversation_id(self, mock_proxy):
        """If the run config has no vfs_session_id/thread_id, return inline."""
        tools = _register_and_get_tools()

        list_resp = {"messages": [{"id": "m1"}]}
        msg_resp = {
            "id": "m1",
            "threadId": "t1",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [{"name": "From", "value": "a@b.com"}],
                "body": {"data": ""},
            },
        }
        list_iter = iter([list_resp])
        message_iter = iter([msg_resp])

        def side_effect(*args, **kwargs):
            endpoint = kwargs.get("endpoint", "")
            # List call: exactly /users/me/messages (no id segment after).
            if re.match(r".+/users/me/messages/?$", endpoint):
                return next(list_iter)
            return next(message_iter)

        mock_proxy.side_effect = side_effect

        with patch(
            "app.services.composio.custom_tools.gmail_tools.get_config",
            return_value={"configurable": {}},  # no vfs_session_id / thread_id
        ):
            result = tools["FETCH_INBOX_SUMMARY"](
                request=FetchInboxSummaryInput(
                    timeframe="today",
                    per_page=10,
                    body_processing="none",
                ),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        # Inline returned (not offloaded, no digest).
        assert "offloaded_to" not in result
        assert result["fetched_count"] == 1
