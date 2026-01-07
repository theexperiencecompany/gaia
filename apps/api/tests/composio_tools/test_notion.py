"""
Notion custom tool tests using pytest.

Tests 3 Notion tools with self-contained fixtures:
- FETCH_PAGE_AS_MARKDOWN (read-only)
- INSERT_MARKDOWN (modifies page)
- DUPLICATE_PAGE (complex/destructive test, simulates moving/copying)

Creates a temp page, runs tests, then archives it.

Usage:
    python -m tests.composio_tools.run_tests notion
    pytest tests/composio_tools/test_notion.py -v --user-id USER_ID
"""

from datetime import datetime
from typing import Any, Dict, Generator

import pytest
from pytest_check import check

from tests.composio_tools.conftest import execute_tool


@pytest.fixture(scope="function")
def test_page(composio_client, user_id) -> Generator[Dict[str, Any], None, None]:
    """
    Create a test Notion page with some content.

    Creates page via NOTION_CREATE_PAGE, adds content, yields info, then archives.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    title = f"[PYTEST] Test Page {timestamp}"

    # Create a new Notion page
    try:
        create_result = execute_tool(
            composio_client,
            "NOTION_CUSTOM_CREATE_TEST_PAGE",
            {
                "title": title,
                # "parent_page_id": "..." # Optional, hopefully defaults correctly or searched
            },
            user_id,
        )
    except Exception as e:
        pytest.fail(f"Could not create test page (check Notion connection): {e}")

    if not create_result.get("successful"):
        # If NOTION_CREATE_PAGE fails, check if's 404 (tool not found)
        err = create_result.get("error", {})
        if isinstance(err, dict) and err.get("code") == 2401:  # Tool not found
            pytest.fail(
                "Tool NOTION_CREATE_PAGE not found. Please verify correct tool name."
            )
        pytest.fail(f"Create page failed: {err}")

    data = create_result.get("data", {})
    page_id = data.get("id") or data.get("page_id")

    if not page_id:
        pytest.fail("Could not get page ID from create response")

    # Add some initial content
    try:
        execute_tool(
            composio_client,
            "NOTION_INSERT_MARKDOWN",
            {
                "parent_block_id": page_id,
                "markdown": "## Initial Content\n\nThis is test content for pytest.\n\n- Item 1\n- Item 2",
            },
            user_id,
        )
    except Exception:
        pass  # Content is optional for tests

    page_info = {
        "page_id": page_id,
        "title": title,
    }

    yield page_info

    # Cleanup: Archive the page
    try:
        execute_tool(
            composio_client,
            "NOTION_UPDATE_A_PAGE",  # Or NOTION_archive_notion_page
            {
                "page_id": page_id,
                "archived": True,
            },
            user_id,
        )
    except Exception:
        pass  # Best effort cleanup


class TestNotionReadOperations:
    """Tests for read-only Notion operations."""

    def test_fetch_page_as_markdown(self, composio_client, user_id, test_page):
        """Test FETCH_PAGE_AS_MARKDOWN returns page content."""
        result = execute_tool(
            composio_client,
            "NOTION_FETCH_PAGE_AS_MARKDOWN",
            {
                "page_id": test_page["page_id"],
                "recursive": True,
                "include_block_ids": True,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})

        with check:
            assert "markdown" in data, "Should have 'markdown' field"
            assert "page_id" in data, "Should have 'page_id' field"


class TestNotionModifyOperations:
    """Tests for Notion modify operations."""

    def test_insert_markdown(self, composio_client, user_id, test_page):
        """Test INSERT_MARKDOWN adds content to the page."""
        result = execute_tool(
            composio_client,
            "NOTION_INSERT_MARKDOWN",
            {
                "parent_block_id": test_page["page_id"],
                "markdown": "## Added by Test\n\nThis content was added by the pytest test.\n\n1. Step one\n2. Step two",
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

    def test_duplicate_page(self, composio_client, user_id, test_page):
        """Test DUPLICATE_PAGE (using NOTION_DUPLICATE_PAGE)."""
        # Create a separate page to act as the parent for duplication
        parent_page = execute_tool(
            composio_client,
            "NOTION_CUSTOM_CREATE_TEST_PAGE",
            {"title": "[PYTEST] Parent for Duplication"},
            user_id,
        )
        assert parent_page.get("successful"), "Failed to create parent page"
        parent_id = parent_page.get("data", {}).get("page_id")

        # Add delay to avoid rate limits
        import time

        time.sleep(2)

        # This simulates "moving/copying" a page
        result = execute_tool(
            composio_client,
            "NOTION_DUPLICATE_PAGE",
            {
                "page_id": test_page["page_id"],
                "parent_id": parent_id,
            },
            user_id,
        )

        # If tool not found, we skip but mark failure if we want to enforce implementation
        if not result.get("successful") and "not found" in str(result.get("error")):
            pytest.skip("NOTION_DUPLICATE_PAGE tool not found")

        assert result.get("successful"), f"API call failed: {result.get('error')}"

        # Cleanup the duplicate
        data = result.get("data", {})
        if isinstance(data, str):
            import json

            try:
                data = json.loads(data)
            except Exception:
                pytest.fail(f"Tool execution failed with message: {data}")

        dup_id = data.get("id") or (data.get("object") == "page" and data.get("id"))

        if dup_id:
            try:
                execute_tool(
                    composio_client,
                    "NOTION_UPDATE_A_PAGE",
                    {"page_id": dup_id, "archived": True},
                    user_id,
                )
            except Exception:
                pass
