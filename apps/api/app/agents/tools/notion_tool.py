"""Notion custom tools using Composio custom tool infrastructure.

These tools wrap existing Composio Notion tools and add markdown conversion:
- FETCH_PAGE_AS_MARKDOWN: Calls NOTION_FETCH_ALL_BLOCK_CONTENTS → converts to markdown
- INSERT_MARKDOWN: Converts markdown → calls NOTION_ADD_MULTIPLE_PAGE_CONTENT
- MOVE_PAGE: Uses execute_request (no existing Composio equivalent)

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Any, Dict, List

import httpx
from app.config.loggers import chat_logger as logger
from app.decorators import with_doc
from app.models.notion_models import (
    CreateTestPageInput,
    FetchPageAsMarkdownInput,
    InsertMarkdownInput,
    MovePageInput,
)
from app.templates.docstrings.notion_tool_docs import (
    FETCH_PAGE_AS_MARKDOWN_DOC,
    INSERT_MARKDOWN_DOC,
    MOVE_PAGE_DOC,
)
from app.utils.notion_md import blocks_to_markdown, markdown_to_notion_blocks
from composio import Composio
from composio.core.models.tools import ToolExecutionResponse


def register_notion_custom_tools(composio: Composio) -> List[str]:
    """Register Notion tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="NOTION")
    @with_doc(MOVE_PAGE_DOC)
    def MOVE_PAGE(
        request: MovePageInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        # Build parent object based on type
        if request.parent_type == "page_id":
            parent = {"type": "page_id", "page_id": request.parent_id}
        else:
            parent = {"type": "database_id", "database_id": request.parent_id}

        response = execute_request(
            endpoint=f"/pages/{request.page_id}",
            method="PATCH",
            body={"parent": parent},
        )

        data = response.data if hasattr(response, "data") else response
        return {
            "page_id": data.get("id"),
            "new_parent": parent,
            "url": data.get("url"),
        }

    @composio.tools.custom_tool(toolkit="NOTION")
    @with_doc(FETCH_PAGE_AS_MARKDOWN_DOC)
    def FETCH_PAGE_AS_MARKDOWN(
        request: FetchPageAsMarkdownInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        # Get page title using NOTION_GET_PAGE_PROPERTY_ACTION
        title = ""
        try:
            title_response: ToolExecutionResponse = composio.tools.execute(
                slug="NOTION_GET_PAGE_PROPERTY_ACTION",
                arguments={
                    "page_id": request.page_id,
                    "property_id": "title",
                },
                version=auth_credentials.get("version"),
                dangerously_skip_version_check=True,
                user_id=auth_credentials.get("user_id"),
            )
            # Composio tools return ToolExecutionResponse format
            if not title_response["successful"]:
                logger.warning(f"Failed to fetch title: {title_response.get('error')}")
            else:
                title_data = title_response["data"]
                # Extract title from results array
                if isinstance(title_data, dict):
                    results = title_data.get("results", [])
                else:
                    results = []
                if isinstance(results, list):
                    for item in results:
                        if item.get("type") == "title" and item.get("title"):
                            title = item["title"].get("plain_text", "")
                            break
        except Exception as e:
            logger.warning(f"Could not fetch title: {e}")

        # Call NOTION_FETCH_ALL_BLOCK_CONTENTS via composio
        blocks_response: ToolExecutionResponse = composio.tools.execute(
            slug="NOTION_FETCH_ALL_BLOCK_CONTENTS",
            arguments={
                "block_id": request.page_id,
                "recursive": request.recursive,
                "page_size": 100,
            },
            version=auth_credentials.get("version"),
            dangerously_skip_version_check=True,
            user_id=auth_credentials.get("user_id"),
        )

        # Extract blocks from response (ToolExecutionResponse format)
        if not blocks_response["successful"]:
            raise ValueError(f"Failed to fetch blocks: {blocks_response.get('error')}")

        blocks_data = blocks_response["data"]
        blocks = (
            blocks_data.get("results", blocks_data.get("blocks", []))
            if isinstance(blocks_data, dict)
            else []
        )

        # Convert to markdown (with block IDs for insertion positioning)
        if isinstance(blocks, list):
            markdown = blocks_to_markdown(
                blocks, include_block_ids=request.include_block_ids
            )
        else:
            markdown = ""

        # Prepend title as H1 if present
        if title:
            markdown = f"# {title}\n\n{markdown}"

        return {
            "page_id": request.page_id,
            "title": title,
            "markdown": markdown,
            "block_count": len(blocks) if isinstance(blocks, list) else 0,
        }

    @composio.tools.custom_tool(toolkit="NOTION")
    @with_doc(INSERT_MARKDOWN_DOC)
    def INSERT_MARKDOWN(
        request: InsertMarkdownInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        # Convert markdown to Notion blocks
        content_blocks = markdown_to_notion_blocks(request.markdown)

        if not content_blocks:
            raise ValueError(
                "No content to insert - markdown conversion produced no blocks"
            )

        # Build params for NOTION_ADD_MULTIPLE_PAGE_CONTENT
        params: Dict[str, Any] = {
            "parent_block_id": request.parent_block_id,
            "content_blocks": content_blocks,
        }

        # Add after param if specified
        if request.after:
            params["after"] = request.after

        # Call NOTION_ADD_MULTIPLE_PAGE_CONTENT
        response: ToolExecutionResponse = composio.tools.execute(
            slug="NOTION_ADD_MULTIPLE_PAGE_CONTENT",
            arguments=params,
            version=auth_credentials.get("version"),
            dangerously_skip_version_check=True,
            user_id=auth_credentials.get("user_id"),
        )

        # ToolExecutionResponse format
        if not response["successful"]:
            raise ValueError(f"Failed to insert markdown: {response.get('error')}")

        data = response["data"]

        return {
            "parent_block_id": request.parent_block_id,
            "blocks_added": len(content_blocks),
            "after": request.after,
            "response": data,
        }

    @composio.tools.custom_tool(toolkit="NOTION")
    @with_doc("Create a simple test page for integration testing.")
    def CUSTOM_CREATE_TEST_PAGE(
        request: CreateTestPageInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a new page in Notion."""
        # This is a wrapper around NOTION_CREATE_PAGE but simplified

        # We need to construct the payload as expected by Notion API
        # Parent can be page or database, for test page usually it's a page or workspace (if no parent?)
        # Actually Notion API requires a parent.
        # If parent_page_id is not provided, we might fail or try to find a root page?
        # For testing, we assume parent is provided or we might default to search?

        headers = {
            "Authorization": f"Bearer {auth_credentials.get('access_token')}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

        if not request.parent_page_id:
            # Search for any page to use as parent
            try:
                search_resp = httpx.post(
                    "https://api.notion.com/v1/search",
                    headers=headers,
                    json={
                        "filter": {"property": "object", "value": "page"},
                        "page_size": 1,
                    },
                    timeout=30,
                )
                search_resp.raise_for_status()
                results = search_resp.json().get("results", [])
                if results:
                    request.parent_page_id = results[0]["id"]
                else:
                    raise ValueError(
                        "No parent page provided and no pages found in workspace."
                    )
            except Exception as e:
                raise ValueError(f"Failed to search for parent page: {e}")

        properties = {"title": [{"type": "text", "text": {"content": request.title}}]}

        parent = {"page_id": request.parent_page_id}

        try:
            resp = httpx.post(
                "https://api.notion.com/v1/pages",
                headers=headers,
                json={"parent": parent, "properties": properties},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return {"page_id": data.get("id"), "url": data.get("url")}
        except Exception as e:
            raise RuntimeError(f"Failed to create page: {e}")

    return [
        "NOTION_MOVE_PAGE",
        "NOTION_FETCH_PAGE_AS_MARKDOWN",
        "NOTION_INSERT_MARKDOWN",
        "NOTION_CUSTOM_CREATE_TEST_PAGE",
    ]
