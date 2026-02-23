"""
Google Docs trigger payloads.

Reference: node_modules/@composio/core/generated/googledocs.ts
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GoogleDocsDocument(BaseModel):
    """Google Doc document details."""

    createdTime: str = Field(..., description="Creation time in ISO format")
    id: str = Field(..., description="Unique identifier of the document")
    lastModifyingUser: Optional[Dict[str, Any]] = Field(
        None, description="Last modifying user info"
    )
    mimeType: str = Field(..., description="MIME type of the document")
    modifiedTime: str = Field(..., description="Last modification time in ISO format")
    name: str = Field(..., description="Name of the document")
    owners: Optional[List[Dict[str, Any]]] = Field(
        None, description="List of document owners"
    )


class GoogleDocsPageAddedPayload(BaseModel):
    """Payload for GOOGLEDOCS_PAGE_ADDED_TRIGGER."""

    document: Optional[GoogleDocsDocument] = Field(
        None, description="The newly added Google document"
    )
