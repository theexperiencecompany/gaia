"""
Google Docs trigger payloads.

Reference: node_modules/@composio/core/generated/googledocs.ts
"""

from typing import Any

from pydantic import BaseModel, Field


class GoogleDocsDocument(BaseModel):
    """Google Doc document details."""

    createdTime: str = Field(..., description="Creation time in ISO format")
    id: str = Field(..., description="Unique identifier of the document")
    lastModifyingUser: dict[str, Any] | None = Field(None, description="Last modifying user info")
    mimeType: str = Field(..., description="MIME type of the document")
    modifiedTime: str = Field(..., description="Last modification time in ISO format")
    name: str = Field(..., description="Name of the document")
    owners: list[dict[str, Any]] | None = Field(None, description="List of document owners")


class GoogleDocsPageAddedPayload(BaseModel):
    """Payload for GOOGLEDOCS_PAGE_ADDED_TRIGGER.

    Field set verified against Composio triggers_types API (2026-08).
    """

    document: GoogleDocsDocument | None = Field(None, description="The newly added Google document")
    event_type: str | None = Field(None, description="Type of event that occurred")


class GoogleDocsDocumentDeletedPayload(BaseModel):
    """Payload for GOOGLEDOCS_DOCUMENT_DELETED_TRIGGER."""

    document: GoogleDocsDocument | None = Field(None, description="The deleted Google document")
    event_type: str | None = Field(None, description="Type of event that occurred")


class GoogleDocsDocumentUpdatedPayload(BaseModel):
    """Payload for GOOGLEDOCS_DOCUMENT_UPDATED_TRIGGER."""

    document: GoogleDocsDocument | None = Field(None, description="The updated Google document")
    event_type: str | None = Field(None, description="Type of event that occurred")
