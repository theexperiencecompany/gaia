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
from app.services.storage import ArtifactInfo, ensure_safe_path_id

ARTIFACT_CHANNEL_PREFIX = "artifacts:"


class ArtifactFileEvent(TypedDict):
    """A file GAIA wrote appeared or changed in the session's artifacts/."""

    event: Literal["upsert"]
    session_id: str
    path: str
    size_bytes: int
    mtime: float
    content_type: str | None
    body: NotRequired[str]
    # The artifact's public heygaia.link, present only when the tool that wrote
    # the file this turn attached one. Watcher rescans never carry it; the
    # owner shares those from the file card.
    short_url: NotRequired[str]


class ArtifactRemoveEvent(TypedDict):
    event: Literal["remove"]
    session_id: str
    path: str


ArtifactEvent = ArtifactFileEvent | ArtifactRemoveEvent


class ArtifactEventMessage(TypedDict):
    """An ArtifactEvent as subscribers receive it, stamped with user_id and ts."""

    event: Literal["upsert", "remove"]
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


def upsert_event(
    session_id: str,
    info: ArtifactInfo,
    *,
    body: str | None = None,
    short_url: str | None = None,
) -> ArtifactFileEvent:
    """Return an artifacts/ file-created-or-changed event.

    body inlines small text files (callers enforce the inline rule); omitted
    for large or binary. short_url is the heygaia.link the writing tool
    attached; this builder never mints one.
    """
    payload: ArtifactFileEvent = {
        "event": "upsert",
        "session_id": session_id,
        "path": info.path,
        "size_bytes": info.size_bytes,
        "mtime": info.mtime,
        "content_type": info.content_type,
    }
    if body is not None:
        payload["body"] = body
    if short_url is not None:
        payload["short_url"] = short_url
    return payload


def remove_event(session_id: str, path: str) -> ArtifactRemoveEvent:
    """Return an artifacts/ file-removed-or-renamed event."""
    return {"event": "remove", "session_id": session_id, "path": path}


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
