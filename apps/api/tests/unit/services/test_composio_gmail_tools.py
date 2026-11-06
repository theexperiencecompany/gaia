"""Unit tests for Gmail custom tools (post-Composio-proxy migration).

Each tool routes provider API calls through proxy_request_sync instead of
raw httpx. Tests patch that helper and assert on the request shape.
"""

import base64
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import re
from typing import Any
from unittest.mock import MagicMock, patch

from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, ValidationError
import pytest
import time_machine

from app.agents.prompts import todo_prompts
from app.agents.tools.coding.query_json_tool import _apply_query
from app.agents.tools.execute.dispatch import dispatch_config_for
from app.constants.email import DEFAULT_SUMMARY_FIELDS, MessageFieldLiteral
from app.constants.offload import OFFLOAD_MIN_MESSAGES
from app.models.agent_config import ComposioAccountSelection
from app.models.common_models import GatherContextInput
from app.models.composio_schemas.gmail import (
    BodyProcessingLiteral,
    FetchMessagesInput,
    FetchThreadInput,
)
from app.services.composio import account_scope as account_scope_module
from app.services.composio.custom_tools import gmail_tools as gmail_tools_module
from app.services.composio.custom_tools.gmail_constants import FETCH_CONCURRENCY
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
from app.utils.concurrency import ContextThreadPoolExecutor
from app.utils.errors import AppError
from app.utils.timezone import Timezone

AUTH_CREDS: dict[str, Any] = {"user_id": "user_test_123"}
GMAIL_TOOLS = "app.services.composio.custom_tools.gmail_tools"
PROXY_PATH = f"{GMAIL_TOOLS}.proxy_request_sync"


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

    @time_machine.travel(datetime(2026, 10, 20, 12, tzinfo=UTC), tick=False)
    def test_any_count_of_days_weeks_months_resolves_to_its_window(self):
        assert _timeframe_clause("14d", Timezone.utc()) == "after:2026/10/07 before:2026/10/21"
        assert _timeframe_clause("2m", Timezone.utc()) == "after:2026/08/22 before:2026/10/21"

    def test_a_named_timeframe_has_no_day_count(self):
        with pytest.raises(ValueError, match=r"^not a relative timeframe: 'today'$"):
            gmail_tools_module._relative_days("today")

    @pytest.mark.parametrize(
        ("timeframe", "expected_max"),
        [("2d", 100), ("5d", 200), ("14d", 400), ("30d", 500), ("2m", 500), ("this_week", 200)],
    )
    def test_default_cap_scales_with_the_window_length(self, timeframe: str, expected_max: int):
        _, default_max = _resolve_timeframe(timeframe, None, Timezone.utc())
        assert default_max == expected_max


