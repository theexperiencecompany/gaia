"""Notion custom tools using Composio custom tool infrastructure.

These tools wrap existing Composio Notion tools and add markdown conversion:
- FETCH_PAGE_AS_MARKDOWN: Calls NOTION_FETCH_ALL_BLOCK_CONTENTS → converts to markdown
- INSERT_MARKDOWN: Converts markdown → calls NOTION_ADD_MULTIPLE_PAGE_CONTENT
- MOVE_PAGE / FETCH_DATA : route through Composio's
  proxy via `proxy_request_sync` (no existing Composio equivalent)

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Any

from composio import Composio
from composio.core.models.tools import ToolExecutionResponse

from app.decorators import with_doc
from app.models.common_models import GatherContextInput
from app.models.notion_models import (
    FetchDataInput,
    FetchPageAsMarkdownInput,
    InsertMarkdownInput,
    MovePageInput,
)
from app.services.composio.proxy_client import proxy_request_sync
from app.templates.docstrings.notion_tool_docs import (
    FETCH_DATA_DOC,
    FETCH_PAGE_AS_MARKDOWN_DOC,
    INSERT_MARKDOWN_DOC,
    MOVE_PAGE_DOC,
)
from app.utils.context_utils import execute_tool
from app.utils.errors import AppError
from app.utils.notion_md import blocks_to_markdown, markdown_to_notion_blocks
from shared.py.wide_events import log

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_TOOLKIT = "NOTION"
_NOTION_HEADERS = {"Notion-Version": "2022-06-28"}


def _user_id(auth_credentials: dict[str, Any]) -> str:
    user_id = auth_credentials.get("user_id")
    if not user_id:
        raise ValueError("Missing user_id in auth_credentials")
    return user_id


def register_notion_custom_tools(composio: Composio) -> list[str]:
    """Register Notion tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="NOTION")
    @with_doc(MOVE_PAGE_DOC)
    def MOVE_PAGE(
        request: MovePageInput,
        execute_request: Any,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        log.set(tool={"integration": "notion", "action": "move_page"})
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
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        log.set(tool={"integration": "notion", "action": "fetch_page_as_markdown"})
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
                log.warning(f"Failed to fetch title: {title_response.get('error')}")
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
            log.warning(f"Could not fetch title: {e}")

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
            markdown = blocks_to_markdown(blocks, include_block_ids=request.include_block_ids)
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
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        log.set(tool={"integration": "notion", "action": "insert_markdown"})
        # Convert markdown to Notion blocks
        all_blocks = markdown_to_notion_blocks(request.markdown)

        if not all_blocks:
            raise ValueError("No content to insert - markdown conversion produced no blocks")

        blocks_added = 0
        first_inserted = True

        for block in all_blocks:
            is_table = block.get("type") == "table"

            if is_table:
                params: dict[str, Any] = {
                    "block_id": request.parent_block_id,
                    "table_width": block["table_width"],
                    "has_column_header": block.get("has_column_header", True),
                    "rows": block["rows"],
                }
                response: ToolExecutionResponse = composio.tools.execute(
                    slug="NOTION_APPEND_TABLE_BLOCKS",
                    arguments=params,
                    version=auth_credentials.get("version"),
                    dangerously_skip_version_check=True,
                    user_id=auth_credentials.get("user_id"),
                )

                if not response["successful"]:
                    raise ValueError(f"Failed to insert table: {response.get('error')}")

                blocks_added += 1
            else:
                params = {
                    "parent_block_id": request.parent_block_id,
                    "content_blocks": [block],
                }
                if first_inserted and request.after:
                    params["after"] = request.after
                    first_inserted = False

                response = composio.tools.execute(
                    slug="NOTION_ADD_MULTIPLE_PAGE_CONTENT",
                    arguments=params,
                    version=auth_credentials.get("version"),
                    dangerously_skip_version_check=True,
                    user_id=auth_credentials.get("user_id"),
                )

                if not response["successful"]:
                    raise ValueError(f"Failed to insert markdown: {response.get('error')}")

                blocks_added += 1

        tables_added = sum(1 for b in all_blocks if b.get("type") == "table")

        return {
            "parent_block_id": request.parent_block_id,
            "blocks_added": blocks_added,
            "tables_added": tables_added,
            "after": request.after,
        }

    @composio.tools.custom_tool(toolkit="NOTION")
    @with_doc(FETCH_DATA_DOC)
    def FETCH_DATA(
        request: FetchDataInput,
        execute_request: Any,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch databases or pages from Notion workspace."""
        log.set(tool={"integration": "notion", "action": "fetch_data"})
        user_id = _user_id(auth_credentials)

        search_filter = {"property": "object", "value": request.fetch_type.rstrip("s")}

        search_body: dict[str, Any] = {
            "filter": search_filter,
            "page_size": min(request.page_size, 100),
        }

        if request.query:
            search_body["query"] = request.query

        try:
            search_results = (
                proxy_request_sync(
                    user_id=user_id,
                    toolkit=NOTION_TOOLKIT,
                    endpoint=f"{NOTION_API_BASE}/search",
                    method="POST",
                    body=search_body,
                    headers=_NOTION_HEADERS,
                )
                or {}
            )

            results = search_results.get("results", [])
            values = []

            for item in results:
                item_id = item.get("id")
                object_type = item.get("object")

                title = "Untitled"
                if object_type == "database":
                    title_array = item.get("title", [])
                    if title_array and len(title_array) > 0:
                        title = title_array[0].get("plain_text", "Untitled")
                elif object_type == "page":
                    properties = item.get("properties", {})
                    for _prop_name, prop_value in properties.items():
                        if prop_value.get("type") == "title":
                            title_data = prop_value.get("title", [])
                            if title_data and len(title_data) > 0:
                                title = title_data[0].get("plain_text", "Untitled")
                            break

                if item_id:
                    values.append({"id": item_id, "title": title, "type": object_type})

            return {
                "values": values,
                "count": len(values),
                "has_more": search_results.get("has_more", False),
            }

        except AppError as e:
            log.error(f"Notion API error: {e.message}")
            raise RuntimeError(f"Failed to fetch {request.fetch_type}: {e.message}")
        except Exception as e:
            log.error(f"Error fetching Notion {request.fetch_type}: {e}")
            raise RuntimeError(f"Failed to fetch {request.fetch_type}: {e!s}")

    @composio.tools.custom_tool(toolkit="NOTION")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Get Notion workspace context: recently edited pages and databases.

        Zero required parameters. Returns recently modified content for situational awareness.
        """
        log.set(tool={"integration": "notion", "action": "gather_context"})
        user_id = _user_id(auth_credentials)
        data = execute_tool("NOTION_SEARCH_NOTION_PAGE", {"query": "", "page_size": 10}, user_id)
        pages = data.get("results", data.get("pages", []))
        return {"relevant_pages": pages}

    return [
        "NOTION_MOVE_PAGE",
        "NOTION_FETCH_PAGE_AS_MARKDOWN",
        "NOTION_INSERT_MARKDOWN",
        "NOTION_FETCH_DATA",
        "NOTION_CUSTOM_GATHER_CONTEXT",
    ]
