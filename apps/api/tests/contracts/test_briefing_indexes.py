"""The briefings collection's indexes against real Mongo: one payload per user, date and kind."""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError
import pytest

from app.constants import briefing as briefing_constants
from app.db.mongodb import indexes


@pytest.fixture(autouse=True)
def _briefings_collection(raw_collection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(indexes, "get_async_collection", lambda name: raw_collection)


async def _index_names(collection) -> set[str]:
    return {index["name"] async for index in collection.list_indexes()}


async def test_a_user_has_one_brief_per_date_and_kind(raw_collection) -> None:
    await indexes.create_briefing_indexes()
    brief = {"user_id": "u1", "date": "2026-11-11", "kind": "daily"}
    await raw_collection.insert_one(dict(brief))

    with pytest.raises(DuplicateKeyError):
        await raw_collection.insert_one(dict(brief))
    await raw_collection.insert_one({**brief, "kind": "weekly"})


async def _ttl_of(collection, key: str) -> int | None:
    async for index in collection.list_indexes():
        if list(index["key"]) == [key] and "expireAfterSeconds" in index:
            return int(index["expireAfterSeconds"])
    return None


async def test_a_briefs_age_index_carries_no_ttl_so_the_sweep_deletes_its_image_too(
    raw_collection,
) -> None:
    await indexes.create_briefing_indexes()

    assert await _ttl_of(raw_collection, "created_at") is None
    assert "created_at_1" in await _index_names(raw_collection)


async def test_a_held_result_left_behind_expires_after_its_retention(raw_collection) -> None:
    await indexes.create_pending_brief_item_indexes()

    retention = briefing_constants.PENDING_BRIEF_ITEM_RETENTION_SECONDS
    assert await _ttl_of(raw_collection, "created_at") == retention
