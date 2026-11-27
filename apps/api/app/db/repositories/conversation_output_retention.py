"""The retention sweep's reads and writes of conversation_entries: old entries whose tool outputs are still stored."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import bson
from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymongo import UpdateOne

from app.constants.chat import CONVERSATION_ENTRIES_COLLECTION
from app.db.repositories.conversation_entries import (
    OUTPUTS_DROPPED_FIELD,
    REVISION_FIELD,
    store_errors,
)
from app.db.repositories.conversations import ConversationRepository

#: An entry with tool cards, the partial filter of the sweep's index and a clause of its query.
HOLDS_CARDS: dict[str, object] = {"tool_data.0": {"$exists": True}}
OUTPUTS_TO_DROP_INDEX = "entry_outputs_to_drop"
_UNSWEPT: dict[str, object] = {OUTPUTS_DROPPED_FIELD: {"$exists": False}}


class EntryCards(BaseModel):
    """An entry's tool cards as stored, with the _id and revision its rewrite is conditional on."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(alias="_id")
    revision: int | None = None
    # Raw on purpose: a typed read would drop a card's undeclared keys from what is written back.
    tool_data: list[dict[str, object]]

    @field_validator("id", mode="before")
    @classmethod
    def _id_text(cls, value: object) -> object:
        return str(value) if isinstance(value, ObjectId) else value

    @property
    def stored_bytes(self) -> int:
        """Return the BSON size of the entry's cards."""
        return len(bson.encode({"tool_data": self.tool_data}))


class ToolOutputRetentionRepository(ConversationRepository):
    """Finds the entries older than a cutoff the sweep has not cut, and writes their cut cards back."""

    async def list_unswept(self, at_before: datetime, limit: int) -> list[EntryCards]:
        """Return up to limit entries committed before at_before whose cards the sweep has not cut, oldest first."""
        entries = self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
        unswept = {**HOLDS_CARDS, **_UNSWEPT, "at": {"$lt": at_before}}
        with store_errors("output retention read"):  # pragma: no mutate — error label
            # pragma: no mutate start — the projection, order and hint only shape how the index is read
            cursor = entries.find(
                unswept,
                {"_id": 1, REVISION_FIELD: 1, "tool_data": 1},
                sort=[("at", 1)],
                hint=OUTPUTS_TO_DROP_INDEX,
            )
            # pragma: no mutate end
            rows = [row async for row in cursor.limit(limit)]
        return [EntryCards.model_validate(row) for row in rows]

    async def store_cut(self, cut: Sequence[EntryCards]) -> int:
        """Write each entry's cut cards and mark it swept, unless it changed since it was read; return how many landed.

        Neither revision nor the head's updatedAt moves: no client is told to refetch.
        """
        writes = [
            UpdateOne(
                {"_id": ObjectId(entry.id), REVISION_FIELD: entry.revision, **_UNSWEPT},
                {"$set": {"tool_data": entry.tool_data, OUTPUTS_DROPPED_FIELD: True}},
            )
            for entry in cut
        ]
        entries = self._sibling_collection(CONVERSATION_ENTRIES_COLLECTION)
        with store_errors("output retention write"):  # pragma: no mutate — error label
            # conditional updates that miss are no errors, so the order of the batch changes nothing
            result = await entries.bulk_write(writes, ordered=False)  # pragma: no mutate
        return result.matched_count


tool_output_retention_repository = ToolOutputRetentionRepository()
