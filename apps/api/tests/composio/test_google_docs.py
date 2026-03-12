"""Tests for Google Docs custom tools (google_docs_tool.py).

These tests verify the core logic of each tool function registered by
`register_google_docs_custom_tools`. External HTTP calls (httpx via the
module-level _http_client) and Composio SDK calls (composio.tools.execute)
are mocked so no real credentials are needed. Tests will fail if the
production module is deleted or its core behaviour changes.
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Production imports – failures here mean the module is gone/renamed
# ---------------------------------------------------------------------------
from app.agents.tools.integrations.google_docs_tool import (
    _auth_headers,
    _get_access_token,
    register_google_docs_custom_tools,
)
from app.models.google_docs_models import (
    CreateTOCInput,
    DeleteDocInput,
    ShareDocInput,
    ShareRecipient,
)


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

AUTH_CREDENTIALS: Dict[str, Any] = {
    "access_token": "ya29.google-token",
    "version": "v1",
    "user_id": "user-456",
}

DOC_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"


def _make_composio_mock() -> MagicMock:
    """Return a Composio mock that captures custom_tool registrations."""
    composio = MagicMock()
    registered_functions: Dict[str, Any] = {}

    def custom_tool_decorator(toolkit: str):
        def decorator(fn):
            registered_functions[fn.__name__] = fn
            return fn

        return decorator

    composio.tools.custom_tool.side_effect = custom_tool_decorator
    composio._registered = registered_functions
    return composio


def _register_and_extract(composio: MagicMock) -> Dict[str, Any]:
    register_google_docs_custom_tools(composio)
    return composio._registered


# ---------------------------------------------------------------------------
# Module-level helper functions
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestHelperFunctions:
    """Unit tests for the non-tool helper functions in the module."""

    def test_get_access_token_returns_token(self):
        creds = {"access_token": "token-abc"}
        assert _get_access_token(creds) == "token-abc"

    def test_get_access_token_raises_when_missing(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            _get_access_token({})

    def test_get_access_token_raises_on_empty_string(self):
        with pytest.raises(ValueError, match="Missing access_token"):
            _get_access_token({"access_token": ""})

    def test_auth_headers_returns_bearer_header(self):
        headers = _auth_headers("my-token")
        assert headers == {"Authorization": "Bearer my-token"}


# ---------------------------------------------------------------------------
# CUSTOM_SHARE_DOC
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestCustomShareDoc:
    """Tests for the CUSTOM_SHARE_DOC Google Docs custom tool."""

    def _share_request(
        self,
        doc_id: str = DOC_ID,
        emails: list[str] | None = None,
        role: str = "writer",
    ) -> ShareDocInput:
        if emails is None:
            emails = ["alice@example.com"]
        recipients = [
            ShareRecipient(email=e, role=role, send_notification=True) for e in emails
        ]
        return ShareDocInput(document_id=doc_id, recipients=recipients)

    def _permission_response(self, perm_id: str = "perm-001") -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {"id": perm_id}
        resp.raise_for_status.return_value = None
        return resp

    def test_share_single_recipient_happy_path(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_SHARE_DOC"]

        request = self._share_request()

        with patch(
            "app.agents.tools.integrations.google_docs_tool._http_client"
        ) as mock_client:
            mock_client.post.return_value = self._permission_response("perm-1")
            result = fn(request, MagicMock(), AUTH_CREDENTIALS)

        assert result["document_id"] == DOC_ID
        assert len(result["shared"]) == 1
        assert result["shared"][0]["email"] == "alice@example.com"
        assert result["shared"][0]["role"] == "writer"
        assert result["shared"][0]["permission_id"] == "perm-1"
        expected_url = f"https://docs.google.com/document/d/{DOC_ID}/edit"
        assert result["url"] == expected_url

    def test_share_multiple_recipients(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_SHARE_DOC"]

        request = self._share_request(emails=["alice@example.com", "bob@example.com"])

        with patch(
            "app.agents.tools.integrations.google_docs_tool._http_client"
        ) as mock_client:
            mock_client.post.side_effect = [
                self._permission_response("perm-a"),
                self._permission_response("perm-b"),
            ]
            result = fn(request, MagicMock(), AUTH_CREDENTIALS)

        assert len(result["shared"]) == 2
        shared_emails = [s["email"] for s in result["shared"]]
        assert "alice@example.com" in shared_emails
        assert "bob@example.com" in shared_emails

    def test_share_partial_failure_returns_shared_and_skips_failed(self):
        """If one recipient fails but others succeed, result contains successes."""
        import httpx

        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_SHARE_DOC"]

        request = self._share_request(emails=["ok@example.com", "fail@example.com"])

        error_response = MagicMock()
        error_response.status_code = 403
        error_response.text = "Forbidden"

        with patch(
            "app.agents.tools.integrations.google_docs_tool._http_client"
        ) as mock_client:
            mock_client.post.side_effect = [
                self._permission_response("perm-ok"),
                MagicMock(
                    raise_for_status=MagicMock(
                        side_effect=httpx.HTTPStatusError(
                            "403", request=MagicMock(), response=error_response
                        )
                    )
                ),
            ]
            result = fn(request, MagicMock(), AUTH_CREDENTIALS)

        # One shared, one error – no exception raised
        assert len(result["shared"]) == 1
        assert result["shared"][0]["email"] == "ok@example.com"

    def test_share_all_recipients_fail_raises_runtime_error(self):
        import httpx

        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_SHARE_DOC"]

        request = self._share_request()

        error_response = MagicMock()
        error_response.status_code = 500
        error_response.text = "Internal Server Error"

        with patch(
            "app.agents.tools.integrations.google_docs_tool._http_client"
        ) as mock_client:
            mock_client.post.return_value = MagicMock(
                raise_for_status=MagicMock(
                    side_effect=httpx.HTTPStatusError(
                        "500", request=MagicMock(), response=error_response
                    )
                )
            )
            with pytest.raises(RuntimeError, match="Failed to share document"):
                fn(request, MagicMock(), AUTH_CREDENTIALS)

    def test_share_correct_drive_api_url_called(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_SHARE_DOC"]

        request = self._share_request()

        with patch(
            "app.agents.tools.integrations.google_docs_tool._http_client"
        ) as mock_client:
            mock_client.post.return_value = self._permission_response()
            fn(request, MagicMock(), AUTH_CREDENTIALS)

        call_url = mock_client.post.call_args.args[0]
        assert DOC_ID in call_url
        assert "permissions" in call_url
        assert call_url.startswith("https://www.googleapis.com/drive/v3/files/")

    def test_share_bearer_token_sent_in_headers(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_SHARE_DOC"]

        request = self._share_request()

        with patch(
            "app.agents.tools.integrations.google_docs_tool._http_client"
        ) as mock_client:
            mock_client.post.return_value = self._permission_response()
            fn(request, MagicMock(), AUTH_CREDENTIALS)

        call_headers = mock_client.post.call_args.kwargs["headers"]
        assert call_headers["Authorization"] == "Bearer ya29.google-token"

    def test_share_send_notification_param_forwarded(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_SHARE_DOC"]

        recipients = [
            ShareRecipient(email="x@y.com", role="reader", send_notification=False)
        ]
        request = ShareDocInput(document_id=DOC_ID, recipients=recipients)

        with patch(
            "app.agents.tools.integrations.google_docs_tool._http_client"
        ) as mock_client:
            mock_client.post.return_value = self._permission_response()
            fn(request, MagicMock(), AUTH_CREDENTIALS)

        call_params = mock_client.post.call_args.kwargs["params"]
        assert call_params["sendNotificationEmail"] == "false"

    def test_share_raises_when_access_token_missing(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_SHARE_DOC"]

        request = self._share_request()
        with pytest.raises(ValueError, match="Missing access_token"):
            fn(request, MagicMock(), {})


# ---------------------------------------------------------------------------
# CUSTOM_CREATE_TOC
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestCustomCreateTOC:
    """Tests for the CUSTOM_CREATE_TOC Google Docs custom tool."""

    def _doc_with_headings(self) -> Dict[str, Any]:
        """Minimal Google Docs JSON with H1 and H2 headings."""
        return {
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "paragraph": {
                            "paragraphStyle": {"namedStyleType": "HEADING_1"},
                            "elements": [{"textRun": {"content": "Introduction\n"}}],
                        },
                    },
                    {
                        "startIndex": 14,
                        "paragraph": {
                            "paragraphStyle": {"namedStyleType": "HEADING_2"},
                            "elements": [{"textRun": {"content": "Background\n"}}],
                        },
                    },
                    {
                        "startIndex": 25,
                        "paragraph": {
                            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                            "elements": [
                                {"textRun": {"content": "Just a paragraph.\n"}}
                            ],
                        },
                    },
                ]
            }
        }

    def _make_get_doc_response(
        self, doc_data: Dict[str, Any] | None = None, successful: bool = True
    ) -> Dict[str, Any]:
        if doc_data is None:
            doc_data = self._doc_with_headings()
        return {"successful": successful, "data": doc_data, "error": None}

    def _make_insert_response(self, successful: bool = True) -> Dict[str, Any]:
        return {"successful": successful, "data": {"replies": []}, "error": "fail"}

    def test_create_toc_happy_path(self):
        composio = _make_composio_mock()
        composio.tools.execute.side_effect = [
            self._make_get_doc_response(),
            self._make_insert_response(),
        ]

        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TOC"]
        request = CreateTOCInput(document_id=DOC_ID, insertion_index=1)
        result = fn(request, MagicMock(), AUTH_CREDENTIALS)

        assert result["document_id"] == DOC_ID
        assert result["headings_found"] == 2
        # TOC content must mention both heading texts
        assert "Introduction" in result["toc_content"]
        assert "Background" in result["toc_content"]
        expected_url = f"https://docs.google.com/document/d/{DOC_ID}/edit"
        assert result["url"] == expected_url

    def test_create_toc_calls_get_document_then_insert(self):
        composio = _make_composio_mock()
        composio.tools.execute.side_effect = [
            self._make_get_doc_response(),
            self._make_insert_response(),
        ]

        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TOC"]
        request = CreateTOCInput(document_id=DOC_ID)
        fn(request, MagicMock(), AUTH_CREDENTIALS)

        assert composio.tools.execute.call_count == 2
        first_call = composio.tools.execute.call_args_list[0].kwargs
        assert first_call["slug"] == "GOOGLEDOCS_GET_DOCUMENT_BY_ID"
        assert first_call["arguments"]["id"] == DOC_ID

        second_call = composio.tools.execute.call_args_list[1].kwargs
        assert second_call["slug"] == "GOOGLEDOCS_INSERT_TEXT_ACTION"
        assert second_call["arguments"]["document_id"] == DOC_ID

    def test_create_toc_insertion_index_forwarded(self):
        composio = _make_composio_mock()
        composio.tools.execute.side_effect = [
            self._make_get_doc_response(),
            self._make_insert_response(),
        ]

        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TOC"]
        request = CreateTOCInput(document_id=DOC_ID, insertion_index=5)
        fn(request, MagicMock(), AUTH_CREDENTIALS)

        insert_call = composio.tools.execute.call_args_list[1].kwargs
        assert insert_call["arguments"]["insertion_index"] == 5

    def test_create_toc_raises_when_get_document_fails(self):
        composio = _make_composio_mock()
        composio.tools.execute.return_value = {
            "successful": False,
            "error": "Not Found",
        }

        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TOC"]
        request = CreateTOCInput(document_id="nonexistent")
        with pytest.raises(ValueError, match="Failed to get document"):
            fn(request, MagicMock(), AUTH_CREDENTIALS)

    def test_create_toc_raises_when_document_has_no_body(self):
        composio = _make_composio_mock()
        composio.tools.execute.return_value = {
            "successful": True,
            "data": {"title": "No Body Doc"},  # missing "body" key
        }

        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TOC"]
        request = CreateTOCInput(document_id=DOC_ID)
        with pytest.raises(ValueError, match="no body content"):
            fn(request, MagicMock(), AUTH_CREDENTIALS)

    def test_create_toc_raises_when_insert_fails(self):
        composio = _make_composio_mock()
        composio.tools.execute.side_effect = [
            self._make_get_doc_response(),
            {"successful": False, "error": "Insert failed"},
        ]

        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TOC"]
        request = CreateTOCInput(document_id=DOC_ID)
        with pytest.raises(ValueError, match="Failed to insert text"):
            fn(request, MagicMock(), AUTH_CREDENTIALS)

    def test_create_toc_handles_stringified_json_doc_data(self):
        """doc_data that arrives as a JSON string must be parsed."""
        import json

        composio = _make_composio_mock()
        composio.tools.execute.side_effect = [
            {"successful": True, "data": json.dumps(self._doc_with_headings())},
            self._make_insert_response(),
        ]

        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TOC"]
        request = CreateTOCInput(document_id=DOC_ID)
        result = fn(request, MagicMock(), AUTH_CREDENTIALS)
        # Should still find headings after JSON parsing
        assert result["headings_found"] == 2

    def test_create_toc_only_requested_heading_levels_included(self):
        composio = _make_composio_mock()
        composio.tools.execute.side_effect = [
            self._make_get_doc_response(),
            self._make_insert_response(),
        ]

        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TOC"]
        # Only H1 – should exclude the H2 heading
        request = CreateTOCInput(document_id=DOC_ID, include_heading_levels=[1])
        result = fn(request, MagicMock(), AUTH_CREDENTIALS)
        assert result["headings_found"] == 1
        assert result["headings"][0]["text"] == "Introduction"

    def test_create_toc_empty_document_returns_no_headings_toc(self):
        """A doc with no heading blocks returns a TOC with 0 headings found."""
        composio = _make_composio_mock()
        composio.tools.execute.side_effect = [
            {
                "successful": True,
                "data": {
                    "body": {
                        "content": [
                            {
                                "paragraph": {
                                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                                    "elements": [
                                        {"textRun": {"content": "Plain text\n"}}
                                    ],
                                }
                            }
                        ]
                    }
                },
            },
            self._make_insert_response(),
        ]

        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TOC"]
        request = CreateTOCInput(document_id=DOC_ID)
        result = fn(request, MagicMock(), AUTH_CREDENTIALS)
        assert result["headings_found"] == 0
        assert "No headings found" in result["toc_content"]

    def test_create_toc_custom_title_used(self):
        composio = _make_composio_mock()
        composio.tools.execute.side_effect = [
            self._make_get_doc_response(),
            self._make_insert_response(),
        ]

        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_CREATE_TOC"]
        request = CreateTOCInput(document_id=DOC_ID, title="Contents")
        result = fn(request, MagicMock(), AUTH_CREDENTIALS)
        assert "Contents" in result["toc_content"]


# ---------------------------------------------------------------------------
# CUSTOM_DELETE_DOC
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestCustomDeleteDoc:
    """Tests for the CUSTOM_DELETE_DOC Google Docs custom tool."""

    def test_delete_doc_happy_path(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_DELETE_DOC"]

        request = DeleteDocInput(document_id=DOC_ID)

        with patch(
            "app.agents.tools.integrations.google_docs_tool._http_client"
        ) as mock_client:
            mock_client.delete.return_value = MagicMock(
                raise_for_status=MagicMock(return_value=None)
            )
            result = fn(request, MagicMock(), AUTH_CREDENTIALS)

        assert result["successful"] is True
        assert result["document_id"] == DOC_ID

    def test_delete_doc_calls_correct_drive_api_url(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_DELETE_DOC"]

        request = DeleteDocInput(document_id=DOC_ID)

        with patch(
            "app.agents.tools.integrations.google_docs_tool._http_client"
        ) as mock_client:
            mock_client.delete.return_value = MagicMock(
                raise_for_status=MagicMock(return_value=None)
            )
            fn(request, MagicMock(), AUTH_CREDENTIALS)

        call_url = mock_client.delete.call_args.args[0]
        assert DOC_ID in call_url
        assert call_url.startswith("https://www.googleapis.com/drive/v3/files/")

    def test_delete_doc_sends_bearer_token(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_DELETE_DOC"]

        request = DeleteDocInput(document_id=DOC_ID)

        with patch(
            "app.agents.tools.integrations.google_docs_tool._http_client"
        ) as mock_client:
            mock_client.delete.return_value = MagicMock(
                raise_for_status=MagicMock(return_value=None)
            )
            fn(request, MagicMock(), AUTH_CREDENTIALS)

        call_headers = mock_client.delete.call_args.kwargs["headers"]
        assert call_headers["Authorization"] == "Bearer ya29.google-token"

    def test_delete_doc_raises_runtime_error_on_http_error(self):
        import httpx

        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_DELETE_DOC"]

        request = DeleteDocInput(document_id=DOC_ID)

        error_response = MagicMock()
        error_response.status_code = 404
        error_response.text = "File not found"

        with patch(
            "app.agents.tools.integrations.google_docs_tool._http_client"
        ) as mock_client:
            mock_client.delete.return_value = MagicMock(
                raise_for_status=MagicMock(
                    side_effect=httpx.HTTPStatusError(
                        "404", request=MagicMock(), response=error_response
                    )
                )
            )
            with pytest.raises(RuntimeError, match="Failed to delete document"):
                fn(request, MagicMock(), AUTH_CREDENTIALS)

    def test_delete_doc_raises_when_access_token_missing(self):
        composio = _make_composio_mock()
        fns = _register_and_extract(composio)
        fn = fns["CUSTOM_DELETE_DOC"]

        request = DeleteDocInput(document_id=DOC_ID)
        with pytest.raises(ValueError, match="Missing access_token"):
            fn(request, MagicMock(), {})


# ---------------------------------------------------------------------------
# register_google_docs_custom_tools – registration contract
# ---------------------------------------------------------------------------


@pytest.mark.composio
class TestRegisterGoogleDocsCustomTools:
    """Verify the registration function returns the correct slug list."""

    def test_returns_expected_slugs(self):
        composio = _make_composio_mock()
        slugs = register_google_docs_custom_tools(composio)
        assert set(slugs) == {
            "GOOGLEDOCS_CUSTOM_SHARE_DOC",
            "GOOGLEDOCS_CUSTOM_CREATE_TOC",
            "GOOGLEDOCS_CUSTOM_DELETE_DOC",
            "GOOGLEDOCS_CUSTOM_GATHER_CONTEXT",
        }

    def test_registers_four_tools(self):
        composio = _make_composio_mock()
        register_google_docs_custom_tools(composio)
        assert composio.tools.custom_tool.call_count == 4

    def test_all_tool_functions_are_callable(self):
        composio = _make_composio_mock()
        register_google_docs_custom_tools(composio)
        for fn in composio._registered.values():
            assert callable(fn)
