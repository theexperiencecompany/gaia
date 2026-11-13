"""The artifact card's payload: a file a coding tool wrote under a session's artifacts/ tree."""

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
