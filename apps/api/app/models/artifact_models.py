"""The conversation artifact registry element, shared by the document model and
the registry service that owns its writes, and the artifact_data card's payloads."""

from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ResponseModel


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


class ArtifactFileEvent(ResponseModel):
    """An artifact_data card's payload when a file appeared or changed."""

    event: Literal["upsert"]
    session_id: str
    path: str
    size_bytes: int
    mtime: float
    content_type: str | None
    #: The file's heygaia.link, only when the tool that wrote it this turn attached one; absent otherwise.
    short_url: str | None = Field(default=None, exclude_if=lambda url: url is None)


class ArtifactRemoveEvent(ResponseModel):
    """An artifact_data card's payload when a file was deleted; a client drops its card."""

    event: Literal["remove"]
    session_id: str
    path: str


#: What an artifact_data card's data is, as its producers write it.
ArtifactEvent = Annotated[ArtifactFileEvent | ArtifactRemoveEvent, Field(discriminator="event")]


class ArtifactCard(BaseModel):
    """An artifact card's payload as a reader parses it, whichever event it carries.

    Lenient on purpose: stored history holds cards older producers wrote, such as upload events.
    """

    model_config = ConfigDict(extra="ignore")

    event: str
    path: str
    content_type: str | None = None
    short_url: str | None = None
