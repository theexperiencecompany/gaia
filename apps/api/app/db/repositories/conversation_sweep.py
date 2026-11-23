"""The heads the sweeper and the bot followers visit: unflushed entries, unsettled inputs or live work."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from bson import ObjectId
from pydantic import ConfigDict, Field

from app.db.repositories.conversation_entries import (
    OUTBOX_FIELD,
    STATE_FIELD,
    current_state,
    store_errors,
)
from app.db.repositories.conversation_log_reads import LogReadRepository
from app.models.conversation_log_models import ConversationState
from app.models.conversation_models import ConversationHead

#: A head the sweep must visit: unflushed entries, unsettled inputs or live work. A non-empty
#: outbox sorts after {}. Also the sweep index's partial filter, so only these heads are indexed.
SWEEP_DUE_FILTER: dict[str, object] = {
    "$or": [
        {OUTBOX_FIELD: {"$gt": {}}},
        {f"{STATE_FIELD}.unsettled_waking.0": {"$exists": True}},
        {f"{STATE_FIELD}.work.0": {"$exists": True}},
    ]
}
SWEEP_INDEX_NAME = "conversation_sweep_due_by_id"
_SWEEP_PROJECTION = {"_id": 1, "conversation_id": 1, "user_id": 1, OUTBOX_FIELD: 1, STATE_FIELD: 1}


@dataclass(frozen=True)
class SweepHead:
    """A step-run head as the sweeper reads it; cursor is its _id, where the next page starts."""

    cursor: str
    conversation_id: str
    user_id: str
    has_outbox: bool
    state: ConversationState


class ConversationSweepRepository(LogReadRepository):
    """The due-head scans over the sweep index, beside the log reads and flush a sweep finishes with."""

    async def list_heads_to_sweep(self, limit: int, after: str | None) -> list[SweepHead]:
        """Return up to limit heads with unflushed entries, unsettled inputs or live work, in _id order past after."""
        query = (
            SWEEP_DUE_FILTER
            if after is None
            else {"_id": {"$gt": ObjectId(after)}, **SWEEP_DUE_FILTER}
        )
        return await self._due_heads(query, limit)

    async def list_live_heads(self, source: str, limit: int) -> list[SweepHead]:
        """Return the source's heads with live work or unanswered inputs (an open reply has its inputs unsettled)."""
        heads = await self._due_heads({"source": source, **SWEEP_DUE_FILTER}, limit)
        return [head for head in heads if head.state.work or head.state.unsettled_waking]

    async def _due_heads(self, query: Mapping[str, object], limit: int) -> list[SweepHead]:
        """Read up to limit heads matching query along the sweep index, in _id order."""
        with store_errors("log sweep"):  # pragma: no mutate — error label
            # pragma: no mutate start — the projection, order and hint only shape how the index is read
            cursor = self._raw_collection().find(
                query, _SWEEP_PROJECTION, sort=[("_id", 1)], hint=SWEEP_INDEX_NAME
            )
            # pragma: no mutate end
            rows = [row async for row in cursor.limit(limit)]
        return [_sweep_head(row) for row in rows]


conversation_sweep_repository = ConversationSweepRepository()


class _SweepRow(ConversationHead):
    """A head as a sweep projects it, with the _id the next page resumes after."""

    model_config = ConfigDict(extra="allow", populate_by_name=True, arbitrary_types_allowed=True)

    id: ObjectId = Field(alias="_id")


def _sweep_head(raw: Mapping[str, object]) -> SweepHead:
    row = _SweepRow.model_validate(raw)
    return SweepHead(
        cursor=str(row.id),
        conversation_id=row.conversation_id,
        user_id=row.user_id,
        has_outbox=bool(row.outbox),
        state=current_state(row),
    )
