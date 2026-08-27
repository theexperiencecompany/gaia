"""Unit tests for app.memory.chroma_store — per-conversation chunk deletion.

The Chroma collection is mocked at the ``_get_collection`` seam; the id-prefix
selection logic under test is real.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.constants.memory import CHROMA_CONVERSATION_CHUNKS_COLLECTION
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
