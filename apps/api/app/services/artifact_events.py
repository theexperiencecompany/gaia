"""The artifact card's payload: a file under a session's artifacts/ tree appeared, changed, or went away."""

from __future__ import annotations

from typing import Literal, TypedDict

from app.services.storage import ArtifactInfo


class ArtifactFileEvent(TypedDict):
    """A file appeared or changed."""

    event: Literal["upsert"]
    session_id: str
    path: str
    size_bytes: int
    mtime: float
    content_type: str | None


class ArtifactRemoveEvent(TypedDict):
    """A file was deleted; a client drops its card."""

    event: Literal["remove"]
    session_id: str
    path: str


def remove_event(session_id: str, path: str) -> ArtifactRemoveEvent:
    """Return the card payload for an artifacts/ file that no longer exists."""
    return {"event": "remove", "session_id": session_id, "path": path}


def upsert_event(session_id: str, info: ArtifactInfo) -> ArtifactFileEvent:
    """Return the card payload for an artifacts/ file that was created or changed."""
    return {
        "event": "upsert",
        "session_id": session_id,
        "path": info.path,
        "size_bytes": info.size_bytes,
        "mtime": info.mtime,
        "content_type": info.content_type,
    }
