"""Unit tests for app.utils.todo_vector_utils."""

from datetime import datetime, timezone
from typing import Generator, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId

from app.models.todo_models import Priority, TodoResponse
from app.utils.todo_vector_utils import (
    bulk_index_todos,
    create_todo_content_for_embedding,
    delete_todo_embedding,
    hybrid_search_todos,
    semantic_search_todos,
    store_todo_embedding,
    update_todo_embedding,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = "507f1f77bcf86cd799439011"
TODO_ID = "507f1f77bcf86cd799439099"
NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_todo_data(**overrides: Any) -> dict:
    """Build a realistic todo dict, merging *overrides* on top of defaults."""
    base: dict[str, Any] = {
        "title": "Buy groceries",
        "description": "Milk, eggs, bread",
        "labels": ["shopping", "personal"],
        "priority": "high",
        "completed": False,
        "project_id": "proj_123",
        "subtasks": [
            {"title": "Get milk", "completed": False},
            {"title": "Get eggs", "completed": True},
        ],
        "due_date": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return base


def _make_todo_response(**overrides: Any) -> TodoResponse:
    """Build a ``TodoResponse`` for use in mock return values."""
    base: dict[str, Any] = {
        "id": TODO_ID,
        "user_id": USER_ID,
        "title": "Buy groceries",
        "description": "Milk, eggs, bread",
        "labels": ["shopping"],
        "priority": Priority.HIGH,
        "completed": False,
        "subtasks": [],
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return TodoResponse(**base)


# ===========================================================================
# create_todo_content_for_embedding
# ===========================================================================


@pytest.mark.unit
class TestCreateTodoContentForEmbedding:
    """Pure-function tests — no mocking required."""

    def test_all_fields_present(self) -> None:
        todo = _make_todo_data()
        result = create_todo_content_for_embedding(todo)

        assert "Title: Buy groceries" in result
        assert "Description: Milk, eggs, bread" in result
        assert "Labels: shopping, personal" in result
        assert "Priority: high" in result
        assert "Project ID: proj_123" in result
        assert "Status: pending" in result
        assert "Subtasks: Get milk, Get eggs" in result
        # Parts are separated by " | "
        assert result.count(" | ") == 6

    def test_empty_or_missing_fields_only_present_fields_included(self) -> None:
        todo = _make_todo_data(
            description=None,
            labels=[],
            priority="none",
            project_id=None,
            subtasks=[],
        )
        result = create_todo_content_for_embedding(todo)

        assert "Title: Buy groceries" in result
        assert "Status: pending" in result
        # Absent fields must NOT appear
        assert "Description" not in result
        assert "Labels" not in result
        assert "Priority" not in result
        assert "Project ID" not in result
        assert "Subtasks" not in result

    def test_priority_none_excluded(self) -> None:
        todo = _make_todo_data(priority="none")
        result = create_todo_content_for_embedding(todo)
        assert "Priority" not in result

    def test_priority_present_when_not_none(self) -> None:
        for prio in ("high", "medium", "low"):
            todo = _make_todo_data(priority=prio)
            result = create_todo_content_for_embedding(todo)
            assert f"Priority: {prio}" in result

    def test_with_subtasks(self) -> None:
        todo = _make_todo_data(
            subtasks=[
                {"title": "A", "completed": False},
                {"title": "B", "completed": True},
                {"title": "", "completed": False},  # empty title — filtered out
            ]
        )
        result = create_todo_content_for_embedding(todo)
        assert "Subtasks: A, B" in result

    def test_subtasks_with_no_title_key(self) -> None:
        todo = _make_todo_data(subtasks=[{"completed": False}])
        result = create_todo_content_for_embedding(todo)
        assert "Subtasks" not in result

    def test_completed_todo_status(self) -> None:
        todo = _make_todo_data(completed=True)
        result = create_todo_content_for_embedding(todo)
        assert "Status: completed" in result

    def test_empty_todo_minimal_output(self) -> None:
        """Completely empty dict should still produce a status line."""
        result = create_todo_content_for_embedding({})
        assert result == "Status: pending"

    def test_empty_title_string_excluded(self) -> None:
        todo = _make_todo_data(title="")
        result = create_todo_content_for_embedding(todo)
        assert "Title" not in result

    def test_empty_description_string_excluded(self) -> None:
        todo = _make_todo_data(description="")
        result = create_todo_content_for_embedding(todo)
        assert "Description" not in result

    def test_labels_empty_list_excluded(self) -> None:
        todo = _make_todo_data(labels=[])
        result = create_todo_content_for_embedding(todo)
        assert "Labels" not in result


# ===========================================================================
# store_todo_embedding
# ===========================================================================


@pytest.mark.unit
class TestStoreTodoEmbedding:
    """Async tests — ChromaDB and log are mocked."""

    @pytest.fixture(autouse=True)
    def _patch_chroma_and_log(self) -> Generator[None, None, None]:
        self.mock_collection = MagicMock()
        self.mock_collection.add_texts = MagicMock()

        patcher_chroma = patch(
            "app.utils.todo_vector_utils.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            return_value=self.mock_collection,
        )
        patcher_log = patch("app.utils.todo_vector_utils.log", new_callable=MagicMock)
        self.mock_chroma = patcher_chroma.start()
        self.mock_log = patcher_log.start()
        yield
        patcher_chroma.stop()
        patcher_log.stop()

    async def test_success_returns_true(self) -> None:
        todo = _make_todo_data()
        result = await store_todo_embedding(TODO_ID, todo, USER_ID)
        assert result is True
        self.mock_collection.add_texts.assert_called_once()
        call_kwargs = self.mock_collection.add_texts.call_args
        assert call_kwargs[1]["ids"] == [TODO_ID]

    async def test_exception_returns_false(self) -> None:
        self.mock_chroma.side_effect = RuntimeError("ChromaDB unavailable")
        result = await store_todo_embedding(TODO_ID, _make_todo_data(), USER_ID)
        assert result is False

    async def test_datetime_fields_converted_to_iso(self) -> None:
        todo = _make_todo_data(created_at=NOW, updated_at=NOW, due_date=NOW)
        await store_todo_embedding(TODO_ID, todo, USER_ID)

        call_args = self.mock_collection.add_texts.call_args
        metadata = call_args[1]["metadatas"][0]
        assert metadata["created_at"] == NOW.isoformat()
        assert metadata["updated_at"] == NOW.isoformat()
        assert metadata["due_date"] == NOW.isoformat()

    async def test_string_fields_kept_as_strings(self) -> None:
        todo = _make_todo_data(created_at="2026-01-01", updated_at="2026-06-01")
        await store_todo_embedding(TODO_ID, todo, USER_ID)

        metadata = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert metadata["created_at"] == "2026-01-01"
        assert metadata["updated_at"] == "2026-06-01"

    async def test_boolean_int_fields_converted_to_lowercase_strings(self) -> None:
        todo = _make_todo_data(completed=True, due_date=NOW)
        await store_todo_embedding(TODO_ID, todo, USER_ID)

        metadata = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert metadata["completed"] == "true"
        assert metadata["has_due_date"] == "true"

        # False case
        todo2 = _make_todo_data(completed=False, due_date=None)
        await store_todo_embedding(TODO_ID, todo2, USER_ID)
        metadata2 = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert metadata2["completed"] == "false"
        assert metadata2["has_due_date"] == "false"

    async def test_optional_fields_missing_not_in_metadata(self) -> None:
        todo = _make_todo_data(project_id=None, labels=[], due_date=None)
        await store_todo_embedding(TODO_ID, todo, USER_ID)

        metadata = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert "project_id" not in metadata
        assert "labels" not in metadata
        assert "due_date" not in metadata

    async def test_optional_fields_present_in_metadata(self) -> None:
        todo = _make_todo_data(
            project_id="proj_42",
            labels=["work", "urgent"],
            due_date=NOW,
        )
        await store_todo_embedding(TODO_ID, todo, USER_ID)

        metadata = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert metadata["project_id"] == "proj_42"
        assert metadata["labels"] == "work, urgent"
        assert "due_date" in metadata

    async def test_labels_count_and_subtasks_count(self) -> None:
        todo = _make_todo_data(
            labels=["a", "b", "c"],
            subtasks=[{"title": "x"}, {"title": "y"}],
        )
        await store_todo_embedding(TODO_ID, todo, USER_ID)

        metadata = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert metadata["labels_count"] == "3"
        assert metadata["subtasks_count"] == "2"

    async def test_user_id_and_todo_id_in_metadata(self) -> None:
        await store_todo_embedding(TODO_ID, _make_todo_data(), USER_ID)

        metadata = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert metadata["user_id"] == USER_ID
        assert metadata["todo_id"] == TODO_ID

    async def test_due_date_as_string_kept(self) -> None:
        todo = _make_todo_data(due_date="2026-03-20")
        await store_todo_embedding(TODO_ID, todo, USER_ID)

        metadata = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert metadata["due_date"] == "2026-03-20"


# ===========================================================================
# update_todo_embedding
# ===========================================================================


@pytest.mark.unit
class TestUpdateTodoEmbedding:
    async def test_calls_delete_then_store_returns_true(self) -> None:
        with (
            patch(
                "app.utils.todo_vector_utils.delete_todo_embedding",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_delete,
            patch(
                "app.utils.todo_vector_utils.store_todo_embedding",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_store,
        ):
            result = await update_todo_embedding(TODO_ID, _make_todo_data(), USER_ID)
            assert result is True
            mock_delete.assert_awaited_once_with(TODO_ID)
            mock_store.assert_awaited_once_with(TODO_ID, _make_todo_data(), USER_ID)

    async def test_returns_false_when_store_fails(self) -> None:
        with (
            patch(
                "app.utils.todo_vector_utils.delete_todo_embedding",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.utils.todo_vector_utils.store_todo_embedding",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await update_todo_embedding(TODO_ID, _make_todo_data(), USER_ID)
            assert result is False

    async def test_returns_false_on_exception(self) -> None:
        with (
            patch(
                "app.utils.todo_vector_utils.delete_todo_embedding",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch("app.utils.todo_vector_utils.log", new_callable=MagicMock),
        ):
            result = await update_todo_embedding(TODO_ID, _make_todo_data(), USER_ID)
            assert result is False


# ===========================================================================
# delete_todo_embedding
# ===========================================================================


@pytest.mark.unit
class TestDeleteTodoEmbedding:
    async def test_success_returns_true(self) -> None:
        mock_collection = MagicMock()
        mock_collection.delete = MagicMock()

        with (
            patch(
                "app.utils.todo_vector_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                return_value=mock_collection,
            ),
            patch("app.utils.todo_vector_utils.log", new_callable=MagicMock),
        ):
            result = await delete_todo_embedding(TODO_ID)
            assert result is True
            mock_collection.delete.assert_called_once_with(ids=[TODO_ID])

    async def test_exception_returns_false(self) -> None:
        with (
            patch(
                "app.utils.todo_vector_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                side_effect=RuntimeError("fail"),
            ),
            patch("app.utils.todo_vector_utils.log", new_callable=MagicMock),
        ):
            result = await delete_todo_embedding(TODO_ID)
            assert result is False


# ===========================================================================
# semantic_search_todos
# ===========================================================================


@pytest.mark.unit
class TestSemanticSearchTodos:
    @pytest.fixture(autouse=True)
    def _patch_deps(self) -> Generator[None, None, None]:
        self.mock_collection = MagicMock()
        patcher_chroma = patch(
            "app.utils.todo_vector_utils.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            return_value=self.mock_collection,
        )
        patcher_log = patch("app.utils.todo_vector_utils.log", new_callable=MagicMock)
        patcher_todos_col = patch(
            "app.utils.todo_vector_utils.todos_collection",
            new_callable=AsyncMock,
        )
        patcher_serialize = patch(
            "app.utils.todo_vector_utils.serialize_document",
            side_effect=lambda doc: {
                "id": str(doc["_id"]),
                "user_id": doc["user_id"],
                "title": doc.get("title", "Test"),
                "priority": doc.get("priority", "none"),
                "completed": doc.get("completed", False),
                "subtasks": doc.get("subtasks", []),
                "labels": doc.get("labels", []),
                "created_at": NOW,
                "updated_at": NOW,
            },
        )
        self.mock_chroma = patcher_chroma.start()
        self.mock_log = patcher_log.start()
        self.mock_todos_col = patcher_todos_col.start()
        self.mock_serialize = patcher_serialize.start()
        yield
        patcher_chroma.stop()
        patcher_log.stop()
        patcher_todos_col.stop()
        patcher_serialize.stop()

    def _make_search_result(self, todo_id: str, score: float = 0.9) -> tuple:
        """Create a (Document, score) tuple mimicking ChromaDB results."""
        doc = MagicMock()
        doc.metadata = {"todo_id": todo_id}
        return (doc, score)

    async def test_results_found_returns_todo_response_list(self) -> None:
        oid = ObjectId()
        self.mock_collection.similarity_search_with_score.return_value = [
            self._make_search_result(str(oid), 0.95),
        ]
        self.mock_todos_col.find_one = AsyncMock(
            return_value={
                "_id": oid,
                "user_id": USER_ID,
                "title": "Matched todo",
                "priority": "high",
                "completed": False,
                "subtasks": [],
                "labels": [],
            }
        )

        results = await semantic_search_todos("groceries", USER_ID)
        assert len(results) == 1
        assert isinstance(results[0], TodoResponse)
        assert results[0].title == "Matched todo"

    async def test_no_results_returns_empty_list(self) -> None:
        self.mock_collection.similarity_search_with_score.return_value = []
        results = await semantic_search_todos("nonexistent", USER_ID)
        assert results == []

    async def test_no_metadata_todo_id_skipped(self) -> None:
        """Document without todo_id in metadata should be skipped."""
        doc_no_id = MagicMock()
        doc_no_id.metadata = {"user_id": USER_ID}  # no todo_id key
        self.mock_collection.similarity_search_with_score.return_value = [
            (doc_no_id, 0.8),
        ]
        results = await semantic_search_todos("query", USER_ID)
        assert results == []

    async def test_mongodb_returns_none_for_id_skipped(self) -> None:
        oid = ObjectId()
        self.mock_collection.similarity_search_with_score.return_value = [
            self._make_search_result(str(oid), 0.9),
        ]
        self.mock_todos_col.find_one = AsyncMock(return_value=None)

        results = await semantic_search_todos("query", USER_ID)
        assert results == []

    async def test_filter_completed_applied(self) -> None:
        self.mock_collection.similarity_search_with_score.return_value = []
        await semantic_search_todos("q", USER_ID, completed=True)

        call_kwargs = self.mock_collection.similarity_search_with_score.call_args[1]
        assert call_kwargs["filter"]["completed"] == "true"

    async def test_filter_completed_false_applied(self) -> None:
        self.mock_collection.similarity_search_with_score.return_value = []
        await semantic_search_todos("q", USER_ID, completed=False)

        call_kwargs = self.mock_collection.similarity_search_with_score.call_args[1]
        assert call_kwargs["filter"]["completed"] == "false"

    async def test_filter_priority_applied(self) -> None:
        self.mock_collection.similarity_search_with_score.return_value = []
        await semantic_search_todos("q", USER_ID, priority="high")

        call_kwargs = self.mock_collection.similarity_search_with_score.call_args[1]
        assert call_kwargs["filter"]["priority"] == "high"

    async def test_filter_priority_none_excluded(self) -> None:
        self.mock_collection.similarity_search_with_score.return_value = []
        await semantic_search_todos("q", USER_ID, priority="none")

        call_kwargs = self.mock_collection.similarity_search_with_score.call_args[1]
        assert "priority" not in call_kwargs["filter"]

    async def test_filter_project_id_applied(self) -> None:
        self.mock_collection.similarity_search_with_score.return_value = []
        await semantic_search_todos("q", USER_ID, project_id="proj_42")

        call_kwargs = self.mock_collection.similarity_search_with_score.call_args[1]
        assert call_kwargs["filter"]["project_id"] == "proj_42"

    async def test_user_id_always_in_filter(self) -> None:
        self.mock_collection.similarity_search_with_score.return_value = []
        await semantic_search_todos("q", USER_ID)

        call_kwargs = self.mock_collection.similarity_search_with_score.call_args[1]
        assert call_kwargs["filter"]["user_id"] == USER_ID

    async def test_top_k_passed_through(self) -> None:
        self.mock_collection.similarity_search_with_score.return_value = []
        await semantic_search_todos("q", USER_ID, top_k=5)

        call_kwargs = self.mock_collection.similarity_search_with_score.call_args[1]
        assert call_kwargs["k"] == 5

    async def test_exception_with_traditional_search_falls_back(self) -> None:
        self.mock_chroma.side_effect = RuntimeError("vector db down")
        fallback_todo = _make_todo_response(title="Fallback result")

        with patch(
            "app.services.todos.todo_service.search_todos",
            new_callable=AsyncMock,
            return_value=[fallback_todo],
        ) as mock_search:
            results = await semantic_search_todos(
                "q", USER_ID, include_traditional_search=True
            )
            assert len(results) == 1
            assert results[0].title == "Fallback result"
            mock_search.assert_awaited_once_with("q", USER_ID)

    async def test_exception_without_traditional_search_returns_empty(self) -> None:
        self.mock_chroma.side_effect = RuntimeError("vector db down")

        results = await semantic_search_todos(
            "q", USER_ID, include_traditional_search=False
        )
        assert results == []

    async def test_multiple_results_preserve_order(self) -> None:
        oid1 = ObjectId()
        oid2 = ObjectId()
        self.mock_collection.similarity_search_with_score.return_value = [
            self._make_search_result(str(oid1), 0.95),
            self._make_search_result(str(oid2), 0.80),
        ]

        async def _find_one(query: dict) -> dict | None:
            oid = query["_id"]
            if oid == oid1:
                return {
                    "_id": oid1,
                    "user_id": USER_ID,
                    "title": "First",
                    "priority": "high",
                    "completed": False,
                    "subtasks": [],
                    "labels": [],
                }
            if oid == oid2:
                return {
                    "_id": oid2,
                    "user_id": USER_ID,
                    "title": "Second",
                    "priority": "low",
                    "completed": False,
                    "subtasks": [],
                    "labels": [],
                }
            return None

        self.mock_todos_col.find_one = AsyncMock(side_effect=_find_one)

        results = await semantic_search_todos("query", USER_ID)
        assert len(results) == 2
        assert results[0].title == "First"
        assert results[1].title == "Second"


# ===========================================================================
# bulk_index_todos
# ===========================================================================


@pytest.mark.unit
class TestBulkIndexTodos:
    @pytest.fixture(autouse=True)
    def _patch_deps(self) -> Generator[None, None, None]:
        patcher_log = patch("app.utils.todo_vector_utils.log", new_callable=MagicMock)
        self.mock_log = patcher_log.start()
        yield
        patcher_log.stop()

    def _mock_cursor(self, batches: list[list[dict]]) -> MagicMock:
        """Create a mock cursor that returns batches via to_list calls."""
        call_count = 0

        async def _to_list(length: int) -> list[dict]:
            nonlocal call_count
            if call_count < len(batches):
                batch = batches[call_count]
                call_count += 1
                return batch
            return []

        cursor = MagicMock()
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.to_list = AsyncMock(side_effect=_to_list)
        return cursor

    async def test_success_returns_count(self) -> None:
        oid1 = ObjectId()
        oid2 = ObjectId()
        batch = [
            {"_id": oid1, "title": "Todo 1", "user_id": USER_ID},
            {"_id": oid2, "title": "Todo 2", "user_id": USER_ID},
        ]

        with (
            patch(
                "app.utils.todo_vector_utils.todos_collection",
            ) as mock_col,
            patch(
                "app.utils.todo_vector_utils.store_todo_embedding",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_store,
        ):
            mock_col.find.return_value = self._mock_cursor([batch])
            result = await bulk_index_todos(USER_ID, batch_size=100)
            assert result == 2
            assert mock_store.await_count == 2

    async def test_partial_failures_counted_separately(self) -> None:
        oid1 = ObjectId()
        oid2 = ObjectId()
        oid3 = ObjectId()
        batch = [
            {"_id": oid1, "title": "T1", "user_id": USER_ID},
            {"_id": oid2, "title": "T2", "user_id": USER_ID},
            {"_id": oid3, "title": "T3", "user_id": USER_ID},
        ]

        call_count = 0

        async def _store_side_effect(*args: Any, **kwargs: Any) -> bool:
            nonlocal call_count
            call_count += 1
            # Second todo fails
            return call_count != 2

        with (
            patch(
                "app.utils.todo_vector_utils.todos_collection",
            ) as mock_col,
            patch(
                "app.utils.todo_vector_utils.store_todo_embedding",
                new_callable=AsyncMock,
                side_effect=_store_side_effect,
            ),
        ):
            mock_col.find.return_value = self._mock_cursor([batch])
            result = await bulk_index_todos(USER_ID, batch_size=100)
            assert result == 2  # 3 total, 1 failed

    async def test_empty_todos_returns_zero(self) -> None:
        with patch(
            "app.utils.todo_vector_utils.todos_collection",
        ) as mock_col:
            mock_col.find.return_value = self._mock_cursor([[]])
            result = await bulk_index_todos(USER_ID)
            assert result == 0

    async def test_exception_returns_zero(self) -> None:
        with patch(
            "app.utils.todo_vector_utils.todos_collection",
        ) as mock_col:
            mock_col.find.side_effect = RuntimeError("DB down")
            result = await bulk_index_todos(USER_ID)
            assert result == 0

    async def test_multiple_batches(self) -> None:
        """When there are more todos than batch_size, multiple batches are fetched."""
        batch1 = [
            {"_id": ObjectId(), "title": f"T{i}", "user_id": USER_ID} for i in range(3)
        ]
        batch2 = [
            {"_id": ObjectId(), "title": "T3", "user_id": USER_ID},
        ]

        with (
            patch(
                "app.utils.todo_vector_utils.todos_collection",
            ) as mock_col,
            patch(
                "app.utils.todo_vector_utils.store_todo_embedding",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_store,
        ):
            mock_col.find.return_value = self._mock_cursor([batch1, batch2])
            result = await bulk_index_todos(USER_ID, batch_size=3)
            assert result == 4
            assert mock_store.await_count == 4


# ===========================================================================
# hybrid_search_todos
# ===========================================================================


@pytest.mark.unit
class TestHybridSearchTodos:
    @pytest.fixture(autouse=True)
    def _patch_log(self) -> Generator[None, None, None]:
        patcher = patch("app.utils.todo_vector_utils.log", new_callable=MagicMock)
        self.mock_log = patcher.start()
        yield
        patcher.stop()

    async def test_both_searches_return_results_combined_and_ranked(self) -> None:
        sem_todo = _make_todo_response(id="sem_1", title="Semantic match")
        trad_todo = _make_todo_response(id="trad_1", title="Traditional match")

        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[sem_todo],
            ),
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                return_value=[trad_todo],
            ),
        ):
            results = await hybrid_search_todos("query", USER_ID)
            assert len(results) == 2
            result_ids = [r.id for r in results]
            assert "sem_1" in result_ids
            assert "trad_1" in result_ids

    async def test_semantic_only_weighted_by_semantic_weight(self) -> None:
        sem_todo = _make_todo_response(id="sem_1", title="Semantic")

        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[sem_todo],
            ),
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            results = await hybrid_search_todos("query", USER_ID, semantic_weight=0.9)
            assert len(results) == 1
            assert results[0].id == "sem_1"

    async def test_traditional_only(self) -> None:
        trad_todo = _make_todo_response(id="trad_1", title="Traditional")

        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                return_value=[trad_todo],
            ),
        ):
            results = await hybrid_search_todos("query", USER_ID)
            assert len(results) == 1
            assert results[0].id == "trad_1"

    async def test_duplicate_todos_across_searches_deduplicated(self) -> None:
        shared_todo = _make_todo_response(id="shared_1", title="Both methods found")

        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[shared_todo],
            ),
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                return_value=[shared_todo],
            ),
        ):
            results = await hybrid_search_todos("query", USER_ID)
            assert len(results) == 1
            assert results[0].id == "shared_1"

    async def test_semantic_results_ranked_higher_with_default_weight(self) -> None:
        """Default semantic_weight=0.7 means semantic results score higher."""
        sem_todo = _make_todo_response(id="sem", title="Semantic")
        trad_todo = _make_todo_response(id="trad", title="Traditional")

        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[sem_todo],
            ),
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                return_value=[trad_todo],
            ),
        ):
            # semantic_weight=0.7 (default)
            results = await hybrid_search_todos("query", USER_ID)
            assert results[0].id == "sem"

    async def test_exception_falls_back_to_semantic_only(self) -> None:
        sem_todo = _make_todo_response(id="sem_1", title="Fallback")

        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[sem_todo],
            ),
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                side_effect=RuntimeError("search service down"),
            ),
        ):
            results = await hybrid_search_todos("query", USER_ID)
            # The exception in search_todos is caught by the outer try/except,
            # which falls back to semantic_search_todos
            assert len(results) >= 1

    async def test_filters_applied_to_traditional_results(self) -> None:
        completed_todo = _make_todo_response(
            id="t1", title="Done", completed=True, priority=Priority.HIGH
        )
        pending_todo = _make_todo_response(
            id="t2", title="Pending", completed=False, priority=Priority.LOW
        )

        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                return_value=[completed_todo, pending_todo],
            ),
        ):
            results = await hybrid_search_todos("query", USER_ID, completed=True)
            result_ids = [r.id for r in results]
            assert "t1" in result_ids
            assert "t2" not in result_ids

    async def test_priority_filter_applied_to_traditional(self) -> None:
        high_todo = _make_todo_response(id="h1", priority=Priority.HIGH)
        low_todo = _make_todo_response(id="l1", priority=Priority.LOW)

        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                return_value=[high_todo, low_todo],
            ),
        ):
            results = await hybrid_search_todos(
                "query", USER_ID, priority=Priority.HIGH
            )
            assert all(r.priority == Priority.HIGH for r in results)

    async def test_project_id_filter_applied_to_traditional(self) -> None:
        t1 = _make_todo_response(id="t1", project_id="proj_1")
        t2 = _make_todo_response(id="t2", project_id="proj_2")

        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                return_value=[t1, t2],
            ),
        ):
            results = await hybrid_search_todos("query", USER_ID, project_id="proj_1")
            assert len(results) == 1
            assert results[0].id == "t1"

    async def test_top_k_limits_combined_results(self) -> None:
        todos = [_make_todo_response(id=f"t{i}") for i in range(5)]

        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=todos[:3],
            ),
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                return_value=todos[3:],
            ),
        ):
            results = await hybrid_search_todos("query", USER_ID, top_k=3)
            assert len(results) <= 3

    async def test_semantic_search_called_without_traditional_fallback(self) -> None:
        """hybrid_search passes include_traditional_search=False to semantic_search."""
        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_sem,
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            await hybrid_search_todos("query", USER_ID)
            call_kwargs = mock_sem.call_args[1]
            assert call_kwargs["include_traditional_search"] is False

    async def test_empty_results_from_both_returns_empty(self) -> None:
        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            results = await hybrid_search_todos("query", USER_ID)
            assert results == []
