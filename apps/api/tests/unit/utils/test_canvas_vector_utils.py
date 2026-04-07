"""Unit tests for app.utils.canvas_vector_utils.

Verifies that ChromaDB metadata booleans are stored and filtered as lowercase
strings ("true"/"false"), not Python bool values. This is a ChromaDB requirement
documented in todo_vector_utils.py — canvas_vector_utils had a bug where it used
raw Python bools, causing search_canvas_context to always return empty results.
"""

from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.utils.canvas_vector_utils import (
    mark_canvas_completed,
    search_canvas_context,
    store_canvas_embedding,
    update_canvas_embedding,
)

USER_ID = "507f1f77bcf86cd799439011"
TODO_ID = "507f1f77bcf86cd799439099"
CANVAS_CONTENT = "# My Todo\n\n## Key Details\nSome context here."


# ===========================================================================
# store_canvas_embedding
# ===========================================================================


@pytest.mark.unit
class TestStoreCanvasEmbedding:
    @pytest.fixture(autouse=True)
    def _patch(self) -> Generator[None, None, None]:
        self.mock_collection = MagicMock()
        self.mock_collection.aadd_texts = AsyncMock()

        patcher = patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            return_value=self.mock_collection,
        )
        self.mock_chroma = patcher.start()
        yield
        patcher.stop()

    async def test_returns_true_on_success(self) -> None:
        result = await store_canvas_embedding(TODO_ID, CANVAS_CONTENT, USER_ID)
        assert result is True

    async def test_stores_completed_as_string_false(self) -> None:
        """ChromaDB requires booleans as lowercase strings — must be "false" not False."""
        await store_canvas_embedding(TODO_ID, CANVAS_CONTENT, USER_ID)

        call_kwargs = self.mock_collection.aadd_texts.call_args
        metadata = call_kwargs[1]["metadatas"][0]
        assert metadata["completed"] == "false"
        assert not isinstance(metadata["completed"], bool)

    async def test_stores_correct_ids_and_content(self) -> None:
        await store_canvas_embedding(TODO_ID, CANVAS_CONTENT, USER_ID, title="My Todo")

        call_kwargs = self.mock_collection.aadd_texts.call_args
        assert call_kwargs[1]["ids"] == [f"canvas_{TODO_ID}"]
        assert call_kwargs[1]["texts"] == [CANVAS_CONTENT]
        metadata = call_kwargs[1]["metadatas"][0]
        assert metadata["user_id"] == USER_ID
        assert metadata["todo_id"] == TODO_ID
        assert metadata["title"] == "My Todo"

    async def test_stores_labels_as_comma_string(self) -> None:
        await store_canvas_embedding(
            TODO_ID, CANVAS_CONTENT, USER_ID, labels=["gaia-tracked", "work"]
        )
        metadata = self.mock_collection.aadd_texts.call_args[1]["metadatas"][0]
        assert metadata["labels"] == "gaia-tracked, work"

    async def test_returns_false_on_exception(self) -> None:
        self.mock_chroma.side_effect = RuntimeError("ChromaDB unavailable")
        result = await store_canvas_embedding(TODO_ID, CANVAS_CONTENT, USER_ID)
        assert result is False


# ===========================================================================
# mark_canvas_completed
# ===========================================================================


@pytest.mark.unit
class TestMarkCanvasCompleted:
    @pytest.fixture(autouse=True)
    def _patch(self) -> Generator[None, None, None]:
        self.mock_collection = MagicMock()
        self.mock_collection.get = AsyncMock(
            return_value={
                "metadatas": [
                    {
                        "user_id": USER_ID,
                        "todo_id": TODO_ID,
                        "completed": "false",
                        "title": "My Todo",
                    }
                ]
            }
        )
        self.mock_collection.update = AsyncMock()

        mock_raw_client = AsyncMock()
        mock_raw_client.get_collection = AsyncMock(return_value=self.mock_collection)

        patcher = patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_client",
            new_callable=AsyncMock,
            return_value=mock_raw_client,
        )
        self.mock_chroma = patcher.start()
        yield
        patcher.stop()

    async def test_sets_completed_to_string_true(self) -> None:
        """ChromaDB requires booleans as lowercase strings — must be "true" not True."""
        result = await mark_canvas_completed(TODO_ID)

        assert result is True
        update_call = self.mock_collection.update.call_args
        updated_metadata = update_call[1]["metadatas"][0]
        assert updated_metadata["completed"] == "true"
        assert not isinstance(updated_metadata["completed"], bool)

    async def test_sets_completed_at_timestamp(self) -> None:
        await mark_canvas_completed(TODO_ID)
        updated_metadata = self.mock_collection.update.call_args[1]["metadatas"][0]
        assert "completed_at" in updated_metadata

    async def test_returns_false_when_document_not_found(self) -> None:
        self.mock_collection.get = AsyncMock(return_value={"metadatas": []})
        result = await mark_canvas_completed(TODO_ID)
        assert result is False
        self.mock_collection.update.assert_not_called()

    async def test_returns_false_on_exception(self) -> None:
        self.mock_chroma.side_effect = RuntimeError("ChromaDB error")
        result = await mark_canvas_completed(TODO_ID)
        assert result is False


