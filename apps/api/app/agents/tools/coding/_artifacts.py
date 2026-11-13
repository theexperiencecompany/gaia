"""The artifact card the coding tools put on their run when they write under artifacts/.

write, edit and bash all funnel through here so the card's shape lives in one place.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.tools.coding._context import safe_emit
from app.agents.workspace.paths import MountRole, detect_content_type, session_artifacts
from app.constants.chat import ARTIFACT_CARD
from app.services.artifact_events import upsert_event
from app.services.storage import ArtifactInfo


def publish_artifact(conv_id: str, rel: str, size_bytes: int, mtime: float) -> None:
    """Put one written file on the run as an artifact card; rel is relative to the session's artifacts/.

    The card rides the run's reply, so every device shows the file and fetches its body.
    """
    event = upsert_event(
        conv_id,
        ArtifactInfo(
            path=rel,
            size_bytes=size_bytes,
            mtime=mtime,
            content_type=detect_content_type(rel),
        ),
    )
    safe_emit({ARTIFACT_CARD: dict(event)})


@dataclass(frozen=True)
class WrittenFile:
    """A file a coding tool wrote: whose, the mount it landed in, and where."""

    user_id: str
    role: MountRole
    role_conv: str | None
    abs_path: str


def publish_artifact_write(written: WrittenFile, size_bytes: int, mtime: float) -> None:
    """Put the file's artifact card on the run when a write or edit lands under artifacts/."""
    role_conv, abs_path = written.role_conv, written.abs_path
    if written.role != MountRole.ARTIFACTS or not role_conv:
        return
    artifacts_root = session_artifacts(role_conv) + "/"
    rel = (
        abs_path[len(artifacts_root) :]
        if abs_path.startswith(artifacts_root)
        else abs_path.rsplit("/", 1)[-1]
    )
    publish_artifact(role_conv, rel, size_bytes, mtime)
