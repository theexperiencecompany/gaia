from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument


class DocumentPageModel(BaseModel):
    """One extracted page: its 1-based number and its text."""

    page_number: int = Field(
        ...,
        gt=0,
    )
    content: str = Field(...)
    # Other metadata fields can be added here


class DocumentSummaryModel(BaseModel):
    """A page's extracted content paired with its summary."""

    data: DocumentPageModel
    summary: str = Field(
        ...,
        max_length=100000,
    )


# A page-wise summary is stored either as one summary (str/dict) or a list of
# per-page summary dicts (``DocumentSummaryModel`` serialised to JSON).
PageWiseSummary = list[dict[str, Any]] | dict[str, Any] | str | None


class FileDocument(UserScopedDocument):
    """An uploaded file's metadata as stored in the ``files`` collection.

    User-scoped and addressed by the business ``file_id`` (a UUID); the Mongo
    ``_id`` (ObjectId) rides along as ``id`` because the update endpoint still
    returns it. ``updated_at`` is stamped by the base on every write.
    """

    file_id: str
    filename: str
    type: str
    size: int
    url: str
    public_id: str | None = None
    description: str | None = None
    page_wise_summary: PageWiseSummary = None
    sandbox_path: str | None = None
    conversation_id: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class FileMimetypeRow(BaseModel):
    """One file row's mimetype fields, readable even when the row is legacy.

    The migration needs rows that ``FileDocument`` rejects (no ``type``), so
    this carries both field names without requiring either.
    """

    file_id: str
    filename: str
    type: str | None = None
    content_type: str | None = None


class FileUpdate(BaseModel):
    """Editable file-metadata fields (server-controlled, never the raw payload)."""

    model_config = ConfigDict(extra="forbid")

    filename: str | None = None
    description: str | None = None
    page_wise_summary: PageWiseSummary = None
    # Server-set only: stamped when an upload is attached to the conversation
    # that adopted it. Never accepted from a client update payload.
    conversation_id: str | None = None
    # Server-set only: the /workspace path the bytes were mirrored to. Written
    # by the attach path so the agent reads the real file, never a guess.
    sandbox_path: str | None = None
