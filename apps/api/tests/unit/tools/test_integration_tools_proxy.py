"""Smoke tests for integration tools after the Composio proxy migration.

Each integration tool registration is verified end-to-end:
1. Tools are registered under the expected names.
2. The tool body invokes `proxy_request_sync` with the right toolkit + endpoint.

Detailed per-function behavior tests live in the per-tool unit modules
(e.g. `test_composio_gmail_tools.py`). This file provides a regression net
that fails fast if a tool stops routing through the proxy.
"""

from collections.abc import Callable
import json
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from app.models.common_models import GatherContextInput
from app.models.google_docs_models import (
    CreateTOCInput,
    DeleteDocInput,
    ShareDocInput,
    ShareRecipient,
)
from app.models.google_sheets_models import (
    ShareRecipient as SheetsRecipient,
    ShareSpreadsheetInput,
)
from app.models.linkedin_models import AddCommentInput, ReactToPostInput
from app.models.notion_models import (
    FetchDataInput,
    FetchPageAsMarkdownInput,
    InsertMarkdownInput,
    MovePageInput,
)
from app.models.twitter_models import (
    BatchFollowInput,
    BatchUnfollowInput,
    CreateThreadInput,
    ScheduleTweetInput,
    SearchUsersInput,
)

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


# --- Google Docs: detailed behavior -------------------------------------------


GOOGLE_DOCS_MODULE = "app.agents.tools.integrations.google_docs_tool"
GOOGLE_DOCS_AUTH: dict[str, Any] = {"user_id": "user_test_123", "version": "v1"}


def _google_docs_tools() -> tuple[dict[str, Any], MagicMock]:
    """Register google docs tools; return (captured tools, composio mock)."""
    from app.agents.tools.integrations.google_docs_tool import (
        register_google_docs_custom_tools,
    )

    tools: dict[str, Any] = {}
    composio = MagicMock()

    def custom_tool(**_kwargs: Any) -> Callable[[Any], Any]:
        def decorator(fn: Any) -> Any:
            tools[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    register_google_docs_custom_tools(composio)
    return tools, composio


def test_google_docs_register_returns_expected_tool_names() -> None:
    from app.agents.tools.integrations.google_docs_tool import (
        register_google_docs_custom_tools,
    )

    assert register_google_docs_custom_tools(MagicMock()) == [
        "GOOGLEDOCS_CUSTOM_SHARE_DOC",
        "GOOGLEDOCS_CUSTOM_CREATE_TOC",
        "GOOGLEDOCS_CUSTOM_DELETE_DOC",
        "GOOGLEDOCS_CUSTOM_GATHER_CONTEXT",
    ]


# --- _user_id -----------------------------------------------------------------


@pytest.mark.parametrize(
    "creds",
    [{}, {"user_id": ""}, {"user_id": None}, {"user_id": 123}],
    ids=["missing", "empty", "none", "not-a-string"],
)
def test_google_docs_user_id_rejects_invalid_credentials(creds: dict[str, Any]) -> None:
    from app.agents.tools.integrations.google_docs_tool import _user_id

    with pytest.raises(ValueError) as excinfo:
        _user_id(creds)
    assert str(excinfo.value) == "Missing user_id in auth_credentials"


def test_google_docs_user_id_returns_credentials_user_id() -> None:
    from app.agents.tools.integrations.google_docs_tool import _user_id

    assert _user_id({"user_id": "user-1"}) == "user-1"


# --- CUSTOM_SHARE_DOC ---------------------------------------------------------


def test_google_docs_share_doc_exact_proxy_calls_and_result() -> None:
    tools, _composio = _google_docs_tools()

    with (
        patch(
            f"{GOOGLE_DOCS_MODULE}.proxy_request_sync", return_value={"id": "perm-1"}
        ) as proxy,
        patch(f"{GOOGLE_DOCS_MODULE}.log.set") as log_set,
    ):
        result = tools["CUSTOM_SHARE_DOC"](
            ShareDocInput(
                document_id="doc-share",
                recipients=[
                    ShareRecipient(email="a@x.com", role="writer"),
                    ShareRecipient(email="b@x.com", role="reader", send_notification=False),
                ],
            ),
            EXECUTE_REQUEST,
            GOOGLE_DOCS_AUTH,
        )

    assert result == {
        "document_id": "doc-share",
        "url": "https://docs.google.com/document/d/doc-share/edit",
        "shared": [
            {
                "email": "a@x.com",
                "role": "writer",
                "permission_id": "perm-1",
                "notification_sent": True,
            },
            {
                "email": "b@x.com",
                "role": "reader",
                "permission_id": "perm-1",
                "notification_sent": False,
            },
        ],
    }
    log_set.assert_called_once_with(tool={"integration": "google_docs", "action": "share_doc"})
    assert proxy.call_args_list == [
        call(
            user_id="user_test_123",
            toolkit="GOOGLEDOCS",
            endpoint="https://www.googleapis.com/drive/v3/files/doc-share/permissions",
            method="POST",
            body={"type": "user", "role": "writer", "emailAddress": "a@x.com"},
            query={"sendNotificationEmail": "true"},
        ),
        call(
            user_id="user_test_123",
            toolkit="GOOGLEDOCS",
            endpoint="https://www.googleapis.com/drive/v3/files/doc-share/permissions",
            method="POST",
            body={"type": "user", "role": "reader", "emailAddress": "b@x.com"},
            query={"sendNotificationEmail": "false"},
        ),
    ]


def test_google_docs_share_doc_missing_permission_id_becomes_none() -> None:
    with patch(f"{GOOGLE_DOCS_MODULE}.proxy_request_sync", return_value=None) as proxy:
        tools, _composio = _google_docs_tools()
        result = tools["CUSTOM_SHARE_DOC"](
            ShareDocInput(
                document_id="doc-1",
                recipients=[ShareRecipient(email="a@x.com")],
            ),
            EXECUTE_REQUEST,
            GOOGLE_DOCS_AUTH,
        )

    assert result["shared"] == [
        {
            "email": "a@x.com",
            "role": "writer",
            "permission_id": None,
            "notification_sent": True,
        }
    ]
    proxy.assert_called_once()


def test_google_docs_share_doc_recipient_failure_logged_and_skipped() -> None:
    from app.constants.log_tags import LogTag
    from app.utils.errors import AppError

    with (
        patch(
            f"{GOOGLE_DOCS_MODULE}.proxy_request_sync",
            side_effect=[{"id": "perm-1"}, AppError(message="denied", status_code=403)],
        ) as proxy,
        patch(f"{GOOGLE_DOCS_MODULE}.log.error") as err_log,
        patch(f"{GOOGLE_DOCS_MODULE}.log.set"),
    ):
        tools, _composio = _google_docs_tools()
        result = tools["CUSTOM_SHARE_DOC"](
            ShareDocInput(
                document_id="doc-1",
                recipients=[
                    ShareRecipient(email="ok@x.com", role="writer"),
                    ShareRecipient(email="bad@x.com", role="reader"),
                ],
            ),
            EXECUTE_REQUEST,
            GOOGLE_DOCS_AUTH,
        )

    # The failing recipient is dropped from the result, not reported as shared.
    assert result["shared"] == [
        {
            "email": "ok@x.com",
            "role": "writer",
            "permission_id": "perm-1",
            "notification_sent": True,
        }
    ]
    err_log.assert_called_once_with(
        f"{LogTag.TOOL} Error sharing doc with recipient", error_type="AppError"
    )
    assert proxy.call_count == 2


def test_google_docs_share_doc_all_recipients_fail_raises_runtime_error() -> None:
    from app.constants.log_tags import LogTag
    from app.utils.errors import AppError

    with (
        patch(
            f"{GOOGLE_DOCS_MODULE}.proxy_request_sync",
            side_effect=AppError(message="denied", status_code=403),
        ) as proxy,
        patch(f"{GOOGLE_DOCS_MODULE}.log.error") as err_log,
        patch(f"{GOOGLE_DOCS_MODULE}.log.set"),
    ):
        tools, _composio = _google_docs_tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools["CUSTOM_SHARE_DOC"](
                ShareDocInput(
                    document_id="doc-1",
                    recipients=[ShareRecipient(email="bad@x.com", role="reader")],
                ),
                EXECUTE_REQUEST,
                GOOGLE_DOCS_AUTH,
            )

    assert str(excinfo.value) == (
        "Failed to share document with all recipients: "
        "[{'email': 'bad@x.com', 'role': 'reader', "
        "'error': 'Failed to share: 403 - denied'}]"
    )
    err_log.assert_called_once_with(
        f"{LogTag.TOOL} Error sharing doc with recipient", error_type="AppError"
    )
    assert proxy.call_count == 1


def test_google_docs_share_doc_missing_user_id_rejected_before_proxy() -> None:
    with patch(f"{GOOGLE_DOCS_MODULE}.proxy_request_sync") as proxy:
        tools, _composio = _google_docs_tools()
        with pytest.raises(ValueError, match="Missing user_id in auth_credentials"):
            tools["CUSTOM_SHARE_DOC"](
                ShareDocInput(
                    document_id="doc-1",
                    recipients=[ShareRecipient(email="a@x.com")],
                ),
                EXECUTE_REQUEST,
                {},
            )

    proxy.assert_not_called()


# --- CUSTOM_CREATE_TOC --------------------------------------------------------


DOCS_DOCUMENT: dict[str, Any] = {
    "body": {
        "content": [
            {
                "startIndex": 1,
                "paragraph": {
                    "elements": [{"textRun": {"content": "Intro"}}],
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                },
            },
            {
                "startIndex": 2,
                "paragraph": {
                    "elements": [{"textRun": {"content": "Chapter One"}}],
                    "paragraphStyle": {"namedStyleType": "HEADING_1"},
                },
            },
            {
                "startIndex": 3,
                "paragraph": {
                    "elements": [{"textRun": {"content": "Section"}}],
                    "paragraphStyle": {"namedStyleType": "HEADING_2"},
                },
            },
            {
                "startIndex": 4,
                "paragraph": {
                    "elements": [{"textRun": {"content": "# Markdown Heading"}}],
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                },
            },
        ]
    }
}
EXPECTED_HEADINGS: list[dict[str, Any]] = [
    {"level": 1, "text": "Chapter One", "start_index": 2},
    {"level": 2, "text": "Section", "start_index": 3},
    {"level": 1, "text": "Markdown Heading", "start_index": 4},
]


def test_google_docs_create_toc_full_pipeline_and_exact_execute_calls() -> None:
    tools, composio = _google_docs_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": DOCS_DOCUMENT},
        {"successful": True, "data": {"ok": True}},
    ]

    with patch(f"{GOOGLE_DOCS_MODULE}.log.set") as log_set:
        result = tools["CUSTOM_CREATE_TOC"](
            CreateTOCInput(document_id="doc-toc"),
            EXECUTE_REQUEST,
            GOOGLE_DOCS_AUTH,
        )

    toc_text = (
        "Table of Contents\n"
        "=================\n"
        "\n"
        "• Chapter One\n"
        "  ○ Section\n"
        "• Markdown Heading\n"
        "\n"
    )
    assert result == {
        "document_id": "doc-toc",
        "url": "https://docs.google.com/document/d/doc-toc/edit",
        "headings_found": 3,
        "toc_content": toc_text,
        "headings": EXPECTED_HEADINGS,
        "insert_response": {"ok": True},
    }
    log_set.assert_called_once_with(tool={"integration": "google_docs", "action": "create_toc"})
    assert composio.tools.execute.call_args_list == [
        call(
            slug="GOOGLEDOCS_GET_DOCUMENT_BY_ID",
            arguments={"id": "doc-toc"},
            version="v1",
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        ),
        call(
            slug="GOOGLEDOCS_INSERT_TEXT_ACTION",
            arguments={
                "document_id": "doc-toc",
                "text": toc_text,
                "insertion_index": 1,
            },
            version="v1",
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        ),
    ]


def test_google_docs_create_toc_parses_stringified_document_data() -> None:
    tools, composio = _google_docs_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": json.dumps(DOCS_DOCUMENT)},
        {"successful": True, "data": {"ok": True}},
    ]

    with patch(f"{GOOGLE_DOCS_MODULE}.log.set"):
        result = tools["CUSTOM_CREATE_TOC"](
            CreateTOCInput(document_id="doc-toc"),
            EXECUTE_REQUEST,
            GOOGLE_DOCS_AUTH,
        )

    assert result["headings"] == EXPECTED_HEADINGS
    assert result["headings_found"] == 3
    assert "• Chapter One" in result["toc_content"]


