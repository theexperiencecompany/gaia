"""The artifact card's payload: a file under a session's artifacts/ tree appeared, changed, or went away."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from app.services.storage import ArtifactInfo


class ArtifactFileEvent(TypedDict):
    """A file appeared or changed."""

    event: Literal["upsert"]
    session_id: str
    path: str
    size_bytes: int
    mtime: float
    content_type: str | None
    # The file's heygaia.link, present only when the tool that wrote it this turn
    # attached one; a reconcile card never carries it.
    short_url: NotRequired[str]


class ArtifactRemoveEvent(TypedDict):
    """A file was deleted; a client drops its card."""

    event: Literal["remove"]
    session_id: str
    path: str


def remove_event(session_id: str, path: str) -> ArtifactRemoveEvent:
    """Return the card payload for an artifacts/ file that no longer exists."""
    return {"event": "remove", "session_id": session_id, "path": path}


def upsert_event(
    session_id: str, info: ArtifactInfo, *, short_url: str | None = None
) -> ArtifactFileEvent:
    """Return the card payload for an artifacts/ file that was created or changed.

    short_url is the heygaia.link the writing tool attached; this builder never mints one.
    """
    payload: ArtifactFileEvent = {
        "event": "upsert",
        "session_id": session_id,
        "path": info.path,
        "size_bytes": info.size_bytes,
        "mtime": info.mtime,
        "content_type": info.content_type,
    }
    if short_url is not None:
        payload["short_url"] = short_url
    return payload
