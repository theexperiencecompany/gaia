"""Pydantic schemas for file metadata operations."""

from pydantic import BaseModel, Field


class UpdateFileRequest(BaseModel):
    """Editable file metadata fields. Only these may be updated by the client."""

    filename: str | None = Field(default=None, description="New display name for the file.")
    description: str | None = Field(default=None, description="New description for the file.")