# ===========================================================================
# search_canvas_context
# ===========================================================================


@pytest.mark.unit
class TestSearchCanvasContext:
    def _make_doc(self, todo_id: str = TODO_ID, completed: str = "false") -> MagicMock:
        doc = MagicMock()
        doc.metadata = {
            "user_id": USER_ID,
            "todo_id": todo_id,
            "title": "My Todo",
            "completed": completed,
        }
        doc.page_content = CANVAS_CONTENT
        return doc

    @pytest.fixture(autouse=True)
    def _patch(self) -> Generator[None, None, None]:
        self.mock_collection = MagicMock()
        self.mock_collection.asimilarity_search_with_score = AsyncMock(
            return_value=[(self._make_doc(), 0.85)]
        )

        patcher = patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            return_value=self.mock_collection,
        )
        self.mock_chroma = patcher.start()
        yield
        patcher.stop()

    async def test_filter_include_completed_uses_only_user_id(self) -> None:
        """When include_completed=True, filter must only contain user_id."""
        await search_canvas_context("contract", USER_ID, include_completed=True)

        call_kwargs = self.mock_collection.asimilarity_search_with_score.call_args[1]
        assert call_kwargs["filter"] == {"user_id": USER_ID}

    async def test_filter_exclude_completed_uses_string_false(self) -> None:
        """When include_completed=False, filter must use "false" string not Python False."""
        await search_canvas_context("contract", USER_ID, include_completed=False)

        call_kwargs = self.mock_collection.asimilarity_search_with_score.call_args[1]
        expected_filter = {
            "$and": [
                {"user_id": USER_ID},
                {"completed": "false"},
            ]
        }
        assert call_kwargs["filter"] == expected_filter
        # Verify no Python bool slipped through
        completed_filter = call_kwargs["filter"]["$and"][1]["completed"]
        assert completed_filter == "false"
        assert not isinstance(completed_filter, bool)

    async def test_maps_results_correctly(self) -> None:
        results = await search_canvas_context("contract", USER_ID)

        assert len(results) == 1
        r = results[0]
        assert r["todo_id"] == TODO_ID
        assert r["title"] == "My Todo"
        assert r["score"] == 0.85
        assert r["snippet"] == CANVAS_CONTENT[:500]
        assert r["completed"] == "false"

    async def test_returns_empty_on_exception(self) -> None:
        self.mock_chroma.side_effect = RuntimeError("ChromaDB unavailable")
        results = await search_canvas_context("contract", USER_ID)
        assert results == []

    async def test_respects_top_k(self) -> None:
        await search_canvas_context("contract", USER_ID, top_k=5)
        call_kwargs = self.mock_collection.asimilarity_search_with_score.call_args[1]
        assert call_kwargs["k"] == 5


# ===========================================================================
# update_canvas_embedding
# ===========================================================================


@pytest.mark.unit
class TestUpdateCanvasEmbedding:
    @pytest.fixture(autouse=True)
    def _patch(self) -> Generator[None, None, None]:
        self.mock_langchain_collection = MagicMock()
        self.mock_langchain_collection.aadd_texts = AsyncMock()
        self.mock_langchain_collection.adelete = AsyncMock()

        self.mock_raw_collection = MagicMock()
        self.mock_raw_collection.get = AsyncMock(
            return_value={"metadatas": [{"completed": "false"}]}
        )

        mock_raw_client = AsyncMock()
        mock_raw_client.get_collection = AsyncMock(return_value=self.mock_raw_collection)

        patcher_langchain = patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            return_value=self.mock_langchain_collection,
        )
        patcher_raw = patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_client",
            new_callable=AsyncMock,
            return_value=mock_raw_client,
        )
        patcher_langchain.start()
        patcher_raw.start()
        yield
        patcher_langchain.stop()
        patcher_raw.stop()

    async def test_does_not_restore_completed_when_not_completed(self) -> None:
        """If existing metadata has completed="false", mark_canvas_completed must NOT be called."""
        self.mock_raw_collection.get = AsyncMock(
            return_value={"metadatas": [{"completed": "false"}]}
        )
        with patch(
            "app.utils.canvas_vector_utils.mark_canvas_completed",
            new_callable=AsyncMock,
        ) as mock_mark:
            await update_canvas_embedding(TODO_ID, CANVAS_CONTENT, USER_ID)
            mock_mark.assert_not_called()

    async def test_restores_completed_when_previously_completed(self) -> None:
        """If existing metadata has completed="true", mark_canvas_completed must be called."""
        self.mock_raw_collection.get = AsyncMock(
            return_value={"metadatas": [{"completed": "true"}]}
        )
        with patch(
            "app.utils.canvas_vector_utils.mark_canvas_completed",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_mark:
            await update_canvas_embedding(TODO_ID, CANVAS_CONTENT, USER_ID)
            mock_mark.assert_called_once_with(TODO_ID)

    async def test_returns_true_on_success(self) -> None:
        result = await update_canvas_embedding(TODO_ID, CANVAS_CONTENT, USER_ID)
        assert result is True
