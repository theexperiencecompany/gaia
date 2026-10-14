"""The saved turn's tool_data, the way Mongo would hold it, for runs that write into it.

Doubles the three conversation_repository calls a turn's cards are saved through —
append, the positional read, and the array-filtered subagent-row extend — with the
same semantics, so what a reload would show is asserted on, not what was called.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from app.constants.chat import SUBAGENT_GROUP_TOOL_NAME
from app.models.chat_models import MessageModel, SavedSubagentGroup


class SavedToolData:
    """Per-message tool_data, appended to and extended in place like the real documents."""

    def __init__(self) -> None:
        self.by_message: dict[str, list[dict[str, Any]]] = {}
        #: Every append, in order: (message_id, entries).
        self.appends: list[tuple[str, list[dict[str, Any]]]] = []

    async def append_message_tool_data(
        self,
        conversation_id: str,
        *,
        user_id: str,
        message_id: str,
        entries: Sequence[Mapping[str, object]],
    ) -> bool:
        copied = [dict(entry) for entry in entries]
        self.appends.append((message_id, copied))
        self.by_message.setdefault(message_id, []).extend(copied)
        return True

    async def get_message(
        self, conversation_id: str, message_id: str, *, user_id: str
    ) -> MessageModel:
        return MessageModel(
            type="bot", response="", tool_data=list(self.by_message.get(message_id, []))
        )

    async def extend_subagent_group(
        self, conversation_id: str, *, user_id: str, message_id: str, group: SavedSubagentGroup
    ) -> bool:
        for entry in self.by_message.get(message_id, []):
            data = entry["data"]
            if (
                entry["tool_name"] == SUBAGENT_GROUP_TOOL_NAME
                and data["subagent_id"] == group.subagent_id
            ):
                entry["data"] = {
                    **data,
                    "tool_calls": [*data["tool_calls"], *group.tool_calls],
                    "completed_at": group.completed_at,
                    "duration_ms": group.duration_ms,
                }
                return True
        return False

    def entries(self) -> list[dict[str, Any]]:
        """Every saved entry across messages, in save order."""
        return [entry for entries in self.by_message.values() for entry in entries]
