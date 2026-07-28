"""Pydantic schemas for file metadata operations."""

from pydantic import BaseModel, Field


class UpdateFileRequest(BaseModel):
    """Editable file metadata fields. Only these may be updated by the client."""

    filename: str | None = Field(default=None, description="New display name for the file.")
    description: str | None = Field(default=None, description="New description for the file.")


class FileDeletedResponse(BaseModel):
    """Result of removing a file from Mongo, Cloudinary, and the vector index."""

    message: str = Field(description="Human-readable outcome.")
    file_id: str = Field(description="Business id of the deleted file.")
    filename: str = Field(description="Name the deleted file was stored under.")
