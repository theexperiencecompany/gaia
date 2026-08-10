"""
Notion trigger payload and tool output models.

Reference: node_modules/@composio/core/generated/notion.ts
"""

from pydantic import BaseModel, Field

# =============================================================================
# Trigger Payloads
# =============================================================================


class NotionPageAddedPayload(BaseModel):  # type: ignore[explicit-any]
    """Payload for NOTION_PAGE_ADDED_TRIGGER."""

    block: dict[str, object] | None = Field(None, description="The added block/page")
    event_type: str = Field(..., description="Event type")


class NotionPageUpdatedPayload(BaseModel):  # type: ignore[explicit-any]
    """Payload for NOTION_PAGE_UPDATED_TRIGGER."""

    block: dict[str, object] | None = Field(None, description="The updated block/page")
    event_type: str = Field(..., description="Event type")


class NotionAllPageEventsPayload(BaseModel):  # type: ignore[explicit-any]
    """Payload for NOTION_ALL_PAGE_EVENTS_TRIGGER."""

    block: dict[str, object] | None = Field(None, description="The block/page")
    event_type: str = Field(..., description="Event type")
