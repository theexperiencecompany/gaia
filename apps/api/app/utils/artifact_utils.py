"""Builders for the ``artifact_data`` chunks streamed and persisted per turn."""

from datetime import UTC, datetime
from typing import Any


def build_artifact_full_entry(payload: dict[str, Any]) -> dict[str, Any]:
    """A live-stream ``artifact_data`` chunk carrying the file's full data."""
    return {
        "tool_name": "artifact_data",
        "data": payload,
        "timestamp": datetime.now(UTC).isoformat(),
        "tool_category": "artifact",
    }


def build_artifact_ref_entry(conversation_id: str, path: str, event: str | None) -> dict[str, Any]:
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
