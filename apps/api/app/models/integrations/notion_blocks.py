"""Notion block objects as notion_md walks them into Markdown.

Reference: https://developers.notion.com/reference/block and
https://developers.notion.com/reference/rich-text

Reading side: a block keeps its type-specific object under a key named by type.
NotionBlockContent declares the union of the fields the converter reads across
every type; fields a type does not carry stay at their defaults. children is
Composio's recursive-fetch nesting, not part of Notion's own block object.

Writing side: markdown_to_notion_blocks emits the blocks
NOTION_ADD_MULTIPLE_PAGE_CONTENT (NotionContentBlock, NotionCodeBlock) and
NOTION_APPEND_TABLE_BLOCKS (NotionTableBlock) accept.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NotionAnnotations(BaseModel):
    """A rich-text item's styling flags."""

    model_config = ConfigDict(extra="ignore")

    bold: bool = False
    italic: bool = False
    strikethrough: bool = False
    underline: bool = False
    code: bool = False


class NotionEquation(BaseModel):
    """An equation rich-text item's or block's expression."""

    model_config = ConfigDict(extra="ignore")

    expression: str = ""


class NotionRichText(BaseModel):
    """One item of a rich_text array: text, mention or equation."""

    model_config = ConfigDict(extra="ignore")

    type: str = ""
    plain_text: str = ""
    href: str | None = None
    annotations: NotionAnnotations = Field(default_factory=NotionAnnotations)
    equation: NotionEquation = Field(default_factory=NotionEquation)


class NotionFileRef(BaseModel):
    """external or file on a file-like block — either way a url."""

    model_config = ConfigDict(extra="ignore")

    url: str = ""


class NotionIcon(BaseModel):
    """A callout's icon: an emoji when type is emoji."""

    model_config = ConfigDict(extra="ignore")

    type: str = ""
    emoji: str = ""


class NotionBlockContent(BaseModel):
    """The type-specific object of a block: every field notion_md reads, across types.

    rich_text carries the text of text blocks (text is the pre-2022 name
    Composio still emits for some); caption the caption of file-like blocks;
    type/external/file a file-like block's source (type is
    page_id/database_id on link_to_page); cells a table row.
    """

    model_config = ConfigDict(extra="ignore")

    rich_text: list[NotionRichText] = Field(default_factory=list)
    text: list[NotionRichText] = Field(default_factory=list)
    caption: list[NotionRichText] = Field(default_factory=list)
    type: str = ""
    external: NotionFileRef = Field(default_factory=NotionFileRef)
    file: NotionFileRef = Field(default_factory=NotionFileRef)
    url: str = ""
    expression: str = ""
    title: str | None = None
    cells: list[list[NotionRichText]] = Field(default_factory=list)
    language: str = ""
    icon: NotionIcon | None = None
    checked: bool = False
    page_id: str = ""
    database_id: str = ""


class NotionBlock(BaseModel):
    """A block object; the type-specific content is read through content."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    type: str = ""
    has_children: bool = False
    children: "list[NotionBlock]" = Field(default_factory=list)

    @property
    def content(self) -> NotionBlockContent | None:
        """Return the object under the key named by type.

        None when that key is absent, not an object, or empty.
        """
        raw = (self.model_extra or {}).get(self.type)
        if not isinstance(raw, dict) or not raw:
            return None
        return NotionBlockContent.model_validate(raw)


class NotionTextContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str


class NotionTextRun(BaseModel):
    """A plain text rich-text item as the write tools take it."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["text"] = "text"
    text: NotionTextContent


class NotionContentBlock(BaseModel):
    """NOTION_ADD_MULTIPLE_PAGE_CONTENT's unwrapped form: the tool parses the
    Markdown in content itself. block_property is one of the tool's block
    kinds (paragraph, heading_1, bulleted_list_item, ...)."""

    model_config = ConfigDict(extra="forbid")

    block_property: str
    content: str


class NotionCodeBlockBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str
    rich_text: list[NotionTextRun]


class NotionCodeBlock(BaseModel):
    """A code block in Notion's full form — the unwrapped form has no language."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["code"] = "code"
    code: NotionCodeBlockBody


class NotionTableRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cells: list[list[NotionTextRun]]


class NotionTableBlock(BaseModel):
    """NOTION_APPEND_TABLE_BLOCKS's arguments for one table."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["table"] = "table"
    table_width: int
    has_column_header: bool = True
    rows: list[NotionTableRow]


NotionMarkdownBlock = NotionContentBlock | NotionCodeBlock | NotionTableBlock
