"""Notion custom tools using Composio custom tool infrastructure.

These tools wrap existing Composio Notion tools and add markdown conversion:
- FETCH_PAGE_AS_MARKDOWN: Calls NOTION_FETCH_ALL_BLOCK_CONTENTS → converts to markdown
- INSERT_MARKDOWN: Converts markdown → calls NOTION_ADD_MULTIPLE_PAGE_CONTENT
- MOVE_PAGE / FETCH_DATA : route through Composio's
  proxy via `proxy_request_sync` (no existing Composio equivalent)

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Any, cast

from composio import Composio
from composio.core.models.tools import ToolExecutionResponse
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
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
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("Missing user_id in auth_credentials")
    return user_id


def _execute_notion_action(
    composio: Composio,
    slug: str,
    arguments: dict[str, Any],
    auth_credentials: dict[str, Any],
) -> ToolExecutionResponse:
    return composio.tools.execute(
        slug=slug,
        arguments=arguments,
        version=auth_credentials.get("version"),
        dangerously_skip_version_check=True,
        user_id=auth_credentials.get("user_id"),
    )


def _build_parent(parent_type: str, parent_id: str) -> dict[str, Any]:
    if parent_type == "page_id":
        return {"type": "page_id", "page_id": parent_id}
    return {"type": "database_id", "database_id": parent_id}


def _move_page(request: MovePageInput, execute_request: ExecuteRequestFn) -> dict[str, Any]:
    parent = _build_parent(request.parent_type, request.parent_id)

    response = execute_request(
        endpoint=f"/pages/{request.page_id}",
        method="PATCH",
        body={"parent": parent},
    )

    # ToolProxyResponse.data is typed Optional[object] by the framework's own
    # Pydantic model; this endpoint's real payload is a JSON object.
    data = cast("dict[str, Any]", response.data if hasattr(response, "data") else response)
    return {
        "page_id": data.get("id"),
        "new_parent": parent,
        "url": data.get("url"),
    }


def _fetch_page_title(
    composio: Composio,
    page_id: str,
    auth_credentials: dict[str, Any],
) -> str:
    title_response = _execute_notion_action(
        composio,
        "NOTION_GET_PAGE_PROPERTY_ACTION",
        {"page_id": page_id, "property_id": "title"},
        auth_credentials,
    )
    if not title_response["successful"]:
        raise AppError(
            message=f"Failed to fetch Notion page title: {title_response.get('error')}",
            status_code=502,
        )

    # ToolExecutionResponse.data is typed as a plain Dict, but real
    # Notion API responses aren't guaranteed to match — widen via
    # annotation so the isinstance narrowing below is meaningful.
    # (A runtime cast("object", …) here is a no-op the interpreter
    # discards; an annotation widens without executable code.)
    title_data: object = title_response["data"]
    # No .get default: a missing key yields None, and isinstance(None, list)
    # below already routes it to the no-title path — same as any non-list value.
    results = title_data.get("results") if isinstance(title_data, dict) else []
    if isinstance(results, list):
        for item in results:
            if item.get("type") == "title" and item.get("title"):
                return str(item["title"].get("plain_text", ""))
    return ""


def _fetch_page_blocks(
    composio: Composio,
    request: FetchPageAsMarkdownInput,
    auth_credentials: dict[str, Any],
) -> list[Any]:
    blocks_response = _execute_notion_action(
        composio,
        "NOTION_FETCH_ALL_BLOCK_CONTENTS",
        {
            "block_id": request.page_id,
            "recursive": request.recursive,
            "page_size": 100,
        },
        auth_credentials,
    )

    if not blocks_response["successful"]:
        raise ValueError(f"Failed to fetch blocks: {blocks_response.get('error')}")

    blocks_data = blocks_response["data"]
    blocks = (
        blocks_data.get("results", blocks_data.get("blocks"))
        if isinstance(blocks_data, dict)
        else []
    )
    return blocks if isinstance(blocks, list) else []


def _fetch_page_as_markdown(
    composio: Composio,
    request: FetchPageAsMarkdownInput,
    auth_credentials: dict[str, Any],
) -> dict[str, Any]:
    title = _fetch_page_title(composio, request.page_id, auth_credentials)
    blocks = _fetch_page_blocks(composio, request, auth_credentials)

    markdown = blocks_to_markdown(blocks, include_block_ids=request.include_block_ids)
    if title:
        markdown = f"# {title}\n\n{markdown}"

    return {
        "page_id": request.page_id,
        "title": title,
        "markdown": markdown,
        "block_count": len(blocks),
    }


def _append_table_block(
    composio: Composio,
    request: InsertMarkdownInput,
    block: dict[str, Any],
    auth_credentials: dict[str, Any],
) -> None:
    response = _execute_notion_action(
        composio,
        "NOTION_APPEND_TABLE_BLOCKS",
        {
            "block_id": request.parent_block_id,
            "table_width": block["table_width"],
            "has_column_header": block.get("has_column_header", True),
            "rows": block["rows"],
        },
        auth_credentials,
    )

    if not response["successful"]:
        raise ValueError(f"Failed to insert table: {response.get('error')}")


def _append_content_block(
    composio: Composio,
    request: InsertMarkdownInput,
    block: dict[str, Any],
    after: str | None,
    auth_credentials: dict[str, Any],
) -> None:
    params: dict[str, Any] = {
        "parent_block_id": request.parent_block_id,
        "content_blocks": [block],
    }
    if after:
        params["after"] = after

    response = _execute_notion_action(
        composio,
        "NOTION_ADD_MULTIPLE_PAGE_CONTENT",
        params,
        auth_credentials,
    )

    if not response["successful"]:
        raise ValueError(f"Failed to insert markdown: {response.get('error')}")


def _insert_markdown(
    composio: Composio,
    request: InsertMarkdownInput,
    auth_credentials: dict[str, Any],
) -> dict[str, Any]:
    all_blocks = markdown_to_notion_blocks(request.markdown)

    if not all_blocks:
        raise ValueError("No content to insert - markdown conversion produced no blocks")

    blocks_added = 0
    anchor_uses_left = int(request.after is not None)

    for block in all_blocks:
        if block.get("type") == "table":
            _append_table_block(composio, request, block, auth_credentials)
        elif anchor_uses_left > 0:
            anchor_uses_left = 0
            _append_content_block(composio, request, block, request.after, auth_credentials)
        else:
            _append_content_block(composio, request, block, None, auth_credentials)
        blocks_added += 1

    tables_added = sum(1 for b in all_blocks if b.get("type") == "table")

    return {
        "parent_block_id": request.parent_block_id,
        "blocks_added": blocks_added,
        "tables_added": tables_added,
        "after": request.after,
    }


def _item_title(item: dict[str, Any]) -> str:
    object_type = item.get("object")
    if object_type == "database":
        title_array = item.get("title", [])
        if title_array:
            return str(title_array[0].get("plain_text", "Untitled"))
    elif object_type == "page":
        properties = item.get("properties", {})
        for prop_value in properties.values():
            if prop_value.get("type") == "title":
                title_data = prop_value.get("title", [])
                if title_data:
                    return str(title_data[0].get("plain_text", "Untitled"))
                break
    return "Untitled"


def _fetch_data(request: FetchDataInput, auth_credentials: dict[str, Any]) -> dict[str, Any]:
    user_id = _user_id(auth_credentials)

    search_body: dict[str, Any] = {
        "filter": {"property": "object", "value": request.fetch_type.rstrip("s")},
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
    except AppError as e:
        log.error(f"{LogTag.TOOL} Notion API error", error_type=type(e).__name__)
        raise RuntimeError(f"Failed to fetch {request.fetch_type}: {e.message}") from e
    except Exception as e:
        log.error(
            f"{LogTag.TOOL} Error fetching from Notion",
            fetch_type=request.fetch_type,
            error_type=type(e).__name__,
        )
        raise RuntimeError(f"Failed to fetch {request.fetch_type}: {e!s}") from e

    values = [
        {"id": item.get("id"), "title": _item_title(item), "type": item.get("object")}
        for item in search_results.get("results", [])
        if item.get("id")
    ]

    return {
        "values": values,
        "count": len(values),
        "has_more": search_results.get("has_more", False),
    }


def register_notion_custom_tools(composio: Composio) -> list[str]:
    """Register Notion tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="NOTION")
    @with_doc(MOVE_PAGE_DOC)
    def MOVE_PAGE(
        request: MovePageInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        del auth_credentials  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "notion", "action": "move_page"})
        return _move_page(request, execute_request)

    @composio.tools.custom_tool(toolkit="NOTION")
    @with_doc(FETCH_PAGE_AS_MARKDOWN_DOC)
    def FETCH_PAGE_AS_MARKDOWN(
        request: FetchPageAsMarkdownInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "notion", "action": "fetch_page_as_markdown"})
        return _fetch_page_as_markdown(composio, request, auth_credentials)

    @composio.tools.custom_tool(toolkit="NOTION")
    @with_doc(INSERT_MARKDOWN_DOC)
    def INSERT_MARKDOWN(
        request: InsertMarkdownInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "notion", "action": "insert_markdown"})
        return _insert_markdown(composio, request, auth_credentials)

    @composio.tools.custom_tool(toolkit="NOTION")
    @with_doc(FETCH_DATA_DOC)
    def FETCH_DATA(
        request: FetchDataInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch databases or pages from Notion workspace."""
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "notion", "action": "fetch_data"})
        return _fetch_data(request, auth_credentials)

    @composio.tools.custom_tool(toolkit="NOTION")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Get Notion workspace context: recently edited pages and databases.

        Zero required parameters. Returns recently modified content for situational awareness.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
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
