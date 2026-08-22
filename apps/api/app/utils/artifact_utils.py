"""Builders for the ``artifact_data`` chunks streamed and persisted per turn."""

from datetime import UTC, datetime
from typing import Any, TypedDict

from app.config.settings import settings
from app.constants.artifacts import ARTIFACT_URL_PATH_TEMPLATE


class ArtifactDataEntry(TypedDict):
    """One ``artifact_data`` tool_data entry — streamed live and/or persisted.

    ``data`` stays ``dict[str, Any]``: the live variant carries the watcher's raw
    artifact payload, whose keys are the sandbox's to define (see the module
    docstring of ``app/services/chat/artifact_forwarder.py``).
    """

    tool_name: str
    data: dict[str, Any]
    timestamp: str
    tool_category: str


def artifact_url_base(conversation_id: str) -> str:
    """Public backend URL base under which this conversation's artifacts are served.

    A file written to ``artifacts/<name>`` is fetchable at ``<base>/<name>``.
    Single source of truth for the save-time relative→absolute rewrite and the
    agent-facing session banner.
    """
    return f"{settings.HOST}{ARTIFACT_URL_PATH_TEMPLATE.format(conversation_id=conversation_id)}"


def build_artifact_full_entry(payload: dict[str, Any]) -> ArtifactDataEntry:
    """A live-stream ``artifact_data`` chunk carrying the file's full data."""
    return {
        "tool_name": "artifact_data",
        "data": payload,
        "timestamp": datetime.now(UTC).isoformat(),
        "tool_category": "artifact",
    }


def build_artifact_ref_entry(
    conversation_id: str, path: str, event: str | None
) -> ArtifactDataEntry:
    """A lightweight ``artifact_data`` reference for a persisted message.

    Full artifact data lives in the conversation registry; the message stores
    only the fields the frontend needs to resolve it back to a card.
    """
    return {
        "tool_name": "artifact_data",
        "data": {"session_id": conversation_id, "path": path, "event": event},
        "timestamp": datetime.now(UTC).isoformat(),
        "tool_category": "artifact",
    }
