"""Behavior tests for Google Docs custom tool registration and error paths.

The proxy smoke test (test_integration_tools_proxy.py) proves routing; these
tests pin the exact registration contract (tool names + toolkit kwarg) and
the delete-doc failure path.
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.tools.integrations.google_docs_tool import register_google_docs_custom_tools
from app.models.google_docs_models import DeleteDocInput
from app.utils.errors import AppError

MODULE = "app.agents.tools.integrations.google_docs_tool"

AUTH_CREDS: dict[str, Any] = {"user_id": "user_test_123"}

EXPECTED_TOOL_NAMES = [
    "GOOGLEDOCS_CUSTOM_SHARE_DOC",
    "GOOGLEDOCS_CUSTOM_CREATE_TOC",
    "GOOGLEDOCS_CUSTOM_DELETE_DOC",
    "GOOGLEDOCS_CUSTOM_GATHER_CONTEXT",
]


def _capture_tools(
    register_fn: Callable[..., list[str]],
) -> tuple[list[str], dict[str, tuple[Callable[..., Any], dict[str, Any]]]]:
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
    return registered, captured


def test_register_returns_exact_tool_names_and_toolkits() -> None:
    registered, captured = _capture_tools(register_google_docs_custom_tools)

    assert registered == EXPECTED_TOOL_NAMES
    assert sorted(captured) == sorted(EXPECTED_TOOL_NAMES)
    assert all(kwargs == {"toolkit": "GOOGLEDOCS"} for _, kwargs in captured.values())


def test_delete_doc_raises_runtime_error_on_app_error() -> None:
    _, tools = _capture_tools(register_google_docs_custom_tools)
    delete_doc, _ = tools["GOOGLEDOCS_CUSTOM_DELETE_DOC"]
    error = AppError(message="Drive API error (403)", status_code=403)

    with patch(f"{MODULE}.proxy_request_sync", side_effect=error) as proxy:
        with pytest.raises(RuntimeError) as excinfo:
            delete_doc(DeleteDocInput(document_id="doc-1"), MagicMock(), AUTH_CREDS)

    assert str(excinfo.value) == "Failed to delete document: 403 - Drive API error (403)"
    assert excinfo.value.__cause__ is error
    assert proxy.call_args.kwargs["method"] == "DELETE"
    assert proxy.call_args.kwargs["endpoint"].endswith("/files/doc-1")
