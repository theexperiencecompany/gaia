"""The conversation entries' indexes against real Mongo: a superseded index is dropped on boot."""

from __future__ import annotations

import pytest

from app.constants.chat import CONVERSATION_ENTRIES_COLLECTION
from app.db.mongodb import indexes


@pytest.fixture(autouse=True)
def _conversation_collections(raw_collection, entries_collection, monkeypatch: pytest.MonkeyPatch):
    def accessor(name: str):
        return entries_collection if name == CONVERSATION_ENTRIES_COLLECTION else raw_collection

    monkeypatch.setattr(indexes, "get_async_collection", accessor)


async def _index_names(collection) -> set[str]:
    return {index["name"] async for index in collection.list_indexes()}


async def test_boot_drops_the_user_kind_index_an_older_release_created(entries_collection) -> None:
    await entries_collection.create_index(
        [("user_id", 1), ("kind", 1)], name=indexes.SUPERSEDED_ENTRY_KIND_INDEX
    )

    await indexes.create_conversation_indexes()

    names = await _index_names(entries_collection)
    assert indexes.SUPERSEDED_ENTRY_KIND_INDEX not in names
    assert "user_entry_kind_at" in names


async def test_boot_without_the_old_index_succeeds(entries_collection) -> None:
    await indexes.create_conversation_indexes()
    await indexes.create_conversation_indexes()

    assert indexes.SUPERSEDED_ENTRY_KIND_INDEX not in await _index_names(entries_collection)
