"""
Google Docs custom tool tests using pytest.

Tests 2 docs tools:
- CUSTOM_CREATE_TOC (read/modify)
- CUSTOM_SHARE_DOC (destructive - requires manual run)

Usage:
    pytest tests/composio_tools/test_google_docs_pytest.py -v --user-id USER_ID --document-id DOC_ID
"""

import pytest
from pytest_check import check

from tests.composio_tools.conftest import execute_tool


def pytest_addoption(parser):
    """Add custom CLI options."""
    try:
        parser.addoption(
            "--document-id",
            action="store",
            default=None,
            help="Google Docs document ID to test with",
        )
    except ValueError:
        pass  # Already added


@pytest.fixture(scope="session")
def document_id(request) -> str:
    """Get document ID from CLI argument."""
    doc_id = request.config.getoption("--document-id")
    if not doc_id:
        pytest.skip("--document-id required for Google Docs tests")
    return doc_id


class TestGoogleDocsReadOperations:
    """Tests for non-destructive Google Docs operations."""

    def test_create_toc(self, composio_client, user_id, document_id):
        """Test CUSTOM_CREATE_TOC creates a table of contents."""
        result = execute_tool(
            composio_client,
            "GOOGLEDOCS_CUSTOM_CREATE_TOC",
            {
                "document_id": document_id,
                "title": "Table of Contents",
                "insertion_index": 1,
                "include_heading_levels": [1, 2, 3],
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

        data = result.get("data", {})
        assert data, "Expected response data from CREATE_TOC"

        # Validate TOC structure
        with check:
            assert "toc_entries" in data or "entries" in data, "Should have TOC entries"


class TestGoogleDocsDestructiveOperations:
    """Tests for destructive operations - run manually."""

    @pytest.mark.skip(reason="Destructive: adds real permissions. Run manually.")
    def test_share_doc(self, composio_client, user_id, document_id):
        """Test CUSTOM_SHARE_DOC shares a document.

        MANUAL TEST: This adds a real permission to the document.
        Run with: pytest ... -k test_share_doc --runxfail
        """
        test_email = "test@example.com"  # Replace with real email

        result = execute_tool(
            composio_client,
            "GOOGLEDOCS_CUSTOM_SHARE_DOC",
            {
                "document_id": document_id,
                "recipients": [
                    {
                        "email": test_email,
                        "role": "reader",
                        "send_notification": False,
                    }
                ],
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

        data = result.get("data", {})
        assert data, "Expected response data from SHARE_DOC"
