"""Artifact event wire contract.

Single source of truth for the Redis channel + payload shape shared by the
three sites that touch it: the per-sandbox ArtifactWatcher (publisher), the
upload pipeline (publisher), and the chat stream (subscriber/forwarder).

Keeping this here — depending only on storage + redis, never on the sandbox
package — keeps `chat_service`/`file_service` from reaching into watcher
internals just to learn the channel name.
"""

from __future__ import annotations

import contextlib
import json
import time
from typing import Any

from app.db.redis import redis_cache
from app.services.storage import ArtifactInfo, ensure_safe_path_id

ARTIFACT_CHANNEL_PREFIX = "artifacts:"


def artifact_channel(user_id: str) -> str:
    """Per-user pub/sub channel name.

    ``ensure_safe_path_id`` belt-and-suspenders behind the auth layer: today
    ``user_id`` comes only from authenticated context (WorkOS-issued opaque
    string), but any future identity source that returns a value containing
    ``:`` or a wildcard would otherwise be able to alias another user's
    channel. Raises ``ValueError`` on a malformed id — callers treat that
    the same as a missing Redis (event delivery is a latency optimization;
    the listing endpoint is the authoritative recovery path).
    """
    ensure_safe_path_id(user_id, label="user_id")
    return f"{ARTIFACT_CHANNEL_PREFIX}{user_id}"


def upsert_event(session_id: str, info: ArtifactInfo, *, body: str | None = None) -> dict[str, Any]:
    """An `artifacts/` file was created or changed.

    `body` is the UTF-8 file contents inlined for small textual artifacts —
    callers must enforce the size/type rule (see paths.is_inlineable_content_type
    and INLINE_ARTIFACT_MAX_BYTES). When present, the side panel renders
    instantly without a follow-up fetch and the value survives a reload via
    the persisted conversation. Omitted for large or binary files.
    """
    payload: dict[str, Any] = {
        "event": "upsert",
        "session_id": session_id,
        "path": info.path,
        "size_bytes": info.size_bytes,
        "mtime": info.mtime,
        "content_type": info.content_type,
    }
    if body is not None:
        payload["body"] = body
    return payload


def remove_event(session_id: str, path: str) -> dict[str, Any]:
    """A `artifacts/` file was removed or renamed away."""
    return {"event": "remove", "session_id": session_id, "path": path}


def upload_event(
    session_id: str,
    path: str,
    *,
    size_bytes: int,
    content_type: str | None,
    mtime: float | None = None,
) -> dict[str, Any]:
    """A user upload landed in `user-uploaded/` (host-side, cross-mount)."""
    return {
        "event": "upload",
        "session_id": session_id,
        "path": path,
        "size_bytes": size_bytes,
        "mtime": mtime if mtime is not None else time.time(),
        "content_type": content_type,
    }


async def publish_artifact_event(user_id: str, payload: dict[str, Any]) -> None:
    """Stamp user_id + ts and publish to `artifacts:{user_id}`.

    No-ops if Redis is unavailable and never raises — artifact delivery is a
    latency optimization; the `GET /sessions/{conv}/artifacts` endpoint is the
    authoritative recovery path.
    """
    if redis_cache.redis is None:
        return
    enriched = {**payload, "user_id": user_id, "ts": time.time()}
    with contextlib.suppress(Exception):
        await redis_cache.redis.publish(artifact_channel(user_id), json.dumps(enriched))
