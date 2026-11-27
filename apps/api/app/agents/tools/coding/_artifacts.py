"""The artifact card the coding tools put on their run when they write under artifacts/.

write, edit and bash all funnel through here so the card's shape, and the link it carries,
lives in one place.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.agents.tools.coding._context import safe_emit
from app.agents.workspace.paths import MountRole, detect_content_type, session_artifacts
from app.constants.chat import ARTIFACT_CARD
from app.models.short_link_models import ShortLinkTargetType, WorkspaceFileTarget
from app.models.tool_card_registry import tool_card
from app.services.artifact_events import upsert_event
from app.services.links.placeholders import LINK_NOTE, link_placeholder
from app.services.links.service import attach_link
from app.services.links.urls import build_url
from app.services.storage import ArtifactInfo


async def publish_artifact(
    user_id: str, conv_id: str, artifact: ArtifactInfo, *, written_this_turn: bool
) -> str | None:
    """Put one file on the run as an artifact card; return the placeholder for the link it carries.

    Only a file the tool wrote this turn gets a link, so bash re-listing an unchanged file
    never shares it; None as well when the owner stopped sharing it or the mint failed. The
    card gets the URL, the agent only the placeholder. artifact.path is relative to artifacts/.
    """
    link = (
        await attach_link(
            user_id,
            WorkspaceFileTarget(
                type=ShortLinkTargetType.WORKSPACE_FILE,
                conversation_id=conv_id,
                path=artifact.path,
            ),
        )
        if written_this_turn
        else None
    )
    short_url = build_url(link.slug) if link else None
    safe_emit(tool_card(ARTIFACT_CARD, upsert_event(conv_id, artifact, short_url=short_url)))
    return link_placeholder(link.target) if link else None


def artifact_links_note(links: Mapping[str, str]) -> str:
    """Return the tool-result footer handing the agent each written file's link placeholder."""
    if not links:
        return ""
    lines = "\n".join(f"- {name}: {placeholder}" for name, placeholder in links.items())
    return f"\n\n{LINK_NOTE} Links:\n{lines}"


@dataclass(frozen=True)
class WrittenFile:
    """A file a coding tool wrote: whose, the mount it landed in, and where."""

    user_id: str
    role: MountRole
    role_conv: str | None
    abs_path: str


async def publish_artifact_write(written: WrittenFile, size_bytes: int, mtime: float) -> str | None:
    """Card a write or edit that lands under artifacts/ on the run; return its link placeholder."""
    role_conv, abs_path = written.role_conv, written.abs_path
    if written.role != MountRole.ARTIFACTS or not role_conv:
        return None
    artifacts_root = session_artifacts(role_conv) + "/"
    rel = (
        abs_path[len(artifacts_root) :]
        if abs_path.startswith(artifacts_root)
        else abs_path.rsplit("/", 1)[-1]
    )
    artifact = ArtifactInfo(
        path=rel, size_bytes=size_bytes, mtime=mtime, content_type=detect_content_type(rel)
    )
    return await publish_artifact(written.user_id, role_conv, artifact, written_this_turn=True)
