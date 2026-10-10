"""Behavior tests for Google Docs custom tool registration and error paths.

The proxy smoke test (test_integration_tools_proxy.py) proves routing; these
tests pin the exact registration contract (tool names + toolkit kwarg) and
the delete-doc failure path.
"""

from collections.abc import Callable
import json
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from app.agents.tools.integrations.google_docs_tool import (
    _create_toc,
    _delete_doc,
    _fetch_document_data,
    _gather_recent_docs,
    _insert_toc_text,
    _share_doc,
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
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.google_docs import (
    GoogleDocsDocument,
    GoogleDocsHeading,
    GoogleDocsToolExecution,
)
from app.services.composio.proxy_client import ProxyRequest
from app.utils.errors import AppError

MODULE = "app.agents.tools.integrations.google_docs_tool"

AUTH_CREDS: dict[str, Any] = {"user_id": "user_test_123"}
CREDS = CustomToolAuthCredentials(user_id="user_test_123")

EXPECTED_TOOL_NAMES = [
    "GOOGLEDOCS_CUSTOM_SHARE_DOC",
    "GOOGLEDOCS_CUSTOM_CREATE_TOC",
    "GOOGLEDOCS_CUSTOM_DELETE_DOC",
    "GOOGLEDOCS_CUSTOM_GATHER_CONTEXT",
]


def _capture_tools(
    register_fn: Callable[..., list[str]],
) -> tuple[
    list[str],
    dict[str, tuple[Callable[..., Any], dict[str, Any]]],
    MagicMock,
]:
    captured: dict[str, tuple[Callable[..., Any], dict[str, Any]]] = {}
    composio = MagicMock()

    def custom_tool(**kwargs: Any) -> Callable[[Any], Any]:
        def decorator(fn: Any) -> Any:
            # Composio registers custom tools under "<TOOLKIT>_<fn name>".
            registered_name = f"{kwargs.get('toolkit', '')}_{fn.__name__}"
            captured[registered_name] = (fn, kwargs)
            return fn

        return decorator

    composio.tools.custom_tool = custom_tool
    registered = register_fn(composio)
    return registered, captured, composio


def test_register_returns_exact_tool_names_and_toolkits() -> None:
    registered, captured, _ = _capture_tools(register_google_docs_custom_tools)

    assert registered == EXPECTED_TOOL_NAMES
    assert sorted(captured) == sorted(EXPECTED_TOOL_NAMES)
    assert all(kwargs == {"toolkit": "GOOGLEDOCS"} for _, kwargs in captured.values())


def test_register_docstring_pins_tool_description() -> None:
    assert register_google_docs_custom_tools.__doc__ == (
        "Register Google Docs tools as Composio custom tools."
    )


# --- _share_doc --------------------------------------------------------------


def test_share_doc_sends_exact_permission_request_per_recipient() -> None:
    request = ShareDocInput(
        document_id="doc-77",
        recipients=[
            ShareRecipient(email="a@x.com", role="writer", send_notification=True),
            ShareRecipient(email="b@x.com", role="reader", send_notification=False),
        ],
    )
    proxy = MagicMock(side_effect=[{"id": "perm-1"}, {"id": "perm-2"}])

    with patch(f"{MODULE}.proxy_request_sync", proxy):
        result = _share_doc(request, "user_42")

    assert proxy.call_args_list == [
        call(
            ProxyRequest(
                user_id="user_42",
                toolkit="GOOGLEDOCS",
                endpoint="https://www.googleapis.com/drive/v3/files/doc-77/permissions",
                method="POST",
                body={"type": "user", "role": "writer", "emailAddress": "a@x.com"},
                query={"sendNotificationEmail": "true"},
            )
        ),
        call(
            ProxyRequest(
                user_id="user_42",
                toolkit="GOOGLEDOCS",
                endpoint="https://www.googleapis.com/drive/v3/files/doc-77/permissions",
                method="POST",
                body={"type": "user", "role": "reader", "emailAddress": "b@x.com"},
                query={"sendNotificationEmail": "false"},
            )
        ),
    ]
    assert result == {
        "document_id": "doc-77",
        "url": "https://docs.google.com/document/d/doc-77/edit",
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
                "permission_id": "perm-2",
                "notification_sent": False,
            },
        ],
    }


