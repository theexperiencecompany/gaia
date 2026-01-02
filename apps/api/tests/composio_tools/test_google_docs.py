"""
Google Docs custom tool tests using pytest.

Tests Google Docs custom tools:
- GOOGLEDOCS_CREATE_DOCUMENT (Composio built-in)
- GOOGLEDOCS_CUSTOM_CREATE_TOC (custom)
- GOOGLEDOCS_CUSTOM_SHARE_DOC (custom)
- GOOGLEDOCS_CUSTOM_DELETE_DOC (custom)

Creates a temp document, runs tests, then deletes it.

Usage:
    python -m tests.composio_tools.run_tests google_docs
    pytest tests/composio_tools/test_google_docs.py -v --user-id USER_ID
"""

import json
from datetime import datetime
from typing import Any, Dict, Generator

import pytest

from tests.composio_tools.config_utils import get_integration_config
from tests.composio_tools.conftest import execute_tool


def parse_data(result: Dict[str, Any]) -> Dict[str, Any]:
    """Parse result data, handling string JSON responses."""
    data = result.get("data", {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            pass
    return data if isinstance(data, dict) else {}


@pytest.fixture(scope="module")
def test_document(composio_client, user_id) -> Generator[Dict[str, Any], None, None]:
    """
    Create a test document with headings for TOC testing.

    Creates doc via GOOGLEDOCS_CREATE_DOCUMENT, yields info, then deletes.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    title = f"[PYTEST] Test Document {timestamp}"

    config = get_integration_config("google_docs")
    share_email = config.get("share_email")

    # Create a new Google Doc with initial content
    try:
        create_result = execute_tool(
            composio_client,
            "GOOGLEDOCS_CREATE_DOCUMENT",
            {
                "title": title,
                "text": "# Introduction\n\nThis is the introduction section.\n\n# Chapter 1\n\nFirst chapter content.\n\n# Chapter 2\n\nSecond chapter content.\n\n# Conclusion\n\nFinal thoughts.",
            },
            user_id,
        )
    except Exception as e:
        pytest.skip(f"Could not create test document: {e}")

    if not create_result.get("successful"):
        pytest.skip(f"Create document failed: {create_result.get('error')}")

    data = parse_data(create_result)

    # Schema: data.documentId is the ID
    document_id = data.get("documentId") or data.get("id") or data.get("document_id")

    if not document_id:
        pytest.skip(f"Could not get document ID from create response: {data}")

    doc_info = {
        "document_id": document_id,
        "title": title,
        "share_email": share_email,
    }

    yield doc_info

    # Cleanup: Delete the document
    try:
        execute_tool(
            composio_client,
            "GOOGLEDOCS_CUSTOM_DELETE_DOC",
            {"document_id": document_id},
            user_id,
        )
    except Exception:
        pass  # Best effort cleanup


class TestGoogleDocsOperations:
    """Tests for Google Docs custom tools using temp document."""

    def test_create_toc(self, composio_client, user_id, test_document):
        """
        Test CUSTOM_CREATE_TOC creates a table of contents.

        Expected output schema:
        {
          "data": {
            "document_id": "...",
            "url": "https://docs.google.com/document/d/.../edit",
            "headings_found": 4,
            "toc_content": "Table of Contents\\n=================\\n...",
            "headings": [{"level": 1, "text": "...", "start_index": 1}, ...],
            "insert_response": {...}
          },
          "error": null,
          "successful": true
        }
        """
        result = execute_tool(
            composio_client,
            "GOOGLEDOCS_CUSTOM_CREATE_TOC",
            {
                "document_id": test_document["document_id"],
                "title": "Table of Contents",
                "insertion_index": 1,
                "include_heading_levels": [1, 2, 3],
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

        data = parse_data(result)
        assert data.get("document_id") == test_document["document_id"], (
            "document_id should match"
        )
        assert data.get("url"), "url should be present"
        assert data.get("toc_content"), "toc_content should be present"
        assert data.get("headings_found", 0) > 0, "Should find at least one heading"
        assert isinstance(data.get("headings"), list), "headings should be a list"

    def test_share_doc(self, composio_client, user_id, test_document):
        """
        Test CUSTOM_SHARE_DOC shares a document.

        Expected output schema:
        {
          "data": {
            "document_id": "...",
            "url": "https://docs.google.com/document/d/.../edit",
            "shared": [{"email": "...", "role": "...", "permission_id": "..."}]
          },
          "error": null,
          "successful": true
        }
        """
        share_email = test_document.get("share_email")
        if not share_email:
            pytest.skip("No share_email configured in config.yaml")

        result = execute_tool(
            composio_client,
            "GOOGLEDOCS_CUSTOM_SHARE_DOC",
            {
                "document_id": test_document["document_id"],
                "recipients": [
                    {
                        "email": share_email,
                        "role": "reader",
                        "send_notification": True,
                    }
                ],
            },
            user_id,
        )

        # Check if successful
        if not result.get("successful"):
            pytest.fail(f"API call failed: {result.get('error')}")

        data = parse_data(result)

        # Verify structure
        assert data.get("document_id") == test_document["document_id"], (
            "document_id should match"
        )
        shared_list = data.get("shared", [])
        assert len(shared_list) > 0, "Should have shared with at least one recipient"
        assert shared_list[0].get("email") == share_email, "Shared email should match"

    def test_delete_doc(self, composio_client, user_id):
        """
        Test CUSTOM_DELETE_DOC deletes a document.

        Expected output schema:
        {
          "data": {
            "successful": true,
            "document_id": "..."
          },
          "error": null,
          "successful": true
        }
        """
        # Create a temporary document just for this test
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        title = f"[PYTEST] Delete Test {timestamp}"

        create_result = execute_tool(
            composio_client,
            "GOOGLEDOCS_CREATE_DOCUMENT",
            {"title": title, "text": "Test content for deletion"},
            user_id,
        )

        if not create_result.get("successful"):
            pytest.skip(
                f"Could not create test document for deletion: {create_result.get('error')}"
            )

        data = parse_data(create_result)
        document_id = data.get("documentId") or data.get("id")

        if not document_id:
            pytest.skip("Could not get document ID for deletion test")

        # Now delete it
        delete_result = execute_tool(
            composio_client,
            "GOOGLEDOCS_CUSTOM_DELETE_DOC",
            {"document_id": document_id},
            user_id,
        )

        assert delete_result.get("successful"), (
            f"Delete failed: {delete_result.get('error')}"
        )

        delete_data = parse_data(delete_result)
        assert delete_data.get("successful") is True, (
            "Delete data should indicate success"
        )
        assert delete_data.get("document_id") == document_id, (
            "Deleted document_id should match"
        )
