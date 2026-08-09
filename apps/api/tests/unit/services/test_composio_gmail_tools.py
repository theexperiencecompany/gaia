"""Unit tests for Gmail custom tools (post-Composio-proxy migration).

Each tool routes provider API calls through `proxy_request_sync` instead of
raw httpx. Tests patch that helper and assert on the request shape.
"""

import base64
import datetime
import json
import re
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch
import uuid

import pytest

from app.constants.log_tags import LogTag
from app.constants.offload import OFFLOAD_RESULT_KEY
from app.models.common_models import GatherContextInput
from app.models.composio_schemas.gmail import (
    FetchMessagesInput,
    FetchThreadInput,
    GmailLabelDetail,
    GmailMessagesListResponse,
)
from app.services.composio.custom_tools import gmail_tools
from app.services.composio.custom_tools.gmail_constants import (
    GMAIL_API_BASE,
    GMAIL_BATCH_MODIFY_CAP,
    GMAIL_FORMAT_FULL,
    GMAIL_FORMAT_METADATA,
    GMAIL_TOOLKIT,
    INLINE_LIMIT_CHARS,
    MAX_ABSOLUTE_MESSAGES,
    OFFLOAD_MIN_MESSAGES,
    OFFLOAD_PREVIEW_SIZE,
    TIMEFRAME_DEFAULT_MAX,
)
from app.services.composio.custom_tools.gmail_tools import (
    ArchiveEmailInput,
    GetContactListInput,
    GetUnreadCountInput,
    MarkAsReadInput,
    MarkAsUnreadInput,
    StarEmailInput,
    _aggregate_pages,
    _aggregate_threads,
    _batch_modify,
    _build_read_plan,
    _conversation_id,
    _count_inline_fit,
    _count_messages,
    _current_config,
    _date_window_clause,
    _effective_max,
    _emit_email_card,
    _fetch_list_page,
    _fetch_message_view,
    _fetch_messages_for_contacts,
    _fetch_one_thread,
    _format_inline_result,
    _format_offload_result,
    _format_partial_result,
    _gmail_date,
    _gmail_label,
    _gmail_proxy,
    _gmail_user_profile,
    _human_size,
    _label_stats,
    _no_session_inline_fallback,
    _offload_path,
    _PartialResult,
    _recent_inbox_ids,
    _resolve_timeframe,
    _summarize,
    _summarize_threads,
    _thread_needs_full,
    _timeframe_clause,
    _unread_count_label_mode,
    _unread_count_query_mode,
    _user_id,
    register_gmail_custom_tools,
)
from app.utils.errors import AppError
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
            "GMAIL_FETCH_MESSAGES",
            "GMAIL_FETCH_THREAD",
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
        assert kwargs["user_id"] == "user_test_123"
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
        assert mock_proxy.call_args.kwargs["user_id"] == "user_test_123"
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
        assert mock_proxy.call_args.kwargs["user_id"] == "user_test_123"
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
        assert result == {"action": "starred", "modified_count": 1, "failed_count": 0}
        assert mock_proxy.call_args.kwargs["user_id"] == "user_test_123"
        assert mock_proxy.call_args.kwargs["body"]["addLabelIds"] == ["STARRED"]

    def test_unstar_removes_starred_label(self, mock_proxy):
        tools = _register_and_get_tools()
        result = tools["STAR_EMAIL"](
            request=StarEmailInput(message_ids=["m1"], unstar=True),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result == {"action": "unstarred", "modified_count": 1, "failed_count": 0}
        assert mock_proxy.call_args.kwargs["user_id"] == "user_test_123"
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
        assert mock_proxy.call_args.kwargs["user_id"] == "user_test_123"
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
        assert all(c.kwargs["user_id"] == "user_test_123" for c in mock_proxy.call_args_list)
        assert all(
            c.kwargs["query"]["includeSpamTrash"] == "false"
            for c in mock_proxy.call_args_list
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
        assert mock_proxy.call_args_list[0].kwargs == {
            "user_id": "user_test_123",
            "toolkit": GMAIL_TOOLKIT,
            "endpoint": f"{GMAIL_API_BASE}/users/me/messages",
            "method": "GET",
            "body": None,
            "query": {"q": "boss", "maxResults": 30},
        }
        assert mock_proxy.call_args_list[1].kwargs["user_id"] == "user_test_123"


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
# FETCH_MESSAGES — timeframe resolution
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
# FETCH_MESSAGES — pagination, field shaping, offload
# ---------------------------------------------------------------------------


class TestFetchMessages:
    """Tests for the GMAIL_FETCH_MESSAGES custom tool."""

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

        result = tools["FETCH_MESSAGES"](
            request=FetchMessagesInput(timeframe="today", per_page=3, body_processing="none"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert result["fetched_count"] == 9
        assert result["truncated"] is False
        assert len(result["messages"]) == 9
        assert all(c.kwargs["user_id"] == "user_test_123" for c in mock_proxy.call_args_list)

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

        result = tools["FETCH_MESSAGES"](
            request=FetchMessagesInput(
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

        result = tools["FETCH_MESSAGES"](
            request=FetchMessagesInput(
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
        defaults = FetchMessagesInput.model_fields["fields"].default_factory()
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

        result = tools["FETCH_MESSAGES"](
            request=FetchMessagesInput(
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
        """Response above INLINE_LIMIT_CHARS → writes JSONL file and returns digest."""
        tools = _register_and_get_tools()

        # Build a synthetic list response with 5 messages; each message body
        # is large enough that the aggregate exceeds INLINE_LIMIT_CHARS (120K).
        big_body = "x" * 30_000  # 30KB per message; 5 messages = 150KB+
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
                "app.services.composio.custom_tools.gmail_tools.write_session_file_sync"
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
            fields_with_body = list(FetchMessagesInput.model_fields["fields"].default_factory()) + [
                "body"
            ]
            result = tools["FETCH_MESSAGES"](
                request=FetchMessagesInput(
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
        assert "query_json" in result["hint"]
        assert result["read_plan"]["recommended_subagents"] >= 2

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
            result = tools["FETCH_MESSAGES"](
                request=FetchMessagesInput(
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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class TestUserId:
    def test_returns_user_id(self):
        assert _user_id({"user_id": "u1"}) == "u1"

    def test_missing_user_id_raises(self):
        with pytest.raises(ValueError) as exc_info:
            _user_id({})
        assert str(exc_info.value) == "Missing user_id in auth_credentials"

    def test_empty_user_id_raises(self):
        with pytest.raises(ValueError):
            _user_id({"user_id": ""})

    def test_none_user_id_raises(self):
        with pytest.raises(ValueError):
            _user_id({"user_id": None})


class TestGmailProxy:
    def test_forwards_all_arguments(self, mock_proxy):
        mock_proxy.return_value = {"ok": True}
        result = _gmail_proxy(
            "u1", endpoint="/ep", method="POST", body={"a": 1}, query={"q": "x"}
        )
        mock_proxy.assert_called_once_with(
            user_id="u1",
            toolkit=GMAIL_TOOLKIT,
            endpoint="/ep",
            method="POST",
            body={"a": 1},
            query={"q": "x"},
        )
        assert result == {"ok": True}

    def test_defaults_body_and_query_to_none(self, mock_proxy):
        _gmail_proxy("u1", endpoint="/ep", method="GET")
        assert mock_proxy.call_args.kwargs["body"] is None
        assert mock_proxy.call_args.kwargs["query"] is None


class TestCurrentConfig:
    def test_returns_get_config_value(self):
        with patch.object(gmail_tools, "get_config", return_value={"configurable": {}}):
            assert _current_config() == {"configurable": {}}

    def test_empty_config_outside_run(self):
        with patch.object(gmail_tools, "get_config", side_effect=RuntimeError):
            assert _current_config() == {}


class TestConversationId:
    def test_vfs_session_id_wins(self):
        config = {"configurable": {"vfs_session_id": "s1", "thread_id": "t1"}}
        assert _conversation_id(config) == "s1"

    def test_thread_id_fallback(self):
        assert _conversation_id({"configurable": {"thread_id": "t1"}}) == "t1"

    def test_empty_vfs_falls_back_to_thread_id(self):
        config = {"configurable": {"vfs_session_id": "", "thread_id": "t1"}}
        assert _conversation_id(config) == "t1"

    def test_no_session_keys(self):
        assert _conversation_id({"configurable": {}}) is None

    def test_missing_configurable(self):
        assert _conversation_id({}) is None


# ---------------------------------------------------------------------------
# Timeframe resolution — exact clause strings
# ---------------------------------------------------------------------------


class TestTimeframeClauseExact:
    """Exact after:/before: strings with a frozen clock.

    2024-06-19 is a Wednesday, so the ISO week's Monday is 2024-06-17.
    """

    FIXED_NOW = datetime.datetime(2024, 6, 19, 12, 0, 0)

    @pytest.fixture(autouse=True)
    def _freeze_clock(self):
        with patch.object(Timezone, "now", return_value=self.FIXED_NOW):
            yield

    def test_today(self):
        assert _timeframe_clause("today", Timezone.utc()) == (
            "after:2024/06/19 before:2024/06/20"
        )

    def test_yesterday(self):
        assert _timeframe_clause("yesterday", Timezone.utc()) == (
            "after:2024/06/18 before:2024/06/19"
        )

    def test_tomorrow(self):
        assert _timeframe_clause("tomorrow", Timezone.utc()) == (
            "after:2024/06/20 before:2024/06/21"
        )

    def test_this_week(self):
        assert _timeframe_clause("this_week", Timezone.utc()) == (
            "after:2024/06/17 before:2024/06/24"
        )

    def test_last_week(self):
        assert _timeframe_clause("last_week", Timezone.utc()) == (
            "after:2024/06/10 before:2024/06/17"
        )

    def test_next_week(self):
        assert _timeframe_clause("next_week", Timezone.utc()) == (
            "after:2024/06/24 before:2024/07/01"
        )

    def test_relative_days_inclusive_of_today(self):
        assert _timeframe_clause("1d", Timezone.utc()) == (
            "after:2024/06/19 before:2024/06/20"
        )
        assert _timeframe_clause("3d", Timezone.utc()) == (
            "after:2024/06/17 before:2024/06/20"
        )
        assert _timeframe_clause("7d", Timezone.utc()) == (
            "after:2024/06/13 before:2024/06/20"
        )

    def test_relative_weeks(self):
        assert _timeframe_clause("1w", Timezone.utc()) == (
            "after:2024/06/13 before:2024/06/20"
        )
        assert _timeframe_clause("2w", Timezone.utc()) == (
            "after:2024/06/06 before:2024/06/20"
        )

    def test_relative_months(self):
        assert _timeframe_clause("1m", Timezone.utc()) == (
            "after:2024/05/21 before:2024/06/20"
        )

    def test_relative_years(self):
        assert _timeframe_clause("1y", Timezone.utc()) == (
            "after:2023/06/21 before:2024/06/20"
        )

    def test_unrecognized_timeframe_returns_empty(self):
        assert _timeframe_clause("fortnight", Timezone.utc()) == ""

    def test_empty_timeframe_returns_empty(self):
        assert _timeframe_clause("", Timezone.utc()) == ""

    def test_resolve_timeframe_none_query_exact(self):
        assert _resolve_timeframe("today", None, Timezone.utc()) == (
            "after:2024/06/19 before:2024/06/20",
            100,
        )

    def test_resolve_timeframe_combined_exact(self):
        combined, _ = _resolve_timeframe("today", "is:unread", Timezone.utc())
        assert combined == "after:2024/06/19 before:2024/06/20 is:unread"


class TestDateWindowClause:
    def test_days_forward(self):
        assert _date_window_clause(datetime.date(2024, 6, 18), days=1) == (
            "after:2024/06/18 before:2024/06/19"
        )

    def test_days_span(self):
        assert _date_window_clause(datetime.date(2024, 6, 18), days=7) == (
            "after:2024/06/18 before:2024/06/25"
        )

    def test_end_date_makes_end_exclusive(self):
        assert _date_window_clause(
            datetime.date(2024, 6, 13), end_date=datetime.date(2024, 6, 19)
        ) == "after:2024/06/13 before:2024/06/20"

    def test_neither_days_nor_end_date_raises(self):
        with pytest.raises(ValueError) as exc_info:
            _date_window_clause(datetime.date(2024, 6, 18))
        assert str(exc_info.value) == "Provide either days= or end_date="


class TestGmailDate:
    def test_slash_format(self):
        assert _gmail_date(datetime.date(2024, 6, 18)) == "2024/06/18"

    def test_single_digit_components_padded(self):
        assert _gmail_date(datetime.date(2024, 1, 5)) == "2024/01/05"

    def test_year_boundary(self):
        assert _gmail_date(datetime.date(2023, 12, 31)) == "2023/12/31"
        assert _gmail_date(datetime.date(2024, 1, 1)) == "2024/01/01"


class TestResolveTimeframeExact:
    def test_default_max_per_timeframe(self):
        assert _resolve_timeframe("today", None, Timezone.utc())[1] == 100
        assert _resolve_timeframe("yesterday", None, Timezone.utc())[1] == 100
        assert _resolve_timeframe("tomorrow", None, Timezone.utc())[1] == 100
        assert _resolve_timeframe("this_week", None, Timezone.utc())[1] == 200
        assert _resolve_timeframe("last_week", None, Timezone.utc())[1] == 200
        assert _resolve_timeframe("next_week", None, Timezone.utc())[1] == 200
        assert _resolve_timeframe("1d", None, Timezone.utc())[1] == 100
        assert _resolve_timeframe("3d", None, Timezone.utc())[1] == 100
        assert _resolve_timeframe("5d", None, Timezone.utc())[1] == 200
        assert _resolve_timeframe("7d", None, Timezone.utc())[1] == 200
        assert _resolve_timeframe("1w", None, Timezone.utc())[1] == 200
        assert _resolve_timeframe("2w", None, Timezone.utc())[1] == 400
        assert _resolve_timeframe("1m", None, Timezone.utc())[1] == 500
        assert _resolve_timeframe("3m", None, Timezone.utc())[1] == 500
        assert _resolve_timeframe("6m", None, Timezone.utc())[1] == 500
        assert _resolve_timeframe("1y", None, Timezone.utc())[1] == 500

    def test_no_timeframe_no_query(self):
        assert _resolve_timeframe(None, None, Timezone.utc()) == ("", 100)

    def test_no_timeframe_defaults_match_constants(self):
        combined, default_max = _resolve_timeframe(None, None, Timezone.utc())
        assert default_max == TIMEFRAME_DEFAULT_MAX.get("", 100)
        assert combined == ""

    def test_explicit_after_returns_query_unchanged(self):
        combined, default_max = _resolve_timeframe(
            "today", "from:alice after:2024/01/01", Timezone.utc()
        )
        assert combined == "from:alice after:2024/01/01"
        assert default_max == 100

    def test_explicit_before_returns_query_unchanged(self):
        combined, _ = _resolve_timeframe(
            "this_week", "is:unread before:2024/01/01", Timezone.utc()
        )
        assert combined == "is:unread before:2024/01/01"

    def test_explicit_after_without_timeframe(self):
        combined, _ = _resolve_timeframe(None, "after:2024/01/01", Timezone.utc())
        assert combined == "after:2024/01/01"

    def test_explicit_after_logs_warning(self):
        with patch.object(gmail_tools.log, "warning") as warn:
            _resolve_timeframe("today", "after:2024/01/01", Timezone.utc())
        warn.assert_called_once_with(
            "GMAIL_FETCH_MESSAGES: query already has after:/before:, ignoring timeframe",
            timeframe="today",
        )

    def test_empty_query_with_timeframe(self):
        combined, default_max = _resolve_timeframe("today", "", Timezone.utc())
        assert default_max == 100
        assert combined.startswith("after:")
        assert "before:" in combined

    def test_empty_query_string_is_not_explicit(self):
        # An empty-string query must not count as "explicit after:/before:".
        combined, _ = _resolve_timeframe("today", "", Timezone.utc())
        assert combined.startswith("after:")


class TestEffectiveMax:
    def test_default_used_when_no_override(self):
        assert _effective_max(_request(max_messages=None), 100) == 100

    def test_override_wins_over_default(self):
        assert _effective_max(_request(max_messages=250), 500) == 250

    def test_capped_at_absolute_maximum(self):
        assert _effective_max(_request(max_messages=5000), 100) == MAX_ABSOLUTE_MESSAGES

    def test_override_at_ceiling(self):
        assert _effective_max(_request(max_messages=1000), 100) == 1000

    def test_small_override_respected(self):
        assert _effective_max(_request(max_messages=1), 100) == 1


def _request(**kwargs) -> FetchMessagesInput:
    return FetchMessagesInput(**kwargs)


# ---------------------------------------------------------------------------
# FETCH_MESSAGES internals — list page, message view, aggregation
# ---------------------------------------------------------------------------


class TestFetchListPage:
    def test_request_shape_without_token(self, mock_proxy):
        data = _fetch_list_page("u1", query="is:unread", per_page=25, page_token=None)
        assert mock_proxy.call_args.kwargs == {
            "user_id": "u1",
            "toolkit": GMAIL_TOOLKIT,
            "endpoint": f"{GMAIL_API_BASE}/users/me/messages",
            "method": "GET",
            "body": None,
            "query": {"q": "is:unread", "maxResults": 25},
        }
        assert data.messages == []
        assert data.next_page_token is None
        assert data.result_size_estimate is None

    def test_page_token_included_when_present(self, mock_proxy):
        mock_proxy.return_value = {
            "messages": [{"id": "m1"}, {"id": "m2"}],
            "nextPageToken": "t2",
            "resultSizeEstimate": 42,
        }
        data = _fetch_list_page("u1", query="q", per_page=10, page_token="t1")
        assert mock_proxy.call_args.kwargs["query"] == {
            "q": "q",
            "maxResults": 10,
            "pageToken": "t1",
        }
        assert [ref.id for ref in data.messages] == ["m1", "m2"]
        assert data.next_page_token == "t2"
        assert data.result_size_estimate == 42

    def test_none_response_validates_to_empty(self, mock_proxy):
        mock_proxy.return_value = None
        data = _fetch_list_page("u1", query="q", per_page=10, page_token=None)
        assert data.messages == []
        assert data.result_size_estimate is None


class TestFetchMessageView:
    def test_metadata_when_fields_exclude_body(self):
        with (
            patch.object(gmail_tools, "_gmail_proxy", return_value={"id": "m1"}) as proxy,
            patch.object(
                gmail_tools, "build_message_view", return_value={"view": 1}
            ) as build,
        ):
            result = _fetch_message_view(
                "u1", "m1", fields=["id"], body_processing="normalize"
            )
        proxy.assert_called_once_with(
            "u1",
            endpoint=f"{GMAIL_API_BASE}/users/me/messages/m1",
            method="GET",
            query={"format": GMAIL_FORMAT_METADATA},
        )
        build.assert_called_once_with({"id": "m1"}, body_processing="none")
        assert result == {"view": 1}

    def test_full_when_fields_are_all(self):
        with (
            patch.object(gmail_tools, "_gmail_proxy", return_value={"id": "m1"}) as proxy,
            patch.object(gmail_tools, "build_message_view") as build,
        ):
            _fetch_message_view("u1", "m1", fields=None, body_processing="normalize")
        assert proxy.call_args.kwargs["query"] == {"format": GMAIL_FORMAT_FULL}
        assert build.call_args.kwargs["body_processing"] == "normalize"

    def test_body_in_fields_requests_full(self):
        with (
            patch.object(gmail_tools, "_gmail_proxy", return_value={}) as proxy,
            patch.object(gmail_tools, "build_message_view") as build,
        ):
            _fetch_message_view("u1", "m1", fields=["body"], body_processing="normalize")
        assert proxy.call_args.kwargs["query"] == {"format": GMAIL_FORMAT_FULL}
        assert build.call_args.kwargs["body_processing"] == "normalize"

    def test_none_processing_wins_over_body_field(self):
        with (
            patch.object(gmail_tools, "_gmail_proxy", return_value={}) as proxy,
            patch.object(gmail_tools, "build_message_view") as build,
        ):
            _fetch_message_view("u1", "m1", fields=["body"], body_processing="none")
        assert proxy.call_args.kwargs["query"] == {"format": GMAIL_FORMAT_METADATA}
        assert build.call_args.kwargs["body_processing"] == "none"

    def test_attachments_requests_full_even_without_body(self):
        with (
            patch.object(gmail_tools, "_gmail_proxy", return_value={}) as proxy,
            patch.object(gmail_tools, "build_message_view") as build,
        ):
            _fetch_message_view(
                "u1", "m1", fields=["attachments"], body_processing="none"
            )
        assert proxy.call_args.kwargs["query"] == {"format": GMAIL_FORMAT_FULL}
        assert build.call_args.kwargs["body_processing"] == "none"

    def test_force_body_overrides_field_selection(self):
        with (
            patch.object(gmail_tools, "_gmail_proxy", return_value={}) as proxy,
            patch.object(gmail_tools, "build_message_view") as build,
        ):
            _fetch_message_view(
                "u1", "m1", fields=["id"], body_processing="raw", force_body=True
            )
        assert proxy.call_args.kwargs["query"] == {"format": GMAIL_FORMAT_FULL}
        assert build.call_args.kwargs["body_processing"] == "raw"

    def test_force_body_still_honors_none_processing(self):
        # ``force_body`` wins the format OR (full payload fetched), but the
        # explicit no-body request still wins the view: ``build_message_view``
        # receives ``body_processing="none"`` so the output carries no body.
        with (
            patch.object(gmail_tools, "_gmail_proxy", return_value={}) as proxy,
            patch.object(gmail_tools, "build_message_view") as build,
        ):
            _fetch_message_view(
                "u1", "m1", fields=["id"], body_processing="none", force_body=True
            )
        assert proxy.call_args.kwargs["query"] == {"format": GMAIL_FORMAT_FULL}
        assert build.call_args.kwargs["body_processing"] == "none"

    def test_non_dict_response_returns_none(self):
        with patch.object(
            gmail_tools, "_gmail_proxy", return_value=["not", "a", "dict"]
        ):
            with patch.object(gmail_tools, "build_message_view") as build:
                result = _fetch_message_view(
                    "u1", "m1", fields=["id"], body_processing="none"
                )
        assert result is None
        build.assert_not_called()


class TestAggregatePages:
    @staticmethod
    def _page(**fields) -> GmailMessagesListResponse:
        return GmailMessagesListResponse.model_validate(fields)

    def _run(
        self,
        mock,
        *,
        max_messages=None,
        body_processing="none",
        effective_max=None,
        **req_kwargs,
    ):
        del mock
        kwargs: dict[str, Any] = {
            "timeframe": "today",
            "per_page": 3,
            "body_processing": body_processing,
            **req_kwargs,
        }
        if max_messages is not None:
            kwargs["max_messages"] = max_messages
        request = _request(**kwargs)
        result = _aggregate_pages(
            "u1",
            request,
            combined_query="is:unread",
            effective_max=effective_max or max_messages or 10,
        )
        return request, result

    def test_empty_first_page(self):
        with (
            patch.object(
                gmail_tools, "_fetch_list_page", return_value=self._page()
            ) as list_page,
            patch.object(gmail_tools, "_fetch_message_view") as view,
        ):
            result = _aggregate_pages("u1", _request(), combined_query="", effective_max=10)
        assert result == ([], False)
        list_page.assert_called_once_with("u1", query="", per_page=100, page_token=None)
        view.assert_not_called()

    def test_single_page(self):
        with (
            patch.object(
                gmail_tools,
                "_fetch_list_page",
                side_effect=[
                    self._page(messages=[{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]),
                ],
            ) as list_page,
            patch.object(
                gmail_tools,
                "_fetch_message_view",
                side_effect=[
                    {"id": "m1", "n": 1},
                    {"id": "m2", "n": 2},
                    {"id": "m3", "n": 3},
                ],
            ) as view,
        ):
            request, result = self._run(None)
        assert result == (
            [{"id": "m1", "n": 1}, {"id": "m2", "n": 2}, {"id": "m3", "n": 3}],
            False,
        )
        assert [c.kwargs["page_token"] for c in list_page.call_args_list] == [None]
        assert [c.args[1] for c in view.call_args_list] == ["m1", "m2", "m3"]
        assert [c.args[0] for c in view.call_args_list] == ["u1"] * 3
        assert [c.kwargs["fields"] for c in view.call_args_list] == [request.fields] * 3
        assert [c.kwargs["body_processing"] for c in view.call_args_list] == ["none"] * 3

    def test_multiple_pages_in_order(self):
        with (
            patch.object(
                gmail_tools,
                "_fetch_list_page",
                side_effect=[
                    self._page(messages=[{"id": "m1"}], nextPageToken="t1"),
                    self._page(messages=[{"id": "m2"}, {"id": "m3"}]),
                ],
            ) as list_page,
            patch.object(
                gmail_tools,
                "_fetch_message_view",
                side_effect=[{"id": f"m{i}"} for i in (1, 2, 3)],
            ),
        ):
            _, result = self._run(None)
        assert result == ([{"id": "m1"}, {"id": "m2"}, {"id": "m3"}], False)
        assert [c.kwargs["page_token"] for c in list_page.call_args_list] == [None, "t1"]

    def test_page_trimmed_at_cap(self):
        with (
            patch.object(
                gmail_tools,
                "_fetch_list_page",
                side_effect=[self._page(messages=[{"id": f"m{i}"} for i in range(4)])],
            ) as list_page,
            patch.object(
                gmail_tools,
                "_fetch_message_view",
                side_effect=[{"id": f"m{i}"} for i in range(1, 3)],
            ) as view,
        ):
            _, result = self._run(None, max_messages=2)
        assert result == ([{"id": "m1"}, {"id": "m2"}], True)
        assert view.call_count == 2
        list_page.assert_called_once()

    def test_cap_reached_at_page_end_stops_paging(self):
        with (
            patch.object(
                gmail_tools,
                "_fetch_list_page",
                side_effect=[
                    self._page(
                        messages=[{"id": "m1"}, {"id": "m2"}, {"id": "m3"}],
                        nextPageToken="t1",
                    )
                ],
            ) as list_page,
            patch.object(gmail_tools, "_fetch_message_view", side_effect=[{"id": "m"}] * 3),
        ):
            _, result = self._run(None, max_messages=3)
        assert result == ([{"id": "m"}, {"id": "m"}, {"id": "m"}], True)
        list_page.assert_called_once()

    def test_empty_next_page_token_stops(self):
        with (
            patch.object(
                gmail_tools,
                "_fetch_list_page",
                side_effect=[
                    self._page(messages=[{"id": "m1"}], nextPageToken=""),
                ],
            ) as list_page,
            patch.object(gmail_tools, "_fetch_message_view", return_value={"id": "m1"}),
        ):
            _, result = self._run(None)
        assert result == ([{"id": "m1"}], False)
        list_page.assert_called_once()

    def test_force_body_on_big_estimate(self):
        with (
            patch.object(
                gmail_tools,
                "_fetch_list_page",
                return_value=self._page(messages=[{"id": "m1"}], resultSizeEstimate=100),
            ),
            patch.object(gmail_tools, "_fetch_message_view") as view,
        ):
            self._run(None, body_processing="raw", effective_max=100)
        assert view.call_args.kwargs["force_body"] is True

    def test_no_force_body_on_small_estimate(self):
        with (
            patch.object(
                gmail_tools,
                "_fetch_list_page",
                return_value=self._page(messages=[{"id": "m1"}], resultSizeEstimate=10),
            ),
            patch.object(gmail_tools, "_fetch_message_view") as view,
        ):
            self._run(None, body_processing="raw", effective_max=100)
        assert view.call_args.kwargs["force_body"] is False

    def test_no_force_body_when_none_processing(self):
        with (
            patch.object(
                gmail_tools,
                "_fetch_list_page",
                return_value=self._page(messages=[{"id": "m1"}], resultSizeEstimate=100),
            ),
            patch.object(gmail_tools, "_fetch_message_view") as view,
        ):
            self._run(None, body_processing="none", effective_max=100)
        assert view.call_args.kwargs["force_body"] is False

    def test_no_force_body_at_exact_offload_min(self):
        with (
            patch.object(
                gmail_tools,
                "_fetch_list_page",
                return_value=self._page(
                    messages=[{"id": "m1"}], resultSizeEstimate=OFFLOAD_MIN_MESSAGES
                ),
            ),
            patch.object(gmail_tools, "_fetch_message_view") as view,
        ):
            self._run(None, body_processing="raw", effective_max=100)
        assert view.call_args.kwargs["force_body"] is False

    def test_first_page_estimate_wins(self):
        with (
            patch.object(
                gmail_tools,
                "_fetch_list_page",
                side_effect=[
                    self._page(
                        messages=[{"id": "m1"}],
                        resultSizeEstimate=100,
                        nextPageToken="t1",
                    ),
                    self._page(messages=[{"id": "m2"}], resultSizeEstimate=5),
                ],
            ),
            patch.object(gmail_tools, "_fetch_message_view") as view,
        ):
            self._run(None, body_processing="raw", effective_max=100)
        assert all(c.kwargs["force_body"] is True for c in view.call_args_list)

    def test_cap_crossing_pages_fetches_exact_messages(self):
        with (
            patch.object(
                gmail_tools,
                "_fetch_list_page",
                side_effect=[
                    self._page(
                        messages=[{"id": "m1"}, {"id": "m2"}, {"id": "m3"}],
                        nextPageToken="t1",
                    ),
                    self._page(messages=[{"id": "m4"}, {"id": "m5"}]),
                ],
            ),
            patch.object(
                gmail_tools,
                "_fetch_message_view",
                side_effect=[{"id": f"m{i}"} for i in range(1, 6)],
            ),
        ):
            _, result = self._run(None, max_messages=4)
        assert result == ([{"id": "m1"}, {"id": "m2"}, {"id": "m3"}, {"id": "m4"}], True)

    def test_error_before_any_message_propagates(self):
        with (
            patch.object(
                gmail_tools, "_fetch_list_page", side_effect=RuntimeError("Gmail 503")
            ),
            patch.object(gmail_tools, "_fetch_message_view") as view,
        ):
            with pytest.raises(RuntimeError, match="Gmail 503"):
                self._run(None)
        view.assert_not_called()

    def test_error_mid_loop_raises_partial(self):
        with (
            patch.object(
                gmail_tools,
                "_fetch_list_page",
                side_effect=[
                    self._page(
                        messages=[{"id": "m1"}, {"id": "m2"}], nextPageToken="t1"
                    ),
                    RuntimeError("Gmail 503"),
                ],
            ),
            patch.object(
                gmail_tools,
                "_fetch_message_view",
                side_effect=[{"id": "m1"}, {"id": "m2"}],
            ),
            patch.object(gmail_tools.log, "warning") as warn,
        ):
            with pytest.raises(_PartialResult) as exc_info:
                self._run(None)
        assert exc_info.value.reason == "Gmail 503"
        assert exc_info.value.partial_messages == [{"id": "m1"}, {"id": "m2"}]
        warn.assert_called_once_with(
            "GMAIL_FETCH_MESSAGES: pagination aborted mid-loop",
            error="Gmail 503",
            error_type="RuntimeError",
            user_id="u1",
        )

    def test_none_views_skipped(self):
        with (
            patch.object(
                gmail_tools,
                "_fetch_list_page",
                return_value=self._page(
                    messages=[{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]
                ),
            ),
            patch.object(
                gmail_tools,
                "_fetch_message_view",
                side_effect=[None, {"id": "m2"}, None],
            ),
        ):
            _, result = self._run(None)
        assert result == ([{"id": "m2"}], False)

    def test_per_message_error_raises_partial(self):
        with (
            patch.object(
                gmail_tools,
                "_fetch_list_page",
                return_value=self._page(messages=[{"id": "m1"}, {"id": "m2"}]),
            ),
            patch.object(
                gmail_tools,
                "_fetch_message_view",
                side_effect=[{"id": "m1"}, RuntimeError("fetch boom")],
            ),
        ):
            with pytest.raises(_PartialResult) as exc_info:
                self._run(None)
        assert exc_info.value.reason == "fetch boom"
        assert exc_info.value.partial_messages == [{"id": "m1"}]


class TestOffloadPath:
    def test_timestamped_unique_path(self):
        fixed = datetime.datetime(2024, 8, 10, 12, 34, 56)
        with (
            patch("app.services.composio.custom_tools.gmail_tools.datetime") as fake_dt,
            patch(
                "app.services.composio.custom_tools.gmail_tools.uuid.uuid4",
                return_value=uuid.UUID("12345678-1234-1234-1234-123456789012"),
            ),
        ):
            fake_dt.datetime.now.return_value = fixed
            path = _offload_path()
        assert path == "gmail/inbox_summary_20240810_123456_12345678.jsonl"


class TestHumanSize:
    def test_bytes_under_1k(self):
        assert _human_size(0) == "0 B"
        assert _human_size(1023) == "1023 B"

    def test_kb_boundary(self):
        assert _human_size(1024) == "1 KB"
        assert _human_size(1536) == "2 KB"
        assert _human_size(1024 * 1024 - 1) == "1024 KB"

    def test_mb(self):
        assert _human_size(1024 * 1024) == "1.0 MB"
        assert _human_size(1024 * 1024 * 10) == "10.0 MB"

    def test_mb_fraction(self):
        assert _human_size(5767168) == "5.5 MB"


class TestBuildReadPlan:
    def test_zero_messages(self):
        assert _build_read_plan(0, 100) == {
            "total_lines": 0,
            "recommended_subagents": 0,
            "chunks": [],
        }

    def test_single_message(self):
        plan = _build_read_plan(1, 0)
        assert plan == {
            "total_lines": 1,
            "recommended_subagents": 1,
            "chunks": [
                {"part": 1, "start_line": 1, "line_count": 1, "read": {"offset": 1, "limit": 1}}
            ],
        }

    def test_small_inbox_one_chunk(self):
        plan = _build_read_plan(25, 1000)
        assert plan["recommended_subagents"] == 1
        assert plan["chunks"] == [
            {"part": 1, "start_line": 1, "line_count": 25, "read": {"offset": 1, "limit": 25}}
        ]

    def test_100_messages_even_chunks(self):
        plan = _build_read_plan(100, 200_000)
        assert plan["recommended_subagents"] == 4
        counts = [c["line_count"] for c in plan["chunks"]]
        assert counts == [25, 25, 25, 25]
        starts = [c["start_line"] for c in plan["chunks"]]
        assert starts == [1, 26, 51, 76]
        for c in plan["chunks"]:
            assert c["read"] == {"offset": c["start_line"], "limit": c["line_count"]}

    def test_remainder_spread_to_leading_chunks(self):
        plan = _build_read_plan(101, 200_000)
        counts = [c["line_count"] for c in plan["chunks"]]
        assert counts == [26, 25, 25, 25]
        assert plan["chunks"][-1]["start_line"] == 77

    def test_capped_at_max_subagents(self):
        plan = _build_read_plan(1000, 1_000_000)
        assert plan["recommended_subagents"] == 4
        assert [c["line_count"] for c in plan["chunks"]] == [250, 250, 250, 250]

    def test_byte_driven_chunking(self):
        plan = _build_read_plan(30, 200_000)
        assert plan["recommended_subagents"] == 4
        assert [c["line_count"] for c in plan["chunks"]] == [8, 8, 7, 7]

    def test_huge_lines_split_by_bytes(self):
        plan = _build_read_plan(10, 500_000)
        assert plan["recommended_subagents"] == 4
        assert [c["line_count"] for c in plan["chunks"]] == [3, 3, 2, 2]

    def test_fewer_messages_than_chunks_stops_at_zero_count(self):
        plan = _build_read_plan(2, 200_000)
        assert plan == {
            "total_lines": 2,
            "recommended_subagents": 2,
            "chunks": [
                {"part": 1, "start_line": 1, "line_count": 1, "read": {"offset": 1, "limit": 1}},
                {"part": 2, "start_line": 2, "line_count": 1, "read": {"offset": 2, "limit": 1}},
            ],
        }

    def test_zero_bytes_defaults_by_bytes_to_one(self):
        plan = _build_read_plan(2, 0)
        assert plan["recommended_subagents"] == 1
        assert plan["chunks"] == [
            {"part": 1, "start_line": 1, "line_count": 2, "read": {"offset": 1, "limit": 2}}
        ]

    def test_byte_split_when_messages_outnumber_bytes(self):
        plan = _build_read_plan(100, 50_000)
        assert plan["recommended_subagents"] == 4
        assert [c["line_count"] for c in plan["chunks"]] == [25, 25, 25, 25]


class TestFormatOffloadResult:
    VIEWS: ClassVar[list[dict[str, Any]]] = [
        {"id": "m1", "from": "a@b.com", "subject": "Hi", "body": "b1"},
        {"id": "m2", "from": "c@d.com", "subject": "Yo"},
    ]

    def _run(
        self,
        views=None,
        *,
        fields=None,
        producer="GMAIL_FETCH_MESSAGES",
        truncated=True,
    ):
        with (
            patch.object(
                gmail_tools, "_offload_path", return_value="gmail/inbox_summary_x.jsonl"
            ),
            patch.object(
                gmail_tools,
                "write_session_file_sync",
                return_value=(
                    "/host/x.jsonl",
                    "/workspace/sessions/u1/s1/gmail/inbox_summary_x.jsonl",
                ),
            ) as writer,
        ):
            result = _format_offload_result(
                views if views is not None else self.VIEWS,
                truncated=truncated,
                user_id="u1",
                conversation_id="s1",
                fields=fields,
                producer=producer,
            )
        return result, writer

    def test_exact_result_shape(self):
        result, writer = self._run(fields=["id", "from"])
        content = "\n".join(json.dumps(v, default=str) for v in self.VIEWS)
        writer.assert_called_once_with(
            user_id="u1",
            conversation_id="s1",
            relative_path="gmail/inbox_summary_x.jsonl",
            content=content,
        )
        assert result["total_messages"] == 2
        assert result["truncated"] is True
        assert result["offloaded_to"] == "/workspace/sessions/u1/s1/gmail/inbox_summary_x.jsonl"
        assert result["file_size_bytes"] == len(content.encode("utf-8"))
        assert result["file_size_human"] == _human_size(len(content.encode("utf-8")))
        assert result["field_count"] == 4
        assert result["inline_preview"] == [
            {"id": "m1", "from": "a@b.com"},
            {"id": "m2", "from": "c@d.com"},
        ]
        assert result["read_plan"]["total_lines"] == 2
        assert result["read_plan"]["recommended_subagents"] == 1
        assert result["read_plan"]["chunks"] == [
            {"part": 1, "start_line": 1, "line_count": 2, "read": {"offset": 1, "limit": 2}}
        ]
        assert "/workspace/sessions/u1/s1/gmail/inbox_summary_x.jsonl" in result["hint"]
        assert "1 subagent" in result["hint"]
        assert (
            "query_json(path='/workspace/sessions/u1/s1/gmail/inbox_summary_x.jsonl'"
            in result["hint"]
        )
        assert result[OFFLOAD_RESULT_KEY] == {
            "path": "/workspace/sessions/u1/s1/gmail/inbox_summary_x.jsonl",
            "bytes": len(content.encode("utf-8")),
            "fmt": "jsonl",
            "producer": "GMAIL_FETCH_MESSAGES",
            "records": 2,
        }

    def test_producer_override(self):
        result, _ = self._run(fields=["id"], producer="GMAIL_FETCH_THREAD")
        assert result[OFFLOAD_RESULT_KEY]["producer"] == "GMAIL_FETCH_THREAD"

    def test_default_producer(self):
        with (
            patch.object(gmail_tools, "_offload_path", return_value="gmail/x.jsonl"),
            patch.object(
                gmail_tools,
                "write_session_file_sync",
                return_value=("/host/x.jsonl", "/workspace/sessions/u1/s1/gmail/x.jsonl"),
            ),
        ):
            result = _format_offload_result(
                [{"id": "m1"}],
                truncated=False,
                user_id="u1",
                conversation_id="s1",
                fields=["id"],
            )
        assert result[OFFLOAD_RESULT_KEY]["producer"] == "GMAIL_FETCH_MESSAGES"

    def test_large_file_read_plan_fans_out(self):
        views = [{"id": f"m{i}", "body": "x" * 30_000} for i in range(3)]
        result, _ = self._run(views=views, fields=["id"])
        assert result["read_plan"]["recommended_subagents"] >= 2

    def test_empty_views(self):
        result, writer = self._run(views=[], fields=["id"], truncated=False)
        assert result["total_messages"] == 0
        assert result["field_count"] == 0
        assert result["file_size_bytes"] == 0
        assert result["file_size_human"] == "0 B"
        assert result["inline_preview"] == []
        assert result["read_plan"] == {
            "total_lines": 0,
            "recommended_subagents": 0,
            "chunks": [],
        }
        assert writer.call_args.kwargs["content"] == ""

    def test_preview_capped_and_all_lines_written(self):
        views = [{"id": f"m{i}"} for i in range(15)]
        result, writer = self._run(views=views, fields=["id"])
        assert len(result["inline_preview"]) == OFFLOAD_PREVIEW_SIZE
        written = writer.call_args.kwargs["content"]
        assert len(written.splitlines()) == 15


class TestEmitEmailCard:
    def test_empty_views_no_writer(self):
        with patch.object(gmail_tools, "get_stream_writer") as get_writer:
            _emit_email_card([])
        get_writer.assert_not_called()

    def test_no_runnable_context_no_writer(self):
        with patch.object(gmail_tools, "get_stream_writer", side_effect=RuntimeError):
            _emit_email_card([{"id": "m1"}])

    def test_writer_none_no_call(self):
        with patch.object(gmail_tools, "get_stream_writer", return_value=None):
            _emit_email_card([{"id": "m1"}])

    def test_writes_card_with_exact_fields(self):
        writer = MagicMock()
        views = [
            {"from": "a@b.com", "subject": "S", "time": "T", "threadId": "th1", "id": "m1"},
            {"id": "m2"},
        ]
        with patch.object(gmail_tools, "get_stream_writer", return_value=writer):
            _emit_email_card(views)
        writer.assert_called_once_with(
            {
                "email_fetch_data": [
                    {
                        "from": "a@b.com",
                        "subject": "S",
                        "time": "T",
                        "thread_id": "th1",
                        "id": "m1",
                    },
                    {"from": "", "subject": "", "time": "", "thread_id": "", "id": "m2"},
                ],
                "resultSize": 2,
            }
        )

    def test_missing_id_defaults_to_empty(self):
        writer = MagicMock()
        with patch.object(gmail_tools, "get_stream_writer", return_value=writer):
            _emit_email_card([{"from": "a@b.com"}])
        writer.assert_called_once_with(
            {
                "email_fetch_data": [
                    {"from": "a@b.com", "subject": "", "time": "", "thread_id": "", "id": ""}
                ],
                "resultSize": 1,
            }
        )


class TestFormatInlineResult:
    def test_exact_shape(self):
        assert _format_inline_result([{"id": "m1"}, {"id": "m2"}], truncated=True) == {
            "fetched_count": 2,
            "truncated": True,
            "messages": [{"id": "m1"}, {"id": "m2"}],
        }

    def test_empty_messages(self):
        assert _format_inline_result([], truncated=False) == {
            "fetched_count": 0,
            "truncated": False,
            "messages": [],
        }


class TestFormatPartialResult:
    def test_exact_shape(self):
        assert _format_partial_result([{"id": "m1"}], reason="boom") == {
            "fetched_count": 1,
            "truncated": True,
            "partial": True,
            "error": "boom",
            "messages": [{"id": "m1"}],
        }

    def test_empty_messages(self):
        assert _format_partial_result([], reason="boom") == {
            "fetched_count": 0,
            "truncated": True,
            "partial": True,
            "error": "boom",
            "messages": [],
        }


class TestCountInlineFit:
    def test_empty(self):
        assert _count_inline_fit([]) == 0

    def test_all_fit(self):
        messages = [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]
        assert _count_inline_fit(messages) == 3

    def test_exact_budget_included(self):
        # A message whose serialized length + 2 separator chars exactly equals
        # the budget is included; one char more is dropped.
        padding = INLINE_LIMIT_CHARS - 10 - 2
        assert _count_inline_fit([{"id": "x" * padding}]) == 1
        assert _count_inline_fit([{"id": "x" * (padding + 1)}]) == 0

    def test_partial_fit_stops_at_first_overflow(self):
        messages = [
            {"id": "small"},
            {"id": "x" * (INLINE_LIMIT_CHARS - 10 - 2 + 1)},
            {"id": "m3"},
        ]
        assert _count_inline_fit(messages) == 1


# ---------------------------------------------------------------------------
# _summarize orchestrator + no-session fallback
# ---------------------------------------------------------------------------


class TestSummarize:
    VIEW: ClassVar[dict[str, Any]] = {"id": "m1", "from": "a@b.com", "subject": "S"}
    REQUEST: ClassVar[FetchMessagesInput] = FetchMessagesInput(fields=["id"], body_processing="none")

    def test_inline_small_result(self):
        with (
            patch.object(gmail_tools, "_current_config", return_value={}),
            patch.object(
                gmail_tools,
                "home_timezone_from_config",
                return_value=Timezone.utc(),
            ) as tz,
            patch.object(
                gmail_tools,
                "_aggregate_pages",
                return_value=([self.VIEW], False),
            ) as agg,
            patch.object(gmail_tools, "_emit_email_card") as card,
        ):
            result = _summarize("u1", self.REQUEST)
        tz.assert_called_once_with({})
        agg.assert_called_once_with("u1", self.REQUEST, combined_query="", effective_max=100)
        card.assert_called_once_with([self.VIEW])
        assert result == {
            "fetched_count": 1,
            "truncated": False,
            "messages": [{"id": "m1"}],
        }

    def test_resolves_timeframe_and_query(self):
        request = FetchMessagesInput(
            fields=["id"],
            timeframe="today",
            query="is:unread",
            body_processing="none",
        )
        fixed = datetime.datetime(2024, 6, 19, 12, 0, 0)
        with (
            patch.object(gmail_tools, "_current_config", return_value={}),
            patch.object(Timezone, "now", return_value=fixed),
            patch.object(
                gmail_tools, "_aggregate_pages", return_value=([self.VIEW], False)
            ) as agg,
            patch.object(gmail_tools, "_emit_email_card"),
        ):
            _summarize("u1", request)
        assert agg.call_args.kwargs["combined_query"] == (
            "after:2024/06/19 before:2024/06/20 is:unread"
        )

    def test_partial_result_path(self):
        partial = _PartialResult(reason="boom", partial_messages=[self.VIEW])
        with (
            patch.object(gmail_tools, "_current_config", return_value={}),
            patch.object(gmail_tools, "_aggregate_pages", side_effect=partial),
            patch.object(gmail_tools, "_emit_email_card") as card,
        ):
            result = _summarize("u1", self.REQUEST)
        card.assert_not_called()
        assert result == {
            "fetched_count": 1,
            "truncated": True,
            "partial": True,
            "error": "boom",
            "messages": [{"id": "m1"}],
        }

    def test_offload_when_over_message_limit(self):
        views = [
            {"id": f"m{i}", "from": "a@b.com"} for i in range(OFFLOAD_MIN_MESSAGES + 1)
        ]
        with (
            patch.object(
                gmail_tools,
                "_current_config",
                return_value={"configurable": {"vfs_session_id": "s1"}},
            ),
            patch.object(gmail_tools, "_aggregate_pages", return_value=(views, True)),
            patch.object(
                gmail_tools, "_format_offload_result", return_value={"offloaded_to": "x"}
            ) as offload,
            patch.object(gmail_tools, "_emit_email_card") as card,
        ):
            result = _summarize("u1", self.REQUEST)
        offload.assert_called_once_with(
            views,
            truncated=True,
            user_id="u1",
            conversation_id="s1",
            fields=["id"],
        )
        card.assert_not_called()
        assert result == {"offloaded_to": "x"}

    def test_50_messages_still_inline(self):
        views = [{"id": f"m{i}"} for i in range(OFFLOAD_MIN_MESSAGES)]
        with (
            patch.object(gmail_tools, "_current_config", return_value={}),
            patch.object(gmail_tools, "_aggregate_pages", return_value=(views, False)),
            patch.object(gmail_tools, "_emit_email_card"),
            patch.object(gmail_tools, "_format_offload_result") as offload,
        ):
            result = _summarize("u1", self.REQUEST)
        offload.assert_not_called()
        assert result["fetched_count"] == OFFLOAD_MIN_MESSAGES
        assert "offloaded_to" not in result

    def test_char_limit_boundary(self):
        base_len = len(json.dumps({"messages": [{"id": ""}]}))
        view = {"id": "x" * (INLINE_LIMIT_CHARS - base_len)}
        with (
            patch.object(gmail_tools, "_current_config", return_value={}),
            patch.object(gmail_tools, "_aggregate_pages", return_value=([view], False)),
            patch.object(gmail_tools, "_emit_email_card") as card,
        ):
            result = _summarize(
                "u1", FetchMessagesInput(fields=["id"], body_processing="none")
            )
        assert "offloaded_to" not in result
        assert result["fetched_count"] == 1
        card.assert_called_once()

    def test_char_limit_overflow_falls_back_inline(self):
        base_len = len(json.dumps({"messages": [{"id": ""}]}))
        view = {"id": "x" * (INLINE_LIMIT_CHARS - base_len + 1)}
        with (
            patch.object(gmail_tools, "_current_config", return_value={}),
            patch.object(gmail_tools, "_aggregate_pages", return_value=([view], False)),
            patch.object(gmail_tools, "_emit_email_card"),
            patch.object(gmail_tools, "_format_offload_result") as offload,
        ):
            result = _summarize(
                "u1", FetchMessagesInput(fields=["id"], body_processing="none")
            )
        offload.assert_not_called()
        assert result["fetched_count"] == 1
        assert "offloaded_to" not in result

    def test_char_limit_exact_boundary_stays_inline_with_session(self):
        base_len = len(json.dumps({"messages": [{"id": ""}]}))
        view = {"id": "x" * (INLINE_LIMIT_CHARS - base_len)}
        with (
            patch.object(
                gmail_tools,
                "_current_config",
                return_value={"configurable": {"vfs_session_id": "s1"}},
            ),
            patch.object(gmail_tools, "_aggregate_pages", return_value=([view], False)),
            patch.object(gmail_tools, "_emit_email_card"),
            patch.object(gmail_tools, "_format_offload_result") as offload,
        ):
            result = _summarize(
                "u1", FetchMessagesInput(fields=["id"], body_processing="none")
            )
        offload.assert_not_called()
        assert result["fetched_count"] == 1
        assert "offloaded_to" not in result

    def test_char_limit_overflow_offloads_with_session(self):
        base_len = len(json.dumps({"messages": [{"id": ""}]}))
        view = {"id": "x" * (INLINE_LIMIT_CHARS - base_len + 1)}
        with (
            patch.object(
                gmail_tools,
                "_current_config",
                return_value={"configurable": {"vfs_session_id": "s1"}},
            ),
            patch.object(gmail_tools, "_aggregate_pages", return_value=([view], False)),
            patch.object(gmail_tools, "_emit_email_card"),
            patch.object(
                gmail_tools, "_format_offload_result", return_value={"offloaded_to": "x"}
            ) as offload,
        ):
            result = _summarize(
                "u1", FetchMessagesInput(fields=["id"], body_processing="none")
            )
        offload.assert_called_once()
        assert result == {"offloaded_to": "x"}

    def test_message_limit_exact_boundary_stays_inline_with_session(self):
        views = [{"id": f"m{i}"} for i in range(OFFLOAD_MIN_MESSAGES)]
        with (
            patch.object(
                gmail_tools,
                "_current_config",
                return_value={"configurable": {"vfs_session_id": "s1"}},
            ),
            patch.object(gmail_tools, "_aggregate_pages", return_value=(views, False)),
            patch.object(gmail_tools, "_emit_email_card"),
            patch.object(gmail_tools, "_format_offload_result") as offload,
        ):
            result = _summarize("u1", self.REQUEST)
        offload.assert_not_called()
        assert result["fetched_count"] == OFFLOAD_MIN_MESSAGES
        assert "offloaded_to" not in result

    def test_no_session_truncated_true_all_fit_keeps_flag(self):
        base_len = len(json.dumps({"messages": [{"id": ""}]}))
        view = {"id": "x" * (INLINE_LIMIT_CHARS - base_len + 1)}
        with (
            patch.object(gmail_tools, "_current_config", return_value={}),
            patch.object(gmail_tools, "_aggregate_pages", return_value=([view], True)),
            patch.object(gmail_tools, "_count_inline_fit", return_value=1),
            patch.object(gmail_tools, "_emit_email_card"),
        ):
            result = _summarize(
                "u1", FetchMessagesInput(fields=["id"], body_processing="none")
            )
        assert result["truncated"] is True
        assert "total_matched" not in result

    def test_respects_max_messages_override(self):
        with (
            patch.object(gmail_tools, "_current_config", return_value={}),
            patch.object(
                gmail_tools, "_aggregate_pages", return_value=([self.VIEW], False)
            ) as agg,
            patch.object(gmail_tools, "_emit_email_card"),
        ):
            _summarize("u1", FetchMessagesInput(fields=["id"], max_messages=5))
        assert agg.call_args.kwargs["effective_max"] == 5


class TestNoSessionInlineFallback:
    def test_truncated_with_total_matched(self):
        full_views = [{"id": f"m{i}", "from": "a@b.com"} for i in range(3)]
        projected = [{"id": f"m{i}"} for i in range(3)]
        with (
            patch.object(gmail_tools, "_count_inline_fit", return_value=2),
            patch.object(gmail_tools, "_emit_email_card") as card,
            patch.object(gmail_tools.log, "warning") as warn,
        ):
            result = _no_session_inline_fallback(full_views, projected, truncated=False)
        card.assert_called_once_with(full_views[:2])
        warn.assert_called_once_with(
            "GMAIL read: no conversation_id for offload; returning / inline",
            shown=2,
            projected_count=3,
        )
        assert result["fetched_count"] == 2
        assert result["truncated"] is True
        assert result["total_matched"] == 3
        assert result["messages"] == projected[:2]
        assert "Showing 2 of 3 matched messages" in result["hint"]

    def test_truncated_true_all_fit_keeps_flag(self):
        projected = [{"id": "m1"}]
        with (
            patch.object(gmail_tools, "_count_inline_fit", return_value=1),
            patch.object(gmail_tools, "_emit_email_card"),
        ):
            result = _no_session_inline_fallback(
                [{"id": "m1"}], projected, truncated=True
            )
        assert result["truncated"] is True
        assert "total_matched" not in result

    def test_all_fit_no_extra_keys(self):
        projected = [{"id": "m1"}]
        with (
            patch.object(gmail_tools, "_count_inline_fit", return_value=1),
            patch.object(gmail_tools, "_emit_email_card"),
        ):
            result = _no_session_inline_fallback(
                [{"id": "m1"}], projected, truncated=False
            )
        assert result == {"fetched_count": 1, "truncated": False, "messages": projected}
        assert "total_matched" not in result

    def test_zero_shown(self):
        projected = [{"id": "m1"}]
        with (
            patch.object(gmail_tools, "_count_inline_fit", return_value=0),
            patch.object(gmail_tools, "_emit_email_card") as card,
        ):
            result = _no_session_inline_fallback(
                [{"id": "m1"}], projected, truncated=False
            )
        card.assert_called_once_with([])
        assert result["fetched_count"] == 0
        assert result["total_matched"] == 1


# ---------------------------------------------------------------------------
# FETCH_THREAD — full-conversation reconstruction
# ---------------------------------------------------------------------------


class TestThreadNeedsFull:
    def test_no_body_no_attachments(self):
        assert (
            _thread_needs_full(
                FetchThreadInput(
                    thread_ids=["t1"], fields=["id"], body_processing="none"
                )
            )
            is False
        )

    def test_none_processing_wins_over_body_field(self):
        assert (
            _thread_needs_full(
                FetchThreadInput(thread_ids=["t1"], fields=["body"], body_processing="none")
            )
            is False
        )

    def test_body_processing_requires_full(self):
        assert (
            _thread_needs_full(
                FetchThreadInput(thread_ids=["t1"], fields=["id"], body_processing="raw")
            )
            is True
        )

    def test_attachments_require_full(self):
        assert (
            _thread_needs_full(
                FetchThreadInput(
                    thread_ids=["t1"], fields=["attachments"], body_processing="none"
                )
            )
            is True
        )

    def test_all_fields_implies_body(self):
        assert (
            _thread_needs_full(
                FetchThreadInput(
                    thread_ids=["t1"], fields=None, body_processing="normalize"
                )
            )
            is True
        )


class TestFetchOneThread:
    def test_metadata_format(self):
        with (
            patch.object(gmail_tools, "_gmail_proxy", return_value={}) as proxy,
            patch.object(gmail_tools, "build_message_view") as build,
        ):
            result = _fetch_one_thread(
                "u1", "t1", needs_full=False, body_processing="normalize"
            )
        proxy.assert_called_once_with(
            "u1",
            endpoint=f"{GMAIL_API_BASE}/users/me/threads/t1",
            method="GET",
            query={"format": GMAIL_FORMAT_METADATA},
        )
        build.assert_not_called()
        assert result == []

    def test_full_format(self):
        with (
            patch.object(gmail_tools, "_gmail_proxy", return_value={}) as proxy,
            patch.object(gmail_tools, "build_message_view"),
        ):
            _fetch_one_thread("u1", "t1", needs_full=True, body_processing="raw")
        assert proxy.call_args.kwargs["query"] == {"format": GMAIL_FORMAT_FULL}

    def test_non_dict_returns_empty(self):
        with (
            patch.object(gmail_tools, "_gmail_proxy", return_value=["nope"]),
            patch.object(gmail_tools, "build_message_view") as build,
        ):
            result = _fetch_one_thread(
                "u1", "t1", needs_full=True, body_processing="normalize"
            )
        assert result == []
        build.assert_not_called()

    def test_builds_views_in_order_filtering_non_dicts(self):
        raw = {"messages": [{"id": "m1"}, "junk", {"id": "m2"}]}
        with (
            patch.object(gmail_tools, "_gmail_proxy", return_value=raw),
            patch.object(
                gmail_tools,
                "build_message_view",
                side_effect=lambda msg, body_processing: {"view": msg["id"]},
            ) as build,
        ):
            result = _fetch_one_thread(
                "u1", "t1", needs_full=False, body_processing="normalize"
            )
        assert result == [{"view": "m1"}, {"view": "m2"}]
        assert [c.kwargs["body_processing"] for c in build.call_args_list] == [
            "normalize",
            "normalize",
        ]


class TestAggregateThreads:
    def _run(self, *, max_messages=None):
        if max_messages is not None:
            return FetchThreadInput(
                thread_ids=["t1", "t2"],
                fields=["id"],
                body_processing="none",
                max_messages=max_messages,
            )
        return FetchThreadInput(
            thread_ids=["t1", "t2"], fields=["id"], body_processing="none"
        )

    def test_groups_threads_and_flat_views(self):
        request = self._run()
        with patch.object(
            gmail_tools,
            "_fetch_one_thread",
            side_effect=[
                [{"id": "t1m1"}, {"id": "t1m2"}],
                [{"id": "t2m1"}, {"id": "t2m2"}, {"id": "t2m3"}],
            ],
        ) as fetch:
            threads, flat_views, truncated = _aggregate_threads("u1", request)
        assert truncated is False
        assert threads == [
            {
                "id": "t1",
                "message_count": 2,
                "messages": [{"id": "t1m1"}, {"id": "t1m2"}],
            },
            {
                "id": "t2",
                "message_count": 3,
                "messages": [{"id": "t2m1"}, {"id": "t2m2"}, {"id": "t2m3"}],
            },
        ]
        assert flat_views == [
            {"id": "t1m1"},
            {"id": "t1m2"},
            {"id": "t2m1"},
            {"id": "t2m2"},
            {"id": "t2m3"},
        ]
        assert [c.args[1] for c in fetch.call_args_list] == ["t1", "t2"]
        assert all(c.kwargs["needs_full"] is False for c in fetch.call_args_list)
        assert all(c.kwargs["body_processing"] == "none" for c in fetch.call_args_list)

    def test_cap_trims_messages(self):
        request = self._run(max_messages=3)
        with patch.object(
            gmail_tools,
            "_fetch_one_thread",
            side_effect=[
                [{"id": "t1m1"}, {"id": "t1m2"}],
                [{"id": "t2m1"}, {"id": "t2m2"}, {"id": "t2m3"}],
            ],
        ):
            threads, flat_views, truncated = _aggregate_threads("u1", request)
        assert truncated is True
        assert threads == [
            {
                "id": "t1",
                "message_count": 2,
                "messages": [{"id": "t1m1"}, {"id": "t1m2"}],
            },
            {"id": "t2", "message_count": 1, "messages": [{"id": "t2m1"}]},
        ]
        assert len(flat_views) == 3

    def test_cap_exhausted_skips_remaining_threads(self):
        request = self._run(max_messages=2)
        with patch.object(
            gmail_tools,
            "_fetch_one_thread",
            side_effect=[
                [{"id": "t1m1"}, {"id": "t1m2"}],
                [{"id": "t2m1"}],
            ],
        ):
            threads, flat_views, truncated = _aggregate_threads("u1", request)
        assert truncated is True
        assert len(threads) == 1
        assert flat_views == [{"id": "t1m1"}, {"id": "t1m2"}]

    def test_exact_fit_cap_not_truncated(self):
        request = self._run(max_messages=5)
        with patch.object(
            gmail_tools,
            "_fetch_one_thread",
            side_effect=[
                [{"id": "t1m1"}, {"id": "t1m2"}],
                [{"id": "t2m1"}, {"id": "t2m2"}, {"id": "t2m3"}],
            ],
        ):
            threads, flat_views, truncated = _aggregate_threads("u1", request)
        assert truncated is False
        assert len(flat_views) == 5
        assert [t["message_count"] for t in threads] == [2, 3]

    def test_error_before_any_view_propagates(self):
        request = self._run()
        with patch.object(
            gmail_tools, "_fetch_one_thread", side_effect=RuntimeError("boom")
        ):
            with pytest.raises(RuntimeError, match="boom"):
                _aggregate_threads("u1", request)

    def test_error_mid_fetch_raises_partial(self):
        request = self._run()
        with (
            patch.object(
                gmail_tools,
                "_fetch_one_thread",
                side_effect=[
                    [{"id": "t1m1"}],
                    RuntimeError("boom"),
                ],
            ),
            patch.object(gmail_tools.log, "warning") as warn,
        ):
            with pytest.raises(_PartialResult) as exc_info:
                _aggregate_threads("u1", request)
        assert exc_info.value.reason == "boom"
        assert exc_info.value.partial_messages == [{"id": "t1m1"}]
        warn.assert_called_once_with(
            "GMAIL_FETCH_THREAD: aborted mid-fetch",
            error="boom",
            error_type="RuntimeError",
            user_id="u1",
        )


class TestSummarizeThreads:
    THREADS: ClassVar[list[dict[str, Any]]] = [
        {
            "id": "t1",
            "message_count": 2,
            "messages": [
                {"id": "m1", "from": "a@b.com"},
                {"id": "m2", "from": "b@c.com"},
            ],
        }
    ]
    FLAT: ClassVar[list[dict[str, Any]]] = [{"id": "m1", "from": "a@b.com"}, {"id": "m2", "from": "b@c.com"}]

    def test_inline_small_result(self):
        request = FetchThreadInput(thread_ids=["t1"], fields=["id"], body_processing="none")
        with (
            patch.object(gmail_tools, "_current_config", return_value={}),
            patch.object(
                gmail_tools,
                "_aggregate_threads",
                return_value=(self.THREADS, self.FLAT, False),
            ) as agg,
            patch.object(gmail_tools, "_emit_email_card") as card,
        ):
            result = _summarize_threads("u1", request)
        agg.assert_called_once_with("u1", request)
        card.assert_called_once_with(self.FLAT)
        assert result == {
            "fetched_threads": 1,
            "total_messages": 2,
            "truncated": False,
            "threads": [
                {
                    "id": "t1",
                    "message_count": 2,
                    "messages": [{"id": "m1"}, {"id": "m2"}],
                }
            ],
        }

    def test_partial_result_path(self):
        request = FetchThreadInput(thread_ids=["t1"], fields=["id"], body_processing="none")
        partial = _PartialResult(reason="boom", partial_messages=self.FLAT)
        with (
            patch.object(gmail_tools, "_current_config", return_value={}),
            patch.object(gmail_tools, "_aggregate_threads", side_effect=partial),
        ):
            result = _summarize_threads("u1", request)
        assert result == {
            "fetched_count": 2,
            "truncated": True,
            "partial": True,
            "error": "boom",
            "messages": [{"id": "m1"}, {"id": "m2"}],
        }

    def test_offload_when_over_message_limit(self):
        request = FetchThreadInput(thread_ids=["t1"], fields=["id"], body_processing="none")
        flat = [
            {"id": f"m{i}", "from": "a@b.com"} for i in range(OFFLOAD_MIN_MESSAGES + 1)
        ]
        threads = [{"id": "t1", "message_count": len(flat), "messages": flat}]
        with (
            patch.object(
                gmail_tools,
                "_current_config",
                return_value={"configurable": {"vfs_session_id": "s1"}},
            ),
            patch.object(gmail_tools, "_aggregate_threads", return_value=(threads, flat, True)),
            patch.object(
                gmail_tools, "_format_offload_result", return_value={"offloaded_to": "x"}
            ) as offload,
        ):
            result = _summarize_threads("u1", request)
        offload.assert_called_once_with(
            flat,
            truncated=True,
            user_id="u1",
            conversation_id="s1",
            fields=["id"],
            producer="GMAIL_FETCH_THREAD",
        )
        assert result == {"offloaded_to": "x", "total_threads": 1}

    def test_no_session_falls_back(self):
        request = FetchThreadInput(thread_ids=["t1"], fields=["id"], body_processing="none")
        flat = [{"id": f"m{i}"} for i in range(OFFLOAD_MIN_MESSAGES + 1)]
        threads = [{"id": "t1", "message_count": len(flat), "messages": flat}]
        with (
            patch.object(gmail_tools, "_current_config", return_value={}),
            patch.object(gmail_tools, "_aggregate_threads", return_value=(threads, flat, False)),
            patch.object(gmail_tools, "_count_inline_fit", return_value=0),
            patch.object(gmail_tools, "_emit_email_card"),
        ):
            result = _summarize_threads("u1", request)
        assert result["total_matched"] == OFFLOAD_MIN_MESSAGES + 1
        assert result["fetched_count"] == 0

    def test_char_limit_exact_boundary_stays_inline_with_session(self):
        base = {"threads": [{"id": "t1", "message_count": 1, "messages": [{"id": ""}]}]}
        base_len = len(json.dumps(base))
        flat = [{"id": "x" * (INLINE_LIMIT_CHARS - base_len)}]
        threads = [{"id": "t1", "message_count": 1, "messages": flat}]
        request = FetchThreadInput(thread_ids=["t1"], fields=["id"], body_processing="none")
        with (
            patch.object(
                gmail_tools,
                "_current_config",
                return_value={"configurable": {"vfs_session_id": "s1"}},
            ),
            patch.object(gmail_tools, "_aggregate_threads", return_value=(threads, flat, False)),
            patch.object(gmail_tools, "_emit_email_card"),
            patch.object(gmail_tools, "_format_offload_result") as offload,
        ):
            result = _summarize_threads("u1", request)
        offload.assert_not_called()
        assert result["fetched_threads"] == 1
        assert "offloaded_to" not in result

    def test_char_limit_overflow_offloads_with_session(self):
        base = {"threads": [{"id": "t1", "message_count": 1, "messages": [{"id": ""}]}]}
        base_len = len(json.dumps(base))
        flat = [{"id": "x" * (INLINE_LIMIT_CHARS - base_len + 1)}]
        threads = [{"id": "t1", "message_count": 1, "messages": flat}]
        request = FetchThreadInput(thread_ids=["t1"], fields=["id"], body_processing="none")
        with (
            patch.object(
                gmail_tools,
                "_current_config",
                return_value={"configurable": {"vfs_session_id": "s1"}},
            ),
            patch.object(gmail_tools, "_aggregate_threads", return_value=(threads, flat, False)),
            patch.object(gmail_tools, "_emit_email_card"),
            patch.object(
                gmail_tools, "_format_offload_result", return_value={"offloaded_to": "x"}
            ) as offload,
        ):
            result = _summarize_threads("u1", request)
        offload.assert_called_once()
        assert result == {"offloaded_to": "x", "total_threads": 1}

    def test_message_limit_exact_boundary_stays_inline_with_session(self):
        flat = [{"id": f"m{i}"} for i in range(OFFLOAD_MIN_MESSAGES)]
        threads = [{"id": "t1", "message_count": len(flat), "messages": flat}]
        request = FetchThreadInput(thread_ids=["t1"], fields=["id"], body_processing="none")
        with (
            patch.object(
                gmail_tools,
                "_current_config",
                return_value={"configurable": {"vfs_session_id": "s1"}},
            ),
            patch.object(gmail_tools, "_aggregate_threads", return_value=(threads, flat, False)),
            patch.object(gmail_tools, "_emit_email_card"),
            patch.object(gmail_tools, "_format_offload_result") as offload,
        ):
            result = _summarize_threads("u1", request)
        offload.assert_not_called()
        assert result["total_messages"] == OFFLOAD_MIN_MESSAGES
        assert "offloaded_to" not in result

    def test_no_session_fallback_projects_to_fields(self):
        flat = [{"id": "m0", "body": "B"} for _ in range(OFFLOAD_MIN_MESSAGES + 1)]
        threads = [{"id": "t1", "message_count": len(flat), "messages": flat}]
        request = FetchThreadInput(thread_ids=["t1"], fields=["id"], body_processing="none")
        with (
            patch.object(gmail_tools, "_current_config", return_value={}),
            patch.object(gmail_tools, "_aggregate_threads", return_value=(threads, flat, False)),
            patch.object(gmail_tools, "_count_inline_fit", return_value=1),
            patch.object(gmail_tools, "_emit_email_card"),
        ):
            result = _summarize_threads("u1", request)
        assert result["messages"] == [{"id": "m0"}]

    def test_no_session_truncated_true_all_fit_keeps_flag(self):
        flat = [{"id": f"m{i}", "body": "B"} for i in range(OFFLOAD_MIN_MESSAGES + 1)]
        threads = [{"id": "t1", "message_count": len(flat), "messages": flat}]
        request = FetchThreadInput(thread_ids=["t1"], fields=["id"], body_processing="none")
        with (
            patch.object(gmail_tools, "_current_config", return_value={}),
            patch.object(gmail_tools, "_aggregate_threads", return_value=(threads, flat, True)),
            patch.object(gmail_tools, "_count_inline_fit", return_value=len(flat)),
            patch.object(gmail_tools, "_emit_email_card"),
        ):
            result = _summarize_threads("u1", request)
        assert result["truncated"] is True
        assert "total_matched" not in result


# ---------------------------------------------------------------------------
# Batch label mutation
# ---------------------------------------------------------------------------


class TestBatchModify:
    def test_empty_ids_no_call(self):
        with (
            patch.object(gmail_tools, "_gmail_proxy") as proxy,
            patch.object(gmail_tools.log, "set") as log_set,
        ):
            assert _batch_modify("u1", []) == {"modified_count": 0, "failed_count": 0}
        proxy.assert_not_called()
        log_set.assert_not_called()

    def test_single_chunk_add_and_remove(self):
        with (
            patch.object(gmail_tools, "_gmail_proxy") as proxy,
            patch.object(gmail_tools.log, "set") as log_set,
        ):
            result = _batch_modify(
                "u1", ["m1", "m2"], add_label_ids=["A"], remove_label_ids=["R"]
            )
        proxy.assert_called_once_with(
            "u1",
            endpoint=f"{GMAIL_API_BASE}/users/me/messages/batchModify",
            method="POST",
            body={"ids": ["m1", "m2"], "addLabelIds": ["A"], "removeLabelIds": ["R"]},
        )
        assert result == {"modified_count": 2, "failed_count": 0}
        log_set.assert_called_once_with(
            gmail_batch_modify={"requested": 2, "modified": 2, "failed": 0}
        )

    def test_no_labels_sends_ids_only(self):
        with patch.object(gmail_tools, "_gmail_proxy") as proxy:
            _batch_modify("u1", ["m1"])
        assert proxy.call_args.kwargs["body"] == {"ids": ["m1"]}

    def test_chunks_at_cap(self):
        ids = [f"m{i}" for i in range(2500)]
        with patch.object(gmail_tools, "_gmail_proxy") as proxy:
            result = _batch_modify("u1", ids, add_label_ids=["UNREAD"])
        assert proxy.call_count == 3
        for i, call in enumerate(proxy.call_args_list):
            chunk = ids[i * GMAIL_BATCH_MODIFY_CAP : (i + 1) * GMAIL_BATCH_MODIFY_CAP]
            assert call.kwargs["body"] == {"ids": chunk, "addLabelIds": ["UNREAD"]}
        assert result == {"modified_count": 2500, "failed_count": 0}

    def test_exact_cap_boundary(self):
        ids = [f"m{i}" for i in range(1000)]
        with patch.object(gmail_tools, "_gmail_proxy") as proxy:
            _batch_modify("u1", ids)
        assert proxy.call_count == 1
        ids_1001 = [f"m{i}" for i in range(1001)]
        with patch.object(gmail_tools, "_gmail_proxy") as proxy:
            _batch_modify("u1", ids_1001)
        assert proxy.call_count == 2
        assert proxy.call_args_list[0].kwargs["body"]["ids"] == ids_1001[:1000]
        assert proxy.call_args_list[1].kwargs["body"]["ids"] == ["m1000"]

    def test_first_chunk_failure_propagates(self):
        with patch.object(
            gmail_tools, "_gmail_proxy", side_effect=RuntimeError("boom")
        ) as proxy:
            with pytest.raises(RuntimeError, match="boom"):
                _batch_modify("u1", ["m1", "m2"])
        proxy.assert_called_once()

    def test_later_chunk_failure_returns_partial(self):
        def side_effect(*args, **kwargs):
            if proxy.call_count == 1:
                return
            raise RuntimeError("boom")

        with (
            patch.object(gmail_tools, "_gmail_proxy", side_effect=side_effect) as proxy,
            patch.object(gmail_tools.log, "set") as log_set,
            patch.object(gmail_tools.log, "warning") as log_warn,
        ):
            result = _batch_modify("u1", [f"m{i}" for i in range(2500)])
        assert result == {
            "modified_count": 1000,
            "failed_count": 1500,
            "partial": True,
            "error": "boom",
        }
        log_set.assert_called_once_with(
            gmail_batch_modify={"requested": 2500, "modified": 1000, "failed": 1500}
        )
        log_warn.assert_called_once_with(
            "GMAIL batchModify aborted after / modified",
            modified=1000,
            message_ids_count=2500,
            error="boom",
            error_type="RuntimeError",
            user_id="u1",
        )


# ---------------------------------------------------------------------------
# Counts, labels, profile, recent ids
# ---------------------------------------------------------------------------


class TestCountMessages:
    def test_request_shape_with_labels(self, mock_proxy):
        mock_proxy.return_value = {"resultSizeEstimate": 42}
        count = _count_messages(
            "u1", query="is:unread", label_ids=["INBOX"], include_spam_trash=False
        )
        assert mock_proxy.call_args.kwargs == {
            "user_id": "u1",
            "toolkit": GMAIL_TOOLKIT,
            "endpoint": f"{GMAIL_API_BASE}/users/me/messages",
            "method": "GET",
            "body": None,
            "query": {
                "maxResults": 1,
                "includeSpamTrash": "false",
                "q": "is:unread",
                "labelIds": ["INBOX"],
            },
        }
        assert count == 42

    def test_no_label_ids_key_when_empty(self, mock_proxy):
        mock_proxy.return_value = {}
        _count_messages("u1", query="q", label_ids=[], include_spam_trash=True)
        query = mock_proxy.call_args.kwargs["query"]
        assert query["includeSpamTrash"] == "true"
        assert "labelIds" not in query

    def test_negative_estimate_clamped(self, mock_proxy):
        mock_proxy.return_value = {"resultSizeEstimate": -5}
        assert _count_messages("u1", query="q", label_ids=[], include_spam_trash=False) == 0

    def test_estimate_none_falls_back_to_page_count(self, mock_proxy):
        mock_proxy.return_value = {"messages": [{"id": "m1"}, {"id": "m2"}]}
        assert _count_messages("u1", query="q", label_ids=[], include_spam_trash=False) == 2

    def test_none_response_counts_zero(self, mock_proxy):
        mock_proxy.return_value = None
        assert _count_messages("u1", query="q", label_ids=[], include_spam_trash=False) == 0


class TestLabelStats:
    def test_uses_label_name(self):
        with patch.object(
            gmail_tools,
            "_gmail_label",
            return_value=GmailLabelDetail.model_validate(
                {"name": "Inbox", "messagesUnread": 7, "messagesTotal": 100}
            ),
        ) as label:
            result = _label_stats("u1", "INBOX")
        label.assert_called_once_with("u1", "INBOX")
        assert result == {
            "label_id": "INBOX",
            "label_name": "Inbox",
            "unreadCount": 7,
            "totalCount": 100,
        }

    def test_missing_name_falls_back_to_label_id(self):
        with patch.object(
            gmail_tools,
            "_gmail_label",
            return_value=GmailLabelDetail.model_validate({}),
        ):
            result = _label_stats("u1", "INBOX")
        assert result["label_name"] == "INBOX"


class TestGmailLabel:
    def test_exact_request(self, mock_proxy):
        mock_proxy.return_value = {"name": "Inbox", "messagesUnread": 3, "messagesTotal": 9}
        label = _gmail_label("u1", "INBOX")
        assert mock_proxy.call_args.kwargs == {
            "user_id": "u1",
            "toolkit": GMAIL_TOOLKIT,
            "endpoint": f"{GMAIL_API_BASE}/users/me/labels/INBOX",
            "method": "GET",
            "body": None,
            "query": None,
        }
        assert label.name == "Inbox"
        assert label.messages_unread == 3
        assert label.messages_total == 9

    def test_none_response_defaults(self, mock_proxy):
        mock_proxy.return_value = None
        label = _gmail_label("u1", "INBOX")
        assert label.name is None
        assert label.messages_unread == 0
        assert label.messages_total == 0


class TestGmailUserProfile:
    def test_exact_request(self, mock_proxy):
        mock_proxy.return_value = {
            "emailAddress": "u@x.com",
            "messagesTotal": 1000,
            "threadsTotal": 500,
        }
        profile = _gmail_user_profile("u1")
        assert mock_proxy.call_args.kwargs == {
            "user_id": "u1",
            "toolkit": GMAIL_TOOLKIT,
            "endpoint": f"{GMAIL_API_BASE}/users/me/profile",
            "method": "GET",
            "body": None,
            "query": None,
        }
        assert profile.email_address == "u@x.com"
        assert profile.messages_total == 1000
        assert profile.threads_total == 500

    def test_none_response_defaults(self, mock_proxy):
        mock_proxy.return_value = None
        profile = _gmail_user_profile("u1")
        assert profile.email_address is None
        assert profile.messages_total is None


class TestRecentInboxIds:
    def test_without_since(self, mock_proxy):
        mock_proxy.return_value = {"messages": [{"id": "m1"}, {"id": "m2"}]}
        ids = _recent_inbox_ids("u1", since=None, max_results=5)
        assert mock_proxy.call_args.kwargs == {
            "user_id": "u1",
            "toolkit": GMAIL_TOOLKIT,
            "endpoint": f"{GMAIL_API_BASE}/users/me/messages",
            "method": "GET",
            "body": None,
            "query": {"labelIds": "INBOX", "maxResults": 5},
        }
        assert ids == ["m1", "m2"]

    def test_with_since_builds_after_query(self, mock_proxy):
        mock_proxy.return_value = {}
        _recent_inbox_ids("u1", since="2026-06-19T00:00:00Z", max_results=5)
        query = mock_proxy.call_args.kwargs["query"]
        expected_ts = int(
            datetime.datetime.fromisoformat("2026-06-19T00:00:00Z").timestamp()
        )
        assert query["q"] == f"after:{expected_ts}"
        assert query["labelIds"] == "INBOX"
        assert query["maxResults"] == 5

    def test_invalid_since_raises_app_error(self, mock_proxy):
        with pytest.raises(AppError) as exc_info:
            _recent_inbox_ids("u1", since="not-a-date", max_results=5)
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "Invalid 'since' value: 'not-a-date'"
        assert exc_info.value.why == (
            "GMAIL_CUSTOM_GATHER_CONTEXT received a 'since' that is not an ISO-8601 "
            "datetime."
        )
        assert exc_info.value.fix == "Pass an ISO-8601 datetime such as 2026-06-19T00:00:00Z."
        mock_proxy.assert_not_called()

    def test_falsy_ids_filtered(self, mock_proxy):
        mock_proxy.return_value = {"messages": [{"id": "m1"}, {"id": None}, {"id": ""}]}
        assert _recent_inbox_ids("u1", since=None, max_results=5) == ["m1"]


class TestUnreadCountQueryMode:
    def test_appends_is_unread_to_second_query(self):
        with patch.object(gmail_tools, "_count_messages", side_effect=[50, 12]) as count:
            result = _unread_count_query_mode(
                "u1", "from:boss", ["INBOX"], include_spam_trash=False
            )
        assert count.call_count == 2
        assert [c.args[0] for c in count.call_args_list] == ["u1", "u1"]
        assert count.call_args_list[0].kwargs["query"] == "from:boss"
        assert count.call_args_list[0].kwargs["label_ids"] == ["INBOX"]
        assert count.call_args_list[0].kwargs["include_spam_trash"] is False
        assert count.call_args_list[1].kwargs["query"] == "from:boss is:unread"
        assert count.call_args_list[1].kwargs["label_ids"] == ["INBOX"]
        assert result == {
            "query": "from:boss",
            "label_ids": ["INBOX"],
            "totalCount": 50,
            "unreadCount": 12,
            "is_estimate": True,
            "label_id": "INBOX",
        }

    def test_is_unread_not_doubled(self):
        with patch.object(gmail_tools, "_count_messages", return_value=1) as count:
            _unread_count_query_mode("u1", "is:unread", [], include_spam_trash=True)
        assert count.call_args_list[1].kwargs["query"] == "is:unread"

    def test_is_unread_case_insensitive(self):
        with patch.object(gmail_tools, "_count_messages", return_value=1) as count:
            _unread_count_query_mode("u1", "IS:UNREAD", [], include_spam_trash=False)
        assert count.call_args_list[1].kwargs["query"] == "IS:UNREAD"

    def test_no_label_id_for_multiple_labels(self):
        with patch.object(gmail_tools, "_count_messages", return_value=1):
            result = _unread_count_query_mode(
                "u1", "q", ["A", "B"], include_spam_trash=False
            )
        assert "label_id" not in result
        assert result["label_ids"] == ["A", "B"]


class TestUnreadCountLabelMode:
    def test_empty_labels(self):
        with patch.object(gmail_tools, "_label_stats") as stats:
            result = _unread_count_label_mode("u1", [])
        stats.assert_not_called()
        assert result == {
            "counts": {},
            "label_ids": [],
            "unreadCount": 0,
            "totalCount": 0,
        }

    def test_single_label_flattened(self):
        with patch.object(
            gmail_tools,
            "_label_stats",
            return_value={
                "label_id": "INBOX",
                "label_name": "Inbox",
                "unreadCount": 7,
                "totalCount": 100,
            },
        ) as stats:
            result = _unread_count_label_mode("u1", ["INBOX"])
        stats.assert_called_once_with("u1", "INBOX")
        assert result == {
            "counts": {
                "INBOX": {
                    "label_id": "INBOX",
                    "label_name": "Inbox",
                    "unreadCount": 7,
                    "totalCount": 100,
                }
            },
            "label_ids": ["INBOX"],
            "label_id": "INBOX",
            "label_name": "Inbox",
            "unreadCount": 7,
            "totalCount": 100,
        }

    def test_multiple_labels_grouped_only(self):
        with patch.object(gmail_tools, "_label_stats", return_value={}) as stats:
            result = _unread_count_label_mode("u1", ["A", "B"])
        assert stats.call_count == 2
        assert [c.args[1] for c in stats.call_args_list] == ["A", "B"]
        assert result == {"counts": {"A": {}, "B": {}}, "label_ids": ["A", "B"]}
        assert "label_id" not in result
        assert "unreadCount" not in result


class TestFetchMessagesForContacts:
    def test_metadata_request_shape(self, mock_proxy):
        mock_proxy.side_effect = [{"id": "m1"}, {"id": "m2"}]
        messages, failures = _fetch_messages_for_contacts("u1", ["m1", "m2"])
        assert messages == [{"id": "m1"}, {"id": "m2"}]
        assert failures == 0
        endpoints = [c.kwargs["endpoint"] for c in mock_proxy.call_args_list]
        assert endpoints == [
            f"{GMAIL_API_BASE}/users/me/messages/m1",
            f"{GMAIL_API_BASE}/users/me/messages/m2",
        ]
        for call in mock_proxy.call_args_list:
            assert call.kwargs["method"] == "GET"
            assert call.kwargs["query"] == {
                "format": GMAIL_FORMAT_METADATA,
                "metadataHeaders": ["From", "To", "Cc", "Reply-To"],
            }

    def test_non_dict_skipped_without_failure(self, mock_proxy):
        mock_proxy.side_effect = [["junk"], {"id": "m2"}]
        messages, failures = _fetch_messages_for_contacts("u1", ["m1", "m2"])
        assert messages == [{"id": "m2"}]
        assert failures == 0

    def test_exception_counts_as_failure(self, mock_proxy):
        mock_proxy.side_effect = [RuntimeError("boom"), {"id": "m2"}, RuntimeError("again")]
        with patch.object(gmail_tools.log, "warning") as warn:
            messages, failures = _fetch_messages_for_contacts("u1", ["m1", "m2", "m3"])
        assert messages == [{"id": "m2"}]
        assert failures == 2
        assert warn.call_count == 2
        for call, message_id in zip(warn.call_args_list, ["m1", "m3"]):
            assert call.args[0] == f"{LogTag.COMPOSIO} Gmail message fetch failed for"
            assert call.kwargs["message_id"] == message_id
            assert call.kwargs["error"] in ("boom", "again")
            assert call.kwargs["error_type"] == "RuntimeError"
            assert call.kwargs["user_id"] == "u1"

    def test_empty_ids(self, mock_proxy):
        messages, failures = _fetch_messages_for_contacts("u1", [])
        assert (messages, failures) == ([], 0)
        mock_proxy.assert_not_called()


# ---------------------------------------------------------------------------
# Tool-level edge cases
# ---------------------------------------------------------------------------


class TestGetUnreadCountEdges:
    def test_empty_label_ids_filtered(self, mock_proxy):
        tools = _register_and_get_tools()
        mock_proxy.return_value = {"messagesUnread": 1, "messagesTotal": 2}
        result = tools["GET_UNREAD_COUNT"](
            request=GetUnreadCountInput(label_ids=["INBOX", ""]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["label_id"] == "INBOX"
        assert mock_proxy.call_count == 1
        assert mock_proxy.call_args.kwargs["user_id"] == "user_test_123"
        assert mock_proxy.call_args.kwargs["endpoint"].endswith("/labels/INBOX")

    def test_empty_label_list_defaults_to_inbox(self, mock_proxy):
        tools = _register_and_get_tools()
        mock_proxy.return_value = {"messagesUnread": 5, "messagesTotal": 9}
        result = tools["GET_UNREAD_COUNT"](
            request=GetUnreadCountInput(label_ids=[]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["label_id"] == "INBOX"

    def test_query_with_label_ids_uses_query_mode(self, mock_proxy):
        tools = _register_and_get_tools()
        mock_proxy.side_effect = [{"resultSizeEstimate": 7}, {"resultSizeEstimate": 3}]
        result = tools["GET_UNREAD_COUNT"](
            request=GetUnreadCountInput(label_ids=["INBOX"], query="from:x"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result["totalCount"] == 7
        assert result["unreadCount"] == 3
        calls = mock_proxy.call_args_list
        assert calls[0].kwargs["query"]["q"] == "from:x"
        assert calls[0].kwargs["query"]["labelIds"] == ["INBOX"]
        assert calls[1].kwargs["query"]["q"] == "from:x is:unread"

    def test_whitespace_query_stripped_and_not_doubled(self, mock_proxy):
        tools = _register_and_get_tools()
        mock_proxy.side_effect = [{"resultSizeEstimate": 7}, {"resultSizeEstimate": 3}]
        tools["GET_UNREAD_COUNT"](
            request=GetUnreadCountInput(query="  is:unread  "),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        calls = mock_proxy.call_args_list
        assert calls[0].kwargs["query"]["q"] == "is:unread"
        assert calls[1].kwargs["query"]["q"] == "is:unread"


class TestGetContactListEdges:
    def test_all_fetches_failed(self, mock_proxy):
        tools = _register_and_get_tools()

        def side_effect(*args, **kwargs):
            if re.match(r".+/users/me/messages/?$", kwargs.get("endpoint", "")):
                return {"messages": [{"id": "m1"}, {"id": "m2"}]}
            raise RuntimeError("Gmail 500")

        mock_proxy.side_effect = side_effect
        with patch.object(gmail_tools.log, "error") as log_err:
            result = tools["GET_CONTACT_LIST"](
                request=GetContactListInput(query="boss"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result == {
            "success": False,
            "error": "Failed to fetch any of the 2 matched messages; cannot extract contacts",
            "contacts": [],
            "count": 0,
        }
        log_err.assert_called_once_with(
            f"{LogTag.COMPOSIO} Gmail contact list: all message fetches failed for user",
            message_ids_count=2,
            user_id="user_test_123",
        )

    def test_partial_fetch_failure_logs_failures(self, mock_proxy):
        tools = _register_and_get_tools()

        def side_effect(*args, **kwargs):
            endpoint = kwargs.get("endpoint", "")
            if re.match(r".+/users/me/messages/?$", endpoint):
                return {"messages": [{"id": "m1"}, {"id": "m2"}]}
            if endpoint.endswith("/messages/m1"):
                raise RuntimeError("Gmail 500")
            return {"id": "m2"}

        mock_proxy.side_effect = side_effect
        with patch.object(gmail_tools.log, "set") as log_set:
            result = tools["GET_CONTACT_LIST"](
                request=GetContactListInput(query="boss"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        assert result["success"] is True
        log_set.assert_called_once_with(gmail_contact_fetch_failures=1)

    def test_empty_inbox_returns_empty_index(self, mock_proxy):
        tools = _register_and_get_tools()
        result = tools["GET_CONTACT_LIST"](
            request=GetContactListInput(query="boss"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result == {"success": True, "contacts": [], "count": 0}
        assert mock_proxy.call_count == 1

    def test_query_filters_non_matching_contacts(self, mock_proxy):
        tools = _register_and_get_tools()
        mock_proxy.side_effect = [
            {"messages": [{"id": "m1"}]},
            {
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Alice <alice@x.com>"},
                    ]
                }
            },
        ]
        result = tools["GET_CONTACT_LIST"](
            request=GetContactListInput(query="boss"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result == {"success": True, "contacts": [], "count": 0}


class TestGatherContextExact:
    def test_exact_result_shape_and_requests(self, mock_proxy):
        tools = _register_and_get_tools()
        mock_proxy.side_effect = [
            {"emailAddress": "u@x.com", "messagesTotal": 1000, "threadsTotal": 500},
            {"messagesUnread": 3, "messagesTotal": 100},
            {"messages": [{"id": "m1"}, {"id": None}, {"id": "m3"}]},
        ]
        result = tools["CUSTOM_GATHER_CONTEXT"](
            request=GatherContextInput(),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result == {
            "user": {"email": "u@x.com", "messages_total": 1000, "threads_total": 500},
            "inbox": {"unread_count": 3, "message_count": 100},
            "recent_message_ids": ["m1", "m3"],
        }
        endpoints = [c.kwargs["endpoint"] for c in mock_proxy.call_args_list]
        assert endpoints == [
            f"{GMAIL_API_BASE}/users/me/profile",
            f"{GMAIL_API_BASE}/users/me/labels/INBOX",
            f"{GMAIL_API_BASE}/users/me/messages",
        ]
        assert all(c.kwargs["user_id"] == "user_test_123" for c in mock_proxy.call_args_list)
        assert mock_proxy.call_args_list[2].kwargs["query"] == {
            "labelIds": "INBOX",
            "maxResults": 5,
        }

    def test_since_builds_after_query(self, mock_proxy):
        tools = _register_and_get_tools()
        mock_proxy.side_effect = [{}, {}, {"messages": [{"id": "m1"}]}]
        tools["CUSTOM_GATHER_CONTEXT"](
            request=GatherContextInput(since="2026-06-19T00:00:00Z"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        query = mock_proxy.call_args_list[2].kwargs["query"]
        expected_ts = int(
            datetime.datetime.fromisoformat("2026-06-19T00:00:00Z").timestamp()
        )
        assert query["q"] == f"after:{expected_ts}"


class TestFetchThreadTool:
    def test_forwards_user_id_and_thread_endpoint(self, mock_proxy):
        tools = _register_and_get_tools()
        mock_proxy.return_value = {
            "messages": [
                {
                    "id": "m1",
                    "threadId": "t1",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "headers": [{"name": "From", "value": "a@b.com"}],
                        "body": {"data": ""},
                    },
                }
            ]
        }
        result = tools["FETCH_THREAD"](
            request=FetchThreadInput(thread_ids=["t1"], fields=["id"], body_processing="none"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert mock_proxy.call_args.kwargs["user_id"] == "user_test_123"
        assert mock_proxy.call_args.kwargs["endpoint"].endswith("/users/me/threads/t1")
        assert result["fetched_threads"] == 1
        assert result["total_messages"] == 1