def test_google_docs_create_toc_invalid_json_logs_debug_and_raises() -> None:
    from app.constants.log_tags import LogTag

    tools, composio = _google_docs_tools()
    composio.tools.execute.side_effect = [{"successful": True, "data": "not-json"}]

    with (
        patch(f"{GOOGLE_DOCS_MODULE}.log.set"),
        patch(f"{GOOGLE_DOCS_MODULE}.log.debug") as debug_log,
        pytest.raises(ValueError) as excinfo,
    ):
        tools["CUSTOM_CREATE_TOC"](
            CreateTOCInput(document_id="doc-toc"),
            EXECUTE_REQUEST,
            GOOGLE_DOCS_AUTH,
        )

    assert str(excinfo.value) == "Failed to get document or document has no body content"
    debug_log.assert_called_once_with(
        f"{LogTag.TOOL} JSON parsing skipped for doc_data", error_type="JSONDecodeError"
    )


def test_google_docs_create_toc_document_without_body_raises() -> None:
    tools, composio = _google_docs_tools()
    composio.tools.execute.side_effect = [{"successful": True, "data": {"title": "x"}}]

    with (
        patch(f"{GOOGLE_DOCS_MODULE}.log.set"),
        pytest.raises(ValueError, match="Failed to get document or document has no body content"),
    ):
        tools["CUSTOM_CREATE_TOC"](
            CreateTOCInput(document_id="doc-toc"),
            EXECUTE_REQUEST,
            GOOGLE_DOCS_AUTH,
        )


def test_google_docs_create_toc_non_dict_data_raises_format_error() -> None:
    tools, composio = _google_docs_tools()
    composio.tools.execute.side_effect = [{"successful": True, "data": ["body"]}]

    with (
        patch(f"{GOOGLE_DOCS_MODULE}.log.set"),
        pytest.raises(ValueError) as excinfo,
    ):
        tools["CUSTOM_CREATE_TOC"](
            CreateTOCInput(document_id="doc-toc"),
            EXECUTE_REQUEST,
            GOOGLE_DOCS_AUTH,
        )

    assert str(excinfo.value) == "Document data is not in expected format"


def test_google_docs_create_toc_get_document_failure_raises() -> None:
    tools, composio = _google_docs_tools()
    composio.tools.execute.side_effect = [{"successful": False, "error": "no access"}]

    with (
        patch(f"{GOOGLE_DOCS_MODULE}.log.set"),
        pytest.raises(ValueError, match="Failed to get document: no access"),
    ):
        tools["CUSTOM_CREATE_TOC"](
            CreateTOCInput(document_id="doc-toc"),
            EXECUTE_REQUEST,
            GOOGLE_DOCS_AUTH,
        )


def test_google_docs_create_toc_execute_type_error_logged_and_reraised() -> None:
    from app.constants.log_tags import LogTag

    tools, composio = _google_docs_tools()
    composio.tools.execute.side_effect = TypeError("bad version")

    with (
        patch(f"{GOOGLE_DOCS_MODULE}.log.set"),
        patch(f"{GOOGLE_DOCS_MODULE}.log.debug") as debug_log,
        pytest.raises(TypeError, match="bad version"),
    ):
        tools["CUSTOM_CREATE_TOC"](
            CreateTOCInput(document_id="doc-toc"),
            EXECUTE_REQUEST,
            GOOGLE_DOCS_AUTH,
        )

    debug_log.assert_called_once_with(
        f"{LogTag.TOOL} TypeError in execute", error_type="TypeError"
    )


def test_google_docs_create_toc_insert_failure_raises() -> None:
    tools, composio = _google_docs_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": DOCS_DOCUMENT},
        {"successful": False, "error": "insert boom"},
    ]

    with (
        patch(f"{GOOGLE_DOCS_MODULE}.log.set"),
        pytest.raises(ValueError, match="Failed to insert text: insert boom"),
    ):
        tools["CUSTOM_CREATE_TOC"](
            CreateTOCInput(document_id="doc-toc"),
            EXECUTE_REQUEST,
            GOOGLE_DOCS_AUTH,
        )


def test_google_docs_create_toc_insert_response_passed_through_verbatim() -> None:
    tools, composio = _google_docs_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": DOCS_DOCUMENT},
        {"successful": True, "data": "plain string response"},
    ]

    with patch(f"{GOOGLE_DOCS_MODULE}.log.set"):
        result = tools["CUSTOM_CREATE_TOC"](
            CreateTOCInput(document_id="doc-toc"),
            EXECUTE_REQUEST,
            GOOGLE_DOCS_AUTH,
        )

    assert result["insert_response"] == "plain string response"


def test_google_docs_create_toc_include_heading_levels_filters_headings() -> None:
    tools, composio = _google_docs_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": DOCS_DOCUMENT},
        {"successful": True, "data": {"ok": True}},
    ]

    with patch(f"{GOOGLE_DOCS_MODULE}.log.set"):
        result = tools["CUSTOM_CREATE_TOC"](
            CreateTOCInput(document_id="doc-toc", include_heading_levels=[1]),
            EXECUTE_REQUEST,
            GOOGLE_DOCS_AUTH,
        )

    assert result["headings"] == [
        {"level": 1, "text": "Chapter One", "start_index": 2},
        {"level": 1, "text": "Markdown Heading", "start_index": 4},
    ]
    assert result["headings_found"] == 2
    assert "  ○ Section" not in result["toc_content"]


def test_google_docs_create_toc_no_headings_still_inserts_placeholder() -> None:
    tools, composio = _google_docs_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": {"body": {"content": []}}},
        {"successful": True, "data": {"ok": True}},
    ]

    with patch(f"{GOOGLE_DOCS_MODULE}.log.set"):
        result = tools["CUSTOM_CREATE_TOC"](
            CreateTOCInput(document_id="doc-toc", title="My TOC"),
            EXECUTE_REQUEST,
            GOOGLE_DOCS_AUTH,
        )

    assert result["headings"] == []
    assert result["headings_found"] == 0
    assert result["toc_content"] == "My TOC\n\n(No headings found in document)\n\n"
    insert_args = composio.tools.execute.call_args_list[1].kwargs["arguments"]
    assert insert_args["text"] == "My TOC\n\n(No headings found in document)\n\n"


# --- CUSTOM_DELETE_DOC --------------------------------------------------------


def test_google_docs_delete_doc_exact_proxy_call_and_result() -> None:
    with (
        patch(f"{GOOGLE_DOCS_MODULE}.proxy_request_sync") as proxy,
        patch(f"{GOOGLE_DOCS_MODULE}.log.set") as log_set,
    ):
        tools, _composio = _google_docs_tools()
        result = tools["CUSTOM_DELETE_DOC"](
            DeleteDocInput(document_id="doc-del"),
            EXECUTE_REQUEST,
            GOOGLE_DOCS_AUTH,
        )

    assert result == {"successful": True, "document_id": "doc-del"}
    log_set.assert_called_once_with(tool={"integration": "google_docs", "action": "delete_doc"})
    proxy.assert_called_once_with(
        user_id="user_test_123",
        toolkit="GOOGLEDOCS",
        endpoint="https://www.googleapis.com/drive/v3/files/doc-del",
        method="DELETE",
    )


def test_google_docs_delete_doc_app_error_logged_and_wrapped() -> None:
    from app.constants.log_tags import LogTag
    from app.utils.errors import AppError

    with (
        patch(
            f"{GOOGLE_DOCS_MODULE}.proxy_request_sync",
            side_effect=AppError(message="gone", status_code=404),
        ),
        patch(f"{GOOGLE_DOCS_MODULE}.log.error") as err_log,
        patch(f"{GOOGLE_DOCS_MODULE}.log.set"),
    ):
        tools, _composio = _google_docs_tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools["CUSTOM_DELETE_DOC"](
                DeleteDocInput(document_id="doc-del"),
                EXECUTE_REQUEST,
                GOOGLE_DOCS_AUTH,
            )

    assert str(excinfo.value) == "Failed to delete document: 404 - gone"
    err_log.assert_called_once_with(
        f"{LogTag.TOOL} Error deleting doc",
        document_id="doc-del",
        error_type="AppError",
    )


def test_google_docs_delete_doc_missing_user_id_rejected_before_proxy() -> None:
    with patch(f"{GOOGLE_DOCS_MODULE}.proxy_request_sync") as proxy:
        tools, _composio = _google_docs_tools()
        with pytest.raises(ValueError, match="Missing user_id in auth_credentials"):
            tools["CUSTOM_DELETE_DOC"](
                DeleteDocInput(document_id="doc-del"),
                EXECUTE_REQUEST,
                {},
            )

    proxy.assert_not_called()


# --- CUSTOM_GATHER_CONTEXT ----------------------------------------------------


def test_google_docs_gather_context_exact_proxy_call_and_field_mapping() -> None:
    with (
        patch(
            f"{GOOGLE_DOCS_MODULE}.proxy_request_sync",
            return_value={
                "files": [
                    {
                        "id": "f1",
                        "name": "Doc One",
                        "modifiedTime": "2026-01-01T00:00:00Z",
                        "webViewLink": "https://docs.google.com/document/d/f1/edit",
                    },
                    {"id": "f2", "name": "Doc Two"},
                ]
            },
        ) as proxy,
        patch(f"{GOOGLE_DOCS_MODULE}.log.set") as log_set,
    ):
        tools, _composio = _google_docs_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, GOOGLE_DOCS_AUTH
        )

    assert result == {
        "recent_docs": [
            {
                "id": "f1",
                "name": "Doc One",
                "modified": "2026-01-01T00:00:00Z",
                "url": "https://docs.google.com/document/d/f1/edit",
            },
            {"id": "f2", "name": "Doc Two", "modified": None, "url": None},
        ],
        "doc_count": 2,
    }
    log_set.assert_called_once_with(
        tool={"integration": "google_docs", "action": "gather_context"}
    )
    proxy.assert_called_once_with(
        user_id="user_test_123",
        toolkit="GOOGLEDOCS",
        endpoint="https://www.googleapis.com/drive/v3/files",
        method="GET",
        query={
            "q": "mimeType='application/vnd.google-apps.document'",
            "orderBy": "viewedByMeTime desc",
            "pageSize": 20,
            "fields": "files(id,name,modifiedTime,webViewLink)",
        },
    )


def test_google_docs_gather_context_none_response_becomes_empty() -> None:
    with (
        patch(f"{GOOGLE_DOCS_MODULE}.proxy_request_sync", return_value=None) as proxy,
        patch(f"{GOOGLE_DOCS_MODULE}.log.set"),
    ):
        tools, _composio = _google_docs_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, GOOGLE_DOCS_AUTH
        )

    assert result == {"recent_docs": [], "doc_count": 0}
    proxy.assert_called_once()


def test_google_docs_gather_context_missing_files_key_is_not_an_error() -> None:
    """A response without a ``files`` key yields an empty list — and must NOT
    take the failure path (no debug log), which is what a ``.get("files", None)``
    regression would do: iterating ``None`` raises, gets swallowed, and the
    debug log fires."""
    with (
        patch(f"{GOOGLE_DOCS_MODULE}.proxy_request_sync", return_value={}) as proxy,
        patch(f"{GOOGLE_DOCS_MODULE}.log.set"),
        patch(f"{GOOGLE_DOCS_MODULE}.log.debug") as debug_log,
    ):
        tools, _composio = _google_docs_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, GOOGLE_DOCS_AUTH
        )

    assert result == {"recent_docs": [], "doc_count": 0}
    proxy.assert_called_once()
    debug_log.assert_not_called()


def test_google_docs_gather_context_app_error_logged_and_returns_empty() -> None:
    from app.constants.log_tags import LogTag
    from app.utils.errors import AppError

    with (
        patch(
            f"{GOOGLE_DOCS_MODULE}.proxy_request_sync",
            side_effect=AppError(message="docs down", status_code=503),
        ),
        patch(f"{GOOGLE_DOCS_MODULE}.log.set"),
        patch(f"{GOOGLE_DOCS_MODULE}.log.debug") as debug_log,
    ):
        tools, _composio = _google_docs_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, GOOGLE_DOCS_AUTH
        )

    assert result == {"recent_docs": [], "doc_count": 0}
    debug_log.assert_called_once_with(
        f"{LogTag.TOOL} Google Docs fetch failed", error_type="AppError"
    )


def test_google_docs_gather_context_generic_exception_logged_and_returns_empty() -> None:
    from app.constants.log_tags import LogTag

    with (
        patch(
            f"{GOOGLE_DOCS_MODULE}.proxy_request_sync",
            side_effect=RuntimeError("boom"),
        ),
        patch(f"{GOOGLE_DOCS_MODULE}.log.set"),
        patch(f"{GOOGLE_DOCS_MODULE}.log.debug") as debug_log,
    ):
        tools, _composio = _google_docs_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, GOOGLE_DOCS_AUTH
        )

    assert result == {"recent_docs": [], "doc_count": 0}
    debug_log.assert_called_once_with(
        f"{LogTag.TOOL} Google Docs fetch failed", error_type="RuntimeError"
    )


