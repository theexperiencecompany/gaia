"""Shared real-time artifact publishing for the coding tools.

When a tool writes a file under a session's ``artifacts/`` tree, the chat UI
expects a live ``artifact_data`` event so the card updates during the turn
without polling. write, edit, and bash all funnel through here so the event
shape — the ``(event, path, size_bytes, mtime)`` dedup signature and the link
it carries — lives in exactly one place and can't drift between the three.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.agents.workspace.paths import (
    INLINE_ARTIFACT_MAX_BYTES,
    MountRole,
    detect_content_type,
    is_inlineable_content_type,
    session_artifacts,
)
from app.models.short_link_models import ShortLinkTargetType
from app.services.artifact_events import publish_artifact_event, upsert_event
from app.services.short_link_projections import session_artifact_target_id
from app.services.short_link_service import optional_short_link
from app.services.storage import ArtifactInfo


async def publish_artifact(
    user_id: str,
    conv_id: str,
    artifact: ArtifactInfo,
    inline_body: str | None,
    *,
    written_this_turn: bool,
) -> str | None:
    """Publish one artifact upsert event; return the heygaia.link it carries.

    Only a file the tool wrote this turn gets a link — the one the agent hands
    the user with it. A file merely re-listed (bash's enumeration of an
    unchanged artifact) publishes without one, so listing a workspace never
    shares it. None as well when the owner stopped sharing the file or the
    mint failed (``optional_short_link``). ``artifact.path`` is relative to the
    session's ``artifacts/`` root; ``artifact.mtime`` must be the real post-write
    value (the ``(event, path, size_bytes, mtime)`` dedup signature depends on it).
    The single owner of the event shape.
    """
    short_url = (
        await optional_short_link(
            user_id,
            ShortLinkTargetType.SESSION_ARTIFACT,
            session_artifact_target_id(conv_id, artifact.path),
        )
        if written_this_turn
        else None
    )
    event = upsert_event(conv_id, artifact, body=inline_body, short_url=short_url)
    await publish_artifact_event(user_id, event)
    return short_url


def artifact_links_note(links: Mapping[str, str]) -> str:
    """The tool-result footer that hands the agent each artifact's public link,
    so it shares a URL the user can open rather than a sandbox path."""
    if not links:
        return ""
    lines = "\n".join(f"- {name}: {url}" for name, url in links.items())
    return (
        "\n\nPublic link (anyone with it can open; give it to the user when "
        f"you hand the file over):\n{lines}"
    )


async def publish_artifact_write(
    user_id: str,
    role: MountRole,
    role_conv: str | None,
    abs_path: str,
    content: str,
    mtime: float,
) -> str | None:
    """Publish an artifact upsert when a write/edit lands under ``artifacts/``
    and return its heygaia.link.

    No-op (``None``) for non-artifact paths. The tool already holds the written ``content``
    as a string, so its UTF-8 size and inline body are derived here and the rest is
    delegated to :func:`publish_artifact`.
    """
    if role != MountRole.ARTIFACTS or not role_conv:
        return None
    artifacts_root = session_artifacts(role_conv) + "/"
    rel = (
        abs_path[len(artifacts_root) :]
        if abs_path.startswith(artifacts_root)
        else abs_path.rsplit("/", 1)[-1]
    )
    artifact = ArtifactInfo(
        path=rel,
        size_bytes=len(content.encode("utf-8")),
        mtime=mtime,
        content_type=detect_content_type(rel),
    )
    inline_body = (
        content
        if artifact.size_bytes <= INLINE_ARTIFACT_MAX_BYTES
        and is_inlineable_content_type(artifact.content_type)
        else None
    )
    return await publish_artifact(user_id, role_conv, artifact, inline_body, written_this_turn=True)
