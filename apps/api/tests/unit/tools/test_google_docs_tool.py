"""Unit tests for app.agents.tools.integrations.google_docs_tool.

Only the true I/O boundary is faked: `proxy_request_sync` and
`composio.tools.execute`. Everything else — user-id validation, request
assembly, response unwrapping, heading extraction, TOC generation — runs
for real, so the assertions below are against the exact JSON Drive/Composio
would see and the exact payloads the agent receives.
"""

import json
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from app.agents.tools.integrations.google_docs_tool import (
    DOCS_TOOLKIT,
    DRIVE_API_BASE,
    _user_id,
    register_google_docs_custom_tools,
)
from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.models.google_docs_models import (
    CreateTOCInput,
    DeleteDocInput,
    ShareDocInput,
    ShareRecipient,
)
from app.templates.docstrings.google_docs_tool_docs import (
    CUSTOM_CREATE_TOC as CUSTOM_CREATE_TOC_DOC,
    CUSTOM_DELETE_DOC as CUSTOM_DELETE_DOC_DOC,
    CUSTOM_SHARE_DOC as CUSTOM_SHARE_DOC_DOC,
)
from app.utils.errors import AppError

MODULE = "app.agents.tools.integrations.google_docs_tool"
AUTH: dict[str, Any] = {"user_id": "user-42", "version": "v1"}
DOC = "doc-abc"
EXPECTED_URL = f"https://docs.google.com/document/d/{DOC}/edit"


