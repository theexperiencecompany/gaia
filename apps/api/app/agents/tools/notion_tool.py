"""Notion custom tools using Composio custom tool infrastructure.

These tools wrap existing Composio Notion tools and add markdown conversion:
- FETCH_PAGE_AS_MARKDOWN: Calls NOTION_FETCH_ALL_BLOCK_CONTENTS → converts to markdown
- INSERT_MARKDOWN: Converts markdown → calls NOTION_ADD_MULTIPLE_PAGE_CONTENT
- MOVE_PAGE: Uses execute_request (no existing Composio equivalent)

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Any, Dict, List

from app.config.loggers import chat_logger as logger
from app.decorators import with_doc
from app.models.notion_models import (
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
            title_response = composio.tools.execute(
                slug="NOTION_GET_PAGE_PROPERTY_ACTION",
                params={
                    "page_id": request.page_id,
                    "property_id": "title",
                },
                auth_credentials=auth_credentials,
            )
            title_data = (
                title_response.data
                if hasattr(title_response, "data")
                else title_response
            )
            # Extract title from results array
            results = title_data.get("results", [])
            for item in results:
                if item.get("type") == "title" and item.get("title"):
                    title = item["title"].get("plain_text", "")
                    break
        except Exception as e:
            logger.warning(f"Could not fetch title: {e}")

        # Call NOTION_FETCH_ALL_BLOCK_CONTENTS via composio
        blocks_response = composio.tools.execute(
            slug="NOTION_FETCH_ALL_BLOCK_CONTENTS",
            params={
                "block_id": request.page_id,
                "recursive": request.recursive,
                "page_size": 100,
            },
            auth_credentials=auth_credentials,
        )

        # Extract blocks from response
        blocks_data = (
            blocks_response.data
            if hasattr(blocks_response, "data")
            else blocks_response
        )
        blocks = blocks_data.get("results", blocks_data.get("blocks", []))

        # Convert to markdown (with block IDs for insertion positioning)
        markdown = blocks_to_markdown(
            blocks, include_block_ids=request.include_block_ids
        )

        # Prepend title as H1 if present
        if title:
            markdown = f"# {title}\n\n{markdown}"

        return {
            "page_id": request.page_id,
            "title": title,
            "markdown": markdown,
            "block_count": len(blocks),
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
        response = composio.tools.execute(
            slug="NOTION_ADD_MULTIPLE_PAGE_CONTENT",
            params=params,
            auth_credentials=auth_credentials,
        )

        data = response.data if hasattr(response, "data") else response

        return {
            "parent_block_id": request.parent_block_id,
            "blocks_added": len(content_blocks),
            "after": request.after,
            "response": data,
        }

    return [
        "NOTION_MOVE_PAGE",
        "NOTION_FETCH_PAGE_AS_MARKDOWN",
        "NOTION_INSERT_MARKDOWN",
    ]
