"""The conversation artifact registry element, shared by the document model and
the registry service that owns its writes."""

from typing import NotRequired, TypedDict


class ArtifactRegistryEntry(TypedDict):
    """One element of ``ConversationDocument.artifacts``.

    ``app.services.chat.artifacts_registry`` owns every write of this shape; the
    conversation document stores it and mirrors it verbatim to the client.
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
