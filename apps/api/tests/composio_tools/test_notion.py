"""
Notion custom tool tests using pytest.

Tests 3 Notion tools:
- FETCH_PAGE_AS_MARKDOWN (read-only)
- INSERT_MARKDOWN (modifies page)
- MOVE_PAGE (modifies page structure)

Usage:
    pytest tests/composio_tools/test_notion_pytest.py -v --user-id USER_ID --page-id PAGE_ID
"""

import pytest
from pytest_check import check

from tests.composio_tools.conftest import execute_tool


def pytest_addoption(parser):
    """Add custom CLI options."""
    try:
        parser.addoption(
            "--page-id",
            action="store",
            default=None,
            help="Notion page ID to test with",
        )
    except ValueError:
        pass  # Already added


@pytest.fixture(scope="session")
def page_id(request) -> str:
    """Get page ID from CLI argument."""
    pid = request.config.getoption("--page-id")
    if not pid:
        pytest.skip("--page-id required for Notion tests")
    return pid


class TestNotionReadOperations:
    """Tests for read-only Notion operations."""

    def test_fetch_page_as_markdown(self, composio_client, user_id, page_id):
        """Test FETCH_PAGE_AS_MARKDOWN returns page content."""
        result = execute_tool(
            composio_client,
            "NOTION_FETCH_PAGE_AS_MARKDOWN",
            {
                "page_id": page_id,
                "recursive": True,
                "include_block_ids": True,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})

        with check:
            assert "markdown" in data or "content" in data, (
                "Should have markdown content"
            )
            assert "title" in data or "page_title" in data, "Should have page title"


class TestNotionModifyOperations:
    """Tests that modify Notion pages - run manually."""

    @pytest.mark.skip(reason="Modifies page content. Run manually.")
    def test_insert_markdown(self, composio_client, user_id, page_id):
        """Test INSERT_MARKDOWN adds content to a page."""
        result = execute_tool(
            composio_client,
            "NOTION_INSERT_MARKDOWN",
            {
                "parent_block_id": page_id,
                "markdown": "## Test Section\n\nContent added by pytest.\n\n- Item 1\n- Item 2",
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})
        assert data, "Expected response data"

    @pytest.mark.skip(reason="Modifies page structure. Run manually.")
    def test_move_page(self, composio_client, user_id, page_id):
        """Test MOVE_PAGE moves a page to a new parent.

        Requires destination_page_id or destination_database_id.
        """
        # Requires manual destination setup
        pytest.skip("Requires destination_page_id to test")
