"""Artifact event wire contract.

Single source of truth for the Redis channel + payload shape shared by the
three sites that touch it: the per-sandbox ArtifactWatcher (publisher), the
upload pipeline (publisher), and the chat stream (subscriber/forwarder).

Keeping this here — depending only on storage + redis, never on the sandbox
package — keeps chat_service/file_service from reaching into watcher
internals just to learn the channel name.
"""

from __future__ import annotations

import contextlib
import json
import time
from typing import Literal, NotRequired, TypedDict

from app.db.redis import redis_cache
from app.models.short_link_models import ShortLinkTargetType
from app.services.short_link_projections import session_artifact_target_id
from app.services.short_link_service import get_or_create_short_link
from app.services.storage import ArtifactInfo, ensure_safe_path_id

ARTIFACT_CHANNEL_PREFIX = "artifacts:"


class ArtifactFileEvent(TypedDict):
    """A file appeared or changed — upsert from the sandbox, upload host-side."""

    event: Literal["upsert", "upload"]
    session_id: str
    path: str
    size_bytes: int
    mtime: float
    content_type: str | None
    body: NotRequired[str]
    # The artifact's public heygaia.link. Agent-produced files (`upsert`) always
    # carry it; user uploads never do — they are the user's own files.
    short_url: NotRequired[str]


class ArtifactRemoveEvent(TypedDict):
    event: Literal["remove"]
    session_id: str
    path: str


ArtifactEvent = ArtifactFileEvent | ArtifactRemoveEvent


class ArtifactEventMessage(TypedDict):
    """An ArtifactEvent as subscribers receive it, stamped with user_id and ts."""

    event: Literal["upsert", "upload", "remove"]
    session_id: str
    path: str
    user_id: str
    ts: float
    size_bytes: NotRequired[int]
    mtime: NotRequired[float]
    content_type: NotRequired[str | None]
    body: NotRequired[str]
    short_url: NotRequired[str]


def artifact_channel(user_id: str) -> str:
    """Return the per-user pub/sub channel name.

    ensure_safe_path_id guards against a future identity source injecting ':'
    or a wildcard to alias another user's channel. Raises ValueError on a bad
    id, treated like a missing Redis — delivery here is a latency
    optimization; the listing endpoint is the authoritative recovery path.
    """
    ensure_safe_path_id(user_id, label="user_id")
    return f"{ARTIFACT_CHANNEL_PREFIX}{user_id}"


async def upsert_event(
    user_id: str, session_id: str, info: ArtifactInfo, *, body: str | None = None
) -> ArtifactFileEvent:
    """Return an artifacts/ file-created-or-changed event carrying the file's heygaia.link.

    Every agent-produced file passes through here, so the chat card, bot message
    and tool result all read one idempotently minted URL. body inlines small
    text files (callers enforce the inline rule); omitted for large or binary.
    """
    payload: ArtifactFileEvent = {
        "event": "upsert",
        "session_id": session_id,
        "path": info.path,
        "size_bytes": info.size_bytes,
        "mtime": info.mtime,
        "content_type": info.content_type,
        "short_url": await get_or_create_short_link(
            user_id,
            ShortLinkTargetType.SESSION_ARTIFACT,
            session_artifact_target_id(session_id, info.path),
        ),
    }
    if body is not None:
        payload["body"] = body
    return payload


def remove_event(session_id: str, path: str) -> ArtifactRemoveEvent:
    """Return an artifacts/ file-removed-or-renamed event."""
    return {"event": "remove", "session_id": session_id, "path": path}


def upload_event(
    session_id: str,
    path: str,
    *,
    size_bytes: int,
    content_type: str | None,
    mtime: float | None = None,
) -> ArtifactFileEvent:
    """Return a user-upload-landed event, for uploads written host-side into user-uploaded/ (cross-mount)."""
    return {
        "event": "upload",
        "session_id": session_id,
        "path": path,
        "size_bytes": size_bytes,
        "mtime": mtime if mtime is not None else time.time(),
        "content_type": content_type,
    }


async def publish_artifact_event(user_id: str, payload: ArtifactEvent) -> None:
    """Stamp user_id + ts and publish to artifacts:{user_id}.

    No-ops if Redis is unavailable and never raises — artifact delivery is a
    latency optimization; the GET /sessions/{conv}/artifacts endpoint is the
    authoritative recovery path.
    """
    if redis_cache.redis is None:
        return
    enriched = {**payload, "user_id": user_id, "ts": time.time()}
    with contextlib.suppress(Exception):
        await redis_cache.redis.publish(artifact_channel(user_id), json.dumps(enriched))