def test_google_docs_gather_context_missing_user_id_rejected_before_proxy() -> None:
    with patch(f"{GOOGLE_DOCS_MODULE}.proxy_request_sync") as proxy:
        tools, _composio = _google_docs_tools()
        with pytest.raises(ValueError, match="Missing user_id in auth_credentials"):
            tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, {})

    proxy.assert_not_called()


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


# --- registration -----------------------------------------------------------


def test_notion_register_returns_expected_tool_names() -> None:
    from app.agents.tools.integrations.notion_tool import (
        register_notion_custom_tools,
    )

    assert register_notion_custom_tools(MagicMock()) == [
        "NOTION_MOVE_PAGE",
        "NOTION_FETCH_PAGE_AS_MARKDOWN",
        "NOTION_INSERT_MARKDOWN",
        "NOTION_FETCH_DATA",
        "NOTION_CUSTOM_GATHER_CONTEXT",
    ]


# --- _user_id ----------------------------------------------------------------


@pytest.mark.parametrize(
    "creds",
    [{}, {"user_id": ""}, {"user_id": None}, {"user_id": 123}],
    ids=["missing", "empty", "none", "not-a-string"],
)
def test_notion_user_id_rejects_invalid_credentials(creds: dict[str, Any]) -> None:
    from app.agents.tools.integrations.notion_tool import _user_id

    with pytest.raises(ValueError) as excinfo:
        _user_id(creds)
    assert str(excinfo.value) == "Missing user_id in auth_credentials"


def test_notion_user_id_returns_credentials_user_id() -> None:
    from app.agents.tools.integrations.notion_tool import _user_id

    assert _user_id({"user_id": "user-1"}) == "user-1"


# --- MOVE_PAGE ---------------------------------------------------------------


NOTION_MODULE = "app.agents.tools.integrations.notion_tool"
NOTION_AUTH_CREDS: dict[str, Any] = {"user_id": "user_test_123", "version": "v1"}


def _notion_tools() -> tuple[dict[str, Any], MagicMock]:
    """Register notion tools; return (captured tools, composio mock)."""
    from app.agents.tools.integrations.notion_tool import (
        register_notion_custom_tools,
    )

    tools: dict[str, Any] = {}
    composio = MagicMock()

    def custom_tool(**_kwargs: Any) -> Callable[[Any], Any]:
        def decorator(fn: Any) -> Any:
            tools[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    register_notion_custom_tools(composio)
    return tools, composio


def test_notion_move_page_page_id_parent_exact_proxy_call() -> None:
    tools, _composio = _notion_tools()
    execute_request = MagicMock()
    execute_request.return_value.data = {"id": "page-1", "url": "https://notion.so/p1"}

    with patch(f"{NOTION_MODULE}.log.set") as log_set:
        result = tools["MOVE_PAGE"](
            MovePageInput(page_id="page-1", parent_id="parent-1", parent_type="page_id"),
            execute_request,
            NOTION_AUTH_CREDS,
        )

    assert result == {
        "page_id": "page-1",
        "new_parent": {"type": "page_id", "page_id": "parent-1"},
        "url": "https://notion.so/p1",
    }
    execute_request.assert_called_once_with(
        endpoint="/pages/page-1",
        method="PATCH",
        body={"parent": {"type": "page_id", "page_id": "parent-1"}},
    )
    log_set.assert_called_once_with(tool={"integration": "notion", "action": "move_page"})


def test_notion_move_page_database_id_parent() -> None:
    tools, _composio = _notion_tools()
    execute_request = MagicMock()
    execute_request.return_value.data = {"id": "page-1", "url": "https://notion.so/p1"}

    result = tools["MOVE_PAGE"](
        MovePageInput(page_id="page-1", parent_id="db-1", parent_type="database_id"),
        execute_request,
        NOTION_AUTH_CREDS,
    )

    assert result["new_parent"] == {"type": "database_id", "database_id": "db-1"}
    execute_request.assert_called_once_with(
        endpoint="/pages/page-1",
        method="PATCH",
        body={"parent": {"type": "database_id", "database_id": "db-1"}},
    )


def test_notion_move_page_uses_plain_response_without_data_attribute() -> None:
    tools, _composio = _notion_tools()
    execute_request = MagicMock()
    execute_request.return_value = {"id": "page-1", "url": "https://notion.so/p1"}

    result = tools["MOVE_PAGE"](
        MovePageInput(page_id="page-1", parent_id="parent-1", parent_type="page_id"),
        execute_request,
        NOTION_AUTH_CREDS,
    )

    assert result["page_id"] == "page-1"
    assert result["url"] == "https://notion.so/p1"


def test_notion_move_page_missing_response_fields_default_to_none() -> None:
    tools, _composio = _notion_tools()
    execute_request = MagicMock()
    execute_request.return_value.data = {}

    result = tools["MOVE_PAGE"](
        MovePageInput(page_id="page-1", parent_id="parent-1", parent_type="page_id"),
        execute_request,
        NOTION_AUTH_CREDS,
    )

    assert result == {
        "page_id": None,
        "new_parent": {"type": "page_id", "page_id": "parent-1"},
        "url": None,
    }


def test_notion_move_page_real_response_object_with_data_attribute() -> None:
    """A real response object (not a MagicMock) must have its ``data``
    attribute read — MagicMock makes ``hasattr`` true for every name, so the
    data-vs-raw-response branch needs a concrete object to discriminate."""
    from types import SimpleNamespace

    tools, _composio = _notion_tools()
    execute_request = MagicMock()
    execute_request.return_value = SimpleNamespace(
        data={"id": "page-1", "url": "https://notion.so/p1"}
    )

    result = tools["MOVE_PAGE"](
        MovePageInput(page_id="page-1", parent_id="parent-1", parent_type="page_id"),
        execute_request,
        NOTION_AUTH_CREDS,
    )

    assert result == {
        "page_id": "page-1",
        "new_parent": {"type": "page_id", "page_id": "parent-1"},
        "url": "https://notion.so/p1",
    }
    execute_request.assert_called_once()


# --- FETCH_PAGE_AS_MARKDOWN --------------------------------------------------


def test_notion_fetch_page_as_markdown_converts_blocks_and_prepends_title() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {
            "successful": True,
            "data": {"results": [{"type": "title", "title": {"plain_text": "My Page"}}]},
        },
        {
            "successful": True,
            "data": {"results": [{"type": "paragraph"}, {"type": "paragraph"}]},
        },
    ]

    with (
        patch(f"{NOTION_MODULE}.blocks_to_markdown", return_value="converted") as to_md,
        patch(f"{NOTION_MODULE}.log.set") as log_set,
    ):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(
                page_id="page-1", recursive=False, include_block_ids=False
            ),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result == {
        "page_id": "page-1",
        "title": "My Page",
        "markdown": "# My Page\n\nconverted",
        "block_count": 2,
    }
    to_md.assert_called_once_with(
        [{"type": "paragraph"}, {"type": "paragraph"}], include_block_ids=False
    )
    log_set.assert_called_once_with(
        tool={"integration": "notion", "action": "fetch_page_as_markdown"}
    )
    assert composio.tools.execute.call_args_list == [
        call(
            slug="NOTION_GET_PAGE_PROPERTY_ACTION",
            arguments={"page_id": "page-1", "property_id": "title"},
            version="v1",
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        ),
        call(
            slug="NOTION_FETCH_ALL_BLOCK_CONTENTS",
            arguments={"block_id": "page-1", "recursive": False, "page_size": 100},
            version="v1",
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        ),
    ]


def test_notion_fetch_page_as_markdown_takes_first_title_and_breaks() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {
            "successful": True,
            "data": {
                "results": [
                    {"type": "title", "title": {"plain_text": "First"}},
                    {"type": "title", "title": {"plain_text": "Second"}},
                ]
            },
        },
        {"successful": True, "data": {"results": []}},
    ]

    with patch(f"{NOTION_MODULE}.blocks_to_markdown", return_value=""):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["title"] == "First"
    assert result["markdown"] == "# First\n\n"
    assert result["block_count"] == 0


def test_notion_fetch_page_as_markdown_skips_items_without_title_text() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {
            "successful": True,
            "data": {
                "results": [
                    {"type": "paragraph", "title": {"plain_text": "not a title"}},
                    {"type": "title", "title": {}},
                    {"type": "title", "title": {"plain_text": "Real"}},
                ]
            },
        },
        {"successful": True, "data": {"results": []}},
    ]

    with patch(f"{NOTION_MODULE}.blocks_to_markdown", return_value=""):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["title"] == "Real"


def test_notion_fetch_page_as_markdown_empty_plain_text_title() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {
            "successful": True,
            "data": {"results": [{"type": "title", "title": {"plain_text": ""}}]},
        },
        {"successful": True, "data": {"results": []}},
    ]

    with patch(f"{NOTION_MODULE}.blocks_to_markdown", return_value="md"):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["title"] == ""
    assert result["markdown"] == "md"


def test_notion_fetch_page_as_markdown_title_without_plain_text_key() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {
            "successful": True,
            "data": {"results": [{"type": "title", "title": {"type": "text"}}]},
        },
        {"successful": True, "data": {"results": []}},
    ]

    with patch(f"{NOTION_MODULE}.blocks_to_markdown", return_value="md"):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result == {
        "page_id": "page-1",
        "title": "",
        "markdown": "md",
        "block_count": 0,
    }


def test_notion_fetch_page_as_markdown_title_data_not_a_dict() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": "unexpected"},
        {"successful": True, "data": {"results": []}},
    ]

    with (
        patch(f"{NOTION_MODULE}.blocks_to_markdown", return_value=""),
        patch(f"{NOTION_MODULE}.log.warning") as warn,
    ):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["title"] == ""
    warn.assert_not_called()


def test_notion_fetch_page_as_markdown_title_response_without_results() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": {}},
        {"successful": True, "data": {"results": []}},
    ]

    with (
        patch(f"{NOTION_MODULE}.blocks_to_markdown", return_value=""),
        patch(f"{NOTION_MODULE}.log.warning") as warn,
    ):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["title"] == ""
    warn.assert_not_called()


def test_notion_fetch_page_as_markdown_title_failure_logs_and_continues() -> None:
    from app.constants.log_tags import LogTag

    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": False, "error": "boom"},
        {"successful": True, "data": {"results": []}},
    ]

    with (
        patch(f"{NOTION_MODULE}.blocks_to_markdown", return_value=""),
        patch(f"{NOTION_MODULE}.log.warning") as warn,
    ):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["title"] == ""
    assert result["markdown"] == ""
    warn.assert_called_once_with(f"{LogTag.TOOL} Failed to fetch title", error="boom")


def test_notion_fetch_page_as_markdown_title_exception_logged_blocks_still_fetched() -> None:
    from app.constants.log_tags import LogTag

    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        RuntimeError("title api down"),
        {"successful": True, "data": {"results": []}},
    ]

    with (
        patch(f"{NOTION_MODULE}.blocks_to_markdown", return_value=""),
        patch(f"{NOTION_MODULE}.log.warning") as warn,
    ):
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["title"] == ""
    assert composio.tools.execute.call_count == 2
    warn.assert_called_once_with(
        f"{LogTag.TOOL} Could not fetch title", error_type="RuntimeError"
    )


def test_notion_fetch_page_as_markdown_blocks_failure_raises() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": {"results": []}},
        {"successful": False, "error": "blocks boom"},
    ]

    with patch(f"{NOTION_MODULE}.blocks_to_markdown", return_value=""):
        with pytest.raises(ValueError, match="Failed to fetch blocks: blocks boom"):
            tools["FETCH_PAGE_AS_MARKDOWN"](
                FetchPageAsMarkdownInput(page_id="page-1"),
                EXECUTE_REQUEST,
                NOTION_AUTH_CREDS,
            )


def test_notion_fetch_page_as_markdown_blocks_fallback_key() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": {"results": []}},
        {"successful": True, "data": {"blocks": [{"type": "paragraph"}]}},
    ]

    with patch(f"{NOTION_MODULE}.blocks_to_markdown", return_value="md") as to_md:
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["block_count"] == 1
    to_md.assert_called_once_with([{"type": "paragraph"}], include_block_ids=True)


def test_notion_fetch_page_as_markdown_blocks_data_not_a_dict() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": {"results": []}},
        {"successful": True, "data": "unexpected"},
    ]

    with patch(f"{NOTION_MODULE}.blocks_to_markdown", return_value="md") as to_md:
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["markdown"] == "md"
    assert result["block_count"] == 0
    to_md.assert_called_once_with([], include_block_ids=True)


