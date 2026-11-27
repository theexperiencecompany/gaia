"""Build the artifact card's payload: a file under a session's artifacts/ tree appeared, changed, or went away."""

from __future__ import annotations

from app.models.artifact_models import ArtifactFileEvent, ArtifactRemoveEvent
from app.services.storage import ArtifactInfo


def remove_event(session_id: str, path: str) -> ArtifactRemoveEvent:
    """Return the card payload for an artifacts/ file that no longer exists."""
    return ArtifactRemoveEvent(event="remove", session_id=session_id, path=path)


def upsert_event(
    session_id: str, info: ArtifactInfo, *, short_url: str | None = None
) -> ArtifactFileEvent:
    """Return the card payload for an artifacts/ file that was created or changed.

    short_url is the heygaia.link the writing tool attached; this builder never mints one.
    """
    return ArtifactFileEvent(
        event="upsert",
        session_id=session_id,
        path=info.path,
        size_bytes=info.size_bytes,
        mtime=info.mtime,
        content_type=info.content_type,
        short_url=short_url,
    )