def _register(composio: Any | None = None) -> dict[str, Any]:
    """Register the tools against the given (or a fresh) Composio mock.

    The tool bodies capture the composio instance from the closure, so tests
    that must drive `composio.tools.execute` pass their own mock in.
    """
    captured: dict[str, Any] = {}
    if composio is None:
        composio = MagicMock()

    def custom_tool(**_kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            captured[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    register_google_docs_custom_tools(composio)
    return captured


def _call(tools: dict[str, Any], name: str, request: Any) -> dict[str, Any]:
    result: dict[str, Any] = tools[name](request, MagicMock(), AUTH)
    return result


def _execute_results(get_doc: Any, insert: Any) -> list[Any]:
    return [get_doc, insert]


@pytest.fixture
def tools() -> dict[str, Any]:
    return _register()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registers_every_advertised_tool(self) -> None:
        composio = MagicMock()
        registered: list[str] = []

        def custom_tool(**kwargs: Any) -> Any:
            assert kwargs == {"toolkit": "GOOGLEDOCS"}

            def decorator(fn: Any) -> Any:
                registered.append(fn.__name__)
                return fn

            return decorator

        composio.tools.custom_tool = custom_tool
        names = register_google_docs_custom_tools(composio)

        # Every returned name must correspond to a function that was actually
        # registered — a name in the list with no tool behind it is a tool the
        # agent can select and never execute.
        assert names == [f"GOOGLEDOCS_{fn}" for fn in registered]

    def test_returns_the_four_tool_names(self) -> None:
        assert register_google_docs_custom_tools(MagicMock()) == [
            "GOOGLEDOCS_CUSTOM_SHARE_DOC",
            "GOOGLEDOCS_CUSTOM_CREATE_TOC",
            "GOOGLEDOCS_CUSTOM_DELETE_DOC",
            "GOOGLEDOCS_CUSTOM_GATHER_CONTEXT",
        ]

    def test_docstrings_are_replaced_with_the_agent_facing_docs(self) -> None:
        # The model selects tools by docstring; the terse developer docstring
        # would strip the parameter contract.
        tools = _register()
        assert tools["CUSTOM_SHARE_DOC"].__doc__ == CUSTOM_SHARE_DOC_DOC
        assert tools["CUSTOM_CREATE_TOC"].__doc__ == CUSTOM_CREATE_TOC_DOC
        assert tools["CUSTOM_DELETE_DOC"].__doc__ == CUSTOM_DELETE_DOC_DOC
        # CUSTOM_GATHER_CONTEXT has no with_doc: its own docstring is the contract.
        assert tools["CUSTOM_GATHER_CONTEXT"].__doc__ is not None
        assert "recently viewed/modified" in tools["CUSTOM_GATHER_CONTEXT"].__doc__

    def test_constants_are_stable(self) -> None:
        assert DRIVE_API_BASE == "https://www.googleapis.com/drive/v3"
        assert DOCS_TOOLKIT == "GOOGLEDOCS"


# ---------------------------------------------------------------------------
# _user_id
# ---------------------------------------------------------------------------


class TestUserId:
    def test_returns_the_credential_user_id(self) -> None:
        assert _user_id({"user_id": "abc"}) == "abc"

    @pytest.mark.parametrize(
        "credentials",
        [{}, {"user_id": ""}, {"user_id": None}, {"user_id": 42}, {"userId": "abc"}],
    )
    def test_unusable_credentials_are_rejected(self, credentials: dict[str, Any]) -> None:
        # Falling through with a blank/None user id would send the request as
        # nobody and surface as a confusing 500 deep inside the proxy.
        with pytest.raises(ValueError) as excinfo:
            _user_id(credentials)
        assert str(excinfo.value) == "Missing user_id in auth_credentials"


# ---------------------------------------------------------------------------
# CUSTOM_SHARE_DOC
# ---------------------------------------------------------------------------


class TestShareDoc:
    def test_shares_with_a_single_recipient(self, tools: Any) -> None:
        with (
            patch(f"{MODULE}.proxy_request_sync", return_value={"id": "perm-1"}) as proxy,
            patch(f"{MODULE}.log.set") as log_set,
        ):
            result = _call(
                tools,
                "CUSTOM_SHARE_DOC",
                ShareDocInput(
                    document_id=DOC,
                    recipients=[ShareRecipient(email="a@x.com", role="reader")],
                ),
            )

        assert result == {
            "document_id": DOC,
            "url": EXPECTED_URL,
            "shared": [
                {
                    "email": "a@x.com",
                    "role": "reader",
                    "permission_id": "perm-1",
                    "notification_sent": True,
                }
            ],
        }
        log_set.assert_called_once_with(tool={"integration": "google_docs", "action": "share_doc"})
        proxy.assert_called_once()

    def test_sends_the_drive_permission_request_google_expects(self, tools: Any) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value={"id": "perm-1"}) as proxy:
            _call(
                tools,
                "CUSTOM_SHARE_DOC",
                ShareDocInput(
                    document_id=DOC,
                    recipients=[ShareRecipient(email="a@x.com", role="commenter")],
                ),
            )

        call_kwargs = proxy.call_args.kwargs
        assert call_kwargs["endpoint"] == f"{DRIVE_API_BASE}/files/{DOC}/permissions"
        assert call_kwargs["method"] == "POST"
        assert call_kwargs["toolkit"] == DOCS_TOOLKIT
        assert call_kwargs["user_id"] == "user-42"
        assert call_kwargs["body"] == {
            "type": "user",
            "role": "commenter",
            "emailAddress": "a@x.com",
        }

    @pytest.mark.parametrize(("send_notification", "expected"), [(True, "true"), (False, "false")])
    def test_notification_flag_is_sent_as_a_lowercase_string(
        self, tools: Any, send_notification: bool, expected: str
    ) -> None:
        # Drive's query API rejects Python's "True"/"False" capitalisation.
        with patch(f"{MODULE}.proxy_request_sync", return_value={"id": "perm-1"}) as proxy:
            _call(
                tools,
                "CUSTOM_SHARE_DOC",
                ShareDocInput(
                    document_id=DOC,
                    recipients=[
                        ShareRecipient(email="a@x.com", send_notification=send_notification)
                    ],
                ),
            )

        assert proxy.call_args.kwargs["query"] == {"sendNotificationEmail": expected}

    def test_every_recipient_gets_its_own_request(self, tools: Any) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value={"id": "perm-1"}) as proxy:
            result = _call(
                tools,
                "CUSTOM_SHARE_DOC",
                ShareDocInput(
                    document_id=DOC,
                    recipients=[
                        ShareRecipient(email="a@x.com"),
                        ShareRecipient(email="b@x.com", role="reader", send_notification=False),
                        ShareRecipient(email="c@x.com"),
                    ],
                ),
            )

        assert [c.kwargs["body"]["emailAddress"] for c in proxy.call_args_list] == [
            "a@x.com",
            "b@x.com",
            "c@x.com",
        ]
        assert [c.kwargs["query"] for c in proxy.call_args_list] == [
            {"sendNotificationEmail": "true"},
            {"sendNotificationEmail": "false"},
            {"sendNotificationEmail": "true"},
        ]
        assert len(result["shared"]) == 3

    def test_missing_permission_id_is_reported_as_none(self, tools: Any) -> None:
        with patch(f"{MODULE}.proxy_request_sync", return_value=None):
            result = _call(
                tools,
                "CUSTOM_SHARE_DOC",
                ShareDocInput(document_id=DOC, recipients=[ShareRecipient(email="a@x.com")]),
            )

        assert result["shared"][0]["permission_id"] is None

    def test_empty_proxy_body_also_yields_none_permission_id(self, tools: Any) -> None:
        # (result or {}) — a falsy payload must not crash the unwrap.
        with patch(f"{MODULE}.proxy_request_sync", return_value={}):
            result = _call(
                tools,
                "CUSTOM_SHARE_DOC",
                ShareDocInput(document_id=DOC, recipients=[ShareRecipient(email="a@x.com")]),
            )

        assert result["shared"][0]["permission_id"] is None

    def test_failed_recipient_is_logged_and_dropped(self, tools: Any) -> None:
        with (
            patch(
                f"{MODULE}.proxy_request_sync",
                side_effect=[{"id": "perm-1"}, AppError(message="denied", status_code=403)],
            ) as proxy,
            patch(f"{MODULE}.log.error") as err_log,
            patch(f"{MODULE}.log.set"),
        ):
            result = _call(
                tools,
                "CUSTOM_SHARE_DOC",
                ShareDocInput(
                    document_id=DOC,
                    recipients=[
                        ShareRecipient(email="ok@x.com", role="writer"),
                        ShareRecipient(email="bad@x.com", role="reader"),
                    ],
                ),
            )

        # The failing recipient is dropped from the result, not reported as shared.
        assert result == {
            "document_id": DOC,
            "url": EXPECTED_URL,
            "shared": [
                {
                    "email": "ok@x.com",
                    "role": "writer",
                    "permission_id": "perm-1",
                    "notification_sent": True,
                }
            ],
        }
        err_log.assert_called_once_with(
            f"{LogTag.TOOL} Error sharing doc with recipient", error_type="AppError"
        )
        assert proxy.call_count == 2

    def test_all_recipients_fail_raises_runtime_error(self, tools: Any) -> None:
        with (
            patch(
                f"{MODULE}.proxy_request_sync",
                side_effect=AppError(message="denied", status_code=403),
            ) as proxy,
            patch(f"{MODULE}.log.error"),
            patch(f"{MODULE}.log.set"),
        ):
            with pytest.raises(RuntimeError) as excinfo:
                _call(
                    tools,
                    "CUSTOM_SHARE_DOC",
                    ShareDocInput(
                        document_id=DOC,
                        recipients=[ShareRecipient(email="bad@x.com", role="reader")],
                    ),
                )

        assert str(excinfo.value) == (
            "Failed to share document with all recipients: "
            "[{'email': 'bad@x.com', 'role': 'reader', "
            "'error': 'Failed to share: 403 - denied'}]"
        )
        assert proxy.call_count == 1

    def test_missing_user_id_is_rejected_before_any_proxy_call(self, tools: Any) -> None:
        with patch(f"{MODULE}.proxy_request_sync") as proxy:
            with pytest.raises(ValueError) as excinfo:
                tools["CUSTOM_SHARE_DOC"](
                    ShareDocInput(document_id=DOC, recipients=[ShareRecipient(email="a@x.com")]),
                    MagicMock(),
                    {},
                )

        assert str(excinfo.value) == "Missing user_id in auth_credentials"
        proxy.assert_not_called()


