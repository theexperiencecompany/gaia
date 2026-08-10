"""Unit tests for app.utils.todo_vector_utils."""

from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

from bson import ObjectId
import pytest

from app.constants.log_tags import LogTag
from app.models.todo_models import Priority, TodoDocument, TodoResponse
from app.utils.todo_vector_utils import (
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
NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


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


class _FixedDatetime(datetime):
    """datetime subclass whose now() is pinned, so ``isinstance`` checks
    against the patched module attribute still behave like the real type."""

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return NOW


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


class TestCreateTodoContentForEmbedding:
    """Pure-function tests — no mocking required."""

    def test_all_fields_present_exact_output(self) -> None:
        todo = _make_todo_data()
        result = create_todo_content_for_embedding(todo)

        assert result == (
            "Title: Buy groceries | Description: Milk, eggs, bread"
            " | Labels: shopping, personal | Priority: high"
            " | Project ID: proj_123 | Status: pending"
            " | Subtasks: Get milk, Get eggs"
        )

    def test_empty_or_missing_fields_only_present_fields_included(self) -> None:
        todo = _make_todo_data(
            description=None,
            labels=[],
            priority="none",
            project_id=None,
            subtasks=[],
        )
        result = create_todo_content_for_embedding(todo)

        assert result == "Title: Buy groceries | Status: pending"

    def test_completed_todo_exact_output(self) -> None:
        todo = _make_todo_data(completed=True)
        result = create_todo_content_for_embedding(todo)

        assert result.endswith("Status: completed | Subtasks: Get milk, Get eggs")

    def test_priority_none_excluded(self) -> None:
        todo = _make_todo_data(priority="none")
        result = create_todo_content_for_embedding(todo)
        assert "Priority" not in result

    def test_priority_present_when_not_none(self) -> None:
        for prio in ("high", "medium", "low"):
            todo = _make_todo_data(priority=prio)
            result = create_todo_content_for_embedding(todo)
            assert f"Priority: {prio}" in result

    def test_with_subtasks_exact_output(self) -> None:
        todo = _make_todo_data(
            subtasks=[
                {"title": "A", "completed": False},
                {"title": "B", "completed": True},
                {"title": "", "completed": False},  # empty title — filtered out
            ]
        )
        result = create_todo_content_for_embedding(todo)
        assert result.endswith("Status: pending | Subtasks: A, B")

    def test_subtasks_with_no_title_key_excluded(self) -> None:
        todo = _make_todo_data(subtasks=[{"completed": False}])
        result = create_todo_content_for_embedding(todo)
        assert result == (
            "Title: Buy groceries | Description: Milk, eggs, bread"
            " | Labels: shopping, personal | Priority: high"
            " | Project ID: proj_123 | Status: pending"
        )

    def test_empty_todo_minimal_output(self) -> None:
        """Completely empty dict should still produce a status line."""
        assert create_todo_content_for_embedding({}) == "Status: pending"

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

    def test_labels_joined_with_comma_space(self) -> None:
        todo = _make_todo_data(labels=["a", "b"])
        result = create_todo_content_for_embedding(todo)
        assert "Labels: a, b" in result


# ===========================================================================
# store_todo_embedding
# ===========================================================================


class TestStoreTodoEmbedding:
    """Async tests — ChromaDB and log are mocked."""

    @pytest.fixture(autouse=True)
    def _patch_chroma_and_log(self) -> Generator[None, None, None]:
        self.mock_collection = MagicMock()
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

    async def test_success_exact_add_texts_call_and_logs(self) -> None:
        todo = _make_todo_data()
        result = await store_todo_embedding(TODO_ID, todo, USER_ID)
        assert result is True

        self.mock_chroma.assert_awaited_once_with(
            collection_name="todos", create_if_not_exists=True
        )
        self.mock_collection.add_texts.assert_called_once_with(
            texts=[
                "Title: Buy groceries | Description: Milk, eggs, bread"
                " | Labels: shopping, personal | Priority: high"
                " | Project ID: proj_123 | Status: pending"
                " | Subtasks: Get milk, Get eggs"
            ],
            metadatas=[
                {
                    "user_id": USER_ID,
                    "todo_id": TODO_ID,
                    "title": "Buy groceries",
                    "priority": "high",
                    "completed": "false",
                    "created_at": NOW.isoformat(),
                    "updated_at": NOW.isoformat(),
                    "has_due_date": "true",
                    "labels_count": "2",
                    "subtasks_count": "2",
                    "project_id": "proj_123",
                    "labels": "shopping, personal",
                    "due_date": NOW.isoformat(),
                }
            ],
            ids=[TODO_ID],
        )
        self.mock_log.set.assert_called_once_with(
            operation="store_todo_embedding", todo_id=TODO_ID, user_id=USER_ID
        )
        self.mock_log.info.assert_called_once_with(
            f"{LogTag.CHROMA} Stored embedding for todo", todo_id=TODO_ID
        )

    async def test_missing_fields_use_defaults(self) -> None:
        todo = _make_todo_data(
            description=None,
            labels=[],
            priority="none",
            project_id=None,
            subtasks=[],
            due_date=None,
        )
        del todo["description"]
        del todo["labels"]
        del todo["priority"]
        del todo["project_id"]
        del todo["subtasks"]
        del todo["due_date"]
        del todo["created_at"]
        del todo["updated_at"]

        with patch("app.utils.todo_vector_utils.datetime", _FixedDatetime):
            result = await store_todo_embedding(TODO_ID, todo, USER_ID)
        assert result is True

        metadata = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert metadata == {
            "user_id": USER_ID,
            "todo_id": TODO_ID,
            "title": "Buy groceries",
            "priority": "none",
            "completed": "false",
            # Missing timestamps default to "" — the vector metadata is
            # derived from the todo row, whose Mongo serialization leaves
            # absent datetimes as empty strings.
            "created_at": "",
            "updated_at": "",
            "has_due_date": "false",
            "labels_count": "0",
            "subtasks_count": "0",
        }

    async def test_datetime_fields_converted_to_iso(self) -> None:
        todo = _make_todo_data(created_at=NOW, updated_at=NOW, due_date=NOW)
        await store_todo_embedding(TODO_ID, todo, USER_ID)

        metadata = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert metadata["created_at"] == NOW.isoformat()
        assert metadata["updated_at"] == NOW.isoformat()
        assert metadata["due_date"] == NOW.isoformat()

    async def test_string_fields_kept_as_strings(self) -> None:
        todo = _make_todo_data(created_at="2026-01-01", updated_at="2026-06-01")
        await store_todo_embedding(TODO_ID, todo, USER_ID)

        metadata = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert metadata["created_at"] == "2026-01-01"
        assert metadata["updated_at"] == "2026-06-01"

    async def test_non_datetime_non_string_fields_casted_to_str(self) -> None:
        todo = _make_todo_data(created_at=1234567890, updated_at=123)
        await store_todo_embedding(TODO_ID, todo, USER_ID)

        metadata = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert metadata["created_at"] == "1234567890"
        assert metadata["updated_at"] == "123"

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

    async def test_due_date_as_string_kept(self) -> None:
        todo = _make_todo_data(due_date="2026-03-20")
        await store_todo_embedding(TODO_ID, todo, USER_ID)

        metadata = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert metadata["due_date"] == "2026-03-20"

    async def test_labels_count_and_subtasks_count_as_strings(self) -> None:
        todo = _make_todo_data(
            labels=["a", "b", "c"],
            subtasks=[{"title": "x"}, {"title": "y"}],
        )
        await store_todo_embedding(TODO_ID, todo, USER_ID)

        metadata = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert metadata["labels_count"] == "3"
        assert metadata["subtasks_count"] == "2"

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
        assert metadata["due_date"] == NOW.isoformat()

    async def test_project_id_casted_to_string(self) -> None:
        todo = _make_todo_data(project_id=12345)
        await store_todo_embedding(TODO_ID, todo, USER_ID)

        metadata = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert metadata["project_id"] == "12345"

    async def test_non_string_ids_converted_to_strings(self) -> None:
        todo_id = ObjectId()
        user_id = ObjectId()
        result = await store_todo_embedding(todo_id, _make_todo_data(), user_id)
        assert result is True

        metadata = self.mock_collection.add_texts.call_args[1]["metadatas"][0]
        assert metadata["user_id"] == str(user_id)
        assert metadata["todo_id"] == str(todo_id)
        assert self.mock_collection.add_texts.call_args[1]["ids"] == [str(todo_id)]

    async def test_chroma_retrieval_failure_logs_and_returns_false(self) -> None:
        self.mock_chroma.side_effect = RuntimeError("ChromaDB unavailable")
        result = await store_todo_embedding(TODO_ID, _make_todo_data(), USER_ID)
        assert result is False
        self.mock_log.error.assert_called_once_with(
            f"{LogTag.CHROMA} Error storing embedding for todo",
            todo_id=TODO_ID,
            error="ChromaDB unavailable",
            error_type="RuntimeError",
            user_id=USER_ID,
        )

    async def test_add_texts_failure_returns_false(self) -> None:
        self.mock_collection.add_texts.side_effect = RuntimeError("write failed")
        result = await store_todo_embedding(TODO_ID, _make_todo_data(), USER_ID)
        assert result is False


# ===========================================================================
# update_todo_embedding
# ===========================================================================


class TestUpdateTodoEmbedding:
    @pytest.fixture(autouse=True)
    def _patch_log(self) -> Generator[None, None, None]:
        patcher = patch("app.utils.todo_vector_utils.log", new_callable=MagicMock)
        self.mock_log = patcher.start()
        yield
        patcher.stop()

    async def test_deletes_then_stores_returns_true(self) -> None:
        todo = _make_todo_data()
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
            result = await update_todo_embedding(TODO_ID, todo, USER_ID)
            assert result is True
            mock_delete.assert_awaited_once_with(TODO_ID)
            mock_store.assert_awaited_once_with(TODO_ID, todo, USER_ID)

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

    async def test_store_exception_logs_and_returns_false(self) -> None:
        with (
            patch(
                "app.utils.todo_vector_utils.delete_todo_embedding",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.utils.todo_vector_utils.store_todo_embedding",
                new_callable=AsyncMock,
                side_effect=RuntimeError("store boom"),
            ),
        ):
            result = await update_todo_embedding(TODO_ID, _make_todo_data(), USER_ID)
            assert result is False
            self.mock_log.error.assert_called_once_with(
                f"{LogTag.CHROMA} Error updating embedding for todo",
                todo_id=TODO_ID,
                error="store boom",
                error_type="RuntimeError",
                user_id=USER_ID,
            )

    async def test_delete_exception_logs_and_returns_false(self) -> None:
        with (
            patch(
                "app.utils.todo_vector_utils.delete_todo_embedding",
                new_callable=AsyncMock,
                side_effect=RuntimeError("delete boom"),
            ),
        ):
            result = await update_todo_embedding(TODO_ID, _make_todo_data(), USER_ID)
            assert result is False
            self.mock_log.error.assert_called_once_with(
                f"{LogTag.CHROMA} Error updating embedding for todo",
                todo_id=TODO_ID,
                error="delete boom",
                error_type="RuntimeError",
                user_id=USER_ID,
            )


# ===========================================================================
# delete_todo_embedding
# ===========================================================================


class TestDeleteTodoEmbedding:
    @pytest.fixture(autouse=True)
    def _patch_chroma_and_log(self) -> Generator[None, None, None]:
        self.mock_collection = MagicMock()
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

    async def test_success_deletes_and_logs(self) -> None:
        result = await delete_todo_embedding(TODO_ID)
        assert result is True
        self.mock_chroma.assert_awaited_once_with(
            collection_name="todos", create_if_not_exists=True
        )
        self.mock_collection.delete.assert_called_once_with(ids=[TODO_ID])
        self.mock_log.info.assert_called_once_with(
            f"{LogTag.CHROMA} Deleted embedding for todo", todo_id=TODO_ID
        )

    async def test_non_string_id_converted_to_string(self) -> None:
        todo_id = ObjectId()
        result = await delete_todo_embedding(todo_id)
        assert result is True
        self.mock_collection.delete.assert_called_once_with(ids=[str(todo_id)])
        self.mock_log.info.assert_called_once_with(
            f"{LogTag.CHROMA} Deleted embedding for todo", todo_id=todo_id
        )

    async def test_delete_failure_logs_and_returns_false(self) -> None:
        self.mock_collection.delete.side_effect = RuntimeError("delete failed")
        result = await delete_todo_embedding(TODO_ID)
        assert result is False
        self.mock_log.error.assert_called_once_with(
            f"{LogTag.CHROMA} Error deleting embedding for todo",
            todo_id=TODO_ID,
            error="delete failed",
            error_type="RuntimeError",
        )

    async def test_chroma_retrieval_failure_logs_and_returns_false(self) -> None:
        self.mock_chroma.side_effect = RuntimeError("fail")
        result = await delete_todo_embedding(TODO_ID)
        assert result is False
        self.mock_log.error.assert_called_once_with(
            f"{LogTag.CHROMA} Error deleting embedding for todo",
            todo_id=TODO_ID,
            error="fail",
            error_type="RuntimeError",
        )


# ===========================================================================
# semantic_search_todos
# ===========================================================================


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
        patcher_repo = patch("app.utils.todo_vector_utils.todo_repository", new_callable=MagicMock)
        self.mock_chroma = patcher_chroma.start()
        self.mock_log = patcher_log.start()
        self.mock_repo = patcher_repo.start()
        self.mock_repo.get = AsyncMock(return_value=None)
        yield
        patcher_chroma.stop()
        patcher_log.stop()
        patcher_repo.stop()

    def _todo_doc(self, todo_id: str, **overrides: object) -> TodoDocument:
        return TodoDocument.model_validate(
            {
                "id": todo_id,
                "user_id": USER_ID,
                "title": "Test",
                "priority": "none",
                "completed": False,
                "created_at": NOW,
                "updated_at": NOW,
                **overrides,
            }
        )

    def _make_search_result(self, todo_id: str, score: float = 0.9) -> tuple:
        """Create a (Document, score) tuple mimicking ChromaDB results."""
        doc = MagicMock()
        doc.metadata = {"todo_id": todo_id}
        return (doc, score)

    async def test_exact_search_call_and_log_set(self) -> None:
        self.mock_collection.similarity_search_with_score.return_value = []
        await semantic_search_todos("groceries", USER_ID, top_k=3)

        self.mock_chroma.assert_awaited_once_with(
            collection_name="todos", create_if_not_exists=True
        )
        self.mock_collection.similarity_search_with_score.assert_called_once_with(
            query="groceries", k=3, filter={"user_id": USER_ID}
        )
        self.mock_log.set.assert_called_once_with(
            operation="semantic_search_todos",
            user_id=USER_ID,
            search_query="groceries",
            top_k=3,
            filter_completed=None,
            filter_priority=None,
            filter_project_id=None,
        )

    async def test_default_top_k_is_ten(self) -> None:
        self.mock_collection.similarity_search_with_score.return_value = []
        await semantic_search_todos("groceries", USER_ID)

        self.mock_collection.similarity_search_with_score.assert_called_once_with(
            query="groceries", k=10, filter={"user_id": USER_ID}
        )

    async def test_filters_build_full_where_clause(self) -> None:
        self.mock_collection.similarity_search_with_score.return_value = []
        await semantic_search_todos(
            "q", USER_ID, completed=True, priority="high", project_id="proj_42"
        )

        self.mock_collection.similarity_search_with_score.assert_called_once_with(
            query="q",
            k=10,
            filter={
                "user_id": USER_ID,
                "completed": "true",
                "priority": "high",
                "project_id": "proj_42",
            },
        )

    async def test_completed_false_applied_as_lowercase_string(self) -> None:
        self.mock_collection.similarity_search_with_score.return_value = []
        await semantic_search_todos("q", USER_ID, completed=False)

        call_kwargs = self.mock_collection.similarity_search_with_score.call_args[1]
        assert call_kwargs["filter"] == {"user_id": USER_ID, "completed": "false"}

    async def test_priority_none_excluded_from_filter(self) -> None:
        self.mock_collection.similarity_search_with_score.return_value = []
        await semantic_search_todos("q", USER_ID, priority="none")

        call_kwargs = self.mock_collection.similarity_search_with_score.call_args[1]
        assert call_kwargs["filter"] == {"user_id": USER_ID}

    async def test_user_id_casted_to_string_in_filter(self) -> None:
        user_id = ObjectId()
        self.mock_collection.similarity_search_with_score.return_value = []
        await semantic_search_todos("q", user_id)

        self.mock_collection.similarity_search_with_score.assert_called_once_with(
            query="q", k=10, filter={"user_id": str(user_id)}
        )

    async def test_results_found_fetch_repo_and_return_todos(self) -> None:
        oid = ObjectId()
        self.mock_collection.similarity_search_with_score.return_value = [
            self._make_search_result(str(oid), 0.95),
        ]
        doc = self._todo_doc(str(oid), title="Matched todo", priority="high")
        self.mock_repo.get = AsyncMock(return_value=doc)

        results = await semantic_search_todos("groceries", USER_ID)
        assert results == [TodoResponse.from_document(doc)]
        self.mock_repo.get.assert_awaited_once_with(str(oid), user_id=USER_ID)
        self.mock_log.info.assert_called_once_with(
            f"{LogTag.CHROMA} Semantic search returned todos",
            todo_count=1,
            query="groceries",
        )

    async def test_no_results_logs_and_returns_empty(self) -> None:
        self.mock_collection.similarity_search_with_score.return_value = []
        results = await semantic_search_todos("nonexistent", USER_ID)
        assert results == []
        self.mock_log.info.assert_called_once_with(
            f"{LogTag.CHROMA} No vector results for query", query="nonexistent"
        )

    async def test_doc_metadata_missing_todo_id_skipped(self) -> None:
        """Document with metadata but no todo_id must be skipped — and if a
        bug starts indexing it, the failure must surface, not fall back."""
        doc_no_id = MagicMock()
        doc_no_id.metadata = {"user_id": USER_ID}  # no todo_id key
        self.mock_collection.similarity_search_with_score.return_value = [
            (doc_no_id, 0.8),
        ]
        with patch(
            "app.services.todos.todo_service.search_todos",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fallback must not run"),
        ):
            results = await semantic_search_todos("query", USER_ID)
        assert results == []

    async def test_doc_without_metadata_attribute_skipped(self) -> None:
        doc = MagicMock()
        del doc.metadata
        self.mock_collection.similarity_search_with_score.return_value = [(doc, 0.8)]
        with patch(
            "app.services.todos.todo_service.search_todos",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fallback must not run"),
        ):
            results = await semantic_search_todos("query", USER_ID)
        assert results == []

    async def test_missing_todo_in_repo_skipped(self) -> None:
        oid = ObjectId()
        self.mock_collection.similarity_search_with_score.return_value = [
            self._make_search_result(str(oid), 0.9),
        ]
        self.mock_repo.get = AsyncMock(return_value=None)

        results = await semantic_search_todos("query", USER_ID)
        assert results == []
        self.mock_repo.get.assert_awaited_once_with(str(oid), user_id=USER_ID)
        self.mock_log.info.assert_called_once_with(
            f"{LogTag.CHROMA} Semantic search returned todos",
            todo_count=0,
            query="query",
        )

    async def test_multiple_results_preserve_order(self) -> None:
        oid1 = ObjectId()
        oid2 = ObjectId()
        self.mock_collection.similarity_search_with_score.return_value = [
            self._make_search_result(str(oid1), 0.95),
            self._make_search_result(str(oid2), 0.80),
        ]

        async def _get(todo_id: str, *, user_id: str) -> TodoDocument | None:
            if todo_id == str(oid1):
                return self._todo_doc(str(oid1), title="First", priority="high")
            if todo_id == str(oid2):
                return self._todo_doc(str(oid2), title="Second", priority="low")
            return None

        self.mock_repo.get = AsyncMock(side_effect=_get)

        results = await semantic_search_todos("query", USER_ID)
        assert [r.title for r in results] == ["First", "Second"]
        self.mock_repo.get.assert_has_awaits(
            [
                call(str(oid1), user_id=USER_ID),
                call(str(oid2), user_id=USER_ID),
            ]
        )

    async def test_exception_falls_back_to_traditional_search(self) -> None:
        self.mock_chroma.side_effect = RuntimeError("vector db down")
        fallback_todo = _make_todo_response(title="Fallback result")

        with patch(
            "app.services.todos.todo_service.search_todos",
            new_callable=AsyncMock,
            return_value=[fallback_todo],
        ) as mock_search:
            results = await semantic_search_todos("q", USER_ID)
            assert results == [fallback_todo]
            mock_search.assert_awaited_once_with("q", USER_ID)
            self.mock_log.error.assert_called_once_with(
                f"{LogTag.CHROMA} Error in semantic search for todos",
                error="vector db down",
                error_type="RuntimeError",
                user_id=USER_ID,
            )
            self.mock_log.info.assert_called_once_with(
                f"{LogTag.CHROMA} Falling back to traditional search due to error"
            )

    async def test_exception_without_traditional_search_returns_empty(self) -> None:
        self.mock_chroma.side_effect = RuntimeError("vector db down")

        results = await semantic_search_todos("q", USER_ID, include_traditional_search=False)
        assert results == []
        self.mock_log.error.assert_called_once_with(
            f"{LogTag.CHROMA} Error in semantic search for todos",
            error="vector db down",
            error_type="RuntimeError",
            user_id=USER_ID,
        )
        self.mock_log.info.assert_not_called()

    async def test_repo_error_falls_back_to_traditional_search(self) -> None:
        oid = ObjectId()
        self.mock_collection.similarity_search_with_score.return_value = [
            self._make_search_result(str(oid), 0.9),
        ]
        self.mock_repo.get = AsyncMock(side_effect=RuntimeError("mongo down"))

        with patch(
            "app.services.todos.todo_service.search_todos",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_search:
            results = await semantic_search_todos("q", USER_ID)
            assert results == []
            mock_search.assert_awaited_once_with("q", USER_ID)


# ===========================================================================
# hybrid_search_todos
# ===========================================================================


class TestHybridSearchTodos:
    @pytest.fixture(autouse=True)
    def _patch_log(self) -> Generator[None, None, None]:
        patcher = patch("app.utils.todo_vector_utils.log", new_callable=MagicMock)
        self.mock_log = patcher.start()
        yield
        patcher.stop()

    async def test_passes_exact_args_to_both_searches(self) -> None:
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
            ) as mock_trad,
        ):
            await hybrid_search_todos(
                "query", USER_ID, top_k=5, completed=True, priority="high", project_id="p1"
            )
            mock_sem.assert_awaited_once_with(
                query="query",
                user_id=USER_ID,
                top_k=5,
                completed=True,
                priority="high",
                project_id="p1",
                include_traditional_search=False,
            )
            mock_trad.assert_awaited_once_with("query", USER_ID)

    async def test_combined_results_ranked_by_weighted_scores(self) -> None:
        """Exact score math with the default weights: semantic 0.7/0.35,
        traditional 0.3/0.15 — and ids chosen so alphabetical ordering
        (s1 < s2 < t1 < t2) differs from score ordering."""
        s2 = _make_todo_response(id="s2", title="Sem2")
        s1 = _make_todo_response(id="s1", title="Sem1")
        t2 = _make_todo_response(id="t2", title="Trad2")
        t1 = _make_todo_response(id="t1", title="Trad1")

        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[s2, s1],
            ),
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                return_value=[t2, t1],
            ),
        ):
            results = await hybrid_search_todos("query", USER_ID)
            assert [r.id for r in results] == ["s2", "s1", "t2", "t1"]
            self.mock_log.info.assert_called_once_with(
                f"{LogTag.CHROMA} Hybrid search returned todos",
                todo_count=4,
                query="query",
            )

    async def test_overlapping_todo_gets_combined_score(self) -> None:
        shared = _make_todo_response(id="shared", title="Both methods found")
        other = _make_todo_response(id="other", title="Sem only")

        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[shared, other],
            ),
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                return_value=[shared],
            ),
        ):
            # shared = 0.7 + 0.3 = 1.0; other = 0.35
            results = await hybrid_search_todos("query", USER_ID)
            assert [r.id for r in results] == ["shared", "other"]

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
            # Scores: t0=0.7, t1=0.467, t3=0.3, t2=0.233, t4=0.24 → top 3.
            results = await hybrid_search_todos("query", USER_ID, top_k=3)
            assert [r.id for r in results] == ["t0", "t1", "t3"]

    async def test_completed_filter_applied_to_traditional(self) -> None:
        done = _make_todo_response(id="t1", title="Done", completed=True, priority=Priority.HIGH)
        pending = _make_todo_response(id="t2", title="Pending", completed=False, priority=Priority.LOW)

        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                return_value=[done, pending],
            ),
        ):
            results = await hybrid_search_todos("query", USER_ID, completed=True)
            assert results == [done]

    async def test_completed_false_filter_applied_to_traditional(self) -> None:
        done = _make_todo_response(id="t1", title="Done", completed=True, priority=Priority.HIGH)
        pending = _make_todo_response(id="t2", title="Pending", completed=False, priority=Priority.LOW)

        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                return_value=[done, pending],
            ),
        ):
            results = await hybrid_search_todos("query", USER_ID, completed=False)
            assert results == [pending]

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
            results = await hybrid_search_todos("query", USER_ID, priority=Priority.HIGH)
            assert results == [high_todo]

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
            assert results == [t1]

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
            self.mock_log.info.assert_called_once_with(
                f"{LogTag.CHROMA} Hybrid search returned todos",
                todo_count=0,
                query="query",
            )

    async def test_exception_falls_back_to_semantic_with_exact_args(self) -> None:
        sem_todo = _make_todo_response(id="sem_1", title="Fallback")

        with (
            patch(
                "app.utils.todo_vector_utils.semantic_search_todos",
                new_callable=AsyncMock,
                return_value=[sem_todo],
            ) as mock_sem,
            patch(
                "app.services.todos.todo_service.search_todos",
                new_callable=AsyncMock,
                side_effect=RuntimeError("search service down"),
            ),
        ):
            results = await hybrid_search_todos(
                "q", USER_ID, top_k=3, completed=True, priority="high", project_id="p1"
            )
            assert results == [sem_todo]
            assert len(mock_sem.await_args_list) == 2
            mock_sem.assert_has_awaits(
                [
                    call(
                        query="q",
                        user_id=USER_ID,
                        top_k=3,
                        completed=True,
                        priority="high",
                        project_id="p1",
                        include_traditional_search=False,
                    ),
                    call("q", USER_ID, 3, completed=True, priority="high", project_id="p1"),
                ]
            )
            self.mock_log.error.assert_called_once_with(
                f"{LogTag.CHROMA} Error in hybrid search",
                error="search service down",
                error_type="RuntimeError",
                user_id=USER_ID,
            )
