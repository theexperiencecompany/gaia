"""Notion custom tools using Composio custom tool infrastructure.

These tools wrap existing Composio Notion tools and add markdown conversion:
- FETCH_PAGE_AS_MARKDOWN: Calls NOTION_FETCH_ALL_BLOCK_CONTENTS → converts to markdown
- INSERT_MARKDOWN: Converts markdown → calls NOTION_ADD_MULTIPLE_PAGE_CONTENT
- MOVE_PAGE / FETCH_DATA : route through Composio's
  proxy via `proxy_request_sync` (no existing Composio equivalent)

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Literal

from composio import Composio
from composio.types import ExecuteRequestFn
from pydantic import BaseModel

from app.constants.log_tags import LogTag
from app.decorators import with_doc
from app.models.common_models import GatherContextInput
from app.models.composio_schemas import ComposioResponse
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.notion import (
    NotionAddPageContentArgs,
    NotionAppendTableBlocksArgs,
    NotionBlockChildren,
    NotionFetchBlockContentsArgs,
    NotionGetPagePropertyArgs,
    NotionMovePageRequest,
    NotionPage,
    NotionPageContentBlock,
    NotionParent,
    NotionPropertyItemList,
    NotionSearchFilter,
    NotionSearchRequest,
    NotionSearchResponse,
    NotionSearchResult,
    NotionSearchToolArgs,
    NotionSearchToolData,
    NotionTable,
)
from app.models.integrations.notion_blocks import NotionBlock, NotionTableBlock
from app.models.notion_models import (
    FetchDataInput,
    FetchPageAsMarkdownInput,
    InsertMarkdownInput,
    MovePageInput,
)
from app.services.composio.proxy_client import ProxyRequest, proxy_request_sync
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

# ``fetch_type`` is the tool's plural noun; Notion's search filter wants the object name.
_SEARCH_OBJECT: dict[Literal["databases", "pages"], Literal["page", "database"]] = {
    "databases": "database",
    "pages": "page",
}


def _execute_notion_action(
    composio: Composio,
    slug: str,
    arguments: BaseModel,
    auth_credentials: CustomToolAuthCredentials,
) -> ComposioResponse:
    return ComposioResponse.model_validate(
        composio.tools.execute(
            slug=slug,
            arguments=arguments.model_dump(  # pragma: no mutate -- dropping mode= is unobservable here and banned by tool-dump-boundary
                mode="json",  # pragma: no mutate -- JSON-native fields only, so any mode value dumps identically
                exclude_none=True,
            ),
            version=auth_credentials.version,
            dangerously_skip_version_check=True,
            user_id=auth_credentials.user_id,
        )
    )


def _build_parent(parent_type: str, parent_id: str) -> NotionParent:
    if parent_type == "page_id":
        return NotionParent(type="page_id", page_id=parent_id)
    return NotionParent(type="database_id", database_id=parent_id)


def _move_page(request: MovePageInput, execute_request: ExecuteRequestFn) -> dict[str, object]:
    parent = _build_parent(request.parent_type, request.parent_id)
    move_request = NotionMovePageRequest(parent=parent)

    response = execute_request(
        endpoint=f"/pages/{request.page_id}",
        method="PATCH",
        body=move_request.model_dump(  # pragma: no mutate -- dropping mode= is unobservable here and banned by tool-dump-boundary
            mode="json",  # pragma: no mutate -- JSON-native fields only, so any mode value dumps identically
            exclude_none=True,
        ),
    )

    page = NotionPage.model_validate(response.data)
    return {
        "page_id": page.id,
        "new_parent": parent.model_dump(  # pragma: no mutate -- dropping mode= is unobservable here and banned by tool-dump-boundary
            mode="json",  # pragma: no mutate -- JSON-native fields only, so any mode value dumps identically
            exclude_none=True,
        ),
        "url": page.url,
    }


def _fetch_page_title(
    composio: Composio,
    page_id: str,
    auth_credentials: CustomToolAuthCredentials,
) -> str:
    title_response = _execute_notion_action(
        composio,
        "NOTION_GET_PAGE_PROPERTY_ACTION",
        NotionGetPagePropertyArgs(page_id=page_id, property_id="title"),
        auth_credentials,
    )
    if not title_response.successful:
        raise AppError(
            message=f"Failed to fetch Notion page title: {title_response.error}",
            status_code=502,
        )

    for item in NotionPropertyItemList.model_validate(title_response.data).results:
        if item.type == "title" and item.title:
            return item.title.plain_text
    return ""


def _fetch_page_blocks(
    composio: Composio,
    request: FetchPageAsMarkdownInput,
    auth_credentials: CustomToolAuthCredentials,
) -> list[NotionBlock]:
    blocks_response = _execute_notion_action(
        composio,
        "NOTION_FETCH_ALL_BLOCK_CONTENTS",
        NotionFetchBlockContentsArgs(
            block_id=request.page_id, recursive=request.recursive, page_size=100
        ),
        auth_credentials,
    )

    if not blocks_response.successful:
        raise ValueError(f"Failed to fetch blocks: {blocks_response.error}")

    children = NotionBlockChildren.model_validate(blocks_response.data)
    blocks = children.results if children.results is not None else children.blocks
    return blocks or []


def _fetch_page_as_markdown(
    composio: Composio,
    request: FetchPageAsMarkdownInput,
    auth_credentials: CustomToolAuthCredentials,
) -> dict[str, object]:
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
    block: NotionTableBlock,
    auth_credentials: CustomToolAuthCredentials,
) -> None:
    response = _execute_notion_action(
        composio,
        "NOTION_APPEND_TABLE_BLOCKS",
        NotionAppendTableBlocksArgs(
            block_id=request.parent_block_id,
            tables=[
                NotionTable(
                    table_width=block.table_width,
                    has_column_header=block.has_column_header,
                    rows=block.rows,
                )
            ],
        ),
        auth_credentials,
    )

    if not response.successful:
        raise ValueError(f"Failed to insert table: {response.error}")


def _append_content_block(
    composio: Composio,
    request: InsertMarkdownInput,
    block: NotionPageContentBlock,
    after: str | None,
    auth_credentials: CustomToolAuthCredentials,
) -> None:
    response = _execute_notion_action(
        composio,
        "NOTION_ADD_MULTIPLE_PAGE_CONTENT",
        NotionAddPageContentArgs(
            parent_block_id=request.parent_block_id, content_blocks=[block], after=after or None
        ),
        auth_credentials,
    )

    if not response.successful:
        raise ValueError(f"Failed to insert markdown: {response.error}")


def _insert_markdown(
    composio: Composio,
    request: InsertMarkdownInput,
    auth_credentials: CustomToolAuthCredentials,
) -> dict[str, object]:
    all_blocks = markdown_to_notion_blocks(request.markdown)

    if not all_blocks:
        raise ValueError("No content to insert - markdown conversion produced no blocks")

    blocks_added = 0
    anchor_uses_left = int(request.after is not None)

    for block in all_blocks:
        if isinstance(block, NotionTableBlock):
            _append_table_block(composio, request, block, auth_credentials)
        elif anchor_uses_left > 0:
            anchor_uses_left = 0
            _append_content_block(composio, request, block, request.after, auth_credentials)
        else:
            _append_content_block(composio, request, block, None, auth_credentials)
        blocks_added += 1

    tables_added = sum(1 for b in all_blocks if isinstance(b, NotionTableBlock))

    return {
        "parent_block_id": request.parent_block_id,
        "blocks_added": blocks_added,
        "tables_added": tables_added,
        "after": request.after,
    }


def _item_title(item: NotionSearchResult) -> str:
    if item.object == "database":
        if item.title:
            return item.title[0].plain_text
    elif item.object == "page":
        for prop_value in item.properties.values():
            if prop_value.type == "title":
                if prop_value.title:
                    return prop_value.title[0].plain_text
                break
    return "Untitled"


def _fetch_data(
    request: FetchDataInput, auth_credentials: CustomToolAuthCredentials
) -> dict[str, object]:
    search_body = NotionSearchRequest(
        filter=NotionSearchFilter(value=_SEARCH_OBJECT[request.fetch_type]),
        page_size=min(request.page_size, 100),
        query=request.query or None,
    )

    try:
        search_results = NotionSearchResponse.model_validate(
            proxy_request_sync(
                ProxyRequest(
                    user_id=auth_credentials.user_id,
                    toolkit=NOTION_TOOLKIT,
                    endpoint=f"{NOTION_API_BASE}/search",
                    method="POST",
                    body=search_body.model_dump(  # pragma: no mutate -- dropping mode= is unobservable here and banned by tool-dump-boundary
                        mode="json",  # pragma: no mutate -- JSON-native fields only, so any mode value dumps identically
                        exclude_none=True,
                    ),
                    headers=_NOTION_HEADERS,
                )
            )
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
        {"id": item.id, "title": _item_title(item), "type": item.object}
        for item in search_results.results
    ]

    return {
        "values": values,
        "count": len(values),
        "has_more": search_results.has_more,
    }


def register_notion_custom_tools(composio: Composio) -> list[str]:
    """Register Notion tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="NOTION")
    @with_doc(MOVE_PAGE_DOC)
    def MOVE_PAGE(
        request: MovePageInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        del auth_credentials  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "notion", "action": "move_page"})
        return _move_page(request, execute_request)

    @composio.tools.custom_tool(toolkit="NOTION")
    @with_doc(FETCH_PAGE_AS_MARKDOWN_DOC)
    def FETCH_PAGE_AS_MARKDOWN(
        request: FetchPageAsMarkdownInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "notion", "action": "fetch_page_as_markdown"})
        return _fetch_page_as_markdown(
            composio, request, CustomToolAuthCredentials.parse(auth_credentials)
        )

    @composio.tools.custom_tool(toolkit="NOTION")
    @with_doc(INSERT_MARKDOWN_DOC)
    def INSERT_MARKDOWN(
        request: InsertMarkdownInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "notion", "action": "insert_markdown"})
        return _insert_markdown(
            composio, request, CustomToolAuthCredentials.parse(auth_credentials)
        )

    @composio.tools.custom_tool(toolkit="NOTION")
    @with_doc(FETCH_DATA_DOC)
    def FETCH_DATA(
        request: FetchDataInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Fetch databases or pages from Notion workspace."""
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "notion", "action": "fetch_data"})
        return _fetch_data(request, CustomToolAuthCredentials.parse(auth_credentials))

    @composio.tools.custom_tool(toolkit="NOTION")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Notion workspace context: recently edited pages and databases.

        Zero required parameters. Returns recently modified content for situational awareness.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "notion", "action": "gather_context"})
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id
        search_args = NotionSearchToolArgs(query="", page_size=10)
        data = NotionSearchToolData.model_validate(
            execute_tool(
                "NOTION_SEARCH_NOTION_PAGE",
                search_args.model_dump(  # pragma: no mutate -- dropping mode= is unobservable here and banned by tool-dump-boundary
                    mode="json",  # pragma: no mutate -- JSON-native fields only, so any mode value dumps identically
                ),
                user_id,
            )
        )
        pages = data.results or data.pages
        return {
            "relevant_pages": [
                page.model_dump(  # pragma: no mutate -- dropping mode= is unobservable here and banned by tool-dump-boundary
                    mode="json",  # pragma: no mutate -- JSON-native fields only, so any mode value dumps identically
                )
                for page in pages
            ]
        }

    return [
        "NOTION_MOVE_PAGE",
        "NOTION_FETCH_PAGE_AS_MARKDOWN",
        "NOTION_INSERT_MARKDOWN",
        "NOTION_FETCH_DATA",
        "NOTION_CUSTOM_GATHER_CONTEXT",
    ]
