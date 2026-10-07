"""Unit tests for Gmail custom tools (post-Composio-proxy migration).

Each tool routes provider API calls through proxy_request_sync instead of
raw httpx. Tests patch that helper and assert on the request shape.
"""

import base64
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any
from unittest.mock import MagicMock, patch

from pydantic import BaseModel
import pytest
import time_machine

from app.agents.prompts import todo_prompts
from app.agents.tools.coding.query_json_tool import _apply_query
from app.constants.offload import OFFLOAD_RESULT_KEY
from app.models.common_models import GatherContextInput
from app.models.composio_schemas.gmail import (
    BodyProcessingLiteral,
    FetchMessagesInput,
    FetchThreadInput,
)
from app.services.composio.custom_tools.gmail_constants import OFFLOAD_MIN_MESSAGES
from app.services.composio.custom_tools.gmail_tools import (
    ArchiveEmailInput,
    GetContactListInput,
    GetUnreadCountInput,
    MarkAsReadInput,
    MarkAsUnreadInput,
    StarEmailInput,
    _format_partial_result,
    _resolve_timeframe,
    _timeframe_clause,
    register_gmail_custom_tools,
)
from app.services.composio.proxy_client import ProxyRequest
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
        request = mock_proxy.call_args.args[0]
        assert request.toolkit == "GMAIL"
        assert request.method == "POST"
        assert request.endpoint.endswith("/users/me/messages/batchModify")
        assert request.body == {
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
        assert mock_proxy.call_args.args[0].body == {
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
        assert mock_proxy.call_args.args[0].body == {
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
        assert mock_proxy.call_args.args[0].body["addLabelIds"] == ["STARRED"]

    def test_unstar_removes_starred_label(self, mock_proxy):
        tools = _register_and_get_tools()
        result = tools["STAR_EMAIL"](
            request=StarEmailInput(message_ids=["m1"], unstar=True),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert result == {"action": "unstarred", "modified_count": 1, "failed_count": 0}
        assert mock_proxy.call_args.args[0].body["removeLabelIds"] == ["STARRED"]


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

    def test_query_mode_sends_two_one_result_list_calls_through_the_users_proxy(self, mock_proxy):
        tools = _register_and_get_tools()
        mock_proxy.side_effect = [{"resultSizeEstimate": 50}, {"resultSizeEstimate": 12}]
        tools["GET_UNREAD_COUNT"](
            request=GetUnreadCountInput(query="from:boss"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        assert [call.args[0] for call in mock_proxy.call_args_list] == [
            ProxyRequest(
                user_id="user_test_123",
                toolkit="GMAIL",
                endpoint="https://gmail.googleapis.com/gmail/v1/users/me/messages",
                method="GET",
                body=None,
                query={"maxResults": 1, "includeSpamTrash": "false", "q": "from:boss"},
            ),
            ProxyRequest(
                user_id="user_test_123",
                toolkit="GMAIL",
                endpoint="https://gmail.googleapis.com/gmail/v1/users/me/messages",
                method="GET",
                body=None,
                query={"maxResults": 1, "includeSpamTrash": "false", "q": "from:boss is:unread"},
            ),
        ]


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

        def side_effect(request: ProxyRequest):
            endpoint = request.endpoint
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

        def side_effect(request: ProxyRequest):
            endpoint = request.endpoint
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
        # State machine: list page 1 OK -> list page 2 RAISE (m1, m2 in between).
        # A counter + raise, since returning the exception as a value would not
        # trigger the tool's error path.
        list_call_count = [0]

        def side_effect(request: ProxyRequest):
            endpoint = request.endpoint
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

        def side_effect(request: ProxyRequest):
            endpoint = request.endpoint
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

        def side_effect(request: ProxyRequest):
            endpoint = request.endpoint
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
                "app.services.composio.custom_tools.gmail_tools.current_run_config",
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

        def side_effect(request: ProxyRequest):
            endpoint = request.endpoint
            # List call: exactly /users/me/messages (no id segment after).
            if re.match(r".+/users/me/messages/?$", endpoint):
                return next(list_iter)
            return next(message_iter)

        mock_proxy.side_effect = side_effect

        with patch(
            "app.services.composio.custom_tools.gmail_tools.current_run_config",
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


class TestPartialFetchResult:
    """A fetch that dies mid-loop still returns the pages it got — what the model is told about the failure decides whether the user gets an answer or a promise that can never arrive."""

    def test_the_partial_shape_reports_what_was_and_was_not_retrieved(self) -> None:
        result = _format_partial_result([{"id": "m1"}, {"id": "m2"}], reason="429 rate limited")

        assert result["fetched_count"] == 2
        assert result["truncated"] is True
        assert result["partial"] is True
        assert result["error"] == "429 rate limited"
        assert result["messages"] == [{"id": "m1"}, {"id": "m2"}]

    def test_an_empty_partial_still_reports_zero_rather_than_omitting_the_count(self) -> None:
        result = _format_partial_result([], reason="timeout")

        assert result["fetched_count"] == 0
        assert result["messages"] == []

    def test_the_note_tells_the_model_the_only_honest_moves(self) -> None:
        """Pinned verbatim: stops a weak model answering "still fetching" on a turn that is already over."""
        note = _format_partial_result([], reason="429")["note"]

        assert note == (
            "This fetch FAILED partway; the messages above are all that could be "
            "retrieved. Retrying the same call will hit the same error. Do NOT "
            "tell the user you are still fetching or that more results are "
            "coming. Either narrow the query (shorter date range, a filter) and "
            "call again NOW, or answer with what you have and state plainly that "
            "the rest failed and why."
        )


FETCH_STARTED = datetime(2026, 10, 1, 17, 24, 5, tzinfo=UTC)


def _gmail_taking_a_minute_per_call(
    traveller: time_machine.Traveller, *, body: str = "", fail_second_page: bool = False
) -> Callable[[ProxyRequest], dict[str, Any]]:
    """Serve one list page of three messages, moving the clock a minute on every call."""
    list_calls = [0]
    message = {
        "id": "m",
        "threadId": "t",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [{"name": "From", "value": "a@b.com"}],
            "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
        },
    }

    def serve(request: ProxyRequest) -> dict[str, Any]:
        traveller.shift(timedelta(minutes=1))
        if not re.match(r".+/users/me/messages/?$", request.endpoint):
            return message
        list_calls[0] += 1
        if list_calls[0] > 1:
            raise RuntimeError("Gmail 503")
        page: dict[str, Any] = {"messages": [{"id": f"m{i}"} for i in range(3)]}
        if fail_second_page:
            page["nextPageToken"] = "t1"
        return page

    return serve


class TestFetchedAt:
    """The Inbox desk's cursor: every result says when its query ran, before Gmail was asked."""

    def _fetch(self, request: FetchMessagesInput) -> dict[str, Any]:
        return _register_and_get_tools()["FETCH_MESSAGES"](
            request=request, execute_request=MagicMock(), auth_credentials=AUTH_CREDS
        )

    @pytest.mark.regression
    def test_an_inline_result_carries_the_moment_before_the_query(
        self, mock_proxy: MagicMock
    ) -> None:
        with time_machine.travel(FETCH_STARTED, tick=False) as traveller:
            mock_proxy.side_effect = _gmail_taking_a_minute_per_call(traveller)
            result = self._fetch(FetchMessagesInput(query="newer_than:1d", per_page=10))

        assert result["fetched_count"] == 3
        assert result["fetched_at"] == int(FETCH_STARTED.timestamp())

    @pytest.mark.regression
    def test_an_offloaded_result_carries_it_beside_its_read_plan(
        self, mock_proxy: MagicMock, tmp_path: Path
    ) -> None:
        with (
            time_machine.travel(FETCH_STARTED, tick=False) as traveller,
            patch(
                "app.services.composio.custom_tools.gmail_tools.write_session_file_sync",
                return_value=(tmp_path / "f.jsonl", "/workspace/sessions/run/f.jsonl"),
            ),
            patch(
                "app.services.composio.custom_tools.gmail_tools.current_run_config",
                return_value={"configurable": {"vfs_session_id": "run"}},
            ),
        ):
            mock_proxy.side_effect = _gmail_taking_a_minute_per_call(traveller, body="x" * 50_000)
            result = self._fetch(
                FetchMessagesInput(
                    query="newer_than:1d",
                    per_page=10,
                    fields=[*FetchMessagesInput.model_fields["fields"].default_factory(), "body"],
                    body_processing="raw",
                )
            )

        assert result["offloaded_to"] == "/workspace/sessions/run/f.jsonl"
        assert "read_plan" in result
        assert result["fetched_at"] == int(FETCH_STARTED.timestamp())
        assert isinstance(result["file_size_bytes"], int) and result["file_size_bytes"] > 0
        assert result["field_count"] >= len(result["inline_preview"][0]) > 0
        assert result["read_plan"]["total_lines"] == result["total_messages"]
        assert result["read_plan"]["recommended_subagents"] == 3

    @pytest.mark.regression
    def test_a_partial_result_carries_it_too(self, mock_proxy: MagicMock) -> None:
        with time_machine.travel(FETCH_STARTED, tick=False) as traveller:
            mock_proxy.side_effect = _gmail_taking_a_minute_per_call(
                traveller, fail_second_page=True
            )
            result = self._fetch(FetchMessagesInput(query="newer_than:1d", per_page=3))

        assert result["partial"] is True
        assert result["fetched_at"] == int(FETCH_STARTED.timestamp())


class TestTheDesksSweep:
    """The Inbox desk's whole-window sweep: headers only, always to a file, counted per address."""

    @staticmethod
    def _sweep(
        mock_proxy: MagicMock,
        tmp_path: Path,
        senders: list[str],
        size: int,
        body_processing: BodyProcessingLiteral = "none",
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
        formats: list[str] = []

        def gmail(request: ProxyRequest) -> dict[str, Any]:
            if re.match(r".+/users/me/messages/?$", request.endpoint):
                refs = [{"id": f"m{i}"} for i in range(size)]
                return {"messages": refs, "resultSizeEstimate": size}
            formats.append(request.query["format"])
            n = int(request.endpoint.rsplit("/m", 1)[1])
            headers = [
                {"name": "From", "value": senders[n % len(senders)]},
                {"name": "Subject", "value": f"[repo] PR #{n}"},
            ]
            body = {"data": base64.urlsafe_b64encode(b"never read").decode()}
            return {
                "id": f"m{n}",
                "threadId": f"t{n}",
                "payload": {"headers": headers, "body": body},
            }

        mock_proxy.side_effect = gmail
        with (
            patch(
                "app.services.composio.custom_tools.gmail_tools.write_session_file_sync",
                return_value=(tmp_path / "f.jsonl", "/workspace/sessions/run/f.jsonl"),
            ) as write,
            patch(
                "app.services.composio.custom_tools.gmail_tools.current_run_config",
                return_value={"configurable": {"vfs_session_id": "run"}},
            ),
        ):
            result = _register_and_get_tools()["FETCH_MESSAGES"](
                request=FetchMessagesInput(
                    query="after:1790000000",
                    max_messages=1000,
                    fields=list(todo_prompts.INBOX_DESK_SWEEP_FIELDS),
                    body_processing=body_processing,
                    offload=True,
                ),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        records = [json.loads(line) for line in write.call_args.kwargs["content"].splitlines()]
        return result, records, formats

    def test_a_window_past_the_offload_size_is_fetched_as_metadata_and_written_bodiless(
        self, mock_proxy: MagicMock, tmp_path: Path
    ) -> None:
        size = OFFLOAD_MIN_MESSAGES + 10
        senders = ["Ann <notifications@github.com>", "Bob <notifications@github.com>"]

        result, records, formats = self._sweep(mock_proxy, tmp_path, senders, size)

        assert result["offloaded_to"] == "/workspace/sessions/run/f.jsonl"
        assert result["total_messages"] == size
        assert formats == ["metadata"] * size
        assert [r["from"] for r in records] == [senders[n % 2] for n in range(size)]
        assert all("body" not in r for r in records)

    @pytest.mark.regression
    def test_a_window_under_the_offload_size_still_never_reaches_the_conversation(
        self, mock_proxy: MagicMock, tmp_path: Path
    ) -> None:
        result, records, _ = self._sweep(mock_proxy, tmp_path, ["a@example.com"], 3)

        assert result["offloaded_to"] == "/workspace/sessions/run/f.jsonl"
        assert "messages" not in result
        assert len(records) == result["total_messages"] == 3

    @pytest.mark.parametrize(
        ("size", "estimate", "expected_format"),
        [
            (3, None, "metadata"),
            (OFFLOAD_MIN_MESSAGES, OFFLOAD_MIN_MESSAGES, "metadata"),
            (OFFLOAD_MIN_MESSAGES + 1, OFFLOAD_MIN_MESSAGES + 1, "full"),
        ],
    )
    def test_the_estimate_decides_the_fetch_format_at_the_boundary(
        self, mock_proxy: MagicMock, size: int, estimate: int | None, expected_format: str
    ) -> None:
        """At the estimate the scan stays metadata; one over it fetches bodies."""
        formats: list[str] = []

        def gmail(request: ProxyRequest) -> dict[str, Any]:
            if re.match(r".+/users/me/messages/?$", request.endpoint):
                refs = [{"id": f"m{i}"} for i in range(size)]
                page: dict[str, Any] = {"messages": refs}
                if estimate is not None:
                    page["resultSizeEstimate"] = estimate
                return page
            formats.append(request.query["format"])
            n = int(request.endpoint.rsplit("/m", 1)[1])
            return {
                "id": f"m{n}",
                "threadId": f"t{n}",
                "payload": {
                    "headers": [{"name": "From", "value": "a@example.com"}],
                    "body": {"data": base64.urlsafe_b64encode(b"x").decode()},
                },
            }

        mock_proxy.side_effect = gmail
        _register_and_get_tools()["FETCH_MESSAGES"](
            request=FetchMessagesInput(query="after:1790000000", per_page=100),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert formats
        assert set(formats) == {expected_format}

    def test_a_requested_file_carries_the_bodies_unless_none_were_asked_for(
        self, mock_proxy: MagicMock, tmp_path: Path
    ) -> None:
        _, records, formats = self._sweep(
            mock_proxy, tmp_path, ["a@example.com"], 3, body_processing="normalize"
        )

        assert formats == ["full"] * 3
        assert [r["body"] for r in records] == ["never read"] * 3

    @pytest.mark.regression
    def test_a_sender_counts_once_per_address_whatever_its_display_name(
        self, mock_proxy: MagicMock, tmp_path: Path
    ) -> None:
        senders = [
            "Ann <notifications@github.com>",
            '"GitHub" <Notifications@GitHub.com>',
            "notifications@github.com",
            "Bob Lee <bob@example.com>",
        ]

        _, records, _ = self._sweep(mock_proxy, tmp_path, senders, 8)

        counts = _apply_query(
            records,
            where=[],
            match="all",
            fields=None,
            sort_by=None,
            order="desc",
            limit=50,
            count_only=False,
            unique_by=None,
            group_count_by="from_address",
        )
        assert counts == [
            {"value": "notifications@github.com", "count": 6},
            {"value": "bob@example.com", "count": 2},
        ]

    def test_an_oversized_result_with_no_session_is_cut_with_a_hint(
        self, mock_proxy: MagicMock
    ) -> None:
        """Over the char limit with nowhere to offload: capped inline plus a too-large hint."""
        big_body = "x" * 30_000
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

        def side_effect(request: ProxyRequest):
            if re.match(r".+/users/me/messages/?$", request.endpoint):
                return next(list_iter)
            return next(message_iter)

        mock_proxy.side_effect = side_effect
        with patch(
            "app.services.composio.custom_tools.gmail_tools.current_run_config",
            return_value={"configurable": {}},
        ):
            fields_with_body = list(FetchMessagesInput.model_fields["fields"].default_factory()) + [
                "body"
            ]
            result = _register_and_get_tools()["FETCH_MESSAGES"](
                request=FetchMessagesInput(
                    timeframe="today",
                    per_page=10,
                    fields=fields_with_body,
                    body_processing="raw",
                ),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        assert "offloaded_to" not in result
        assert result["total_matched"] == 5
        assert "too large to return inline" in result["hint"]

    def test_an_oversized_thread_with_no_session_is_cut_with_a_hint(
        self, mock_proxy: MagicMock
    ) -> None:
        """Same sized-payload contract on the thread path: the char limit decides."""
        big_body = base64.urlsafe_b64encode(b"y" * 30_000).decode()
        mock_proxy.side_effect = lambda request: {
            "id": "thread-1",
            "messages": [
                {
                    "id": f"m{i}",
                    "threadId": "thread-1",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "headers": [{"name": "From", "value": "a@b.com"}],
                        "body": {"data": big_body},
                    },
                }
                for i in range(5)
            ],
        }
        with patch(
            "app.services.composio.custom_tools.gmail_tools.current_run_config",
            return_value={"configurable": {}},
        ):
            fields_with_body = list(FetchThreadInput.model_fields["fields"].default_factory()) + [
                "body"
            ]
            result = _register_and_get_tools()["FETCH_THREAD"](
                request=FetchThreadInput(
                    thread_ids=["thread-1"], fields=fields_with_body, body_processing="raw"
                ),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        assert "offloaded_to" not in result
        assert "too large to return inline" in result["hint"]

    def test_an_empty_window_offloads_with_zero_fields(
        self, mock_proxy: MagicMock, tmp_path: Path
    ) -> None:
        """No messages means no fields: an empty offload still reports its shape."""
        mock_proxy.side_effect = lambda request: {"messages": []}
        with (
            patch(
                "app.services.composio.custom_tools.gmail_tools.write_session_file_sync",
                return_value=(tmp_path / "f.jsonl", "/workspace/sessions/run/f.jsonl"),
            ),
            patch(
                "app.services.composio.custom_tools.gmail_tools.current_run_config",
                return_value={"configurable": {"vfs_session_id": "run"}},
            ),
        ):
            result = _register_and_get_tools()["FETCH_MESSAGES"](
                request=FetchMessagesInput(query="after:1790000000", offload=True),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        assert result["offloaded_to"] == "/workspace/sessions/run/f.jsonl"
        assert result["field_count"] == 0

    def test_a_requested_file_with_no_session_to_hold_it_fails_the_call(
        self, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.return_value = {"messages": [], "resultSizeEstimate": 0}
        with (
            patch(
                "app.services.composio.custom_tools.gmail_tools.current_run_config",
                return_value={"configurable": {}},
            ),
            pytest.raises(AppError, match="no session") as refused,
        ):
            _register_and_get_tools()["FETCH_MESSAGES"](
                request=FetchMessagesInput(query="after:1790000000", offload=True),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        # The refusal is the agent's only account of why nothing came back, so it names
        # the tool that refused, says the file had nowhere to go, and says what to do.
        assert refused.value.message == (
            "GMAIL_FETCH_MESSAGES has no session to write the requested file into"
        )
        assert refused.value.why == (
            "offload was requested outside a conversation, so there is no workspace for it."
        )
        assert "without offload" in refused.value.fix
        assert refused.value.status_code == 400


# ---------------------------------------------------------------------------
# Whose mailbox, and what was asked of it
# ---------------------------------------------------------------------------


def _one_message_mailbox(
    *, sender: str = "Alice <alice@example.com>", subject: str = "Lease renewal"
) -> Callable[[ProxyRequest], dict[str, Any]]:
    """Serve a list page of one message and that same message in full."""
    full = {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["INBOX"],
        "snippet": "the snippet",
        "internalDate": "1767225845000",
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "To", "value": "Bob <bob@example.com>"},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Tue, 02 Jan 2025 09:30:00 +0000"},
            ],
            "body": {"data": base64.urlsafe_b64encode(b"The lease needs signing.").decode()},
        },
    }

    def serve(request: ProxyRequest) -> dict[str, Any]:
        if re.match(r".+/users/me/messages/?$", request.endpoint):
            return {"messages": [{"id": "msg-1", "threadId": "thread-1"}], "resultSizeEstimate": 1}
        return full

    return serve


def threads_formats(proxy: MagicMock) -> list[dict[str, Any]]:
    """Return the query of every users/me/threads call the proxy was asked to make."""
    return [
        dict(call.args[0].query or {})
        for call in proxy.call_args_list
        if "/users/me/threads/" in call.args[0].endpoint
    ]


def _users_asked(proxy: MagicMock) -> set[str | None]:
    """Return the authenticated user every proxy call in this test was made for."""
    return {call.args[0].user_id for call in proxy.call_args_list}


class TestEveryToolActsAsTheAuthenticatedUser:
    """Each tool reads the user off its credentials and hands it to the proxy.

    A tool that passed anything else would read or write the wrong mailbox, and nothing
    downstream re-checks it: the proxy is called with whatever it is given.
    """

    @pytest.mark.parametrize(
        ("tool", "tool_request", "responses"),
        [
            ("MARK_AS_READ", MarkAsReadInput(message_ids=["m1"]), [{"id": "m1"}]),
            ("MARK_AS_UNREAD", MarkAsUnreadInput(message_ids=["m1"]), [{"id": "m1"}]),
            ("ARCHIVE_EMAIL", ArchiveEmailInput(message_ids=["m1"]), [{"id": "m1"}]),
            ("STAR_EMAIL", StarEmailInput(message_ids=["m1"]), [{"id": "m1"}]),
            (
                "GET_UNREAD_COUNT",
                GetUnreadCountInput(),
                [{"name": "INBOX", "messagesUnread": 1, "messagesTotal": 2}],
            ),
            ("GET_CONTACT_LIST", GetContactListInput(query="boss"), [{"messages": []}, {}]),
            (
                "CUSTOM_GATHER_CONTEXT",
                GatherContextInput(),
                [
                    {"emailAddress": "u@x.com", "messagesTotal": 1, "threadsTotal": 1},
                    {"messagesUnread": 0, "messagesTotal": 0},
                    {"messages": []},
                ],
            ),
            (
                "FETCH_MESSAGES",
                FetchMessagesInput(query="after:1790000000", per_page=5),
                None,
            ),
            ("FETCH_THREAD", FetchThreadInput(thread_ids=["thread-1"]), None),
        ],
        ids=[
            "mark-as-read",
            "mark-as-unread",
            "archive",
            "star",
            "unread-count",
            "contact-list",
            "gather-context",
            "fetch-messages",
            "fetch-thread",
        ],
    )
    def test_the_proxy_is_only_ever_called_for_the_caller(
        self,
        mock_proxy: MagicMock,
        tool: str,
        tool_request: BaseModel,
        responses: list[dict[str, object]] | None,
    ) -> None:
        mock_proxy.side_effect = responses if responses is not None else _one_message_mailbox()

        _register_and_get_tools()[tool](
            request=tool_request, execute_request=MagicMock(), auth_credentials=AUTH_CREDS
        )

        assert _users_asked(mock_proxy) == {"user_test_123"}

    def test_credentials_without_a_user_are_refused_before_any_mailbox_call(
        self, mock_proxy: MagicMock
    ) -> None:
        """No user_id means no mailbox to act on, and an empty string is not a mailbox."""
        with pytest.raises(ValueError, match="user_id"):
            _register_and_get_tools()["MARK_AS_READ"](
                request=MarkAsReadInput(message_ids=["m1"]),
                execute_request=MagicMock(),
                auth_credentials={},
            )

        mock_proxy.assert_not_called()


class TestWhatEachToolAsksGmailFor:
    """The query each tool builds, as Gmail receives it.

    Gmail matches its parameter names exactly, so a re-cased or mis-spelled one is
    ignored and the filter the run asked for silently widens to the whole mailbox — an
    unread-inbox filter that matches nothing reads to the desk as "you have no mail".
    """

    def test_the_contact_search_sends_the_query_and_the_page_size(
        self, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [{"messages": [{"id": "m1"}]}, {}]

        _register_and_get_tools()["GET_CONTACT_LIST"](
            request=GetContactListInput(query="from:boss@example.com", max_results=42),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        search = mock_proxy.call_args_list[0].args[0]
        assert search.query == {"q": "from:boss@example.com", "maxResults": 42}
        assert search.endpoint.endswith("/users/me/messages")

    def test_the_recent_inbox_ids_ask_the_inbox_for_a_bounded_page(
        self, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = [
            {"emailAddress": "u@x.com", "messagesTotal": 1, "threadsTotal": 1},
            {"messagesUnread": 0, "messagesTotal": 0},
            {"messages": [{"id": "m1"}]},
        ]

        _register_and_get_tools()["CUSTOM_GATHER_CONTEXT"](
            request=GatherContextInput(), execute_request=MagicMock(), auth_credentials=AUTH_CREDS
        )

        recent = mock_proxy.call_args_list[2].args[0]
        assert recent.query == {"labelIds": "INBOX", "maxResults": 5}


class TestTheInlineEmailCard:
    """The card the chat renders beside an inline result, row by row."""

    def test_each_row_carries_its_own_field_under_the_key_the_card_reads(
        self, mock_proxy: MagicMock
    ) -> None:
        """Every key holds that message's own value, and no others."""
        writer = MagicMock()
        mock_proxy.side_effect = _one_message_mailbox()

        with (
            patch(
                "app.services.composio.custom_tools.gmail_tools.get_stream_writer",
                return_value=writer,
            ),
            patch(
                "app.services.composio.custom_tools.gmail_tools.current_run_config",
                return_value={"configurable": {}},
            ),
        ):
            _register_and_get_tools()["FETCH_MESSAGES"](
                request=FetchMessagesInput(query="after:1790000000", per_page=5),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        payload = writer.call_args.args[0]
        assert payload["resultSize"] == 1
        (row,) = payload["email_fetch_data"]
        assert set(row) == {"from", "subject", "time", "thread_id", "id"}
        assert row["from"] == "Alice <alice@example.com>"
        assert row["subject"] == "Lease renewal"
        assert row["thread_id"] == "thread-1"
        assert row["id"] == "msg-1"
        assert row["time"]


class TestTheOffloadedFile:
    """The JSONL the agent queries instead of holding the mail in context."""

    def test_the_file_is_one_full_view_per_line_written_for_this_run(
        self, mock_proxy: MagicMock, tmp_path: Path
    ) -> None:
        """Every field is in the file, whatever the caller projected."""
        written: dict[str, str] = {}

        def _write(
            *, user_id: str, conversation_id: str, relative_path: str, content: str
        ) -> tuple[Path, str]:
            written.update(user_id=user_id, conversation_id=conversation_id, content=content)
            return tmp_path / "f.jsonl", "/workspace/sessions/run/f.jsonl"

        mock_proxy.side_effect = _one_message_mailbox()

        with (
            patch(
                "app.services.composio.custom_tools.gmail_tools.write_session_file_sync",
                side_effect=_write,
            ),
            patch(
                "app.services.composio.custom_tools.gmail_tools.current_run_config",
                return_value={"configurable": {"vfs_session_id": "run"}},
            ),
        ):
            result = _register_and_get_tools()["FETCH_MESSAGES"](
                request=FetchMessagesInput(
                    query="after:1790000000",
                    offload=True,
                    fields=["id", "from"],
                ),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        assert written["user_id"] == "user_test_123"
        assert written["conversation_id"] == "run"
        assert result["offloaded_to"] == "/workspace/sessions/run/f.jsonl"
        assert result[OFFLOAD_RESULT_KEY]["bytes"] == len(written["content"].encode("utf-8"))
        assert result[OFFLOAD_RESULT_KEY]["path"] == "/workspace/sessions/run/f.jsonl"
        assert result[OFFLOAD_RESULT_KEY]["fmt"] == "jsonl"
        (line,) = written["content"].splitlines()
        assert json.loads(line)["id"] == "msg-1"
        assert "body" in json.loads(line)
        assert "The lease needs signing." in json.loads(line)["body"]


class TestTheFetchQueryAndItsCursor:
    def test_the_list_call_carries_the_combined_query_and_the_page_size(
        self, mock_proxy: MagicMock
    ) -> None:
        """Gmail's own parameter names, spelled as Gmail spells them."""
        seen: list[dict[str, Any]] = []
        mailbox = _one_message_mailbox()

        def _serve(request: ProxyRequest) -> dict[str, Any]:
            seen.append(dict(request.query or {}))
            return mailbox(request)

        mock_proxy.side_effect = _serve

        _register_and_get_tools()["FETCH_MESSAGES"](
            request=FetchMessagesInput(query="newer_than:1d", per_page=7),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert seen[0]["q"]
        assert seen[0]["maxResults"] == 7

    def test_fetched_at_is_the_epoch_second_gmail_was_asked_at(self, mock_proxy: MagicMock) -> None:
        """The desk's cursor is a Unix second, the same everywhere."""
        mock_proxy.side_effect = _one_message_mailbox()

        with time_machine.travel(FETCH_STARTED, tick=False):
            result = _register_and_get_tools()["FETCH_MESSAGES"](
                request=FetchMessagesInput(query="after:1790000000", per_page=5),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        assert result["fetched_at"] == int(FETCH_STARTED.timestamp())

    def test_a_result_exactly_at_the_inline_limit_is_still_inline(
        self, mock_proxy: MagicMock
    ) -> None:
        """A result that exactly fills the inline limit stays in context."""
        request = FetchMessagesInput(query="after:1790000000", per_page=5)
        exact = _inline_size_of(mock_proxy, request)
        mock_proxy.side_effect = _one_message_mailbox()

        with (
            patch(
                "app.services.composio.custom_tools.gmail_tools.INLINE_LIMIT_CHARS",
                exact,
            ),
            patch(
                "app.services.composio.custom_tools.gmail_tools.current_run_config",
                return_value={"configurable": {"vfs_session_id": "run"}},
            ),
            patch(
                "app.services.composio.custom_tools.gmail_tools.write_session_file_sync",
                return_value=("/tmp/f.jsonl", "/workspace/sessions/run/f.jsonl"),
            ),
        ):
            at_limit = _register_and_get_tools()["FETCH_MESSAGES"](
                request=request, execute_request=MagicMock(), auth_credentials=AUTH_CREDS
            )

        mock_proxy.side_effect = _one_message_mailbox()
        with (
            patch(
                "app.services.composio.custom_tools.gmail_tools.INLINE_LIMIT_CHARS",
                exact - 1,
            ),
            patch(
                "app.services.composio.custom_tools.gmail_tools.write_session_file_sync",
                return_value=("/tmp/f.jsonl", "/workspace/sessions/run/f.jsonl"),
            ),
            patch(
                "app.services.composio.custom_tools.gmail_tools.current_run_config",
                return_value={"configurable": {"vfs_session_id": "run"}},
            ),
            patch(
                "app.services.composio.custom_tools.gmail_tools.current_run_config",
                return_value={"configurable": {"vfs_session_id": "run"}},
            ),
        ):
            one_over = _register_and_get_tools()["FETCH_MESSAGES"](
                request=request, execute_request=MagicMock(), auth_credentials=AUTH_CREDS
            )

        assert "offloaded_to" not in at_limit
        assert one_over["offloaded_to"] == "/workspace/sessions/run/f.jsonl"


def _inline_size_of(mock_proxy: MagicMock, request: FetchMessagesInput) -> int:
    """Measure this request's inline result by running it, for use as its own size limit."""
    mock_proxy.side_effect = _one_message_mailbox()
    with patch(
        "app.services.composio.custom_tools.gmail_tools.current_run_config",
        return_value={"configurable": {}},
    ):
        result = _register_and_get_tools()["FETCH_MESSAGES"](
            request=request, execute_request=MagicMock(), auth_credentials=AUTH_CREDS
        )
    return len(json.dumps({"messages": result["messages"]}))


class TestTheThreadRead:
    """FETCH_THREAD rebuilds a conversation; every message of it has to arrive."""

    def _threads(self, count: int = 2) -> Callable[[ProxyRequest], dict[str, Any]]:
        """Serve one thread carrying count messages, addressed by the id asked for."""
        single = _one_message_mailbox()

        def serve(request: ProxyRequest) -> dict[str, Any]:
            if re.match(r".+/users/me/messages/?$", request.endpoint):
                return {"messages": [{"id": "msg-1", "threadId": "thread-1"}]}
            thread_id = re.search(r"/threads/([^/]+)$", request.endpoint).group(1)
            payload = single(
                ProxyRequest(user_id="u", toolkit="gmail", endpoint=request.endpoint, method="GET")
            )
            messages = [
                {
                    **payload,
                    "id": f"msg-{index + 1}",
                    "threadId": thread_id,
                    "snippet": f"message {index + 1}",
                }
                for index in range(count)
            ]
            return {"id": thread_id, "messages": messages}

        return serve

    def test_each_thread_comes_back_under_its_own_id_with_its_message_count(
        self, mock_proxy: MagicMock
    ) -> None:
        """The agent groups by thread id and tells the user how much each one holds."""
        mock_proxy.side_effect = self._threads(count=3)

        result = _register_and_get_tools()["FETCH_THREAD"](
            request=FetchThreadInput(thread_ids=["thread-1"]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert [thread["id"] for thread in result["threads"]] == ["thread-1"]
        (thread,) = result["threads"]
        assert thread["message_count"] == 3
        assert [message["id"] for message in thread["messages"]] == [
            "msg-1",
            "msg-2",
            "msg-3",
        ]

    def test_the_body_is_only_fetched_when_a_field_asks_for_it(self, mock_proxy: MagicMock) -> None:
        """format=full costs a full MIME fetch per thread; a metadata one does not."""
        for fields, processing, expected in (
            (["id"], "none", "metadata"),
            (["subject"], "none", "metadata"),
            (["body"], "raw", "full"),
            (["attachments"], "none", "full"),
        ):
            mock_proxy.reset_mock()
            mock_proxy.side_effect = self._threads()
            _register_and_get_tools()["FETCH_THREAD"](
                request=FetchThreadInput(
                    thread_ids=["thread-1"], fields=fields, body_processing=processing
                ),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
            formats = [
                query["format"] for query in threads_formats(mock_proxy) if "format" in query
            ]

            assert formats == [expected], (fields, processing)

    def test_a_cap_the_thread_fills_exactly_is_not_reported_as_truncated(
        self, mock_proxy: MagicMock
    ) -> None:
        """A cap that exactly fits every message of the thread truncated nothing."""
        mock_proxy.side_effect = self._threads(count=2)

        result = _register_and_get_tools()["FETCH_THREAD"](
            request=FetchThreadInput(thread_ids=["thread-1"], max_messages=2),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert result.get("truncated") is not True
        (thread,) = result["threads"]
        assert thread["message_count"] == 2

    def test_a_cap_below_the_thread_size_reports_what_it_left_out(
        self, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = self._threads(count=4)

        result = _register_and_get_tools()["FETCH_THREAD"](
            request=FetchThreadInput(thread_ids=["thread-1"], max_messages=3),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert result["truncated"] is True
        (thread,) = result["threads"]
        assert len(thread["messages"]) == 3


class TestAStarredMessageIsStillTheCallersOwn:
    def test_unstarring_calls_gmail_for_the_caller_too(self, mock_proxy: MagicMock) -> None:
        """The unstar branch takes the same user as the star branch."""
        mock_proxy.return_value = {"id": "m1"}

        _register_and_get_tools()["STAR_EMAIL"](
            request=StarEmailInput(message_ids=["m1"], unstar=True),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert _users_asked(mock_proxy) == {"user_test_123"}
        assert mock_proxy.call_args.args[0].body["removeLabelIds"] == ["STARRED"]


class TestTheContactHeaderFetch:
    """The metadata read behind GET_CONTACT_LIST, which only needs addressing headers."""

    def test_it_asks_gmail_for_the_addressing_headers_and_nothing_else(
        self, mock_proxy: MagicMock
    ) -> None:
        """The header list decides what the contact list can contain."""
        mock_proxy.side_effect = [{"messages": [{"id": "m1"}]}, {}]

        _register_and_get_tools()["GET_CONTACT_LIST"](
            request=GetContactListInput(query="boss"),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        message_read = mock_proxy.call_args_list[1].args[0]
        assert message_read.query == {
            "format": "metadata",
            "metadataHeaders": ["From", "To", "Cc", "Reply-To"],
        }


class TestTheUnreadCountShape:
    def test_a_single_label_query_reports_which_label_it_counted(
        self, mock_proxy: MagicMock
    ) -> None:
        """One label counted, the result says which — so a caller can tell two runs apart."""
        mock_proxy.return_value = {"resultSizeEstimate": "12", "messagesUnreadEstimate": "4"}

        result = _register_and_get_tools()["GET_UNREAD_COUNT"](
            request=GetUnreadCountInput(mode="query", query="is:unread", label_ids=["INBOX"]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert result["label_id"] == "INBOX"
        assert result["is_estimate"] is True

    def test_several_labels_counted_report_no_single_label(self, mock_proxy: MagicMock) -> None:
        """Two labels is not one label: naming either of them would misattribute the count."""
        mock_proxy.return_value = {"resultSizeEstimate": "12", "messagesUnreadEstimate": "4"}

        result = _register_and_get_tools()["GET_UNREAD_COUNT"](
            request=GetUnreadCountInput(
                mode="query", query="is:unread", label_ids=["INBOX", "STARRED"]
            ),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert "label_id" not in result
        assert result["label_ids"] == ["INBOX", "STARRED"]


class TestAMessageReadForMetadataStaysAMetadataRead:
    def test_a_body_no_one_asked_for_is_not_fetched(self, mock_proxy: MagicMock) -> None:
        """format=metadata is the default for a read whose fields exclude the body."""
        formats: list[str] = []
        mailbox = _one_message_mailbox()

        def _serve(request: ProxyRequest) -> dict[str, Any]:
            if "/users/me/messages/" in request.endpoint and (request.query or {}).get("format"):
                formats.append(request.query["format"])
            return mailbox(request)

        mock_proxy.side_effect = _serve

        _register_and_get_tools()["FETCH_MESSAGES"](
            request=FetchMessagesInput(query="after:1790000000", per_page=5, fields=["id"]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert formats and set(formats) == {"metadata"}


class TestTheThreadCapStopsTheWalk:
    def test_a_cap_reached_on_the_first_thread_stops_the_walk(self, mock_proxy: MagicMock) -> None:
        """The cap is a budget for the whole read, not per thread."""

        def _serve(request: ProxyRequest) -> dict[str, Any]:
            if match := re.search(r"/users/me/threads/([^/]+)$", request.endpoint):
                payload = {
                    "id": match.group(1),
                    "messages": [
                        {"id": f"{match.group(1)}-m{index}", "labelIds": ["INBOX"]}
                        for index in range(2)
                    ],
                }
                return payload
            return {"messages": [{"id": "t1-m0", "threadId": "thread-1"}]}

        mock_proxy.side_effect = _serve

        result = _register_and_get_tools()["FETCH_THREAD"](
            request=FetchThreadInput(
                thread_ids=["thread-1", "thread-2"], max_messages=2, body_processing="none"
            ),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert [thread["id"] for thread in result["threads"]] == ["thread-1"]
        assert result["truncated"] is True

    def test_a_complete_thread_carries_only_the_fields_asked_for(
        self, mock_proxy: MagicMock
    ) -> None:
        """The grouped thread path projects too, not just the partial one."""
        mock_proxy.side_effect = lambda request: {
            "id": "thread-1",
            "messages": [{"id": "m1", "threadId": "thread-1", "labelIds": ["INBOX"]}],
        }

        result = _register_and_get_tools()["FETCH_THREAD"](
            request=FetchThreadInput(thread_ids=["thread-1"], fields=["id"]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert set(result["threads"][0]["messages"][0]) == {"id"}

    def test_a_body_no_one_asked_to_process_is_dropped_from_threads(
        self, mock_proxy: MagicMock
    ) -> None:
        """body_processing="none" drops the body even when the fields ask for it."""
        body = base64.urlsafe_b64encode(b"secret body").decode()
        mock_proxy.side_effect = lambda request: {
            "id": "thread-1",
            "messages": [
                {
                    "id": "m1",
                    "threadId": "thread-1",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "headers": [{"name": "From", "value": "a@b.com"}],
                        "body": {"data": body},
                    },
                }
            ],
        }

        result = _register_and_get_tools()["FETCH_THREAD"](
            request=FetchThreadInput(
                thread_ids=["thread-1"], fields=["id", "body"], body_processing="none"
            ),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert result["threads"][0]["messages"][0].get("body") is None


class TestAPartialThreadRead:
    def test_the_messages_fetched_before_the_failure_come_back_projected(
        self, mock_proxy: MagicMock
    ) -> None:
        """A thread read that dies halfway returns what it had, in the caller's fields."""

        def _serve(request: ProxyRequest) -> dict[str, Any]:
            if match := re.search(r"/users/me/threads/([^/]+)$", request.endpoint):
                if match.group(1) == "thread-2":
                    raise RuntimeError("Gmail 503")
                return {
                    "id": "thread-1",
                    "messages": [{"id": "m1", "threadId": "thread-1", "labelIds": ["INBOX"]}],
                }
            return {"messages": [{"id": "thread-1", "threadId": "thread-1"}]}

        mock_proxy.side_effect = _serve

        result = _register_and_get_tools()["FETCH_THREAD"](
            request=FetchThreadInput(thread_ids=["thread-1", "thread-2"], fields=["id"]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert result["partial"] is True
        assert [message["id"] for message in result["messages"]] == ["m1"]
        assert set(result["messages"][0]) == {"id"}


class TestAPartialFetchStaysProjected:
    def test_the_messages_fetched_before_the_failure_carry_only_the_asked_fields(
        self, mock_proxy: MagicMock
    ) -> None:
        """A partial result is still a result, so it obeys the same field contract."""
        with time_machine.travel(FETCH_STARTED, tick=False) as traveller:
            mock_proxy.side_effect = _gmail_taking_a_minute_per_call(
                traveller, fail_second_page=True
            )

            result = _register_and_get_tools()["FETCH_MESSAGES"](
                request=FetchMessagesInput(query="after:1790000000", per_page=3, fields=["id"]),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        assert result["partial"] is True
        assert result["messages"]
        assert set(result["messages"][0]) == {"id"}

    def test_a_complete_fetch_carries_only_the_fields_asked_for(
        self, mock_proxy: MagicMock
    ) -> None:
        """The whole-result path projects too, not just the partial one."""
        mock_proxy.side_effect = _one_message_mailbox()

        result = _register_and_get_tools()["FETCH_MESSAGES"](
            request=FetchMessagesInput(query="after:1790000000", per_page=5, fields=["id"]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert "offloaded_to" not in result
        assert result["messages"]
        assert set(result["messages"][0]) == {"id"}
