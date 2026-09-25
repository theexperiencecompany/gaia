"""Notion payloads the Notion tool reads and sends.

Two providers meet here: Notion's REST API (/search, /pages) and the
Composio Notion tools the markdown round-trip is built on. The block objects
themselves live in notion_blocks with the converter that walks them.

References:
- https://developers.notion.com/reference
- https://docs.composio.dev/toolkits/notion
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.integrations.notion_blocks import (
    NotionBlock,
    NotionCodeBlock,
    NotionContentBlock,
    NotionTableRow,
)

# =============================================================================
# Notion REST API
# =============================================================================


class NotionRichTextSegment(BaseModel):
    """One rich-text object; ``plain_text`` is always rendered by Notion."""

    model_config = ConfigDict(extra="ignore")

    plain_text: str


class NotionPropertyValue(BaseModel):
    """A page property value; ``title`` is populated only for ``type == "title"``."""

    model_config = ConfigDict(extra="ignore")

    type: str
    title: list[NotionRichTextSegment] = Field(default_factory=list)


class NotionPageSearchResult(BaseModel):
    """A page as ``POST /v1/search`` lists it; its title is the property with ``type: "title"``."""

    model_config = ConfigDict(extra="ignore")

    id: str
    object: Literal["page"]
    properties: dict[str, NotionPropertyValue] = Field(default_factory=dict)


class NotionDatabaseSearchResult(BaseModel):
    """A database as ``POST /v1/search`` lists it; its title is at the top level.

    A database's ``properties`` map is its column schema (a title column is
    ``{}``, not a list of segments), so it is not read.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    object: Literal["database"]
    title: list[NotionRichTextSegment] = Field(default_factory=list)


NotionSearchResult = Annotated[
    NotionPageSearchResult | NotionDatabaseSearchResult, Field(discriminator="object")
]


class NotionSearchResponse(BaseModel):
    """``POST /v1/search``."""

    model_config = ConfigDict(extra="ignore")

    results: list[NotionSearchResult] = Field(default_factory=list)
    has_more: bool = False


class NotionSearchFilter(BaseModel):
    property: Literal["object"] = "object"
    value: Literal["page", "database"]


class NotionSearchRequest(BaseModel):
    """``POST /v1/search`` body; ``query`` only when the caller gave one."""

    filter: NotionSearchFilter
    page_size: int
    query: str | None = None


class NotionParent(BaseModel):
    """A page's ``parent`` reference — exactly one id is set, matching ``type``."""

    type: Literal["page_id", "database_id"]
    page_id: str | None = None
    database_id: str | None = None


class NotionMovePageRequest(BaseModel):
    """``PATCH /v1/pages/{id}`` body for a re-parent."""

    parent: NotionParent


class NotionPage(BaseModel):
    """The page object every ``/v1/pages`` write answers with."""

    model_config = ConfigDict(extra="ignore")

    id: str
    url: str


# =============================================================================
# Composio Notion tools — results
# =============================================================================


class NotionPropertyItem(BaseModel):
    """One ``NOTION_GET_PAGE_PROPERTY_ACTION`` result; a title property lists one item per segment."""

    model_config = ConfigDict(extra="ignore")

    type: str
    title: NotionRichTextSegment | None = None


class NotionPropertyItemList(BaseModel):
    """``NOTION_GET_PAGE_PROPERTY_ACTION`` data; ``results`` only for paginated (title/rich text) properties."""

    model_config = ConfigDict(extra="ignore")

    results: list[NotionPropertyItem] = Field(default_factory=list)


class NotionBlockChildren(BaseModel):
    """``NOTION_FETCH_ALL_BLOCK_CONTENTS`` data; older builds list the blocks under ``blocks``."""

    model_config = ConfigDict(extra="ignore")

    results: list[NotionBlock] | None = None
    blocks: list[NotionBlock] | None = None


class NotionPageSummary(BaseModel):
    """One ``NOTION_SEARCH_NOTION_PAGE`` hit.

    ``extra="allow"``: the context tool forwards each hit verbatim to the agent.
    """

    model_config = ConfigDict(extra="allow")

    id: str


class NotionSearchToolData(BaseModel):
    """``NOTION_SEARCH_NOTION_PAGE`` data; the hits are under ``results`` (older builds: ``pages``)."""

    model_config = ConfigDict(extra="ignore")

    results: list[NotionPageSummary] = Field(default_factory=list)
    pages: list[NotionPageSummary] = Field(default_factory=list)


# =============================================================================
# Composio Notion tools — arguments
# =============================================================================


NotionPageContentBlock = NotionCodeBlock | NotionContentBlock


class NotionTable(BaseModel):
    """One entry of ``NOTION_APPEND_TABLE_BLOCKS``' ``tables``."""

    table_width: int
    has_column_header: bool
    rows: list[NotionTableRow]


class NotionAppendTableBlocksArgs(BaseModel):
    block_id: str
    tables: list[NotionTable]


class NotionAddPageContentArgs(BaseModel):
    """``NOTION_ADD_MULTIPLE_PAGE_CONTENT`` arguments; ``after`` anchors the first block."""

    parent_block_id: str
    content_blocks: list[NotionPageContentBlock]
    after: str | None = None


class NotionGetPagePropertyArgs(BaseModel):
    page_id: str
    property_id: str


class NotionFetchBlockContentsArgs(BaseModel):
    block_id: str
    recursive: bool
    page_size: int


class NotionSearchToolArgs(BaseModel):
    query: str
    page_size: int
