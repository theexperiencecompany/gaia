from typing import List

from pydantic import BaseModel, Field


class ShareRecipient(BaseModel):
    """Single recipient for document sharing."""

    email: str = Field(..., description="Email address to share with")
    role: str = Field(
        "writer",
        description="Permission level: 'reader' (view only), 'writer' (can edit), 'owner' (full control)",
    )
    send_notification: bool = Field(
        True, description="Whether to send email notification to this recipient"
    )


class ShareDocInput(BaseModel):
    """Input for bulk sharing a Google Doc with multiple recipients."""

    document_id: str = Field(..., description="ID of the document to share")
    recipients: List[ShareRecipient] = Field(
        ...,
        description="List of recipients to share the document with",
        min_length=1,
    )


class CreateTOCInput(BaseModel):
    """Input for creating a table of contents in a Google Doc."""

    document_id: str = Field(..., description="ID of the document")
    insertion_index: int = Field(
        default=1,
        description="Position to insert TOC (1 = beginning of document)",
        ge=1,
    )
    include_heading_levels: List[int] = Field(
        default=[1, 2, 3],
        description="Which heading levels to include (1=H1, 2=H2, etc.)",
    )
    title: str = Field(
        default="Table of Contents",
        description="Title for the TOC section",
    )


class DeleteDocInput(BaseModel):
    """Input for deleting a Google Doc."""

    document_id: str = Field(..., description="ID of the document to delete")
