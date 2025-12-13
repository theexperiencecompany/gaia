from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GoogleDocCreate(BaseModel):
    """Model for creating a new Google Doc."""

    title: str = Field(..., description="Title of the document")
    content: Optional[str] = Field(None, description="Initial content for the document")


class GoogleDocUpdate(BaseModel):
    """Model for updating Google Doc content."""

    document_id: str = Field(..., description="ID of the document to update")
    content: str = Field(..., description="Content to add or replace")
    insert_at_end: bool = Field(
        True, description="Whether to insert at end or replace all content"
    )


class GoogleDocFormat(BaseModel):
    """Model for formatting text in a Google Doc."""

    document_id: str = Field(..., description="ID of the document")
    start_index: int = Field(..., description="Start position for formatting")
    end_index: int = Field(..., description="End position for formatting")
    bold: Optional[bool] = Field(None, description="Apply bold formatting")
    italic: Optional[bool] = Field(None, description="Apply italic formatting")
    underline: Optional[bool] = Field(None, description="Apply underline formatting")
    font_size: Optional[int] = Field(None, description="Font size in points")
    foreground_color: Optional[Dict[str, float]] = Field(
        None, description="Text color as RGB values (0-1)"
    )


class GoogleDocShare(BaseModel):
    """Model for sharing a Google Doc."""

    document_id: str = Field(..., description="ID of the document to share")
    email: str = Field(..., description="Email address to share with")
    role: str = Field("writer", description="Role to grant (reader, writer, owner)")
    send_notification: bool = Field(
        True, description="Whether to send email notification"
    )


class GoogleDocSearch(BaseModel):
    """Model for searching Google Docs."""

    query: str = Field(..., description="Search query")
    limit: int = Field(10, description="Maximum number of results to return")


class GoogleDocList(BaseModel):
    """Model for listing Google Docs."""

    limit: int = Field(10, description="Maximum number of documents to return")
    query: Optional[str] = Field(
        None, description="Optional search query to filter documents"
    )


class GoogleDocResponse(BaseModel):
    """Response model for Google Doc operations."""

    document_id: str = Field(..., description="ID of the document")
    title: Optional[str] = Field(None, description="Title of the document")
    content: Optional[str] = Field(None, description="Content of the document")
    url: str = Field(..., description="URL to access the document")
    created_time: Optional[str] = Field(None, description="Creation timestamp")
    modified_time: Optional[str] = Field(
        None, description="Last modification timestamp"
    )
    revision_id: Optional[str] = Field(None, description="Revision ID of the document")


class GoogleDocListResponse(BaseModel):
    """Response model for listing Google Docs."""

    documents: List[GoogleDocResponse] = Field(..., description="List of documents")
    total_count: int = Field(..., description="Total number of documents found")


class GoogleDocShareResponse(BaseModel):
    """Response model for sharing a Google Doc."""

    document_id: str = Field(..., description="ID of the document")
    shared_with: str = Field(..., description="Email address shared with")
    role: str = Field(..., description="Role granted")
    permission_id: str = Field(..., description="ID of the permission created")
    url: str = Field(..., description="URL to access the document")


class GoogleDocFormatResponse(BaseModel):
    """Response model for formatting operations."""

    document_id: str = Field(..., description="ID of the document")
    url: str = Field(..., description="URL to access the document")
    formatting_applied: int = Field(
        ..., description="Number of formatting operations applied"
    )


class GoogleDocUpdateResponse(BaseModel):
    """Response model for update operations."""

    document_id: str = Field(..., description="ID of the document")
    url: str = Field(..., description="URL to access the document")
    updates_applied: int = Field(..., description="Number of updates applied")


class GoogleDocError(BaseModel):
    """Error model for Google Docs operations."""

    error: str = Field(..., description="Error message")
    document_id: Optional[str] = Field(None, description="Document ID if applicable")
    details: Optional[Dict[str, Any]] = Field(
        None, description="Additional error details"
    )
