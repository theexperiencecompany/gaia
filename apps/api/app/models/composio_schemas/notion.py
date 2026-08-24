"""
Notion trigger payload and tool output models.

Field sets verified against the Composio triggers_types API (2026-08);
the legacy NOTION_PAGE_ADDED_TO_DATABASE / NOTION_PAGE_UPDATED_TRIGGER /
NOTION_ALL_PAGE_EVENTS_TRIGGER slugs are retired upstream.
"""

from typing import Any

from pydantic import BaseModel, Field

NOTION_AUTHORS_DESCRIPTION = "Actors who performed the action"


class NotionPageCreatedPayload(BaseModel):
    """Payload for NOTION_PAGE_CREATED."""

    authors: list[dict[str, Any]] | None = Field(None, description=NOTION_AUTHORS_DESCRIPTION)
    data: dict[str, Any] | None = Field(None, description="Where the new page was created")
    event_id: str | None = Field(None, description="Unique ID of the webhook event")
    event_type: str | None = Field(None, description="Notion webhook event type")
    page_id: str | None = Field(None, description="ID of the newly created page")
    timestamp: str | None = Field(None, description="ISO 8601 event timestamp")
    workspace_id: str | None = Field(None, description="Workspace where the event occurred")
    workspace_name: str | None = Field(None, description="Workspace name from the event")


class NotionPagePropertiesUpdatedPayload(BaseModel):
    """Payload for NOTION_PAGE_PROPERTIES_UPDATED."""

    authors: list[dict[str, Any]] | None = Field(None, description=NOTION_AUTHORS_DESCRIPTION)
    data: dict[str, Any] | None = Field(
        None,
        description="Parent reference plus the list of property IDs that changed",
    )
    event_id: str | None = Field(None, description="Unique ID of the webhook event")
    event_type: str | None = Field(None, description="Notion webhook event type")
    page_id: str | None = Field(None, description="ID of the page whose properties changed")
    timestamp: str | None = Field(None, description="ISO 8601 event timestamp")
    workspace_id: str | None = Field(None, description="Workspace where the event occurred")
    workspace_name: str | None = Field(None, description="Workspace name from the event")


class NotionPageContentUpdatedPayload(BaseModel):
    """Payload for NOTION_PAGE_CONTENT_UPDATED."""

    authors: list[dict[str, Any]] | None = Field(None, description=NOTION_AUTHORS_DESCRIPTION)
    data: dict[str, Any] | None = Field(
        None,
        description="Parent reference plus the list of updated blocks",
    )
    event_id: str | None = Field(None, description="Unique ID of the webhook event")
    event_type: str | None = Field(None, description="Notion webhook event type")
    page_id: str | None = Field(None, description="ID of the page whose content changed")
    timestamp: str | None = Field(None, description="ISO 8601 event timestamp")
    workspace_id: str | None = Field(None, description="Workspace where the event occurred")
    workspace_name: str | None = Field(None, description="Workspace name from the event")