class TestFetchInputsModelsSend:
    """Inputs captured from prod GMAIL_FETCH_MESSAGES/FETCH_THREAD calls that the schema refused."""

    @pytest.mark.regression
    @pytest.mark.parametrize("timeframe", ["14d", "30d", "2d", "2m"])
    def test_a_relative_timeframe_of_any_length_is_accepted(self, timeframe: str):
        request = FetchMessagesInput.model_validate(
            {"query": "invoice OR receipt", "timeframe": timeframe, "max_messages": 40}
        )
        assert request.timeframe == timeframe

    @pytest.mark.parametrize("timeframe", ["24h", "this_month", "0d", "fortnight"])
    def test_an_unsupported_timeframe_is_refused_naming_the_accepted_forms(self, timeframe: str):
        with pytest.raises(ValidationError) as refused:
            FetchMessagesInput.model_validate({"timeframe": timeframe})
        assert refused.value.errors()[0]["msg"] == (
            f"Value error, timeframe {timeframe!r} is not supported. Use one of: today, "
            "yesterday, tomorrow, this_week, last_week, next_week, or the last N "
            "days/weeks/months/years written <N>d / <N>w / <N>m / <N>y (2d, 7d, 14d, 30d, "
            "2w, 3m, 1y); for anything else (hours, a calendar month) put after:/before: "
            "in `query` instead."
        )

    def test_omitted_fields_fall_back_to_the_default_set(self):
        assert FetchMessagesInput.model_validate({"fields": None}).fields == DEFAULT_SUMMARY_FIELDS

    def test_a_bare_field_name_is_refused_as_not_a_list(self):
        with pytest.raises(ValueError, match="valid list"):
            FetchMessagesInput.model_validate({"fields": "date"})

    @pytest.mark.regression
    def test_the_field_names_models_reach_for_map_onto_the_projected_ones(self):
        request = FetchMessagesInput.model_validate(
            {
                "timeframe": "1d",
                "fields": ["message_id", "thread_id", "from", "subject", "date", "labelIds"],
            }
        )
        assert request.fields == ["id", "threadId", "from", "subject", "time", "labels"]

    @pytest.mark.regression
    def test_internal_date_spellings_mean_the_message_time(self):
        thread = FetchThreadInput.model_validate(
            {"thread_ids": ["t1"], "fields": ["from", "internalDate", "internal_date", "date"]}
        )
        assert thread.fields == ["from", "time"]

    def test_an_unknown_field_is_still_refused(self):
        with pytest.raises(ValueError, match="isImportant"):
            FetchMessagesInput.model_validate({"fields": ["from", "isImportant"]})


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

        assert result["fetched_count"] == 1
        assert len(result["messages"]) == 1


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
    def test_a_partial_result_carries_it_too(self, mock_proxy: MagicMock) -> None:
        with time_machine.travel(FETCH_STARTED, tick=False) as traveller:
            mock_proxy.side_effect = _gmail_taking_a_minute_per_call(
                traveller, fail_second_page=True
            )
            result = self._fetch(FetchMessagesInput(query="newer_than:1d", per_page=3))

        assert result["partial"] is True
        assert result["fetched_at"] == int(FETCH_STARTED.timestamp())


