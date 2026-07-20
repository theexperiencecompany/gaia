from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument


class NoteModel(BaseModel):
    content: str = Field(
        ...,
        max_length=100000,
    )

    plaintext: str = Field(
        ...,
        max_length=100000,
    )


class NoteResponse(BaseModel):
    id: str
    content: str
    plaintext: str
    auto_created: bool = False
    user_id: str | None = None
    title: str | None = None
    description: str | None = None


class NoteDocument(UserScopedDocument):
    """A note as stored in MongoDB. Base stamps created_at/updated_at on write."""

    content: str
    plaintext: str
    auto_created: bool = False
    title: str | None = None
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NoteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = None
    plaintext: str | None = None


class NoteSearchHit(BaseModel):
    """A note matched by a plaintext search (the id is the stringified ``_id``)."""

    id: str
    note_id: str | None = None
    plaintext: str