def test_share_doc_none_proxy_result_maps_to_none_permission_id() -> None:
    request = ShareDocInput(document_id="doc-8", recipients=[ShareRecipient(email="a@x.com")])

    with patch(f"{MODULE}.proxy_request_sync", MagicMock(return_value=None)):
        result = _share_doc(request, "user_42")

    assert result["shared"] == [
        {"email": "a@x.com", "role": "writer", "permission_id": None, "notification_sent": True}
    ]


def test_share_doc_partial_failure_collects_error_and_keeps_successes() -> None:
    request = ShareDocInput(
        document_id="doc-9",
        recipients=[
            ShareRecipient(email="bad@x.com", role="writer"),
            ShareRecipient(email="good@x.com", role="reader"),
        ],
    )
    error = AppError(message="Drive said no", status_code=403)
    proxy = MagicMock(side_effect=[error, {"id": "perm-ok"}])

    with patch(f"{MODULE}.proxy_request_sync", proxy), patch(f"{MODULE}.log") as log_mock:
        result = _share_doc(request, "user_42")

    assert log_mock.error.call_args_list == [
        call(f"{LogTag.TOOL} Error sharing doc with recipient", error_type="AppError")
    ]
    assert proxy.call_count == 2
    assert result == {
        "document_id": "doc-9",
        "url": "https://docs.google.com/document/d/doc-9/edit",
        "shared": [
            {
                "email": "good@x.com",
                "role": "reader",
                "permission_id": "perm-ok",
                "notification_sent": True,
            }
        ],
        "errors": [
            {
                "email": "bad@x.com",
                "role": "writer",
                "error": "Failed to share: 403 - Drive said no",
            }
        ],
    }


def test_share_doc_all_recipients_fail_raises_runtime_error_with_every_error() -> None:
    request = ShareDocInput(
        document_id="doc-10",
        recipients=[
            ShareRecipient(email="a@x.com", role="writer"),
            ShareRecipient(email="b@x.com", role="reader"),
        ],
    )
    expected_errors = [
        {"email": "a@x.com", "role": "writer", "error": "Failed to share: 403 - first no"},
        {"email": "b@x.com", "role": "reader", "error": "Failed to share: 500 - second no"},
    ]
    proxy = MagicMock(
        side_effect=[
            AppError(message="first no", status_code=403),
            AppError(message="second no", status_code=500),
        ]
    )

    with patch(f"{MODULE}.proxy_request_sync", proxy), patch(f"{MODULE}.log") as log_mock:
        with pytest.raises(RuntimeError) as excinfo:
            _share_doc(request, "user_42")

    assert str(excinfo.value) == (
        f"Failed to share document with all recipients: {expected_errors}"
    )
    assert proxy.call_count == 2
    assert log_mock.error.call_count == 2


# --- _delete_doc -------------------------------------------------------------


def test_delete_doc_sends_exact_delete_request_and_returns_confirmation() -> None:
    proxy = MagicMock(return_value=MagicMock())

    with patch(f"{MODULE}.proxy_request_sync", proxy):
        result = _delete_doc(DeleteDocInput(document_id="doc-9"), "user_42")

    proxy.assert_called_once_with(
        ProxyRequest(
            user_id="user_42",
            toolkit="GOOGLEDOCS",
            endpoint="https://www.googleapis.com/drive/v3/files/doc-9",
            method="DELETE",
        )
    )
    assert result == {"successful": True, "document_id": "doc-9"}


def test_delete_doc_app_error_logs_document_and_error_type_before_raising() -> None:
    error = AppError(message="Drive API error (403)", status_code=403)

    with (
        patch(f"{MODULE}.proxy_request_sync", side_effect=error),
        patch(f"{MODULE}.log") as log_mock,
    ):
        with pytest.raises(RuntimeError) as excinfo:
            _delete_doc(DeleteDocInput(document_id="doc-1"), "user_test_123")

    assert str(excinfo.value) == "Failed to delete document: 403 - Drive API error (403)"
    assert excinfo.value.__cause__ is error
    assert log_mock.error.call_args_list == [
        call(
            f"{LogTag.TOOL} Error deleting doc",
            document_id="doc-1",
            error_type="AppError",
        )
    ]


