"""Smoke tests for integration tools after the Composio proxy migration.

Each integration tool registration is verified end-to-end:
1. Tools are registered under the expected names.
2. The tool body invokes `proxy_request_sync` with the right toolkit + endpoint.

Detailed per-function behavior tests live in the per-tool unit modules
(e.g. `test_composio_gmail_tools.py`). This file provides a regression net
that fails fast if a tool stops routing through the proxy.
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.models.common_models import GatherContextInput
from app.models.google_docs_models import DeleteDocInput, ShareDocInput, ShareRecipient
from app.models.google_sheets_models import (
    ShareRecipient as SheetsRecipient,
    ShareSpreadsheetInput,
)
from app.models.linkedin_models import AddCommentInput, ReactToPostInput
from app.models.notion_models import FetchDataInput, MovePageInput
from app.models.twitter_models import BatchFollowInput, CreateThreadInput

AUTH_CREDS: dict[str, Any] = {"user_id": "user_test_123"}
EXECUTE_REQUEST = MagicMock()


def _capture_tools(register_fn: Callable[..., Any]) -> dict[str, Any]:
    tools: dict[str, Any] = {}
    composio = MagicMock()

    def custom_tool(**_kwargs: Any) -> Callable[[Any], Any]:
        def decorator(fn: Any) -> Any:
            tools[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    register_fn(composio)
    return tools


# ---------------------------------------------------------------------------
# Reddit / Instagram / HubSpot / Microsoft Teams / Google Maps gather context
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_path,register_name,toolkit,tool_name",
    [
        (
            "app.agents.tools.integrations.reddit_tool",
            "register_reddit_custom_tools",
            "REDDIT",
            "CUSTOM_GATHER_CONTEXT",
        ),
        (
            "app.agents.tools.integrations.instagram_tool",
            "register_instagram_custom_tools",
            "INSTAGRAM",
            "CUSTOM_GATHER_CONTEXT",
        ),
        (
            "app.agents.tools.integrations.hubspot_tool",
            "register_hubspot_custom_tools",
            "HUBSPOT",
            "CUSTOM_GATHER_CONTEXT",
        ),
        (
            "app.agents.tools.integrations.microsoft_teams_tool",
            "register_microsoft_teams_custom_tools",
            "MICROSOFT_TEAMS",
            "CUSTOM_GATHER_CONTEXT",
        ),
        (
            "app.agents.tools.integrations.google_maps_tool",
            "register_google_maps_custom_tools",
            "GOOGLE_MAPS",
            "CUSTOM_GATHER_CONTEXT",
        ),
        (
            "app.agents.tools.integrations.google_meet_tool",
            "register_google_meet_custom_tools",
            "GOOGLEMEET",
            "CUSTOM_GATHER_CONTEXT",
        ),
    ],
)
def test_gather_context_tools_use_proxy(
    module_path: str, register_name: str, toolkit: str, tool_name: str
) -> None:
    module = __import__(module_path, fromlist=[register_name])
    register = getattr(module, register_name)

    with patch(f"{module_path}.proxy_request_sync") as proxy:
        proxy.return_value = {}
        tools = _capture_tools(register)
        fn = tools[tool_name]
        fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    assert proxy.called
    first_call_kwargs = proxy.call_args_list[0].kwargs
    assert first_call_kwargs["toolkit"] == toolkit
    assert first_call_kwargs["user_id"] == AUTH_CREDS["user_id"]


# ---------------------------------------------------------------------------
# Google Docs
# ---------------------------------------------------------------------------


def test_google_meet_gather_context_swallows_calendar_failures() -> None:
    """If the GOOGLEMEET account lacks calendar scope, the events fetch raises.

    The tool must catch that and return an empty `upcoming_meets` list rather
    than failing the whole gather_context call.
    """
    from app.agents.tools.integrations.google_meet_tool import (
        register_google_meet_custom_tools,
    )
    from app.utils.errors import AppError

    with patch("app.agents.tools.integrations.google_meet_tool.proxy_request_sync") as proxy:
        # First call (userinfo) succeeds; second call (calendar/events) raises.
        proxy.side_effect = [
            {"email": "u@x.com", "name": "User", "picture": None},
            AppError(message="GOOGLEMEET API error (403)", status_code=403),
        ]
        tools = _capture_tools(register_google_meet_custom_tools)
        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    assert result["user"]["email"] == "u@x.com"
    assert result["upcoming_meets"] == []
    assert result["upcoming_meet_count"] == 0


def test_google_docs_share_doc_routes_through_proxy() -> None:
    from app.agents.tools.integrations.google_docs_tool import (
        register_google_docs_custom_tools,
    )

    with patch("app.agents.tools.integrations.google_docs_tool.proxy_request_sync") as proxy:
        proxy.return_value = {"id": "perm-1"}
        tools = _capture_tools(register_google_docs_custom_tools)
        result = tools["CUSTOM_SHARE_DOC"](
            ShareDocInput(
                document_id="doc-1",
                recipients=[ShareRecipient(email="x@y.z", role="writer")],  # type: ignore[call-arg]
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    kwargs = proxy.call_args.kwargs
    assert kwargs["toolkit"] == "GOOGLEDOCS"
    assert kwargs["method"] == "POST"
    assert "/permissions" in kwargs["endpoint"]
    assert result["document_id"] == "doc-1"


def test_google_docs_delete_doc_routes_through_proxy() -> None:
    from app.agents.tools.integrations.google_docs_tool import (
        register_google_docs_custom_tools,
    )

    with patch("app.agents.tools.integrations.google_docs_tool.proxy_request_sync") as proxy:
        proxy.return_value = None
        tools = _capture_tools(register_google_docs_custom_tools)
        result = tools["CUSTOM_DELETE_DOC"](
            DeleteDocInput(document_id="doc-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["successful"] is True
    kwargs = proxy.call_args.kwargs
    assert kwargs["method"] == "DELETE"
    assert kwargs["endpoint"].endswith("/files/doc-1")


# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------


def test_google_sheets_share_routes_through_proxy() -> None:
    from app.agents.tools.integrations.google_sheets_tool import (
        register_google_sheets_custom_tools,
    )

    with patch("app.agents.tools.integrations.google_sheets_tool.proxy_request_sync") as proxy:
        proxy.return_value = {"id": "perm-1"}
        tools = _capture_tools(register_google_sheets_custom_tools)
        result = tools["CUSTOM_SHARE_SPREADSHEET"](
            ShareSpreadsheetInput(
                spreadsheet_id="ss-1",
                recipients=[SheetsRecipient(email="x@y.z")],  # type: ignore[call-arg]
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["total_shared"] == 1
    assert proxy.call_args.kwargs["toolkit"] == "GOOGLESHEETS"


# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------


def test_notion_move_page_uses_execute_request_proxy() -> None:
    from app.agents.tools.integrations.notion_tool import (
        register_notion_custom_tools,
    )

    tools = _capture_tools(register_notion_custom_tools)
    proxy_mock = MagicMock()
    proxy_mock.return_value.data = {"id": "page-1", "url": "https://notion.so/x"}
    result = tools["MOVE_PAGE"](
        MovePageInput(page_id="page-1", parent_id="parent-1", parent_type="page_id"),
        proxy_mock,
        AUTH_CREDS,
    )
    proxy_mock.assert_called_once()
    assert result["page_id"] == "page-1"


def test_notion_fetch_data_routes_through_proxy() -> None:
    from app.agents.tools.integrations.notion_tool import (
        register_notion_custom_tools,
    )

    with patch("app.agents.tools.integrations.notion_tool.proxy_request_sync") as proxy:
        proxy.return_value = {"results": [], "has_more": False}
        tools = _capture_tools(register_notion_custom_tools)
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages", query="x"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {"values": [], "count": 0, "has_more": False}
    kwargs = proxy.call_args.kwargs
    assert kwargs["toolkit"] == "NOTION"
    assert kwargs["endpoint"].endswith("/search")


# ---------------------------------------------------------------------------
# Twitter
# ---------------------------------------------------------------------------


def test_twitter_batch_follow_uses_proxy_via_utils() -> None:
    from app.agents.tools.integrations.twitter_tool import (
        register_twitter_custom_tools,
    )

    with (
        patch(
            "app.agents.tools.integrations.twitter_tool.get_stream_writer",
            return_value=None,
        ),
        patch("app.utils.twitter_utils.proxy_request_sync") as proxy,
    ):
        # First call: get_my_user_id; second: lookup_user_by_username; third: follow
        proxy.side_effect = [
            {"data": {"id": "me"}},
            {"data": {"id": "u1", "username": "elon"}},
            {"data": {"following": True}},
        ]
        tools = _capture_tools(register_twitter_custom_tools)
        result = tools["CUSTOM_BATCH_FOLLOW"](
            BatchFollowInput(usernames=["elon"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["followed_count"] == 1


def test_twitter_create_thread_uses_proxy() -> None:
    from app.agents.tools.integrations.twitter_tool import (
        register_twitter_custom_tools,
    )

    with (
        patch(
            "app.agents.tools.integrations.twitter_tool.get_stream_writer",
            return_value=None,
        ),
        patch("app.utils.twitter_utils.proxy_request_sync") as utils_proxy,
        patch("app.agents.tools.integrations.twitter_tool.proxy_request_sync") as tool_proxy,
    ):
        utils_proxy.side_effect = [
            {"data": {"id": "tw1"}},
            {"data": {"id": "tw2"}},
        ]
        tool_proxy.return_value = {"data": {"username": "me"}}
        tools = _capture_tools(register_twitter_custom_tools)
        result = tools["CUSTOM_CREATE_THREAD"](
            CreateThreadInput(tweets=["a", "b"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["tweet_count"] == 2


# ---------------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------------


def test_linkedin_react_to_post_uses_proxy() -> None:
    from app.agents.tools.integrations.linkedin_tool import (
        register_linkedin_custom_tools,
    )

    with (
        patch("app.agents.tools.integrations.linkedin_tool.proxy_request_sync") as proxy,
        patch(
            "app.agents.tools.integrations.linkedin_tool.get_author_urn",
            return_value="urn:li:person:1",
        ),
    ):
        proxy.return_value = {}
        tools = _capture_tools(register_linkedin_custom_tools)
        result = tools["CUSTOM_REACT_TO_POST"](
            ReactToPostInput(post_urn="urn:li:share:1", reaction_type="LIKE"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["post_urn"] == "urn:li:share:1"
    kwargs = proxy.call_args.kwargs
    assert kwargs["toolkit"] == "LINKEDIN"
    assert kwargs["method"] == "POST"


def test_linkedin_add_comment_uses_proxy_full() -> None:
    from app.agents.tools.integrations.linkedin_tool import (
        register_linkedin_custom_tools,
    )

    with (
        patch("app.agents.tools.integrations.linkedin_tool.proxy_request_full_sync") as proxy_full,
        patch(
            "app.agents.tools.integrations.linkedin_tool.get_author_urn",
            return_value="urn:li:person:1",
        ),
    ):
        proxy_full.return_value = {
            "data": {"id": "comment-1"},
            "headers": {},
        }
        tools = _capture_tools(register_linkedin_custom_tools)
        result = tools["CUSTOM_ADD_COMMENT"](
            AddCommentInput(post_urn="urn:li:share:1", comment_text="hi"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["comment_id"] == "comment-1"
