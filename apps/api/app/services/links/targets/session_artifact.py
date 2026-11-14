"""A file GAIA wrote under a conversation's artifacts/, shared as the snapshot its link pinned.

The target id is conversation_id/path. The live file is read only to publish a
snapshot; opening the link reads the snapshot alone.
"""

import asyncio

from app.constants.short_links import MAX_SNAPSHOT_BYTES, MAX_VIEW_TEXT_BYTES
from app.models.short_link_models import (
    LinkSnapshot,
    PublicSessionArtifact,
    RenderMode,
    ShortLinkTargetType,
)
from app.services.links.content import (
    active_link_content,
    presented_render,
    read_snapshot,
    thumbnail_url,
)
from app.services.links.spec import LinkTargetSpec, PreviewFacts, SnapshotSource
from app.services.storage import JuiceFSUnavailable, resolve_session_path, stat_artifact
from app.utils.errors import AppError

_DEFAULT_CONTENT_TYPE = "application/octet-stream"


def session_artifact_target_id(conversation_id: str, path: str) -> str:
    """Return the target id of the file at path under one conversation's artifacts/.

    Conversation ids are path-safe (no /), so the first / is always the separator.
    """
    return f"{conversation_id}/{path}"


async def _source(owner_id: str, target_id: str) -> SnapshotSource | None:
    """Read the owner's file now; None once it is gone or the id names no artifact.

    Workspace storage being offline is an outage, not a missing file: a 503 the caller sees.
    """
    conversation_id, _, path = target_id.partition("/")
    if not conversation_id or not path:
        return None
    try:
        info = await stat_artifact(owner_id, conversation_id, path)
        if info is None:
            return None
        host_path = await resolve_session_path(owner_id, conversation_id, "artifacts", path)
    except ValueError:
        return None
    except JuiceFSUnavailable as e:
        raise AppError(
            message="Workspace storage is offline, so this file can't be shared right now",
            fix="Try again in a minute",
            status_code=503,
            code="workspace_storage_offline",
        ) from e
    data = (
        await asyncio.to_thread(host_path.read_bytes)
        if info.size_bytes <= MAX_SNAPSHOT_BYTES
        else None
    )
    return SnapshotSource(
        filename=host_path.name,
        declared_mime=info.content_type or _DEFAULT_CONTENT_TYPE,
        size_bytes=info.size_bytes,
        data=data,
    )


async def _text(owner_id: str, snapshot: LinkSnapshot) -> str | None:
    if snapshot.content_id is None or snapshot.size_bytes > MAX_VIEW_TEXT_BYTES:
        return None
    if presented_render(snapshot) is not RenderMode.TEXT:
        return None
    raw = await read_snapshot(owner_id, snapshot.content_id)
    return raw.decode(errors="replace")


async def _project(
    owner_id: str, _target_id: str, snapshot: LinkSnapshot | None
) -> PublicSessionArtifact | None:
    if snapshot is None:
        return None
    return PublicSessionArtifact(
        target_type=ShortLinkTargetType.SESSION_ARTIFACT,
        filename=snapshot.filename,
        content_type=snapshot.mime,
        size_bytes=snapshot.size_bytes,
        text=await _text(owner_id, snapshot),
    )


async def _preview(
    _owner_id: str, _target_id: str, snapshot: LinkSnapshot | None
) -> PreviewFacts | None:
    if snapshot is None:
        return None
    has_image = snapshot.content_id is not None and snapshot.has_thumbnail and active_link_content()
    return PreviewFacts(
        title=snapshot.filename,
        image_url=thumbnail_url(snapshot.content_id) if has_image and snapshot.content_id else None,
    )


SPEC = LinkTargetSpec(
    type=ShortLinkTargetType.SESSION_ARTIFACT,
    kind_line="A file GAIA made, shared with you.",
    project=_project,
    preview=_preview,
    source=_source,
)