def test_notion_fetch_page_as_markdown_blocks_results_not_a_list() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": {"results": []}},
        {"successful": True, "data": {"results": "nope"}},
    ]

    with patch(f"{NOTION_MODULE}.blocks_to_markdown", return_value="md") as to_md:
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["markdown"] == ""
    assert result["block_count"] == 0
    to_md.assert_not_called()


def test_notion_fetch_page_as_markdown_blocks_data_without_keys() -> None:
    tools, composio = _notion_tools()
    composio.tools.execute.side_effect = [
        {"successful": True, "data": {"results": []}},
        {"successful": True, "data": {}},
    ]

    with patch(f"{NOTION_MODULE}.blocks_to_markdown", return_value="md") as to_md:
        result = tools["FETCH_PAGE_AS_MARKDOWN"](
            FetchPageAsMarkdownInput(page_id="page-1"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result == {
        "page_id": "page-1",
        "title": "",
        "markdown": "md",
        "block_count": 0,
    }
    to_md.assert_called_once_with([], include_block_ids=True)


# --- INSERT_MARKDOWN ---------------------------------------------------------


def test_notion_insert_markdown_empty_conversion_raises() -> None:
    tools, _composio = _notion_tools()

    with patch(f"{NOTION_MODULE}.markdown_to_notion_blocks", return_value=[]):
        with pytest.raises(ValueError) as excinfo:
            tools["INSERT_MARKDOWN"](
                InsertMarkdownInput(parent_block_id="parent-1", markdown="# hi"),
                EXECUTE_REQUEST,
                NOTION_AUTH_CREDS,
            )
    assert str(excinfo.value) == "No content to insert - markdown conversion produced no blocks"


def test_notion_insert_markdown_passes_exact_markdown_to_conversion() -> None:
    tools, composio = _notion_tools()
    blocks = [{"type": "paragraph", "content": "a"}]
    composio.tools.execute.side_effect = [{"successful": True}]

    def _convert(markdown: str) -> list[dict[str, Any]]:
        assert markdown == "exact markdown", f"conversion got {markdown!r}"
        return blocks

    with patch(f"{NOTION_MODULE}.markdown_to_notion_blocks", side_effect=_convert):
        tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="exact markdown"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )


def test_notion_insert_markdown_mixed_table_and_blocks_with_after() -> None:
    tools, composio = _notion_tools()
    blocks = [
        {"type": "table", "table_width": 2, "has_column_header": False, "rows": [["a", "b"]]},
        {"type": "paragraph", "rich_text": [{"type": "text", "text": {"content": "hi"}}]},
    ]
    composio.tools.execute.side_effect = [{"successful": True}, {"successful": True}]

    with (
        patch(f"{NOTION_MODULE}.markdown_to_notion_blocks", return_value=blocks),
        patch(f"{NOTION_MODULE}.log.set") as log_set,
    ):
        result = tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md", after="after-1"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result == {
        "parent_block_id": "parent-1",
        "blocks_added": 2,
        "tables_added": 1,
        "after": "after-1",
    }
    log_set.assert_called_once_with(tool={"integration": "notion", "action": "insert_markdown"})
    assert composio.tools.execute.call_args_list == [
        call(
            slug="NOTION_APPEND_TABLE_BLOCKS",
            arguments={
                "block_id": "parent-1",
                "table_width": 2,
                "has_column_header": False,
                "rows": [["a", "b"]],
            },
            version="v1",
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        ),
        call(
            slug="NOTION_ADD_MULTIPLE_PAGE_CONTENT",
            arguments={
                "parent_block_id": "parent-1",
                "content_blocks": [blocks[1]],
                "after": "after-1",
            },
            version="v1",
            dangerously_skip_version_check=True,
            user_id="user_test_123",
        ),
    ]


def test_notion_insert_markdown_after_applies_to_first_content_block_only() -> None:
    tools, composio = _notion_tools()
    blocks = [
        {"type": "paragraph", "content": "a"},
        {"type": "paragraph", "content": "b"},
    ]
    composio.tools.execute.side_effect = [{"successful": True}, {"successful": True}]

    with patch(f"{NOTION_MODULE}.markdown_to_notion_blocks", return_value=blocks):
        result = tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md", after="after-1"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["blocks_added"] == 2
    first, second = composio.tools.execute.call_args_list
    assert first.kwargs["arguments"]["after"] == "after-1"
    assert "after" not in second.kwargs["arguments"]


def test_notion_insert_markdown_after_not_consumed_by_tables() -> None:
    tools, composio = _notion_tools()
    blocks = [
        {"type": "table", "table_width": 1, "rows": [["x"]]},
        {"type": "paragraph", "content": "a"},
        {"type": "paragraph", "content": "b"},
    ]
    composio.tools.execute.side_effect = [{"successful": True}] * 3

    with patch(f"{NOTION_MODULE}.markdown_to_notion_blocks", return_value=blocks):
        tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md", after="after-1"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    table_call, para_a, para_b = composio.tools.execute.call_args_list
    assert "after" not in table_call.kwargs["arguments"]
    assert para_a.kwargs["arguments"]["after"] == "after-1"
    assert "after" not in para_b.kwargs["arguments"]


def test_notion_insert_markdown_without_after_omits_key() -> None:
    tools, composio = _notion_tools()
    blocks = [{"type": "paragraph", "content": "a"}]
    composio.tools.execute.side_effect = [{"successful": True}]

    with patch(f"{NOTION_MODULE}.markdown_to_notion_blocks", return_value=blocks):
        tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    call_args = composio.tools.execute.call_args_list[0]
    assert "after" not in call_args.kwargs["arguments"]


def test_notion_insert_markdown_table_defaults_has_column_header_true() -> None:
    tools, composio = _notion_tools()
    blocks = [{"type": "table", "table_width": 1, "rows": [["x"]]}]
    composio.tools.execute.side_effect = [{"successful": True}]

    with patch(f"{NOTION_MODULE}.markdown_to_notion_blocks", return_value=blocks):
        tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    args = composio.tools.execute.call_args_list[0].kwargs["arguments"]
    assert args["has_column_header"] is True


def test_notion_insert_markdown_tables_added_counts_all_tables() -> None:
    tools, composio = _notion_tools()
    blocks = [
        {"type": "table", "table_width": 1, "rows": [["a"]]},
        {"type": "table", "table_width": 2, "rows": [["b", "c"]]},
    ]
    composio.tools.execute.side_effect = [{"successful": True}, {"successful": True}]

    with patch(f"{NOTION_MODULE}.markdown_to_notion_blocks", return_value=blocks):
        result = tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["blocks_added"] == 2
    assert result["tables_added"] == 2
    assert [c.kwargs["slug"] for c in composio.tools.execute.call_args_list] == [
        "NOTION_APPEND_TABLE_BLOCKS",
        "NOTION_APPEND_TABLE_BLOCKS",
    ]


def test_notion_insert_markdown_table_failure_raises() -> None:
    tools, composio = _notion_tools()
    blocks = [{"type": "table", "table_width": 1, "rows": [["x"]]}]
    composio.tools.execute.side_effect = [{"successful": False, "error": "table boom"}]

    with (
        patch(f"{NOTION_MODULE}.markdown_to_notion_blocks", return_value=blocks),
        pytest.raises(ValueError, match="Failed to insert table: table boom"),
    ):
        tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )


