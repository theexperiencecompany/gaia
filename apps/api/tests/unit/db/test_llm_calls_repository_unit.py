"""The backfill's write path, at unit level.

The behavioural proof that a re-run creates nothing lives in the contract suite
against real Mongo. This pins the operations the repository actually builds —
the parts a fake Mongo cannot show and a real one only shows indirectly: that
the match is on the deterministic key, that it is ``$setOnInsert`` (so an
existing row is never rewritten), and that one bad row cannot abort the batch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.db.repositories.llm_calls import LLMCallDocument, LLMCallsRepository


def _doc(key: str, **overrides: object) -> LLMCallDocument:
    fields: dict[str, object] = {
        "created_at": datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        "agent_name": "comms_agent",
        "background": False,
        "charge_to_budget": True,
        "model_requested": "deepseek/deepseek-v4-flash",
        "cost_source": "table",
        "backfilled": True,
        "backfill_key": key,
    }
    fields.update(overrides)
    return LLMCallDocument.model_validate(fields)


def _collection(upserted: int = 2) -> MagicMock:
    collection = MagicMock()
    collection.bulk_write = AsyncMock(return_value=MagicMock(upserted_count=upserted))
    return collection


async def test_each_row_is_matched_on_its_own_deterministic_key() -> None:
    """Matching on anything else — an ObjectId, an insert order — would make a
    re-run duplicate rather than recognise what it already wrote."""
    collection = _collection()
    repo = LLMCallsRepository()

    with patch.object(repo, "_raw_collection", return_value=collection):
        await repo.insert_backfilled([_doc("key-a"), _doc("key-b")])

    operations = collection.bulk_write.await_args.args[0]
    assert [op._filter for op in operations] == [
        {"backfill_key": "key-a"},
        {"backfill_key": "key-b"},
    ]


async def test_an_existing_row_is_never_rewritten() -> None:
    """``$setOnInsert``, not ``$set``: a row already in the ledger is history,
    and a re-run must not restate it with today's re-derived numbers."""
    collection = _collection()
    repo = LLMCallsRepository()

    with patch.object(repo, "_raw_collection", return_value=collection):
        await repo.insert_backfilled([_doc("key-a")])

    operation = collection.bulk_write.await_args.args[0][0]
    assert set(operation._doc) == {"$setOnInsert"}
    assert operation._upsert is True


async def test_one_duplicate_cannot_abort_the_rest_of_the_batch() -> None:
    """A backfill batch is thousands of rows and some will already exist.
    Ordered writes would stop at the first and silently drop the remainder."""
    collection = _collection()
    repo = LLMCallsRepository()

    with patch.object(repo, "_raw_collection", return_value=collection):
        await repo.insert_backfilled([_doc("key-a")])

    assert collection.bulk_write.await_args.kwargs["ordered"] is False


async def test_the_count_returned_is_what_was_actually_created() -> None:
    """The number the script reports as written. Returning the batch size would
    claim a re-run created rows it recognised and skipped."""
    collection = _collection(upserted=1)
    repo = LLMCallsRepository()

    with patch.object(repo, "_raw_collection", return_value=collection):
        created = await repo.insert_backfilled([_doc("key-a"), _doc("key-b")])

    assert created == 1


async def test_an_empty_batch_does_not_reach_mongo() -> None:
    """The last day of a window is often empty; a bulk_write with no operations
    raises rather than no-opping."""
    collection = _collection()
    repo = LLMCallsRepository()

    with patch.object(repo, "_raw_collection", return_value=collection):
        created = await repo.insert_backfilled([])

    assert created == 0
    collection.bulk_write.assert_not_awaited()


async def test_the_stored_row_keeps_its_own_creation_time() -> None:
    """``created_at`` is when the CALL happened, not when the backfill ran — it
    is the TTL key and the time axis of every ledger query."""
    collection = _collection()
    repo = LLMCallsRepository()

    with patch.object(repo, "_raw_collection", return_value=collection):
        await repo.insert_backfilled([_doc("key-a")])

    stored = collection.bulk_write.await_args.args[0][0]._doc["$setOnInsert"]
    assert stored["created_at"] == datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    assert stored["backfilled"] is True
    # The placeholder id mirrors Mongo's own _id and must not be written as a
    # field; unset optionals are omitted, not stored as null, so the sparse
    # indexes cover only the rows that really carry those values.
    assert "id" not in stored
    assert "workflow_execution_id" not in stored
    assert "job_id" not in stored