class TestTheDesksSweep:
    """The Inbox desk's whole-window sweep: headers only, counted per address."""

    @staticmethod
    def _sweep(
        mock_proxy: MagicMock,
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
        result = _register_and_get_tools()["FETCH_MESSAGES"](
            request=FetchMessagesInput(
                query="after:1790000000",
                max_messages=1000,
                fields=list(todo_prompts.INBOX_DESK_SWEEP_FIELDS),
                body_processing=body_processing,
            ),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )
        return result, result["messages"], formats

    def test_a_window_past_the_message_limit_is_fetched_as_metadata_and_returned_bodiless(
        self, mock_proxy: MagicMock
    ) -> None:
        size = OFFLOAD_MIN_MESSAGES + 10
        senders = ["Ann <notifications@github.com>", "Bob <notifications@github.com>"]

        result, records, formats = self._sweep(mock_proxy, senders, size)

        assert result["fetched_count"] == size
        assert formats == ["metadata"] * size
        assert [r["from"] for r in records] == [senders[n % 2] for n in range(size)]
        assert all("body" not in r for r in records)

    def test_a_window_past_the_message_limit_comes_back_whole_with_its_bodies(
        self, mock_proxy: MagicMock
    ) -> None:
        """Compaction files it, so every field is kept: a body query on a body-less file finds nothing."""
        size = OFFLOAD_MIN_MESSAGES + 1

        _, records, formats = self._sweep(
            mock_proxy, ["a@example.com"], size, body_processing="normalize"
        )

        assert formats == ["full"] * size
        assert [r["body"] for r in records] == ["never read"] * size
        assert "threadId" in records[0], "the caller's field projection leaked into the file"

    def test_a_window_at_the_message_limit_comes_back_projected(
        self, mock_proxy: MagicMock
    ) -> None:
        _, records, formats = self._sweep(
            mock_proxy, ["a@example.com"], OFFLOAD_MIN_MESSAGES, body_processing="normalize"
        )

        assert formats == ["metadata"] * OFFLOAD_MIN_MESSAGES
        assert set(records[0]) <= set(todo_prompts.INBOX_DESK_SWEEP_FIELDS)

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

    @pytest.mark.regression
    def test_a_sender_counts_once_per_address_whatever_its_display_name(
        self, mock_proxy: MagicMock
    ) -> None:
        senders = [
            "Ann <notifications@github.com>",
            '"GitHub" <Notifications@GitHub.com>',
            "notifications@github.com",
            "Bob Lee <bob@example.com>",
        ]

        _, records, _ = self._sweep(mock_proxy, senders, 8)

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

    def test_a_thread_read_past_the_message_limit_comes_back_flat_and_whole(
        self, mock_proxy: MagicMock
    ) -> None:
        """Flat so compaction files one record per message; each keeps its threadId to regroup."""
        size = OFFLOAD_MIN_MESSAGES + 1
        body = base64.urlsafe_b64encode(b"y").decode()
        mock_proxy.side_effect = lambda request: {
            "id": "thread-1",
            "messages": [
                {
                    "id": f"m{i}",
                    "threadId": "thread-1",
                    "payload": {
                        "headers": [{"name": "From", "value": "a@b.com"}],
                        "body": {"data": body},
                    },
                }
                for i in range(size)
            ],
        }

        result = _register_and_get_tools()["FETCH_THREAD"](
            request=FetchThreadInput(thread_ids=["thread-1"], fields=["id"]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert "threads" not in result
        assert result["fetched_count"] == size
        assert {m["threadId"] for m in result["messages"]} == {"thread-1"}
        assert result["messages"][0]["body"] == "y"


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
                "app.services.composio.custom_tools.gmail_tools.current_stream_writer",
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

    @pytest.mark.regression
    def test_a_sandbox_dispatched_fetch_returns_its_messages_without_a_card(
        self, mock_proxy: MagicMock
    ) -> None:
        """Regression for GAIA-BACKEND-433: the sandbox route's run config carries no graph runtime."""
        mock_proxy.side_effect = _one_message_mailbox()
        fetch = _register_and_get_tools()["FETCH_MESSAGES"]

        result = RunnableLambda(
            lambda _: fetch(
                request=FetchMessagesInput(query="after:1790000000", per_page=5),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
        ).invoke(None, config=dispatch_config_for(AUTH_CREDS["user_id"]))

        assert [message["id"] for message in result["messages"]] == ["msg-1"]


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


class TestAFileBoundFetch:
    """Past OFFLOAD_MIN_MESSAGES a fetch comes back whole for compaction to file."""

    @staticmethod
    def _inbox(size: int) -> Callable[[ProxyRequest], dict[str, Any]]:
        def serve(request: ProxyRequest) -> dict[str, Any]:
            if re.match(r".+/users/me/messages/?$", request.endpoint):
                return {"messages": [{"id": f"m{i}"} for i in range(size)]}
            n = request.endpoint.rsplit("/", 1)[1]
            return {"id": n, "threadId": f"t-{n}", "payload": {"headers": []}}

        return serve

    def test_a_cut_at_the_cap_says_so_and_renders_no_card(self, mock_proxy: MagicMock) -> None:
        writer = MagicMock()
        mock_proxy.side_effect = self._inbox(OFFLOAD_MIN_MESSAGES + 10)

        with patch(f"{GMAIL_TOOLS}.current_stream_writer", return_value=writer):
            result = _register_and_get_tools()["FETCH_MESSAGES"](
                request=FetchMessagesInput(
                    query="after:1790000000", max_messages=OFFLOAD_MIN_MESSAGES + 5
                ),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        assert result["fetched_count"] == OFFLOAD_MIN_MESSAGES + 5
        assert result["truncated"] is True
        writer.assert_not_called()

    def test_a_timeframe_is_resolved_in_the_runs_home_timezone(self, mock_proxy: MagicMock) -> None:
        queries: list[object] = []
        mailbox = self._inbox(1)

        def serve(request: ProxyRequest) -> dict[str, Any]:
            queries.append((request.query or {}).get("q"))
            return mailbox(request)

        mock_proxy.side_effect = serve
        # 20:00 UTC is already tomorrow in +05:30, so the two days differ.
        with (
            time_machine.travel(datetime(2026, 10, 1, 20, tzinfo=UTC), tick=False),
            patch(
                f"{GMAIL_TOOLS}.current_run_config",
                return_value={"configurable": {"user_timezone": "+05:30"}},
            ),
        ):
            _register_and_get_tools()["FETCH_MESSAGES"](
                request=FetchMessagesInput(timeframe="today"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
            expected, _ = _resolve_timeframe("today", None, Timezone.parse("+05:30"))
            in_utc, _ = _resolve_timeframe("today", None, Timezone.parse("+00:00"))

        assert expected != in_utc
        assert queries[0] == expected


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

    def test_a_small_thread_read_reports_its_counts_and_renders_the_card(
        self, mock_proxy: MagicMock
    ) -> None:
        writer = MagicMock()
        mock_proxy.side_effect = self._threads(count=3)

        with patch(f"{GMAIL_TOOLS}.current_stream_writer", return_value=writer):
            result = _register_and_get_tools()["FETCH_THREAD"](
                request=FetchThreadInput(thread_ids=["thread-1"]),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        assert (result["fetched_threads"], result["total_messages"]) == (1, 3)
        assert writer.call_args.args[0]["resultSize"] == 3

    def test_a_thread_read_at_the_message_limit_stays_grouped(self, mock_proxy: MagicMock) -> None:
        mock_proxy.side_effect = self._threads(count=OFFLOAD_MIN_MESSAGES)

        result = _register_and_get_tools()["FETCH_THREAD"](
            request=FetchThreadInput(thread_ids=["thread-1"]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert result["threads"][0]["message_count"] == OFFLOAD_MIN_MESSAGES

    def test_a_large_thread_read_cut_at_its_cap_says_so_and_renders_no_card(
        self, mock_proxy: MagicMock
    ) -> None:
        writer = MagicMock()
        mock_proxy.side_effect = self._threads(count=OFFLOAD_MIN_MESSAGES + 5)

        with patch(f"{GMAIL_TOOLS}.current_stream_writer", return_value=writer):
            result = _register_and_get_tools()["FETCH_THREAD"](
                request=FetchThreadInput(
                    thread_ids=["thread-1"], max_messages=OFFLOAD_MIN_MESSAGES + 1
                ),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        assert result["fetched_count"] == OFFLOAD_MIN_MESSAGES + 1
        assert result["truncated"] is True
        writer.assert_not_called()

    def test_the_body_is_only_fetched_when_a_field_asks_for_it(self, mock_proxy: MagicMock) -> None:
        """format=full costs a full MIME fetch per thread; a metadata one does not."""
        cases: tuple[tuple[list[MessageFieldLiteral], BodyProcessingLiteral, str], ...] = (
            (["id"], "none", "metadata"),
            (["subject"], "none", "metadata"),
            (["body"], "raw", "full"),
            (["attachments"], "none", "full"),
        )
        for fields, processing, expected in cases:
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
            request=GetUnreadCountInput(query="is:unread", label_ids=["INBOX"]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert result["label_id"] == "INBOX"
        assert result["is_estimate"] is True

    def test_several_labels_counted_report_no_single_label(self, mock_proxy: MagicMock) -> None:
        """Two labels is not one label: naming either of them would misattribute the count."""
        mock_proxy.return_value = {"resultSizeEstimate": "12", "messagesUnreadEstimate": "4"}

        result = _register_and_get_tools()["GET_UNREAD_COUNT"](
            request=GetUnreadCountInput(query="is:unread", label_ids=["INBOX", "STARRED"]),
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

    @pytest.mark.parametrize("gone", ["thread-1", "thread-2", "thread-3"])
    def test_a_thread_gmail_no_longer_has_is_skipped_and_the_rest_come_back(
        self, mock_proxy: MagicMock, gone: str
    ) -> None:
        """Gmail's 404 on one thread of a batch drops that thread, never the batch."""

        def _serve(request: ProxyRequest) -> dict[str, Any]:
            thread_id = re.search(r"/users/me/threads/([^/]+)$", request.endpoint).group(1)
            if thread_id == gone:
                raise AppError(message="gmail API error (404)", status_code=404)
            return {"id": thread_id, "messages": [{"id": f"m-{thread_id}", "threadId": thread_id}]}

        mock_proxy.side_effect = _serve

        result = _register_and_get_tools()["FETCH_THREAD"](
            request=FetchThreadInput(
                thread_ids=["thread-1", "thread-2", "thread-3"], fields=["id"]
            ),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert "partial" not in result
        kept = [
            thread_id for thread_id in ["thread-1", "thread-2", "thread-3"] if thread_id != gone
        ]
        assert [thread["id"] for thread in result["threads"]] == kept
        assert result["missing_thread_ids"] == [gone]

    def test_a_batch_whose_every_thread_is_gone_returns_empty_not_an_error(
        self, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = AppError(message="gmail API error (404)", status_code=404)

        result = _register_and_get_tools()["FETCH_THREAD"](
            request=FetchThreadInput(thread_ids=["thread-1", "thread-2"], fields=["id"]),
            execute_request=MagicMock(),
            auth_credentials=AUTH_CREDS,
        )

        assert result["threads"] == []
        assert result["missing_thread_ids"] == ["thread-1", "thread-2"]

    def test_any_other_gmail_error_on_a_thread_still_fails_the_read(
        self, mock_proxy: MagicMock
    ) -> None:
        mock_proxy.side_effect = AppError(message="gmail API error (500)", status_code=500)

        with pytest.raises(AppError):
            _register_and_get_tools()["FETCH_THREAD"](
                request=FetchThreadInput(thread_ids=["thread-1"], fields=["id"]),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )


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

        assert result["messages"]
        assert set(result["messages"][0]) == {"id"}


class TestTheScopedAccountReachesEveryRequest:
    """A fetch fans its per-message and per-thread reads out to worker threads.

    The account a call is scoped to lives in a context variable; a worker that
    lost it would ask the primary for another mailbox's ids and get Gmail's 404.
    """

    @staticmethod
    def _recording(serve: Callable[[ProxyRequest], dict[str, Any]], seen: list[str | None]):
        def record(request: ProxyRequest) -> dict[str, Any]:
            selection = account_scope_module.current_selection("gmail")
            seen.append(selection.connected_account_id if selection else None)
            return serve(request)

        return record

    def test_every_message_read_runs_as_the_scoped_account(self, mock_proxy: MagicMock) -> None:
        def serve(request: ProxyRequest) -> dict[str, Any]:
            if re.match(r".+/users/me/messages/?$", request.endpoint):
                return {"messages": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]}
            return TestFetchMessages._make_message_response()

        seen: list[str | None] = []
        mock_proxy.side_effect = self._recording(serve, seen)
        work = ComposioAccountSelection(toolkit="gmail", connected_account_id="ca_work")

        with account_scope_module.account_scope(work):
            _register_and_get_tools()["FETCH_MESSAGES"](
                request=FetchMessagesInput(timeframe="today", body_processing="none"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        assert seen == ["ca_work"] * 4

    def test_every_thread_read_runs_as_the_scoped_account(self, mock_proxy: MagicMock) -> None:
        seen: list[str | None] = []
        mock_proxy.side_effect = self._recording(TestTheThreadRead()._threads(count=1), seen)
        work = ComposioAccountSelection(toolkit="gmail", connected_account_id="ca_work")

        with account_scope_module.account_scope(work):
            _register_and_get_tools()["FETCH_THREAD"](
                request=FetchThreadInput(thread_ids=["thread-1", "thread-2"]),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        assert seen == ["ca_work", "ca_work"]

    def test_message_and_thread_reads_share_the_fetch_concurrency_cap(
        self, mock_proxy: MagicMock
    ) -> None:
        # Assert the requested size: _max_workers normalizes None to min(32, cpu+4),
        # which is 8 on a 4-CPU runner and would let a None mutant survive.
        requested: list[int | None] = []

        class RecordingPool(ContextThreadPoolExecutor):
            def __init__(self, max_workers: int | None = None) -> None:
                requested.append(max_workers)
                super().__init__(max_workers=max_workers)

        threads = TestTheThreadRead()._threads(count=1)

        def serve(request: ProxyRequest) -> dict[str, Any]:
            if "/threads/" in request.endpoint or re.match(
                r".+/users/me/messages/?$", request.endpoint
            ):
                return threads(request)
            return TestFetchMessages._make_message_response()

        mock_proxy.side_effect = serve
        tools = _register_and_get_tools()
        with patch(f"{GMAIL_TOOLS}.ContextThreadPoolExecutor", RecordingPool):
            tools["FETCH_MESSAGES"](
                request=FetchMessagesInput(timeframe="today", body_processing="none"),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )
            tools["FETCH_THREAD"](
                request=FetchThreadInput(thread_ids=["thread-1"]),
                execute_request=MagicMock(),
                auth_credentials=AUTH_CREDS,
            )

        assert requested == [FETCH_CONCURRENCY] * 2
