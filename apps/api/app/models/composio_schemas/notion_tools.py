"""
Notion tool schemas.

Reference: NOTION_FETCH_DATA tool schema (updated 2026-01)

Note: All Composio tool responses are wrapped in ToolExecutionResponse with
`data`, `error`, `successful` keys. These models represent the INNER data structure.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NotionFetchDataInput(BaseModel):
    """Input for NOTION_FETCH_DATA."""

    fetch_type: Literal["pages", "databases", "all"] = Field(
        ..., description="Type of data to fetch"
    )
    page_size: int | None = Field(100, description="Max items per page (1-100)")
    query: str | None = Field(None, description="Search query to filter by title")


class NotionItem(BaseModel):
    """Notion item (page or database)."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    title: str | None = None
    type: str | None = None  # 'page' or 'database'
    url: str | None = None


class NotionFetchDataData(BaseModel):
    """Data inside ToolExecutionResponse.data for NOTION_FETCH_DATA."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    values: list[dict] = Field(default_factory=list)

    def get_items(self) -> list[NotionItem]:
        """Get items as typed models."""
        return [
            NotionItem.model_validate(v) for v in self.values if isinstance(v, dict)
        ]