# --- registered tool wrappers: log.set + delegation contract ------------------


def test_custom_share_doc_wrapper_logs_action_and_shares_via_proxy() -> None:
    _, tools, _ = _capture_tools(register_google_docs_custom_tools)
    share_doc, _ = tools["GOOGLEDOCS_CUSTOM_SHARE_DOC"]
    request = ShareDocInput(document_id="doc-5", recipients=[ShareRecipient(email="a@x.com")])
    proxy = MagicMock(return_value={"id": "p1"})

    with patch(f"{MODULE}.proxy_request_sync", proxy), patch(f"{MODULE}.log") as log_mock:
        result = share_doc(request, MagicMock(), AUTH_CREDS)

    assert log_mock.set.call_args_list == [
        call(tool={"integration": "google_docs", "action": "share_doc"})
    ]
    assert proxy.call_args.args[0].user_id == "user_test_123"
    assert result["document_id"] == "doc-5"
    assert result["url"] == "https://docs.google.com/document/d/doc-5/edit"
    assert result["shared"] == [
        {"email": "a@x.com", "role": "writer", "permission_id": "p1", "notification_sent": True}
    ]


def test_custom_create_toc_wrapper_logs_action_and_delegates() -> None:
    _, tools, composio = _capture_tools(register_google_docs_custom_tools)
    create_toc, _ = tools["GOOGLEDOCS_CUSTOM_CREATE_TOC"]
    request = CreateTOCInput(document_id="doc-6")
    delegate_result: dict[str, Any] = {"document_id": "doc-6", "toc_content": "# TOC"}

    with (
        patch(f"{MODULE}._create_toc", MagicMock(return_value=delegate_result)) as delegate,
        patch(f"{MODULE}.log") as log_mock,
    ):
        result = create_toc(request, MagicMock(), AUTH_CREDS)

    assert log_mock.set.call_args_list == [
        call(tool={"integration": "google_docs", "action": "create_toc"})
    ]
    delegate.assert_called_once_with(composio, request, CREDS)
    assert result == delegate_result


@pytest.mark.parametrize(
    "creds",
    [{}, {"user_id": ""}, {"user_id": None}, {"user_id": 123}, {"userId": "abc"}],
    ids=["missing", "blank", "none", "int", "wrong-key"],
)
def test_wrappers_reject_unusable_credentials_before_any_call(creds: dict[str, Any]) -> None:
    _, tools, composio = _capture_tools(register_google_docs_custom_tools)
    wrappers = [
        (
            tools["GOOGLEDOCS_CUSTOM_SHARE_DOC"][0],
            ShareDocInput(document_id="d", recipients=[ShareRecipient(email="a@x.com")]),
        ),
        (tools["GOOGLEDOCS_CUSTOM_CREATE_TOC"][0], CreateTOCInput(document_id="d")),
        (tools["GOOGLEDOCS_CUSTOM_DELETE_DOC"][0], DeleteDocInput(document_id="d")),
        (tools["GOOGLEDOCS_CUSTOM_GATHER_CONTEXT"][0], GatherContextInput()),
    ]
    with patch(f"{MODULE}.proxy_request_sync") as proxy:
        for wrapper, request in wrappers:
            with pytest.raises(ValueError, match="Missing user_id in auth_credentials"):
                wrapper(request, MagicMock(), creds)
    proxy.assert_not_called()
    composio.tools.execute.assert_not_called()


def test_custom_delete_doc_wrapper_logs_action_and_deletes() -> None:
    _, tools, _ = _capture_tools(register_google_docs_custom_tools)
    delete_doc, _ = tools["GOOGLEDOCS_CUSTOM_DELETE_DOC"]
    proxy = MagicMock(return_value=None)

    with patch(f"{MODULE}.proxy_request_sync", proxy), patch(f"{MODULE}.log") as log_mock:
        result = delete_doc(DeleteDocInput(document_id="doc-7"), MagicMock(), AUTH_CREDS)

    assert log_mock.set.call_args_list == [
        call(tool={"integration": "google_docs", "action": "delete_doc"})
    ]
    proxy.assert_called_once_with(
        ProxyRequest(
            user_id="user_test_123",
            toolkit="GOOGLEDOCS",
            endpoint="https://www.googleapis.com/drive/v3/files/doc-7",
            method="DELETE",
        )
    )
    assert result == {"successful": True, "document_id": "doc-7"}


