"""The briefings collection's indexes against real Mongo: one payload per user, date and kind."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pymongo.errors import DuplicateKeyError, OperationFailure
import pytest

from app.constants import briefing as briefing_constants
from app.db.mongodb import indexes

_LEGACY = "user_id_1_created_at_-1"


@pytest.fixture(autouse=True)
def _briefings_collection(raw_collection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(indexes, "get_async_collection", lambda name: raw_collection)


async def _index_names(collection) -> set[str]:
    return {index["name"] async for index in collection.list_indexes()}


async def test_the_unique_user_date_kind_index_is_made_and_the_legacy_write_time_one_dropped(
    raw_collection,
) -> None:
    await raw_collection.create_index([("user_id", 1), ("created_at", -1)])

    await indexes.create_briefing_indexes()

    names = await _index_names(raw_collection)
    assert "user_date_kind_unique" in names
    assert _LEGACY not in names


async def test_a_second_run_finds_the_legacy_index_gone_and_carries_on(raw_collection) -> None:
    await indexes.create_briefing_indexes()

    await indexes.create_briefing_indexes()

    assert "user_date_kind_unique" in await _index_names(raw_collection)


async def test_a_user_has_one_brief_per_date_and_kind(raw_collection) -> None:
    await indexes.create_briefing_indexes()
    brief = {"user_id": "u1", "date": "2026-11-11", "kind": "daily"}
    await raw_collection.insert_one(dict(brief))

    with pytest.raises(DuplicateKeyError):
        await raw_collection.insert_one(dict(brief))
    await raw_collection.insert_one({**brief, "kind": "weekly"})


async def test_dropping_the_legacy_index_failing_for_another_reason_is_not_swallowed(
    raw_collection, monkeypatch: pytest.MonkeyPatch
) -> None:
    refused = AsyncMock(side_effect=OperationFailure("not allowed", code=13))
    monkeypatch.setattr(raw_collection, "drop_index", refused)

    with pytest.raises(OperationFailure):
        await indexes.create_briefing_indexes()


async def _ttl_of(collection, key: str) -> int | None:
    async for index in collection.list_indexes():
        if list(index["key"]) == [key] and "expireAfterSeconds" in index:
            return int(index["expireAfterSeconds"])
    return None


@pytest.mark.regression
async def test_a_brief_is_kept_for_its_stated_retention_then_expires(raw_collection) -> None:
    await indexes.create_briefing_indexes()

    assert (
        await _ttl_of(raw_collection, "created_at") == briefing_constants.BRIEFING_RETENTION_SECONDS
    )


@pytest.mark.regression
async def test_a_held_result_left_behind_expires_after_its_retention(raw_collection) -> None:
    await indexes.create_pending_brief_item_indexes()

    retention = briefing_constants.PENDING_BRIEF_ITEM_RETENTION_SECONDS
    assert await _ttl_of(raw_collection, "created_at") == retention