# ---------------------------------------------------------------------------
# CUSTOM_CREATE_TOC
# ---------------------------------------------------------------------------

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
            {
                "startIndex": 5,
                "paragraph": {
                    "elements": [{"textRun": {"content": "## Skipped Level"}}],
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                },
            },
        ]
    }
}


def _successful_doc_response() -> dict[str, Any]:
    return {"successful": True, "data": DOCS_DOCUMENT}


def _toc_tools(
    get_doc: Any | None = None, insert: Any | None = None
) -> tuple[dict[str, Any], MagicMock]:
    """Register tools against a composio mock with canned execute results."""
    composio = MagicMock()
    composio.tools.execute.side_effect = [
        _successful_doc_response() if get_doc is None else get_doc,
        {"successful": True, "data": {}} if insert is None else insert,
    ]
    return _register(composio), composio


class TestCreateToc:
    def test_builds_toc_and_inserts_it_with_exact_payloads(self) -> None:
        composio = MagicMock()
        composio.tools.execute.side_effect = _execute_results(
            _successful_doc_response(), {"successful": True, "data": {"inserted": 1}}
        )
        tools = _register(composio)

        with patch(f"{MODULE}.log.set") as log_set:
            result = tools["CUSTOM_CREATE_TOC"](
                CreateTOCInput(document_id=DOC),
                MagicMock(),
                AUTH,
            )

        log_set.assert_called_once_with(tool={"integration": "google_docs", "action": "create_toc"})
        assert composio.tools.execute.call_args_list == [
            call(
                slug="GOOGLEDOCS_GET_DOCUMENT_BY_ID",
                arguments={"id": DOC},
                version="v1",
                dangerously_skip_version_check=True,
                user_id="user-42",
            ),
            call(
                slug="GOOGLEDOCS_INSERT_TEXT_ACTION",
                arguments={
                    "document_id": DOC,
                    "text": (
                        "Table of Contents\n"
                        "=================\n"
                        "\n"
                        "• Chapter One\n"
                        "  ○ Section\n"
                        "• Markdown Heading\n"
                        "  ○ Skipped Level\n"
                        "\n"
                    ),
                    "insertion_index": 1,
                },
                version="v1",
                dangerously_skip_version_check=True,
                user_id="user-42",
            ),
        ]
        assert result == {
            "document_id": DOC,
            "url": EXPECTED_URL,
            "headings_found": 4,
            "toc_content": (
                "Table of Contents\n"
                "=================\n"
                "\n"
                "• Chapter One\n"
                "  ○ Section\n"
                "• Markdown Heading\n"
                "  ○ Skipped Level\n"
                "\n"
            ),
            "headings": [
                {"level": 1, "text": "Chapter One", "start_index": 2},
                {"level": 2, "text": "Section", "start_index": 3},
                {"level": 1, "text": "Markdown Heading", "start_index": 4},
                {"level": 2, "text": "Skipped Level", "start_index": 5},
            ],
            "insert_response": {"inserted": 1},
        }

    def test_title_and_insertion_index_flow_through(self) -> None:
        composio = MagicMock()
        composio.tools.execute.side_effect = _execute_results(
            _successful_doc_response(), {"successful": True, "data": {}}
        )
        tools = _register(composio)

        tools["CUSTOM_CREATE_TOC"](
            CreateTOCInput(document_id=DOC, title="Outline", insertion_index=7),
            MagicMock(),
            AUTH,
        )

        insert_call = composio.tools.execute.call_args_list[1]
        assert insert_call.kwargs["arguments"]["insertion_index"] == 7
        assert insert_call.kwargs["arguments"]["text"].startswith("Outline\n=======\n")

    def test_include_heading_levels_filters_headings(self) -> None:
        composio = MagicMock()
        composio.tools.execute.side_effect = _execute_results(
            _successful_doc_response(), {"successful": True, "data": {}}
        )
        tools = _register(composio)

        result = tools["CUSTOM_CREATE_TOC"](
            CreateTOCInput(document_id=DOC, include_heading_levels=[1]),
            MagicMock(),
            AUTH,
        )

        assert [h["text"] for h in result["headings"]] == [
            "Chapter One",
            "Markdown Heading",
        ]
        assert result["headings_found"] == 2

    def test_get_doc_failure_raises_value_error(self) -> None:
        tools, composio = _toc_tools(get_doc={"successful": False, "error": "doc gone"})

        with pytest.raises(ValueError) as excinfo:
            tools["CUSTOM_CREATE_TOC"](CreateTOCInput(document_id=DOC), MagicMock(), AUTH)
        assert str(excinfo.value) == "Failed to get document: doc gone"

        # The insert call must never happen if the read failed.
        assert composio.tools.execute.call_count == 1

    def test_insert_failure_raises_value_error(self) -> None:
        tools, composio = _toc_tools(insert={"successful": False, "error": "readonly"})

        with pytest.raises(ValueError) as excinfo:
            tools["CUSTOM_CREATE_TOC"](CreateTOCInput(document_id=DOC), MagicMock(), AUTH)
        assert str(excinfo.value) == "Failed to insert text: readonly"

        assert composio.tools.execute.call_count == 2

    def test_type_error_from_execute_is_re_raised(self) -> None:
        composio = MagicMock()
        composio.tools.execute.side_effect = TypeError("bad signature")
        tools = _register(composio)
        with (
            patch(f"{MODULE}.log.debug") as debug_log,
        ):
            with pytest.raises(TypeError, match="bad signature"):
                tools["CUSTOM_CREATE_TOC"](CreateTOCInput(document_id=DOC), MagicMock(), AUTH)

        debug_log.assert_called_once_with(
            f"{LogTag.TOOL} TypeError in execute", error_type="TypeError"
        )

    def test_stringified_json_data_is_unwrapped(self) -> None:
        composio = MagicMock()
        composio.tools.execute.side_effect = _execute_results(
            {
                "successful": True,
                "data": json.dumps(DOCS_DOCUMENT),
            },
            {"successful": True, "data": {}},
        )
        tools = _register(composio)

        result = tools["CUSTOM_CREATE_TOC"](CreateTOCInput(document_id=DOC), MagicMock(), AUTH)

        assert result["headings_found"] == 4

    def test_unparseable_string_data_is_rejected(self) -> None:
        # json.loads fails; doc_data stays a string. A string has no "body"
        # key — the tool must refuse to build a TOC from it.
        tools, _ = _toc_tools(get_doc={"successful": True, "data": "not json"})

        with (
            patch(f"{MODULE}.log.debug") as debug_log,
            pytest.raises(ValueError) as excinfo,
        ):
            tools["CUSTOM_CREATE_TOC"](CreateTOCInput(document_id=DOC), MagicMock(), AUTH)

        assert str(excinfo.value) == "Failed to get document or document has no body content"
        debug_log.assert_called_once_with(
            f"{LogTag.TOOL} JSON parsing skipped for doc_data",
            error_type="JSONDecodeError",
        )

    def test_list_data_containing_body_key_is_rejected_as_wrong_format(self) -> None:
        # A JSON array that happens to contain the string "body" slips past
        # the membership check and must hit the isinstance guard.
        tools, _ = _toc_tools(get_doc={"successful": True, "data": ["body"]})

        with pytest.raises(ValueError) as excinfo:
            tools["CUSTOM_CREATE_TOC"](CreateTOCInput(document_id=DOC), MagicMock(), AUTH)
        assert str(excinfo.value) == "Document data is not in expected format"

    @pytest.mark.parametrize(
        "data",
        [None, "", {}, {"no_body": 1}],
    )
    def test_document_without_body_is_rejected(self, data: Any) -> None:
        tools, _ = _toc_tools(get_doc={"successful": True, "data": data})

        with pytest.raises(ValueError) as excinfo:
            tools["CUSTOM_CREATE_TOC"](CreateTOCInput(document_id=DOC), MagicMock(), AUTH)
        assert str(excinfo.value) == "Failed to get document or document has no body content"

    def test_version_and_user_id_are_taken_from_credentials(self) -> None:
        tools, composio = _toc_tools()

        tools["CUSTOM_CREATE_TOC"](
            CreateTOCInput(document_id=DOC),
            MagicMock(),
            {"user_id": "u-7", "version": "v9"},
        )

        for execute_call in composio.tools.execute.call_args_list:
            assert execute_call.kwargs["version"] == "v9"
            assert execute_call.kwargs["user_id"] == "u-7"
            assert execute_call.kwargs["dangerously_skip_version_check"] is True

    def test_no_headings_produces_fallback_toc_text(self) -> None:
        tools, composio = _toc_tools(
            get_doc={
                "successful": True,
                "data": {"body": {"content": [{"paragraph": {"elements": []}}]}},
            }
        )

        result = tools["CUSTOM_CREATE_TOC"](CreateTOCInput(document_id=DOC), MagicMock(), AUTH)

        assert result["headings"] == []
        assert result["toc_content"] == "Table of Contents\n\n(No headings found in document)\n\n"
        insert_call = composio.tools.execute.call_args_list[1]
        assert insert_call.kwargs["arguments"]["text"] == result["toc_content"]