def test_custom_gather_context_wrapper_logs_action_and_delegates_user_id() -> None:
    _, tools, _ = _capture_tools(register_google_docs_custom_tools)
    gather_context, _ = tools["GOOGLEDOCS_CUSTOM_GATHER_CONTEXT"]
    delegate_result: dict[str, Any] = {"recent_docs": [{"id": "d1"}], "doc_count": 1}

    with (
        patch(f"{MODULE}._gather_recent_docs", MagicMock(return_value=delegate_result)) as delegate,
        patch(f"{MODULE}.log") as log_mock,
    ):
        result = gather_context(GatherContextInput(), MagicMock(), AUTH_CREDS)

    assert log_mock.set.call_args_list == [
        call(tool={"integration": "google_docs", "action": "gather_context"})
    ]
    delegate.assert_called_once_with("user_test_123")
    assert result == delegate_result


def test_wrapper_docstrings_are_pinned() -> None:
    _, captured, _ = _capture_tools(register_google_docs_custom_tools)

    # The other wrappers get their docstrings from @with_doc templates; this
    # one carries its own source docstring through to Composio registration.
    gather_fn, _ = captured["GOOGLEDOCS_CUSTOM_GATHER_CONTEXT"]
    assert gather_fn.__doc__ == (
        "Get Google Docs context snapshot: recently viewed/modified documents.\n"
        "\n"
        "        Zero required parameters. Returns user's recently accessed Google Docs.\n"
        "        "
    )


def test_delete_doc_raises_runtime_error_on_app_error() -> None:
    _, tools, _ = _capture_tools(register_google_docs_custom_tools)
    delete_doc, _ = tools["GOOGLEDOCS_CUSTOM_DELETE_DOC"]
    error = AppError(message="Drive API error (403)", status_code=403)

    with patch(f"{MODULE}.proxy_request_sync", side_effect=error) as proxy:
        with pytest.raises(RuntimeError) as excinfo:
            delete_doc(DeleteDocInput(document_id="doc-1"), MagicMock(), AUTH_CREDS)

    assert str(excinfo.value) == "Failed to delete document: 403 - Drive API error (403)"
    assert excinfo.value.__cause__ is error
    assert proxy.call_args.args[0].method == "DELETE"
    assert proxy.call_args.args[0].endpoint.endswith("/files/doc-1")


# --- _fetch_document_data ------------------------------------------------------


def _composio_returning(result: dict[str, Any]) -> MagicMock:
    composio = MagicMock()
    composio.tools.execute.return_value = result
    return composio


def test_fetch_document_data_returns_parsed_document() -> None:
    composio = _composio_returning({"successful": True, "data": {"body": {"content": []}}})

    assert _fetch_document_data(composio, "doc-1", CREDS) == GoogleDocsDocument.model_validate(
        {"body": {"content": []}}
    )
    composio.tools.execute.assert_called_once_with(
        slug="GOOGLEDOCS_GET_DOCUMENT_BY_ID",
        arguments={"id": "doc-1"},
        version=None,
        dangerously_skip_version_check=True,
        user_id="user_test_123",
    )


def test_fetch_document_data_passes_version_through_from_credentials() -> None:
    composio = _composio_returning({"successful": True, "data": {"body": {}}})
    creds = CustomToolAuthCredentials.parse({"user_id": "user_test_123", "version": "2024-01-01"})

    _fetch_document_data(composio, "doc-1", creds)

    assert composio.tools.execute.call_args.kwargs["version"] == "2024-01-01"


def test_fetch_document_data_parses_stringified_json_payload() -> None:
    document = {
        "body": {
            "content": [
                {
                    "startIndex": 1,
                    "paragraph": {
                        "paragraphStyle": {"namedStyleType": "HEADING_1"},
                        "elements": [{"textRun": {"content": "Intro\n"}}],
                    },
                }
            ]
        }
    }
    composio = _composio_returning({"successful": True, "data": json.dumps(document)})

    parsed = _fetch_document_data(composio, "doc-1", CREDS)

    assert parsed == GoogleDocsDocument.model_validate(document)
    assert parsed.body.content[0].paragraph is not None
    assert parsed.body.content[0].paragraph.elements[0].textRun is not None
    assert parsed.body.content[0].paragraph.elements[0].textRun.content == "Intro\n"


