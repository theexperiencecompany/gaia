"""Shared real-time artifact publishing for the coding tools.

When a tool writes a file under a session's ``artifacts/`` tree, the chat UI
expects a live ``artifact_data`` event so the card updates during the turn
without polling. write, edit, and bash all funnel through here so the event
shape — the ``(event, path, size_bytes, mtime)`` dedup signature, content-type
derivation, and ``ArtifactInfo`` construction — lives in exactly one place and
can't drift between the three.
"""

from __future__ import annotations

import contextlib

from app.agents.workspace.paths import (
    INLINE_ARTIFACT_MAX_BYTES,
    MountRole,
    detect_content_type,
    is_inlineable_content_type,
    session_artifacts,
)
from app.services.artifact_events import publish_artifact_event, upsert_event
from app.services.storage import ArtifactInfo


async def publish_artifact(
    user_id: str,
    conv_id: str,
    rel: str,
    size_bytes: int,
    mtime: float,
    inline_body: str | None,
) -> None:
    """Publish one artifact upsert event. Best-effort; never raises into a tool.

    ``rel`` is the path relative to the session's ``artifacts/`` root; ``mtime``
    must be the real post-write value (the ``(event, path, size_bytes, mtime)``
    dedup signature depends on it). The single owner of the event shape.
    """
    with contextlib.suppress(Exception):
        await publish_artifact_event(
            user_id,
            upsert_event(
                conv_id,
                ArtifactInfo(
                    path=rel,
                    size_bytes=size_bytes,
                    mtime=mtime,
                    content_type=detect_content_type(rel),
                ),
                body=inline_body,
            ),
        )


async def publish_artifact_write(
    user_id: str,
    role: MountRole,
    role_conv: str | None,
    abs_path: str,
    content: str,
    size_bytes: int,
    mtime: float,
) -> None:
    """Publish an artifact upsert when a write/edit lands under ``artifacts/``.

    No-op for non-artifact paths. The tool already holds the written ``content``
    as a string, so the inline body is decided here and the rest is delegated to
    :func:`publish_artifact`.
    """
    if role != MountRole.ARTIFACTS or not role_conv:
        return
    artifacts_root = session_artifacts(role_conv) + "/"
    rel = (
        abs_path[len(artifacts_root) :]
        if abs_path.startswith(artifacts_root)
        else abs_path.rsplit("/", 1)[-1]
    )
    inline_body = (
        content
        if size_bytes <= INLINE_ARTIFACT_MAX_BYTES
        and is_inlineable_content_type(detect_content_type(rel))
        else None
    )
    await publish_artifact(user_id, role_conv, rel, size_bytes, mtime, inline_body)
