"""The conversation artifact registry element, shared by the document model and
the registry service that owns its writes."""

from typing import NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict


class ArtifactRegistryEntry(TypedDict):
    """One element of ``ConversationDocument.artifacts``.

    The conversation document stores it and mirrors it verbatim to the client.
    ``mtime`` is a Unix timestamp, matching what every publisher in
    :mod:`app.services.artifact_events` stamps. ``body`` is present only for
    small textual artifacts inlined at write time.
    """

    path: str
    size_bytes: int | None
    mtime: float | None
    content_type: str | None
    updated_at: str
    body: NotRequired[str]


class ArtifactCard(BaseModel):
    """An artifact card's payload as a reader parses it, whichever event it carries."""

    model_config = ConfigDict(extra="ignore")

    event: str
    path: str
    content_type: str | None = None
    short_url: str | None = None
