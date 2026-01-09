"""
Notion trigger payload models.

Reference: node_modules/@composio/core/generated/notion.ts
"""

from typing import Any

from pydantic import BaseModel, Field


class NotionPageAddedPayload(BaseModel):
    """Payload for NOTION_PAGE_ADDED_TRIGGER."""

    block: dict[str, Any] | None = Field(None, description="The added block/page")
    event_type: str = Field(..., description="Event type")


class NotionPageUpdatedPayload(BaseModel):
    """Payload for NOTION_PAGE_UPDATED_TRIGGER."""

    block: dict[str, Any] | None = Field(None, description="The updated block/page")
    event_type: str = Field(..., description="Event type")


class NotionAllPageEventsPayload(BaseModel):
    """Payload for NOTION_ALL_PAGE_EVENTS_TRIGGER."""

    block: dict[str, Any] | None = Field(None, description="The block/page")
    event_type: str = Field(..., description="Event type")
