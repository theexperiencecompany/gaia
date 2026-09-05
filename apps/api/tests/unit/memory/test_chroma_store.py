"""Unit tests for app.memory.chroma_store — per-conversation chunk deletion.

The Chroma collection is mocked at the ``_get_collection`` seam; the id-prefix
selection logic under test is real.
"""

from unittest.mock import AsyncMock, patch

from chromadb.errors import ChromaError
import pytest

from app.constants.memory import CHROMA_CONVERSATION_CHUNKS_COLLECTION
from app.db.chroma.chromadb import ChromaClient
from app.memory import chroma_store

USER = "user-1"


def _collection(ids: list[str]) -> AsyncMock:
    collection = AsyncMock()
    collection.get.return_value = {"ids": ids}
    return collection


@pytest.mark.unit
class TestDeleteConversationChunks:
    async def test_only_the_forgotten_conversations_chunks_are_deleted(self) -> None:
        collection = _collection([f"{USER}:conv-1:0", f"{USER}:conv-1:1", f"{USER}:conv-2:0"])
        with patch.object(
            chroma_store, "_get_collection", AsyncMock(return_value=collection)
        ) as get_collection:
            await chroma_store.delete_conversation_chunks(USER, "conv-1")

        get_collection.assert_awaited_once_with(CHROMA_CONVERSATION_CHUNKS_COLLECTION)
        collection.get.assert_awaited_once_with(where={"user_id": USER}, include=[])
        collection.delete.assert_awaited_once_with(ids=[f"{USER}:conv-1:0", f"{USER}:conv-1:1"])

    async def test_a_source_id_prefix_collision_is_not_deleted(self) -> None:
        # "conv-1" must not match "conv-12" — the trailing colon is part of
        # the id shape and the selection boundary.
        collection = _collection([f"{USER}:conv-12:0", f"{USER}:conv-1:0"])
        with patch.object(chroma_store, "_get_collection", AsyncMock(return_value=collection)):
            await chroma_store.delete_conversation_chunks(USER, "conv-1")

        collection.delete.assert_awaited_once_with(ids=[f"{USER}:conv-1:0"])

    async def test_no_matching_chunks_issues_no_delete(self) -> None:
        collection = _collection([f"{USER}:conv-2:0"])
        with patch.object(chroma_store, "_get_collection", AsyncMock(return_value=collection)):
            await chroma_store.delete_conversation_chunks(USER, "conv-1")

        collection.delete.assert_not_awaited()


class _RacyChromaServer:
    """A shared Chroma server where a concurrent creator won the race.

    ``list_collections`` returns a stale (empty) snapshot while the collection
    is in fact already registered, so the old check-then-create path calls
    ``create_collection`` and the server rejects it as a duplicate — exactly
    the ``Collection [...] already exists`` teardown failure seen under xdist.
    ``get_or_create_collection`` reads the real state and returns it.
    """

    def __init__(self, existing: dict[str, AsyncMock]) -> None:
        self._collections = existing

    async def list_collections(self) -> list[AsyncMock]:
        return []

    async def create_collection(self, name: str, **_: object) -> AsyncMock:
        if name in self._collections:
            raise ChromaError(f"Collection [{name}] already exists")
        self._collections[name] = AsyncMock()
        return self._collections[name]

    async def get_collection(self, name: str, **_: object) -> AsyncMock:
        return self._collections[name]

    async def get_or_create_collection(self, name: str, **_: object) -> AsyncMock:
        if name not in self._collections:
            self._collections[name] = AsyncMock()
        return self._collections[name]


@pytest.mark.unit
@pytest.mark.regression
class TestGetCollectionConcurrentCreate:
    async def test_get_collection_survives_a_concurrent_creator(self) -> None:
        name = CHROMA_CONVERSATION_CHUNKS_COLLECTION
        existing = AsyncMock()
        server = _RacyChromaServer({name: existing})
        # Drop the per-loop cache so _get_collection actually queries the client.
        chroma_store._loop_collections.clear()
        chroma_store._loop_locks.clear()

        with patch.object(ChromaClient, "get_client", AsyncMock(return_value=server)):
            collection = await chroma_store._get_collection(name)

        assert collection is existing


class _ConflictingChromaServer:
    """A server whose get-or-create rejects a differing persisted embedding
    function, exercising ``_get_collection``'s plain-get fallback.

    ``get_collection`` is keyed by name, so a fallback that drops the name (or
    returns nothing) fails to resolve the right collection.
    """

    def __init__(self, by_name: dict[str, AsyncMock]) -> None:
        self._by_name = by_name

    async def get_or_create_collection(self, name: str, **_: object) -> AsyncMock:
        raise ValueError(
            f"An embedding function already exists in the collection configuration: {name}"
        )

    async def get_collection(self, name: str, **_: object) -> AsyncMock:
        return self._by_name[name]


@pytest.mark.unit
class TestGetCollectionEmbeddingConflictFallback:
    async def test_falls_back_to_plain_get_for_the_same_collection(self) -> None:
        name = CHROMA_CONVERSATION_CHUNKS_COLLECTION
        existing = AsyncMock()
        server = _ConflictingChromaServer({name: existing})
        chroma_store._loop_collections.clear()
        chroma_store._loop_locks.clear()

        with patch.object(ChromaClient, "get_client", AsyncMock(return_value=server)):
            collection = await chroma_store._get_collection(name)

        assert collection is existing