def test_notion_insert_markdown_content_failure_raises() -> None:
    tools, composio = _notion_tools()
    blocks = [{"type": "paragraph", "content": "a"}]
    composio.tools.execute.side_effect = [{"successful": False, "error": "content boom"}]

    with (
        patch(f"{NOTION_MODULE}.markdown_to_notion_blocks", return_value=blocks),
        pytest.raises(ValueError, match="Failed to insert markdown: content boom"),
    ):
        tools["INSERT_MARKDOWN"](
            InsertMarkdownInput(parent_block_id="parent-1", markdown="md"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )


# --- FETCH_DATA --------------------------------------------------------------


def test_notion_fetch_data_exact_proxy_call_and_empty_result() -> None:
    with (
        patch(f"{NOTION_MODULE}.proxy_request_sync") as proxy,
        patch(f"{NOTION_MODULE}.log.set") as log_set,
    ):
        proxy.return_value = {"results": [], "has_more": False}
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages", page_size=100),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result == {"values": [], "count": 0, "has_more": False}
    log_set.assert_called_once_with(tool={"integration": "notion", "action": "fetch_data"})
    proxy.assert_called_once_with(
        user_id="user_test_123",
        toolkit="NOTION",
        endpoint="https://api.notion.com/v1/search",
        method="POST",
        body={
            "filter": {"property": "object", "value": "page"},
            "page_size": 100,
        },
        headers={"Notion-Version": "2022-06-28"},
    )


@pytest.mark.parametrize(
    "fetch_type, filter_value",
    [("pages", "page"), ("databases", "database")],
    ids=["pages", "databases"],
)
def test_notion_fetch_data_filter_value_derived_from_fetch_type(
    fetch_type: str, filter_value: str
) -> None:
    with patch(f"{NOTION_MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {"results": [], "has_more": False}
        tools, _composio = _notion_tools()
        tools["FETCH_DATA"](
            FetchDataInput(fetch_type=fetch_type),  # type: ignore[arg-type]
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert proxy.call_args.kwargs["body"]["filter"] == {
        "property": "object",
        "value": filter_value,
    }


@pytest.mark.parametrize(
    "page_size, expected",
    [(50, 50), (100, 100), (500, 100), (0, 0)],
    ids=["under-cap", "at-cap", "over-cap", "zero"],
)
def test_notion_fetch_data_page_size_capped_at_100(
    page_size: int, expected: int
) -> None:
    with patch(f"{NOTION_MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {"results": [], "has_more": False}
        tools, _composio = _notion_tools()
        tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages", page_size=page_size),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert proxy.call_args.kwargs["body"]["page_size"] == expected


def test_notion_fetch_data_with_query() -> None:
    with patch(f"{NOTION_MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {"results": [], "has_more": False}
        tools, _composio = _notion_tools()
        tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages", query="roadmap"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert proxy.call_args.kwargs["body"] == {
        "filter": {"property": "object", "value": "page"},
        "page_size": 100,
        "query": "roadmap",
    }


def test_notion_fetch_data_without_query() -> None:
    with patch(f"{NOTION_MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {"results": [{"id": "page-1", "object": "page", "properties": {}}]}
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert proxy.call_args.kwargs["body"] == {
        "filter": {"property": "object", "value": "page"},
        "page_size": 100,
    }
    assert result == {
        "values": [{"id": "page-1", "title": "Untitled", "type": "page"}],
        "count": 1,
        "has_more": False,
    }


def test_notion_fetch_data_extracts_database_title_and_has_more() -> None:
    with patch(f"{NOTION_MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [
                {"id": "db-1", "object": "database", "title": [{"plain_text": "Roadmap"}]},
                {"id": "db-2", "object": "database", "title": []},
            ],
            "has_more": True,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="databases"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result == {
        "values": [
            {"id": "db-1", "title": "Roadmap", "type": "database"},
            {"id": "db-2", "title": "Untitled", "type": "database"},
        ],
        "count": 2,
        "has_more": True,
    }


def test_notion_fetch_data_database_title_missing_plain_text_defaults() -> None:
    with patch(f"{NOTION_MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [{"id": "db-1", "object": "database", "title": [{}]}],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="databases"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["values"] == [{"id": "db-1", "title": "Untitled", "type": "database"}]


def test_notion_fetch_data_extracts_page_title_from_properties() -> None:
    with patch(f"{NOTION_MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [
                {
                    "id": "page-1",
                    "object": "page",
                    "properties": {
                        "Status": {"type": "select", "select": {"name": "Done"}},
                        "Name": {"type": "title", "title": [{"plain_text": "Deep dive"}]},
                    },
                }
            ],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["values"] == [
        {"id": "page-1", "title": "Deep dive", "type": "page"}
    ]
    assert result["count"] == 1


def test_notion_fetch_data_uses_first_title_property_only() -> None:
    with patch(f"{NOTION_MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [
                {
                    "id": "page-1",
                    "object": "page",
                    "properties": {
                        "Name": {"type": "title", "title": [{"plain_text": "First"}]},
                        "Other": {"type": "title", "title": [{"plain_text": "Second"}]},
                    },
                }
            ],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["values"][0]["title"] == "First"


def test_notion_fetch_data_untitled_page_without_title_property() -> None:
    with patch(f"{NOTION_MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [
                {
                    "id": "page-1",
                    "object": "page",
                    "properties": {
                        "Status": {"type": "select", "select": {"name": "Done"}},
                        "Tags": {"type": "multi_select", "multi_select": []},
                    },
                }
            ],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["values"][0]["title"] == "Untitled"


def test_notion_fetch_data_page_without_properties_key() -> None:
    with patch(f"{NOTION_MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [{"id": "page-1", "object": "page"}],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["values"] == [{"id": "page-1", "title": "Untitled", "type": "page"}]


def test_notion_fetch_data_page_title_missing_plain_text_defaults() -> None:
    with patch(f"{NOTION_MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [
                {
                    "id": "page-1",
                    "object": "page",
                    "properties": {"Name": {"type": "title", "title": [{}]}},
                }
            ],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result["values"] == [{"id": "page-1", "title": "Untitled", "type": "page"}]


def test_notion_fetch_data_skips_items_without_id() -> None:
    with patch(f"{NOTION_MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {
            "results": [
                {"object": "page", "properties": {}},
                {"id": "page-1", "object": "page", "properties": {}},
            ],
            "has_more": False,
        }
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result == {
        "values": [{"id": "page-1", "title": "Untitled", "type": "page"}],
        "count": 1,
        "has_more": False,
    }


def test_notion_fetch_data_none_response_becomes_empty() -> None:
    with patch(f"{NOTION_MODULE}.proxy_request_sync", return_value=None) as proxy:
        tools, _composio = _notion_tools()
        result = tools["FETCH_DATA"](
            FetchDataInput(fetch_type="pages"),
            EXECUTE_REQUEST,
            NOTION_AUTH_CREDS,
        )

    assert result == {"values": [], "count": 0, "has_more": False}
    proxy.assert_called_once()


def test_notion_fetch_data_app_error_wrapped_in_runtime_error() -> None:
    from app.constants.log_tags import LogTag
    from app.utils.errors import AppError

    with (
        patch(
            f"{NOTION_MODULE}.proxy_request_sync",
            side_effect=AppError(message="notion 429"),
        ),
        patch(f"{NOTION_MODULE}.log.error") as err_log,
    ):
        tools, _composio = _notion_tools()
        with pytest.raises(RuntimeError, match="Failed to fetch pages: notion 429"):
            tools["FETCH_DATA"](
                FetchDataInput(fetch_type="pages"),
                EXECUTE_REQUEST,
                NOTION_AUTH_CREDS,
            )

    err_log.assert_called_once_with(
        f"{LogTag.TOOL} Notion API error", error_type="AppError"
    )


def test_notion_fetch_data_generic_error_wrapped_in_runtime_error() -> None:
    from app.constants.log_tags import LogTag

    with (
        patch(
            f"{NOTION_MODULE}.proxy_request_sync",
            side_effect=RuntimeError("api down"),
        ),
        patch(f"{NOTION_MODULE}.log.error") as err_log,
    ):
        tools, _composio = _notion_tools()
        with pytest.raises(RuntimeError, match="Failed to fetch pages: api down"):
            tools["FETCH_DATA"](
                FetchDataInput(fetch_type="pages"),
                EXECUTE_REQUEST,
                NOTION_AUTH_CREDS,
            )

    err_log.assert_called_once_with(
        f"{LogTag.TOOL} Error fetching from Notion",
        fetch_type="pages",
        error_type="RuntimeError",
    )


def test_notion_fetch_data_missing_user_id_rejected_before_proxy() -> None:
    with patch(f"{NOTION_MODULE}.proxy_request_sync") as proxy:
        tools, _composio = _notion_tools()
        with pytest.raises(ValueError, match="Missing user_id in auth_credentials"):
            tools["FETCH_DATA"](
                FetchDataInput(fetch_type="pages"),
                EXECUTE_REQUEST,
                {},
            )

    proxy.assert_not_called()


# --- CUSTOM_GATHER_CONTEXT ---------------------------------------------------


def test_notion_gather_context_returns_results_key() -> None:
    with (
        patch(
            f"{NOTION_MODULE}.execute_tool",
            return_value={"results": [{"id": "page-1"}]},
        ) as execute,
        patch(f"{NOTION_MODULE}.log.set") as log_set,
    ):
        tools, _composio = _notion_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, NOTION_AUTH_CREDS
        )

    assert result == {"relevant_pages": [{"id": "page-1"}]}
    log_set.assert_called_once_with(tool={"integration": "notion", "action": "gather_context"})
    execute.assert_called_once_with(
        "NOTION_SEARCH_NOTION_PAGE", {"query": "", "page_size": 10}, "user_test_123"
    )


def test_notion_gather_context_falls_back_to_pages_key() -> None:
    with patch(
        f"{NOTION_MODULE}.execute_tool",
        return_value={"pages": [{"id": "page-1"}]},
    ):
        tools, _composio = _notion_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](
            GatherContextInput(), EXECUTE_REQUEST, NOTION_AUTH_CREDS
        )

    assert result == {"relevant_pages": [{"id": "page-1"}]}


def test_notion_gather_context_missing_user_id_rejected() -> None:
    with patch(f"{NOTION_MODULE}.execute_tool") as execute:
        tools, _composio = _notion_tools()
        with pytest.raises(ValueError, match="Missing user_id in auth_credentials"):
            tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, {})

    execute.assert_not_called()


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


TWITTER_MODULE = "app.agents.tools.integrations.twitter_tool"
TWITTER_TOOL_NAMES = [
    "TWITTER_CUSTOM_BATCH_FOLLOW",
    "TWITTER_CUSTOM_BATCH_UNFOLLOW",
    "TWITTER_CUSTOM_CREATE_THREAD",
    "TWITTER_CUSTOM_SEARCH_USERS",
    "TWITTER_CUSTOM_SCHEDULE_TWEET",
    "TWITTER_CUSTOM_GATHER_CONTEXT",
]
TWITTER_BATCH_PARAMS = [
    pytest.param(
        "CUSTOM_BATCH_FOLLOW",
        BatchFollowInput,
        "follow_user",
        "followed_count",
        "Follow",
        "Failed to follow all users",
        id="follow",
    ),
    pytest.param(
        "CUSTOM_BATCH_UNFOLLOW",
        BatchUnfollowInput,
        "unfollow_user",
        "unfollowed_count",
        "Unfollow",
        "Failed to unfollow all users",
        id="unfollow",
    ),
]
TWITTER_REQUEST_PARAMS = [
    pytest.param("CUSTOM_BATCH_FOLLOW", BatchFollowInput(user_ids=["u1"]), id="batch-follow"),
    pytest.param("CUSTOM_BATCH_UNFOLLOW", BatchUnfollowInput(user_ids=["u1"]), id="batch-unfollow"),
    pytest.param("CUSTOM_CREATE_THREAD", CreateThreadInput(tweets=["a", "b"]), id="create-thread"),
    pytest.param("CUSTOM_SEARCH_USERS", SearchUsersInput(query="x"), id="search-users"),
    pytest.param(
        "CUSTOM_SCHEDULE_TWEET",
        ScheduleTweetInput(text="hi", scheduled_time="2025-01-01T00:00:00Z"),
        id="schedule-tweet",
    ),
    pytest.param("CUSTOM_GATHER_CONTEXT", GatherContextInput(), id="gather-context"),
]


def _twitter_tools() -> dict[str, Any]:
    from app.agents.tools.integrations.twitter_tool import (
        register_twitter_custom_tools,
    )

    return _capture_tools(register_twitter_custom_tools)


# --- registration -----------------------------------------------------------


def test_twitter_register_returns_expected_tool_names() -> None:
    from app.agents.tools.integrations.twitter_tool import (
        register_twitter_custom_tools,
    )

    assert register_twitter_custom_tools(MagicMock()) == TWITTER_TOOL_NAMES


def test_twitter_tools_registered_with_toolkit_and_docs() -> None:
    from app.agents.tools.integrations.twitter_tool import (
        register_twitter_custom_tools,
    )
    from app.templates.docstrings.twitter_tool_docs import (
        CUSTOM_BATCH_FOLLOW_DOC,
        CUSTOM_BATCH_UNFOLLOW_DOC,
        CUSTOM_CREATE_THREAD_DOC,
        CUSTOM_SCHEDULE_TWEET_DOC,
        CUSTOM_SEARCH_USERS_DOC,
    )

    registered: dict[str, tuple[str | None, Any]] = {}

    def custom_tool(**kwargs: Any) -> Callable[[Any], Any]:
        def decorator(fn: Any) -> Any:
            registered[fn.__name__] = (kwargs.get("toolkit"), fn)
            return fn

        return decorator

    composio = MagicMock()
    composio.tools.custom_tool = custom_tool
    register_twitter_custom_tools(composio)

    assert set(registered) == {
        "CUSTOM_BATCH_FOLLOW",
        "CUSTOM_BATCH_UNFOLLOW",
        "CUSTOM_CREATE_THREAD",
        "CUSTOM_SEARCH_USERS",
        "CUSTOM_SCHEDULE_TWEET",
        "CUSTOM_GATHER_CONTEXT",
    }
    for toolkit, _fn in registered.values():
        assert toolkit == "TWITTER"
    assert registered["CUSTOM_BATCH_FOLLOW"][1].__doc__ == CUSTOM_BATCH_FOLLOW_DOC
    assert registered["CUSTOM_BATCH_UNFOLLOW"][1].__doc__ == CUSTOM_BATCH_UNFOLLOW_DOC
    assert registered["CUSTOM_CREATE_THREAD"][1].__doc__ == CUSTOM_CREATE_THREAD_DOC
    assert registered["CUSTOM_SEARCH_USERS"][1].__doc__ == CUSTOM_SEARCH_USERS_DOC
    assert registered["CUSTOM_SCHEDULE_TWEET"][1].__doc__ == CUSTOM_SCHEDULE_TWEET_DOC


# --- _user_id ----------------------------------------------------------------


@pytest.mark.parametrize(
    "creds",
    [{}, {"user_id": ""}, {"user_id": None}, {"user_id": 123}],
    ids=["missing", "empty", "none", "not-a-string"],
)
def test_twitter_user_id_rejects_invalid_credentials(creds: dict[str, Any]) -> None:
    from app.agents.tools.integrations.twitter_tool import _user_id

    with pytest.raises(ValueError) as excinfo:
        _user_id(creds)
    assert str(excinfo.value) == "Missing user_id in auth_credentials"


def test_twitter_user_id_returns_credentials_user_id() -> None:
    from app.agents.tools.integrations.twitter_tool import _user_id

    assert _user_id({"user_id": "user-1"}) == "user-1"


@pytest.mark.parametrize("tool_name,request_input", TWITTER_REQUEST_PARAMS)
def test_twitter_tools_reject_missing_user_id(tool_name: str, request_input: Any) -> None:
    tools = _twitter_tools()
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        pytest.raises(ValueError) as excinfo,
    ):
        tools[tool_name](request_input, EXECUTE_REQUEST, {})
    assert str(excinfo.value) == "Missing user_id in auth_credentials"


# --- CUSTOM_BATCH_FOLLOW / CUSTOM_BATCH_UNFOLLOW ------------------------------


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_rejects_unresolvable_my_user_id(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value=None),
        patch(f"{TWITTER_MODULE}.{util_name}") as util,
    ):
        tools = _twitter_tools()
        with pytest.raises(ValueError) as excinfo:
            tools[tool_name](request_model(user_ids=["u1"]), EXECUTE_REQUEST, AUTH_CREDS)
    assert str(excinfo.value) == "Could not get authenticated user ID"
    util.assert_not_called()


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_rejects_empty_inputs(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
    ):
        tools = _twitter_tools()
        with pytest.raises(ValueError) as excinfo:
            tools[tool_name](request_model(), EXECUTE_REQUEST, AUTH_CREDS)
    assert str(excinfo.value) == "Either usernames or user_ids must be provided"


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_user_ids_only_succeeds_exactly(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    writer = MagicMock()
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=writer),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id") as my_id,
        patch(f"{TWITTER_MODULE}.lookup_user_by_username") as lookup,
        patch(f"{TWITTER_MODULE}.{util_name}") as util,
    ):
        util.side_effect = [
            {"success": True, "data": {}},
            {"success": True, "data": {}},
        ]
        tools = _twitter_tools()
        result = tools[tool_name](
            request_model(user_ids=["u1", "u2"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "results": [
            {"user_id": "u1", "username": None, "success": True},
            {"user_id": "u2", "username": None, "success": True},
        ],
        count_key: 2,
        "failed_count": 0,
    }
    my_id.assert_called_once_with(AUTH_CREDS["user_id"])
    lookup.assert_not_called()
    assert util.call_args_list == [
        call(AUTH_CREDS["user_id"], "my_id", "u1"),
        call(AUTH_CREDS["user_id"], "my_id", "u2"),
    ]
    assert writer.call_args_list == [call({"progress": f"{verb}ing 2 users..."})]


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_reports_individual_failures_with_errors(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{TWITTER_MODULE}.lookup_user_by_username"),
        patch(f"{TWITTER_MODULE}.{util_name}") as util,
    ):
        util.side_effect = [
            {"success": False, "error": "rate limited"},
            {"success": True, "data": {}},
            {"success": False, "error": "blocked"},
        ]
        tools = _twitter_tools()
        result = tools[tool_name](
            request_model(user_ids=["u1", "u2", "u3"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "results": [
            {"user_id": "u1", "username": None, "success": False, "error": "rate limited"},
            {"user_id": "u2", "username": None, "success": True},
            {"user_id": "u3", "username": None, "success": False, "error": "blocked"},
        ],
        count_key: 1,
        "failed_count": 2,
    }


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_resolves_usernames_and_reports_missing_ones(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    writer = MagicMock()
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=writer),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{TWITTER_MODULE}.lookup_user_by_username") as lookup,
        patch(f"{TWITTER_MODULE}.{util_name}") as util,
    ):
        lookup.side_effect = [
            {"id": "u1", "username": "elon", "name": "Elon"},
            None,
        ]
        util.return_value = {"success": True, "data": {}}
        tools = _twitter_tools()
        result = tools[tool_name](
            request_model(usernames=["elon", "ghost"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "results": [
            {"username": "ghost", "success": False, "error": "User not found"},
            {"user_id": "u1", "username": "elon", "success": True},
        ],
        count_key: 1,
        "failed_count": 1,
    }
    assert lookup.call_args_list == [
        call(AUTH_CREDS["user_id"], "elon"),
        call(AUTH_CREDS["user_id"], "ghost"),
    ]
    util.assert_called_once_with(AUTH_CREDS["user_id"], "my_id", "u1")
    assert writer.call_args_list == [call({"progress": f"{verb}ing 1 users..."})]


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_lookup_without_id_counts_as_not_found(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{TWITTER_MODULE}.lookup_user_by_username", return_value={"username": "x"}),
    ):
        tools = _twitter_tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools[tool_name](
                request_model(usernames=["x"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert fail_all_msg in str(excinfo.value)
    assert "User not found" in str(excinfo.value)


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_raises_when_all_operations_fail(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{TWITTER_MODULE}.lookup_user_by_username", return_value=None),
    ):
        tools = _twitter_tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools[tool_name](
                request_model(usernames=["ghost"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert fail_all_msg in str(excinfo.value)
    assert "User not found" in str(excinfo.value)


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_raises_when_every_lookup_fails(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{TWITTER_MODULE}.lookup_user_by_username", return_value=None),
    ):
        tools = _twitter_tools()
        with pytest.raises(RuntimeError, match=fail_all_msg):
            tools[tool_name](
                request_model(usernames=["a", "b"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_failure_results_carry_usernames(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(
            f"{TWITTER_MODULE}.lookup_user_by_username",
            return_value={"id": "u2", "username": "elon", "name": "Elon"},
        ),
        patch(f"{TWITTER_MODULE}.{util_name}") as util,
    ):
        util.side_effect = [
            {"success": False, "error": "rate limited"},
            {"success": False, "error": "blocked"},
        ]
        tools = _twitter_tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools[tool_name](
                request_model(user_ids=["u1"], usernames=["elon"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert str(excinfo.value) == (
        f"{fail_all_msg}: "
        "[{'user_id': 'u1', 'username': None, 'success': False, 'error': 'rate limited'}, "
        "{'user_id': 'u2', 'username': 'elon', 'success': False, 'error': 'blocked'}]"
    )


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_reports_progress_every_five(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    writer = MagicMock()
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=writer),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{TWITTER_MODULE}.lookup_user_by_username"),
        patch(f"{TWITTER_MODULE}.{util_name}") as util,
    ):
        util.return_value = {"success": True, "data": {}}
        tools = _twitter_tools()
        result = tools[tool_name](
            request_model(user_ids=[f"u{i}" for i in range(6)]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result[count_key] == 6
    assert result["failed_count"] == 0
    assert writer.call_args_list == [
        call({"progress": f"{verb}ing 6 users..."}),
        call({"progress": f"{verb}ed 5/6 users..."}),
    ]


@pytest.mark.parametrize(
    "tool_name,request_model,util_name,count_key,verb,fail_all_msg",
    TWITTER_BATCH_PARAMS,
)
def test_twitter_batch_is_silent_without_writer(
    tool_name: str,
    request_model: type[Any],
    util_name: str,
    count_key: str,
    verb: str,
    fail_all_msg: str,
) -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my_id"),
        patch(f"{TWITTER_MODULE}.lookup_user_by_username"),
        patch(f"{TWITTER_MODULE}.{util_name}") as util,
    ):
        util.return_value = {"success": True, "data": {}}
        tools = _twitter_tools()
        result = tools[tool_name](
            request_model(user_ids=[f"u{i}" for i in range(6)]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result[count_key] == 6
    assert result["failed_count"] == 0


# --- CUSTOM_CREATE_THREAD -----------------------------------------------------


def test_twitter_create_thread_requires_two_tweets() -> None:
    with patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None):
        tools = _twitter_tools()
        with pytest.raises(ValueError) as excinfo:
            tools["CUSTOM_CREATE_THREAD"](
                CreateThreadInput.model_construct(tweets=["only"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert str(excinfo.value) == "Thread must have at least 2 tweets"


def test_twitter_create_thread_posts_thread_with_media() -> None:
    writer = MagicMock()
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=writer),
        patch(f"{TWITTER_MODULE}.create_tweet") as create_tweet,
        patch(f"{TWITTER_MODULE}.proxy_request_sync") as proxy,
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": True, "data": {"id": "tw2"}},
            {"success": True, "data": {"id": "tw3"}},
        ]
        proxy.return_value = {"data": {"username": "me"}}
        tools = _twitter_tools()
        result = tools["CUSTOM_CREATE_THREAD"](
            CreateThreadInput(
                tweets=["a", "b", "c"],
                media_ids=[["m1"], None, ["m3", "m4"]],
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "thread_id": "tw1",
        "tweet_ids": ["tw1", "tw2", "tw3"],
        "tweet_count": 3,
        "thread_url": "https://twitter.com/me/status/tw1",
    }
    assert create_tweet.call_args_list == [
        call(AUTH_CREDS["user_id"], "a", reply_to_tweet_id=None, media_ids=["m1"]),
        call(AUTH_CREDS["user_id"], "b", reply_to_tweet_id="tw1", media_ids=None),
        call(AUTH_CREDS["user_id"], "c", reply_to_tweet_id="tw2", media_ids=["m3", "m4"]),
    ]
    proxy.assert_called_once_with(
        user_id=AUTH_CREDS["user_id"],
        toolkit="TWITTER",
        endpoint="https://api.twitter.com/2/users/me",
        method="GET",
    )
    assert writer.call_args_list == [
        call({"progress": "Creating thread with 3 tweets..."}),
        call({"progress": "Posted tweet 1/3..."}),
        call({"progress": "Posted tweet 2/3..."}),
        call({"progress": "Posted tweet 3/3..."}),
        call(
            {
                "twitter_thread_created": {
                    "thread_id": "tw1",
                    "tweet_count": 3,
                    "url": "https://twitter.com/me/status/tw1",
                }
            }
        ),
    ]


def test_twitter_create_thread_with_shorter_media_list() -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.create_tweet") as create_tweet,
        patch(f"{TWITTER_MODULE}.proxy_request_sync", return_value=None),
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": True, "data": {"id": "tw2"}},
        ]
        tools = _twitter_tools()
        result = tools["CUSTOM_CREATE_THREAD"](
            CreateThreadInput(tweets=["a", "b"], media_ids=[["m1"]]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "thread_id": "tw1",
        "tweet_ids": ["tw1", "tw2"],
        "tweet_count": 2,
        "thread_url": "https://twitter.com/i/status/tw1",
    }
    assert create_tweet.call_args_list == [
        call(AUTH_CREDS["user_id"], "a", reply_to_tweet_id=None, media_ids=["m1"]),
        call(AUTH_CREDS["user_id"], "b", reply_to_tweet_id="tw1", media_ids=None),
    ]


def test_twitter_create_thread_failure_reports_partial_tweet_ids() -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.create_tweet") as create_tweet,
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": False, "error": "duplicate"},
        ]
        tools = _twitter_tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools["CUSTOM_CREATE_THREAD"](
                CreateThreadInput(tweets=["a", "b", "c"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert str(excinfo.value) == "Failed at tweet 2: duplicate. Partial tweet IDs: ['tw1']"


def test_twitter_create_thread_failure_when_no_tweet_id_returned() -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.create_tweet") as create_tweet,
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": True, "data": {}},
        ]
        tools = _twitter_tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools["CUSTOM_CREATE_THREAD"](
                CreateThreadInput(tweets=["a", "b"]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
    assert str(excinfo.value) == "No ID returned for tweet 2. Partial tweet IDs: ['tw1']"


def test_twitter_create_thread_falls_back_to_generic_username_on_fetch_failure() -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(f"{TWITTER_MODULE}.create_tweet") as create_tweet,
        patch(
            f"{TWITTER_MODULE}.proxy_request_sync",
            side_effect=RuntimeError("api down"),
        ),
    ):
        create_tweet.side_effect = [
            {"success": True, "data": {"id": "tw1"}},
            {"success": True, "data": {"id": "tw2"}},
        ]
        tools = _twitter_tools()
        result = tools["CUSTOM_CREATE_THREAD"](
            CreateThreadInput(tweets=["a", "b"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result["thread_url"] == "https://twitter.com/i/status/tw1"


# --- CUSTOM_SEARCH_USERS ------------------------------------------------------


def test_twitter_search_users_returns_capped_deduped_users() -> None:
    writer = MagicMock()
    long_desc = "d" * 200
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=writer),
        patch(f"{TWITTER_MODULE}.search_tweets") as search,
    ):
        search.return_value = {
            "success": True,
            "data": {
                "includes": {
                    "users": [
                        {
                            "id": "u1",
                            "username": "elonmusk",
                            "name": "Elon",
                            "description": long_desc,
                            "profile_image_url": "p1",
                            "verified": True,
                            "public_metrics": {"followers_count": 55},
                            "created_at": "2020-01-01",
                            "location": "TX",
                        },
                        {
                            "id": "u2",
                            "username": "barackobama",
                            "name": "Barack",
                            "profile_image_url": "p2",
                            "created_at": "2009-01-01",
                            "location": "DC",
                        },
                        {
                            "id": "u1",
                            "username": "elonmusk",
                            "name": "Elon",
                            "description": "duplicate",
                            "profile_image_url": "p1",
                            "verified": True,
                            "public_metrics": {"followers_count": 55},
                            "created_at": "2020-01-01",
                            "location": "TX",
                        },
                        {
                            "id": "u3",
                            "username": "billgates",
                            "name": "Bill",
                            "description": "short3",
                            "profile_image_url": "p3",
                            "verified": True,
                            "public_metrics": {"followers_count": 20},
                            "created_at": "2000-01-01",
                            "location": "WA",
                        },
                    ]
                }
            },
        }
        tools = _twitter_tools()
        result = tools["CUSTOM_SEARCH_USERS"](
            SearchUsersInput(query="elon", max_results=2),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    assert result == {
        "users": [
            {
                "id": "u1",
                "username": "elonmusk",
                "name": "Elon",
                "description": "d" * 150,
                "followers": 55,
                "verified": True,
            },
            {
                "id": "u2",
                "username": "barackobama",
                "name": "Barack",
                "description": "",
                "followers": 0,
                "verified": False,
            },
        ],
        "count": 2,
    }
    search.assert_called_once_with(AUTH_CREDS["user_id"], "elon -is:retweet", max_results=6)
    assert writer.call_args_list == [
        call({"progress": "Searching for users matching: elon..."}),
        call(
            {
                "twitter_user_data": [
                    {
                        "id": "u1",
                        "username": "elonmusk",
                        "name": "Elon",
                        "description": long_desc,
                        "profile_image_url": "p1",
                        "verified": True,
                        "public_metrics": {"followers_count": 55},
                        "created_at": "2020-01-01",
                        "location": "TX",
                    },
                    {
                        "id": "u2",
                        "username": "barackobama",
                        "name": "Barack",
                        "description": "",
                        "profile_image_url": "p2",
                        "verified": False,
                        "public_metrics": {},
                        "created_at": "2009-01-01",
                        "location": "DC",
                    },
                ]
            }
        ),
    ]


def test_twitter_search_users_raises_on_search_failure() -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(
            f"{TWITTER_MODULE}.search_tweets",
            return_value={"success": False, "error": "api down"},
        ),
    ):
        tools = _twitter_tools()
        with pytest.raises(RuntimeError) as excinfo:
            tools["CUSTOM_SEARCH_USERS"](SearchUsersInput(query="x"), EXECUTE_REQUEST, AUTH_CREDS)
    assert str(excinfo.value) == "Search failed: api down"


def test_twitter_search_users_empty_includes_returns_no_users() -> None:
    writer = MagicMock()
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=writer),
        patch(
            f"{TWITTER_MODULE}.search_tweets",
            return_value={"success": True, "data": {"includes": {}}},
        ),
    ):
        tools = _twitter_tools()
        result = tools["CUSTOM_SEARCH_USERS"](
            SearchUsersInput(query="x"), EXECUTE_REQUEST, AUTH_CREDS
        )
    assert result == {"users": [], "count": 0}
    assert writer.call_args_list == [call({"progress": "Searching for users matching: x..."})]


def test_twitter_search_users_skips_users_without_id() -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(
            f"{TWITTER_MODULE}.search_tweets",
            return_value={
                "success": True,
                "data": {"includes": {"users": [{"username": "ghost"}]}},
            },
        ),
    ):
        tools = _twitter_tools()
        result = tools["CUSTOM_SEARCH_USERS"](
            SearchUsersInput(query="x"), EXECUTE_REQUEST, AUTH_CREDS
        )
    assert result == {"users": [], "count": 0}


def test_twitter_search_users_handles_data_without_includes() -> None:
    with (
        patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None),
        patch(
            f"{TWITTER_MODULE}.search_tweets",
            return_value={"success": True, "data": {}},
        ),
    ):
        tools = _twitter_tools()
        result = tools["CUSTOM_SEARCH_USERS"](
            SearchUsersInput(query="x"), EXECUTE_REQUEST, AUTH_CREDS
        )
    assert result == {"users": [], "count": 0}


# --- CUSTOM_SCHEDULE_TWEET ----------------------------------------------------


def test_twitter_schedule_tweet_builds_draft() -> None:
    writer = MagicMock()
    with patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=writer):
        tools = _twitter_tools()
        result = tools["CUSTOM_SCHEDULE_TWEET"](
            ScheduleTweetInput(
                text="hello",
                scheduled_time="2025-01-01T10:00:00Z",
                media_urls=["m1"],
                reply_to_tweet_id="r1",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

    draft = {
        "text": "hello",
        "scheduled_time": "2025-01-01T10:00:00Z",
        "media_urls": ["m1"],
        "reply_to_tweet_id": "r1",
    }
    assert result == {
        "draft": draft,
        "message": "Tweet scheduled for 2025-01-01T10:00:00Z. Note: Actual scheduling requires a backend scheduler service.",
    }
    writer.assert_called_once_with({"twitter_scheduled_draft": draft})


def test_twitter_schedule_tweet_without_writer_or_optional_fields() -> None:
    with patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=None):
        tools = _twitter_tools()
        result = tools["CUSTOM_SCHEDULE_TWEET"](
            ScheduleTweetInput(text="hi", scheduled_time="2025-01-01T00:00:00Z"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
    assert result["draft"] == {
        "text": "hi",
        "scheduled_time": "2025-01-01T00:00:00Z",
        "media_urls": None,
        "reply_to_tweet_id": None,
    }
    assert result["message"] == (
        "Tweet scheduled for 2025-01-01T00:00:00Z. "
        "Note: Actual scheduling requires a backend scheduler service."
    )


# --- CUSTOM_GATHER_CONTEXT ----------------------------------------------------


def test_twitter_gather_context_returns_profile_and_tweets() -> None:
    with patch(f"{TWITTER_MODULE}.proxy_request_sync") as proxy:
        proxy.side_effect = [
            {
                "data": {
                    "id": "tid1",
                    "username": "me",
                    "name": "Me",
                    "description": "d" * 300,
                    "public_metrics": {
                        "followers_count": 10,
                        "following_count": 5,
                        "tweet_count": 3,
                    },
                }
            },
            {
                "data": [
                    {
                        "id": "t1",
                        "text": "x" * 250,
                        "created_at": "c1",
                        "public_metrics": {"like_count": 7, "retweet_count": 2},
                    },
                    {"id": "t2"},
                ]
            },
        ]
        tools = _twitter_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    assert result == {
        "user": {
            "id": "tid1",
            "username": "me",
            "name": "Me",
            "description": "d" * 200,
            "followers": 10,
            "following": 5,
            "tweet_count": 3,
        },
        "recent_tweets": [
            {"id": "t1", "text": "x" * 200, "created_at": "c1", "likes": 7, "retweets": 2},
            {"id": "t2", "text": "", "created_at": None, "likes": 0, "retweets": 0},
        ],
    }
    assert proxy.call_args_list == [
        call(
            user_id=AUTH_CREDS["user_id"],
            toolkit="TWITTER",
            endpoint="https://api.twitter.com/2/users/me",
            method="GET",
            query={"user.fields": "public_metrics,description,username"},
        ),
        call(
            user_id=AUTH_CREDS["user_id"],
            toolkit="TWITTER",
            endpoint="https://api.twitter.com/2/users/tid1/tweets",
            method="GET",
            query={"max_results": 5, "tweet.fields": "created_at,public_metrics"},
        ),
    ]


def test_twitter_gather_context_without_twitter_user_id_skips_tweets() -> None:
    with patch(f"{TWITTER_MODULE}.proxy_request_sync") as proxy:
        proxy.return_value = {"data": {}}
        tools = _twitter_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    assert result == {
        "user": {
            "id": None,
            "username": None,
            "name": None,
            "description": "",
            "followers": 0,
            "following": 0,
            "tweet_count": 0,
        },
        "recent_tweets": [],
    }
    assert proxy.call_count == 1


def test_twitter_gather_context_logs_and_returns_partial_on_tweets_failure() -> None:
    from app.constants.log_tags import LogTag

    with (
        patch(f"{TWITTER_MODULE}.proxy_request_sync") as proxy,
        patch(f"{TWITTER_MODULE}.log.warning") as warn,
    ):
        proxy.side_effect = [
            {
                "data": {
                    "id": "tid1",
                    "username": "me",
                    "name": "Me",
                    "description": "",
                    "public_metrics": {},
                }
            },
            RuntimeError("api down"),
        ]
        tools = _twitter_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    assert result["user"]["id"] == "tid1"
    assert result["recent_tweets"] == []
    warn.assert_called_once_with(
        f"{LogTag.TOOL} Failed to fetch recent tweets, returning profile without them",
        twitter_user_id="tid1",
        error="api down",
        error_type="RuntimeError",
    )


def test_twitter_gather_context_handles_missing_proxy_response() -> None:
    with patch(f"{TWITTER_MODULE}.proxy_request_sync", return_value=None) as proxy:
        tools = _twitter_tools()
        result = tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    assert result["user"]["id"] is None
    assert result["user"]["description"] == ""
    assert result["recent_tweets"] == []
    proxy.assert_called_once()


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


# ---------------------------------------------------------------------------
# Twitter utils (app.utils.twitter_utils)
# ---------------------------------------------------------------------------

TWITTER_UTILS = "app.utils.twitter_utils"
TWITTER_USERS_ME_ENDPOINT = "https://api.twitter.com/2/users/me"


def test_twitter_utils_proxy_passes_exact_kwargs_and_returns_response() -> None:
    from app.utils.twitter_utils import _proxy

    with patch(f"{TWITTER_UTILS}.proxy_request_sync") as proxy:
        proxy.return_value = {"data": {"id": "123"}}
        result = _proxy(
            "user-1",
            endpoint="/tweets",
            method="POST",
            body={"text": "hi"},
            query={"max_results": 5},
        )

    assert result == {"data": {"id": "123"}}
    proxy.assert_called_once_with(
        user_id="user-1",
        toolkit="TWITTER",
        endpoint="/tweets",
        method="POST",
        body={"text": "hi"},
        query={"max_results": 5},
    )


def test_twitter_utils_proxy_passes_none_body_and_query() -> None:
    from app.utils.twitter_utils import _proxy

    with patch(f"{TWITTER_UTILS}.proxy_request_sync") as proxy:
        proxy.return_value = None
        result = _proxy("user-1", endpoint="/x", method="GET")

    assert result is None
    proxy.assert_called_once_with(
        user_id="user-1",
        toolkit="TWITTER",
        endpoint="/x",
        method="GET",
        body=None,
        query=None,
    )


def test_twitter_utils_get_my_user_id_exact_proxy_call_and_log_set() -> None:
    from app.utils.twitter_utils import get_my_user_id

    with (
        patch(
            f"{TWITTER_UTILS}.proxy_request_sync", return_value={"data": {"id": "tid-1"}}
        ) as proxy,
        patch(f"{TWITTER_UTILS}.log") as log_mock,
    ):
        result = get_my_user_id("user-1")

    assert result == "tid-1"
    proxy.assert_called_once_with(
        user_id="user-1",
        toolkit="TWITTER",
        endpoint=TWITTER_USERS_ME_ENDPOINT,
        method="GET",
        body=None,
        query=None,
    )
    log_mock.set.assert_called_once_with(operation="twitter_get_my_user_id")


def test_twitter_utils_get_my_user_id_returns_none_when_data_missing() -> None:
    from app.utils.twitter_utils import get_my_user_id

    with (
        patch(f"{TWITTER_UTILS}.proxy_request_sync", return_value=None) as proxy,
        patch(f"{TWITTER_UTILS}.log") as log_mock,
    ):
        assert get_my_user_id("user-1") is None

    proxy.assert_called_once()
    # None response must resolve via the default-dict path, not the exception handler.
    log_mock.error.assert_not_called()


def test_twitter_utils_get_my_user_id_returns_none_when_data_has_no_id() -> None:
    from app.utils.twitter_utils import get_my_user_id

    with (
        patch(f"{TWITTER_UTILS}.proxy_request_sync", return_value={"data": {}}) as proxy,
        patch(f"{TWITTER_UTILS}.log"),
    ):
        assert get_my_user_id("user-1") is None

    proxy.assert_called_once()


def test_twitter_utils_get_my_user_id_returns_none_when_proxy_response_lacks_data_key() -> None:
    from app.utils.twitter_utils import get_my_user_id

    with (
        patch(f"{TWITTER_UTILS}.proxy_request_sync", return_value={"unexpected": True}) as proxy,
        patch(f"{TWITTER_UTILS}.log") as log_mock,
    ):
        assert get_my_user_id("user-1") is None

    proxy.assert_called_once()
    # Missing key must resolve via the default-dict path, not the exception handler.
    log_mock.error.assert_not_called()


def test_twitter_utils_get_my_user_id_logs_error_and_returns_none_on_exception() -> None:
    from app.constants.log_tags import LogTag
    from app.utils.twitter_utils import get_my_user_id

    with (
        patch(f"{TWITTER_UTILS}.proxy_request_sync", side_effect=RuntimeError("boom")) as proxy,
        patch(f"{TWITTER_UTILS}.log") as log_mock,
    ):
        result = get_my_user_id("user-1")

    assert result is None
    proxy.assert_called_once()
    log_mock.error.assert_called_once_with(
        f"{LogTag.INTEGRATION} Error getting user ID",
        error="boom",
        error_type="RuntimeError",
        user_id="user-1",
    )


def test_twitter_utils_lookup_user_by_username_strips_at_and_exact_query() -> None:
    from app.utils.twitter_utils import lookup_user_by_username

    with patch(f"{TWITTER_UTILS}.proxy_request_sync") as proxy:
        proxy.return_value = {"data": {"id": "u1", "username": "elon"}}
        result = lookup_user_by_username("user-1", "@elon")

    assert result == {"id": "u1", "username": "elon"}
    proxy.assert_called_once_with(
        user_id="user-1",
        toolkit="TWITTER",
        endpoint="https://api.twitter.com/2/users/by/username/elon",
        method="GET",
        body=None,
        query={
            "user.fields": (
                "id,name,username,description,profile_image_url,verified,public_metrics"
            ),
        },
    )


def test_twitter_utils_lookup_user_by_username_without_at() -> None:
    from app.utils.twitter_utils import lookup_user_by_username

    with patch(f"{TWITTER_UTILS}.proxy_request_sync") as proxy:
        proxy.return_value = {"data": {"id": "u1"}}
        result = lookup_user_by_username("user-1", "jack")

    assert result == {"id": "u1"}
    assert proxy.call_args.kwargs["endpoint"] == (
        "https://api.twitter.com/2/users/by/username/jack"
    )


def test_twitter_utils_lookup_user_by_username_strips_only_at_sign() -> None:
    # Pin that ONLY the leading '@' is stripped: a username starting with 'X'
    # must survive untouched (guards against lstrip char-set mutations).
    from app.utils.twitter_utils import lookup_user_by_username

    with patch(f"{TWITTER_UTILS}.proxy_request_sync") as proxy:
        proxy.return_value = {"data": {"id": "u1"}}
        result = lookup_user_by_username("user-1", "@Xavier")

    assert result == {"id": "u1"}
    assert proxy.call_args.kwargs["endpoint"] == (
        "https://api.twitter.com/2/users/by/username/Xavier"
    )


def test_twitter_utils_lookup_user_by_username_returns_none_without_data() -> None:
    from app.utils.twitter_utils import lookup_user_by_username

    with (
        patch(f"{TWITTER_UTILS}.proxy_request_sync", return_value=None) as proxy,
        patch(f"{TWITTER_UTILS}.log") as log_mock,
    ):
        assert lookup_user_by_username("user-1", "elon") is None

    proxy.assert_called_once()
    # None response must resolve via the default-dict path, not the exception handler.
    log_mock.error.assert_not_called()


def test_twitter_utils_lookup_user_by_username_logs_error_and_returns_none_on_exception() -> None:
    from app.constants.log_tags import LogTag
    from app.utils.twitter_utils import lookup_user_by_username

    with (
        patch(f"{TWITTER_UTILS}.proxy_request_sync", side_effect=ValueError("bad")) as proxy,
        patch(f"{TWITTER_UTILS}.log") as log_mock,
    ):
        result = lookup_user_by_username("user-1", "elon")

    assert result is None
    proxy.assert_called_once()
    log_mock.error.assert_called_once_with(
        f"{LogTag.INTEGRATION} Error looking up user",
        username="elon",
        error="bad",
        error_type="ValueError",
        user_id="user-1",
    )


def test_twitter_utils_follow_user_exact_proxy_call_and_success_result() -> None:
    from app.utils.twitter_utils import follow_user

    with patch(f"{TWITTER_UTILS}.proxy_request_sync") as proxy:
        proxy.return_value = {"data": {"following": True}}
        result = follow_user("user-1", "me-1", "target-1")

    assert result == {"success": True, "data": {"data": {"following": True}}}
    proxy.assert_called_once_with(
        user_id="user-1",
        toolkit="TWITTER",
        endpoint="https://api.twitter.com/2/users/me-1/following",
        method="POST",
        body={"target_user_id": "target-1"},
        query=None,
    )


def test_twitter_utils_follow_user_success_with_none_proxy_response() -> None:
    from app.utils.twitter_utils import follow_user

    with patch(f"{TWITTER_UTILS}.proxy_request_sync", return_value=None) as proxy:
        result = follow_user("user-1", "me-1", "target-1")

    assert result == {"success": True, "data": None}
    proxy.assert_called_once()


def test_twitter_utils_follow_user_app_error_formats_http_message() -> None:
    from app.utils.errors import AppError
    from app.utils.twitter_utils import follow_user

    err = AppError(
        message="denied",
        status_code=403,
        meta={"provider_response": "Forbidden: token expired"},
    )
    with patch(f"{TWITTER_UTILS}.proxy_request_sync", side_effect=err) as proxy:
        result = follow_user("user-1", "me-1", "target-1")

    assert result == {
        "success": False,
        "error": "HTTP 403: Forbidden: token expired",
    }
    proxy.assert_called_once()


def test_twitter_utils_follow_user_app_error_without_provider_response() -> None:
    from app.utils.errors import AppError
    from app.utils.twitter_utils import follow_user

    err = AppError(message="gone", status_code=404)
    with patch(f"{TWITTER_UTILS}.proxy_request_sync", side_effect=err) as proxy:
        result = follow_user("user-1", "me-1", "target-1")

    assert result == {"success": False, "error": "HTTP 404: None"}
    proxy.assert_called_once()


def test_twitter_utils_follow_user_generic_exception_returns_str_error() -> None:
    from app.utils.twitter_utils import follow_user

    with patch(
        f"{TWITTER_UTILS}.proxy_request_sync", side_effect=ConnectionError("net down")
    ) as proxy:
        result = follow_user("user-1", "me-1", "target-1")

    assert result == {"success": False, "error": "net down"}
    proxy.assert_called_once()


def test_twitter_utils_unfollow_user_exact_proxy_call_and_success_result() -> None:
    from app.utils.twitter_utils import unfollow_user

    with patch(f"{TWITTER_UTILS}.proxy_request_sync") as proxy:
        proxy.return_value = {"data": {"following": False}}
        result = unfollow_user("user-1", "me-1", "target-1")

    assert result == {"success": True, "data": {"data": {"following": False}}}
    proxy.assert_called_once_with(
        user_id="user-1",
        toolkit="TWITTER",
        endpoint="https://api.twitter.com/2/users/me-1/following/target-1",
        method="DELETE",
        body=None,
        query=None,
    )


def test_twitter_utils_unfollow_user_app_error_formats_http_message() -> None:
    from app.utils.errors import AppError
    from app.utils.twitter_utils import unfollow_user

    err = AppError(message="denied", status_code=403, meta={"provider_response": "nope"})
    with patch(f"{TWITTER_UTILS}.proxy_request_sync", side_effect=err) as proxy:
        result = unfollow_user("user-1", "me-1", "target-1")

    assert result == {"success": False, "error": "HTTP 403: nope"}
    proxy.assert_called_once()


def test_twitter_utils_unfollow_user_generic_exception_returns_str_error() -> None:
    from app.utils.twitter_utils import unfollow_user

    with patch(f"{TWITTER_UTILS}.proxy_request_sync", side_effect=OSError("io")) as proxy:
        result = unfollow_user("user-1", "me-1", "target-1")

    assert result == {"success": False, "error": "io"}
    proxy.assert_called_once()


def test_twitter_utils_create_tweet_plain_text_exact_proxy_call() -> None:
    from app.utils.twitter_utils import create_tweet

    with patch(f"{TWITTER_UTILS}.proxy_request_sync") as proxy:
        proxy.return_value = {"data": {"id": "tw-1"}}
        result = create_tweet("user-1", "hello world")

    assert result == {"success": True, "data": {"id": "tw-1"}}
    proxy.assert_called_once_with(
        user_id="user-1",
        toolkit="TWITTER",
        endpoint="https://api.twitter.com/2/tweets",
        method="POST",
        body={"text": "hello world"},
        query=None,
    )


def test_twitter_utils_create_tweet_all_optional_fields_in_body() -> None:
    from app.utils.twitter_utils import create_tweet

    with patch(f"{TWITTER_UTILS}.proxy_request_sync") as proxy:
        proxy.return_value = {"data": {"id": "tw-1"}}
        result = create_tweet(
            "user-1",
            "text",
            reply_to_tweet_id="rep-1",
            media_ids=["m1", "m2"],
            quote_tweet_id="quote-1",
        )

    assert result["success"] is True
    proxy.assert_called_once_with(
        user_id="user-1",
        toolkit="TWITTER",
        endpoint="https://api.twitter.com/2/tweets",
        method="POST",
        body={
            "text": "text",
            "reply": {"in_reply_to_tweet_id": "rep-1"},
            "media": {"media_ids": ["m1", "m2"]},
            "quote_tweet_id": "quote-1",
        },
        query=None,
    )


def test_twitter_utils_create_tweet_only_reply_field() -> None:
    from app.utils.twitter_utils import create_tweet

    with patch(f"{TWITTER_UTILS}.proxy_request_sync") as proxy:
        create_tweet("user-1", "text", reply_to_tweet_id="rep-1")

    assert proxy.call_args.kwargs["body"] == {
        "text": "text",
        "reply": {"in_reply_to_tweet_id": "rep-1"},
    }


def test_twitter_utils_create_tweet_only_media_field() -> None:
    from app.utils.twitter_utils import create_tweet

    with patch(f"{TWITTER_UTILS}.proxy_request_sync") as proxy:
        create_tweet("user-1", "text", media_ids=["m1"])

    assert proxy.call_args.kwargs["body"] == {
        "text": "text",
        "media": {"media_ids": ["m1"]},
    }


def test_twitter_utils_create_tweet_falsy_optional_fields_omitted() -> None:
    from app.utils.twitter_utils import create_tweet

    with patch(f"{TWITTER_UTILS}.proxy_request_sync") as proxy:
        create_tweet("user-1", "text", reply_to_tweet_id="", media_ids=[], quote_tweet_id=None)

    assert proxy.call_args.kwargs["body"] == {"text": "text"}


def test_twitter_utils_create_tweet_missing_data_becomes_empty_dict() -> None:
    from app.utils.twitter_utils import create_tweet

    with patch(f"{TWITTER_UTILS}.proxy_request_sync", return_value=None) as proxy:
        result = create_tweet("user-1", "text")

    assert result == {"success": True, "data": {}}
    proxy.assert_called_once()


def test_twitter_utils_create_tweet_data_without_data_key_becomes_empty_dict() -> None:
    from app.utils.twitter_utils import create_tweet

    with patch(f"{TWITTER_UTILS}.proxy_request_sync", return_value={"errors": [1]}) as proxy:
        result = create_tweet("user-1", "text")

    assert result == {"success": True, "data": {}}
    proxy.assert_called_once()


def test_twitter_utils_create_tweet_app_error_formats_http_message() -> None:
    from app.utils.errors import AppError
    from app.utils.twitter_utils import create_tweet

    err = AppError(message="rate limited", status_code=429, meta={"provider_response": "slow down"})
    with patch(f"{TWITTER_UTILS}.proxy_request_sync", side_effect=err) as proxy:
        result = create_tweet("user-1", "text")

    assert result == {"success": False, "error": "HTTP 429: slow down"}
    proxy.assert_called_once()


def test_twitter_utils_create_tweet_generic_exception_returns_str_error() -> None:
    from app.utils.twitter_utils import create_tweet

    with patch(f"{TWITTER_UTILS}.proxy_request_sync", side_effect=TimeoutError("slow")) as proxy:
        result = create_tweet("user-1", "text")

    assert result == {"success": False, "error": "slow"}
    proxy.assert_called_once()


def test_twitter_utils_search_tweets_exact_proxy_call_and_log_set() -> None:
    from app.utils.twitter_utils import search_tweets

    with (
        patch(f"{TWITTER_UTILS}.proxy_request_sync") as proxy,
        patch(f"{TWITTER_UTILS}.log") as log_mock,
    ):
        proxy.return_value = {"data": [{"id": "t1"}], "meta": {"result_count": 1}}
        result = search_tweets("user-1", "gaia ai", max_results=10)

    assert result == {
        "success": True,
        "data": {"data": [{"id": "t1"}], "meta": {"result_count": 1}},
    }
    proxy.assert_called_once_with(
        user_id="user-1",
        toolkit="TWITTER",
        endpoint="https://api.twitter.com/2/tweets/search/recent",
        method="GET",
        body=None,
        query={
            "query": "gaia ai",
            "max_results": 10,
            "user.fields": (
                "id,name,username,description,profile_image_url,verified,"
                "public_metrics,created_at,location"
            ),
            "expansions": "author_id",
        },
    )
    log_mock.set.assert_called_once_with(
        operation="twitter_search_tweets",
        search_query="gaia ai",
        max_results=10,
    )


def test_twitter_utils_search_tweets_caps_max_results_at_100() -> None:
    from app.utils.twitter_utils import search_tweets

    with patch(f"{TWITTER_UTILS}.proxy_request_sync") as proxy:
        search_tweets("user-1", "q", max_results=500)

    assert proxy.call_args.kwargs["query"]["max_results"] == 100


def test_twitter_utils_search_tweets_default_max_results_is_10() -> None:
    from app.utils.twitter_utils import search_tweets

    with patch(f"{TWITTER_UTILS}.proxy_request_sync") as proxy:
        search_tweets("user-1", "q")

    assert proxy.call_args.kwargs["query"]["max_results"] == 10


def test_twitter_utils_search_tweets_app_error_formats_http_message() -> None:
    from app.utils.errors import AppError
    from app.utils.twitter_utils import search_tweets

    err = AppError(message="blocked", status_code=401, meta={"provider_response": "unauthorized"})
    with patch(f"{TWITTER_UTILS}.proxy_request_sync", side_effect=err) as proxy:
        result = search_tweets("user-1", "q")

    assert result == {"success": False, "error": "HTTP 401: unauthorized"}
    proxy.assert_called_once()


def test_twitter_utils_search_tweets_generic_exception_returns_str_error() -> None:
    from app.utils.twitter_utils import search_tweets

    with patch(f"{TWITTER_UTILS}.proxy_request_sync", side_effect=RuntimeError("x")) as proxy:
        result = search_tweets("user-1", "q")

    assert result == {"success": False, "error": "x"}
    proxy.assert_called_once()