# ---------------------------------------------------------------------------
# CUSTOM_DELETE_DOC
# ---------------------------------------------------------------------------


class TestDeleteDoc:
    def test_deletes_the_drive_file(self, tools: Any) -> None:
        with (
            patch(f"{MODULE}.proxy_request_sync", return_value=None) as proxy,
            patch(f"{MODULE}.log.set") as log_set,
        ):
            result = _call(
                tools,
                "CUSTOM_DELETE_DOC",
                DeleteDocInput(document_id=DOC),
            )

        log_set.assert_called_once_with(tool={"integration": "google_docs", "action": "delete_doc"})
        assert proxy.call_args.kwargs == {
            "user_id": "user-42",
            "toolkit": DOCS_TOOLKIT,
            "endpoint": f"{DRIVE_API_BASE}/files/{DOC}",
            "method": "DELETE",
        }
        assert result == {"successful": True, "document_id": DOC}

    def test_proxy_failure_raises_runtime_error(self, tools: Any) -> None:
        with (
            patch(
                f"{MODULE}.proxy_request_sync",
                side_effect=AppError(message="denied", status_code=403),
            ),
            patch(f"{MODULE}.log.error") as err_log,
            patch(f"{MODULE}.log.set"),
        ):
            with pytest.raises(RuntimeError) as excinfo:
                _call(
                    tools,
                    "CUSTOM_DELETE_DOC",
                    DeleteDocInput(document_id=DOC),
                )

        assert str(excinfo.value) == "Failed to delete document: 403 - denied"
        err_log.assert_called_once_with(
            f"{LogTag.TOOL} Error deleting doc",
            document_id=DOC,
            error_type="AppError",
        )

    def test_missing_user_id_is_rejected_before_any_proxy_call(self, tools: Any) -> None:
        with patch(f"{MODULE}.proxy_request_sync") as proxy:
            with pytest.raises(ValueError) as excinfo:
                tools["CUSTOM_DELETE_DOC"](DeleteDocInput(document_id=DOC), MagicMock(), {})

        assert str(excinfo.value) == "Missing user_id in auth_credentials"
        proxy.assert_not_called()