def test_fetch_document_data_invalid_json_string_fails_the_body_check() -> None:
    composio = _composio_returning({"successful": True, "data": "{not json"})

    with patch(f"{MODULE}.log") as log_mock:
        with pytest.raises(ValueError) as excinfo:
            _fetch_document_data(composio, "doc-1", CREDS)

    assert str(excinfo.value) == "Failed to get document or document has no body content"
    assert log_mock.debug.call_args.kwargs["error_type"] == "JSONDecodeError"


def test_fetch_document_data_non_dict_payload_with_body_substring_raises_format_error() -> None:
    composio = _composio_returning({"successful": True, "data": "raw body blob"})

    with pytest.raises(ValueError) as excinfo:
        _fetch_document_data(composio, "doc-1", CREDS)

    assert str(excinfo.value) == "Document data is not in expected format"


def test_fetch_document_data_unsuccessful_execute_raises_value_error() -> None:
    composio = _composio_returning({"successful": False, "error": "quota exceeded"})

    with pytest.raises(ValueError) as excinfo:
        _fetch_document_data(composio, "doc-1", CREDS)

    assert str(excinfo.value) == "Failed to get document: quota exceeded"


def test_fetch_document_data_type_error_from_execute_propagates() -> None:
    composio = MagicMock()
    composio.tools.execute.side_effect = TypeError("bad signature")

    with patch(f"{MODULE}.log") as log_mock:
        with pytest.raises(TypeError):
            _fetch_document_data(composio, "doc-1", CREDS)

    assert log_mock.debug.call_args.kwargs["error_type"] == "TypeError"


# --- _insert_toc_text / _create_toc --------------------------------------------


def test_insert_toc_text_sends_exact_insert_request_and_returns_result() -> None:
    request = CreateTOCInput(document_id="doc-6", insertion_index=2)
    composio = _composio_returning({"successful": True, "data": {"done": True}})

    result = _insert_toc_text(composio, request, "# TOC", CREDS)

    composio.tools.execute.assert_called_once_with(
        slug="GOOGLEDOCS_INSERT_TEXT_ACTION",
        arguments={"document_id": "doc-6", "text": "# TOC", "insertion_index": 2},
        version=None,
        dangerously_skip_version_check=True,
        user_id="user_test_123",
    )
    assert result == GoogleDocsToolExecution(successful=True, data={"done": True})


def test_insert_toc_text_passes_version_through_from_credentials() -> None:
    composio = _composio_returning({"successful": True})
    creds = CustomToolAuthCredentials.parse({"user_id": "user_test_123", "version": "2024-06-01"})

    _insert_toc_text(composio, CreateTOCInput(document_id="doc-6"), "# TOC", creds)

    assert composio.tools.execute.call_args.kwargs["version"] == "2024-06-01"


def test_insert_toc_text_failure_raises_value_error() -> None:
    composio = _composio_returning({"successful": False, "error": "insert denied"})

    with pytest.raises(ValueError) as excinfo:
        _insert_toc_text(composio, CreateTOCInput(document_id="doc-6"), "# TOC", CREDS)

    assert str(excinfo.value) == "Failed to insert text: insert denied"


HEADINGS = [
    GoogleDocsHeading(level=1, text="Intro", start_index=1),
    GoogleDocsHeading(level=2, text="Details", start_index=9),
]


