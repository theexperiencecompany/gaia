"""
Notion trigger payload and tool output models.

Reference: node_modules/@composio/core/generated/notion.ts
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Trigger Payloads
# =============================================================================


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


# =============================================================================
# Tool Output Schemas
# =============================================================================


class NotionSearchData(BaseModel):
    """Output data for NOTION_SEARCH_NOTION_PAGE tool."""

    model_config = ConfigDict(extra="ignore")

    response_data: dict[str, Any] = Field(default_factory=dict)

    def get_results(self) -> list[dict[str, Any]]:
        """Get results from nested response_data."""
        if "results" in self.response_data:
            return self.response_data["results"]
        return self.response_data.get("pages", [])
