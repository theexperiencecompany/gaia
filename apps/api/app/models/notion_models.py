"""Notion models for custom tools."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class MovePageInput(BaseModel):
    """Input for moving a page to a new parent."""

    page_id: str = Field(..., description="UUID of the page to move.")
    parent_type: Literal["page_id", "database_id"] = Field(
        ..., description="Type of parent: 'page_id' or 'database_id'."
    )
    parent_id: str = Field(
        ..., description="UUID of the new parent (page or database)."
    )


class FetchPageAsMarkdownInput(BaseModel):
    """Input for fetching a page as markdown."""

    page_id: str = Field(..., description="UUID of the page to fetch.")
    recursive: bool = Field(
        default=True, description="Whether to fetch nested children blocks."
    )
    include_block_ids: bool = Field(
        default=True,
        description="Include block IDs as HTML comments (<!-- block:id -->) for insertion positioning with `after` parameter.",
    )


class InsertMarkdownInput(BaseModel):
    """Input for inserting markdown content into a page or block."""

    parent_block_id: str = Field(
        ...,
        description="UUID of the parent page or block where content will be added.",
    )
    markdown: str = Field(
        ...,
        description="Markdown content to insert. Supports headings, lists, code blocks, quotes, todos, and inline formatting.",
    )
    after: Optional[str] = Field(
        default=None,
        description="UUID of an existing block. New blocks will be inserted immediately after this block. If omitted, blocks are appended to the end.",
    )


class CreateTestPageInput(BaseModel):
    """Input for creating a simple test page."""

    title: str = Field(..., description="Title of the page")
    parent_page_id: Optional[str] = Field(None, description="Parent page ID (optional)")