@patch(f"{MODULE}._insert_toc_text")
@patch(f"{MODULE}.generate_toc_text", return_value="# Table of contents")
@patch(f"{MODULE}.extract_headings_from_document", return_value=HEADINGS)
@patch(f"{MODULE}._fetch_document_data")
def test_create_toc_combines_fetch_extract_and_insert_into_one_response(
    mock_fetch: MagicMock,
    mock_extract: MagicMock,
    mock_generate: MagicMock,
    mock_insert: MagicMock,
) -> None:
    composio = MagicMock()
    request = CreateTOCInput(document_id="doc-6", title="Contents")
    document = GoogleDocsDocument.model_validate({"body": {}})
    mock_fetch.return_value = document
    mock_insert.return_value = GoogleDocsToolExecution(successful=True, data={"revision": 7})

    result = _create_toc(composio, request, CREDS)

    mock_fetch.assert_called_once_with(composio, "doc-6", CREDS)
    mock_extract.assert_called_once_with(document, request.include_heading_levels)
    mock_generate.assert_called_once_with(HEADINGS, "Contents")
    mock_insert.assert_called_once_with(composio, request, "# Table of contents", CREDS)
    assert result == {
        "document_id": "doc-6",
        "url": "https://docs.google.com/document/d/doc-6/edit",
        "headings_found": 2,
        "toc_content": "# Table of contents",
        "headings": [
            {"level": 1, "text": "Intro", "start_index": 1},
            {"level": 2, "text": "Details", "start_index": 9},
        ],
        "insert_response": {"revision": 7},
    }


def test_create_toc_end_to_end_on_a_documents_get_payload() -> None:
    """The real extract + generate path on a documents.get-shaped fixture."""
    document = {
        "documentId": "doc-6",
        "title": "Report",
        "body": {
            "content": [
                {"endIndex": 1, "sectionBreak": {"sectionStyle": {}}},
                {
                    "startIndex": 1,
                    "endIndex": 7,
                    "paragraph": {
                        "elements": [{"startIndex": 1, "textRun": {"content": "Intro\n"}}],
                        "paragraphStyle": {"namedStyleType": "HEADING_1"},
                    },
                },
                {
                    "startIndex": 7,
                    "endIndex": 20,
                    "paragraph": {
                        "elements": [{"textRun": {"content": "Body text\n"}}],
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    },
                },
                {
                    "startIndex": 20,
                    "endIndex": 31,
                    "paragraph": {
                        "elements": [{"textRun": {"content": "## Details\n"}}],
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    },
                },
            ]
        },
    }
    composio = MagicMock()
    composio.tools.execute.side_effect = [
        {"successful": True, "error": None, "data": document},
        {"successful": True, "error": None, "data": {"replies": [{}], "documentId": "doc-6"}},
    ]

    result = _create_toc(composio, CreateTOCInput(document_id="doc-6"), CREDS)

    toc = "Table of Contents\n=================\n\n• Intro\n  ○ Details\n\n"
    assert composio.tools.execute.call_args_list[1] == call(
        slug="GOOGLEDOCS_INSERT_TEXT_ACTION",
        arguments={"document_id": "doc-6", "text": toc, "insertion_index": 1},
        version=None,
        dangerously_skip_version_check=True,
        user_id="user_test_123",
    )
    assert result == {
        "document_id": "doc-6",
        "url": "https://docs.google.com/document/d/doc-6/edit",
        "headings_found": 2,
        "toc_content": toc,
        "headings": [
            {"level": 1, "text": "Intro", "start_index": 1},
            {"level": 2, "text": "Details", "start_index": 20},
        ],
        "insert_response": {"replies": [{}], "documentId": "doc-6"},
    }


# --- _gather_recent_docs -------------------------------------------------------


def test_gather_recent_docs_queries_drive_and_maps_file_fields() -> None:
    proxy = MagicMock(
        return_value={
            "files": [
                {
                    "id": "d1",
                    "name": "Notes",
                    "modifiedTime": "2026-01-01T00:00:00Z",
                    "webViewLink": "https://docs.google.com/d/d1",
                },
                {"id": None},
            ]
        }
    )

    with patch(f"{MODULE}.proxy_request_sync", proxy):
        result = _gather_recent_docs("user_42")

    proxy.assert_called_once_with(
        ProxyRequest(
            user_id="user_42",
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
    )
    assert result == {
        "recent_docs": [
            {
                "id": "d1",
                "name": "Notes",
                "modified": "2026-01-01T00:00:00Z",
                "url": "https://docs.google.com/d/d1",
            },
            {"id": None, "name": None, "modified": None, "url": None},
        ],
        "doc_count": 2,
    }


def test_gather_recent_docs_with_no_proxy_result_reports_zero() -> None:
    with patch(f"{MODULE}.proxy_request_sync", MagicMock(return_value=None)):
        result = _gather_recent_docs("user_42")

    assert result == {"recent_docs": [], "doc_count": 0}