# ---------------------------------------------------------------------------
# CUSTOM_GATHER_CONTEXT
# ---------------------------------------------------------------------------


class TestGatherContext:
    def test_returns_recent_docs_snapshot(self, tools: Any) -> None:
        with (
            patch(
                f"{MODULE}.proxy_request_sync",
                return_value={
                    "files": [
                        {
                            "id": "f1",
                            "name": "Notes",
                            "modifiedTime": "2024-01-02T03:04:05Z",
                            "webViewLink": "https://docs.google.com/document/d/f1/edit",
                            "extra": "ignored",
                        },
                        {"id": "f2", "name": "Plan", "modifiedTime": None, "webViewLink": None},
                    ]
                },
            ) as proxy,
            patch(f"{MODULE}.log.set") as log_set,
        ):
            result = _call(tools, "CUSTOM_GATHER_CONTEXT", GatherContextInput())

        log_set.assert_called_once_with(
            tool={"integration": "google_docs", "action": "gather_context"}
        )
        assert proxy.call_args.kwargs == {
            "user_id": "user-42",
            "toolkit": DOCS_TOOLKIT,
            "endpoint": f"{DRIVE_API_BASE}/files",
            "method": "GET",
            "query": {
                "q": "mimeType='application/vnd.google-apps.document'",
                "orderBy": "viewedByMeTime desc",
                "pageSize": 20,
                "fields": "files(id,name,modifiedTime,webViewLink)",
            },
        }
        assert result == {
            "recent_docs": [
                {
                    "id": "f1",
                    "name": "Notes",
                    "modified": "2024-01-02T03:04:05Z",
                    "url": "https://docs.google.com/document/d/f1/edit",
                },
                {"id": "f2", "name": "Plan", "modified": None, "url": None},
            ],
            "doc_count": 2,
        }

    def test_empty_payload_yields_empty_snapshot(self, tools: Any) -> None:
        # A payload without a "files" key is a normal, expected response — it
        # must not raise into the broad except (which would log a debug error).
        with (
            patch(f"{MODULE}.proxy_request_sync", return_value=None),
            patch(f"{MODULE}.log.debug") as debug_log,
            patch(f"{MODULE}.log.set"),
        ):
            result = _call(tools, "CUSTOM_GATHER_CONTEXT", GatherContextInput())

        assert result == {"recent_docs": [], "doc_count": 0}
        debug_log.assert_not_called()

    def test_fetch_failure_is_logged_and_swallowed(self, tools: Any) -> None:
        with (
            patch(
                f"{MODULE}.proxy_request_sync",
                side_effect=RuntimeError("connection reset"),
            ),
            patch(f"{MODULE}.log.debug") as debug_log,
            patch(f"{MODULE}.log.set"),
        ):
            result = _call(tools, "CUSTOM_GATHER_CONTEXT", GatherContextInput())

        assert result == {"recent_docs": [], "doc_count": 0}
        debug_log.assert_called_once_with(
            f"{LogTag.TOOL} Google Docs fetch failed", error_type="RuntimeError"
        )

    def test_missing_user_id_is_rejected_before_any_proxy_call(self, tools: Any) -> None:
        with patch(f"{MODULE}.proxy_request_sync") as proxy:
            with pytest.raises(ValueError) as excinfo:
                tools["CUSTOM_GATHER_CONTEXT"](GatherContextInput(), MagicMock(), {})

        assert str(excinfo.value) == "Missing user_id in auth_credentials"
        proxy.assert_not_called()
