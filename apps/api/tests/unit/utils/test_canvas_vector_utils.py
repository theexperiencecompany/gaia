"""Unit tests for canvas embedding storage (app.utils.canvas_vector_utils).

ChromaDB is the seam: get_langchain_client / get_client are mocked, and the
tests pin the exact metadata shape, the id scheme, the exact arguments
forwarded to every ChromaDB call, the completed-status preserve/restore
contract, and the fail-loud error paths (return False / [] but log the
exact line — never raise, never silently swallow).
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.utils.canvas_vector_utils import (
    COLLECTION_NAME,
    delete_canvas_embedding,
    mark_canvas_completed,
    search_canvas_context,
    store_canvas_embedding,
    update_canvas_embedding,
)

FIXED_NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)


async def test_store_canvas_embedding_indexes_exact_content_and_metadata() -> None:
    collection = AsyncMock()
    with (
        patch("app.utils.canvas_vector_utils.datetime") as mock_datetime,
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            return_value=collection,
        ) as get_client,
    ):
        mock_datetime.now.return_value = FIXED_NOW
        ok = await store_canvas_embedding(
            "todo-1", "canvas text", "user-1", title="A title", labels=["a", "b"]
        )

    assert ok is True
    get_client.assert_awaited_once_with(
        collection_name=COLLECTION_NAME, create_if_not_exists=True
    )
    mock_datetime.now.assert_called_once_with(UTC)
    collection.aadd_texts.assert_awaited_once_with(
        texts=["canvas text"],
        metadatas=[
            {
                "user_id": "user-1",
                "todo_id": "todo-1",
                "title": "A title",
                "updated_at": "2026-08-10T12:00:00+00:00",
                "completed": False,
                "labels": "a, b",
            }
        ],
        ids=["canvas_todo-1"],
    )


async def test_store_canvas_embedding_uses_default_title_and_omits_labels() -> None:
    collection = AsyncMock()
    with (
        patch("app.utils.canvas_vector_utils.datetime") as mock_datetime,
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            return_value=collection,
        ),
    ):
        mock_datetime.now.return_value = FIXED_NOW
        ok = await store_canvas_embedding("todo-1", "canvas text", "user-1")

    assert ok is True
    collection.aadd_texts.assert_awaited_once_with(
        texts=["canvas text"],
        metadatas=[
            {
                "user_id": "user-1",
                "todo_id": "todo-1",
                "title": "",
                "updated_at": "2026-08-10T12:00:00+00:00",
                "completed": False,
            }
        ],
        ids=["canvas_todo-1"],
    )


async def test_store_canvas_embedding_coerces_ids_to_str() -> None:
    collection = AsyncMock()
    with (
        patch("app.utils.canvas_vector_utils.datetime") as mock_datetime,
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            return_value=collection,
        ),
    ):
        mock_datetime.now.return_value = FIXED_NOW
        ok = await store_canvas_embedding(123, "canvas text", 456)

    assert ok is True
    collection.aadd_texts.assert_awaited_once_with(
        texts=["canvas text"],
        metadatas=[
            {
                "user_id": "456",
                "todo_id": "123",
                "title": "",
                "updated_at": "2026-08-10T12:00:00+00:00",
                "completed": False,
            }
        ],
        ids=["canvas_123"],
    )


async def test_store_canvas_embedding_empty_labels_list_omits_labels_key() -> None:
    collection = AsyncMock()
    with (
        patch("app.utils.canvas_vector_utils.datetime") as mock_datetime,
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            return_value=collection,
        ),
    ):
        mock_datetime.now.return_value = FIXED_NOW
        ok = await store_canvas_embedding("todo-1", "canvas text", "user-1", labels=[])

    assert ok is True
    collection.aadd_texts.assert_awaited_once_with(
        texts=["canvas text"],
        metadatas=[
            {
                "user_id": "user-1",
                "todo_id": "todo-1",
                "title": "",
                "updated_at": "2026-08-10T12:00:00+00:00",
                "completed": False,
            }
        ],
        ids=["canvas_todo-1"],
    )


async def test_store_canvas_embedding_failure_logs_and_returns_false() -> None:
    with (
        patch("app.utils.canvas_vector_utils.log") as mock_log,
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ),
    ):
        ok = await store_canvas_embedding("todo-1", "x", "user-1")

    assert ok is False
    mock_log.error.assert_called_once_with(
        f"{LogTag.CHROMA} Failed to index canvas for todo",
        todo_id="todo-1",
        error="boom",
        error_type="RuntimeError",
        user_id="user-1",
    )


async def test_update_canvas_embedding_reindexes_without_restore_when_not_completed() -> None:
    collection = MagicMock()
    collection.get = AsyncMock(
        return_value={"ids": ["canvas_todo-1"], "metadatas": [{"completed": False, "title": "T"}]}
    )
    raw_client = MagicMock()
    raw_client.get_collection = AsyncMock(return_value=collection)
    calls: list[str] = []

    async def record_delete(todo_id: str) -> None:
        calls.append(f"delete:{todo_id}")

    async def record_store(*args: object) -> bool:
        calls.append("store")
        return True

    with (
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_client",
            new_callable=AsyncMock,
            return_value=raw_client,
        ) as get_client,
        patch(
            "app.utils.canvas_vector_utils.delete_canvas_embedding",
            new_callable=AsyncMock,
            side_effect=record_delete,
        ) as delete,
        patch(
            "app.utils.canvas_vector_utils.store_canvas_embedding",
            new_callable=AsyncMock,
            side_effect=record_store,
        ) as store,
        patch(
            "app.utils.canvas_vector_utils.mark_canvas_completed",
            new_callable=AsyncMock,
        ) as mark,
        patch("app.utils.canvas_vector_utils.log") as mock_log,
    ):
        ok = await update_canvas_embedding("todo-1", "new text", "user-1")

    assert ok is True
    get_client.assert_awaited_once()
    raw_client.get_collection.assert_awaited_once_with(COLLECTION_NAME)
    collection.get.assert_awaited_once_with(ids=["canvas_todo-1"], include=["metadatas"])
    delete.assert_awaited_once_with("todo-1")
    store.assert_awaited_once_with("todo-1", "new text", "user-1", "", None)
    mark.assert_not_awaited()
    mock_log.debug.assert_not_called()
    assert calls == ["delete:todo-1", "store"]


async def test_update_canvas_embedding_restores_completed_status() -> None:
    collection = MagicMock()
    collection.get = AsyncMock(
        return_value={"ids": ["canvas_todo-1"], "metadatas": [{"completed": True}]}
    )
    raw_client = MagicMock()
    raw_client.get_collection = AsyncMock(return_value=collection)
    with (
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_client",
            new_callable=AsyncMock,
            return_value=raw_client,
        ),
        patch(
            "app.utils.canvas_vector_utils.delete_canvas_embedding",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.utils.canvas_vector_utils.store_canvas_embedding",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.utils.canvas_vector_utils.mark_canvas_completed",
            new_callable=AsyncMock,
        ) as mark,
    ):
        ok = await update_canvas_embedding("todo-1", "new text", "user-1")

    assert ok is True
    mark.assert_awaited_once_with("todo-1")


async def test_update_canvas_embedding_does_not_restore_when_store_fails() -> None:
    collection = MagicMock()
    collection.get = AsyncMock(
        return_value={"ids": ["canvas_todo-1"], "metadatas": [{"completed": True}]}
    )
    raw_client = MagicMock()
    raw_client.get_collection = AsyncMock(return_value=collection)
    with (
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_client",
            new_callable=AsyncMock,
            return_value=raw_client,
        ),
        patch(
            "app.utils.canvas_vector_utils.delete_canvas_embedding",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.utils.canvas_vector_utils.store_canvas_embedding",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "app.utils.canvas_vector_utils.mark_canvas_completed",
            new_callable=AsyncMock,
        ) as mark,
    ):
        ok = await update_canvas_embedding("todo-1", "new text", "user-1")

    assert ok is False
    mark.assert_not_awaited()


async def test_update_canvas_embedding_proceeds_when_metadata_read_fails() -> None:
    raw_client = MagicMock()
    raw_client.get_collection = AsyncMock(side_effect=RuntimeError("boom"))
    with (
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_client",
            new_callable=AsyncMock,
            return_value=raw_client,
        ),
        patch(
            "app.utils.canvas_vector_utils.delete_canvas_embedding",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.utils.canvas_vector_utils.store_canvas_embedding",
            new_callable=AsyncMock,
            return_value=True,
        ) as store,
        patch(
            "app.utils.canvas_vector_utils.mark_canvas_completed",
            new_callable=AsyncMock,
        ),
        patch("app.utils.canvas_vector_utils.log") as mock_log,
    ):
        ok = await update_canvas_embedding(
            "todo-1", "new text", "user-1", title="A title", labels=["a", "b"]
        )

    assert ok is True
    store.assert_awaited_once_with("todo-1", "new text", "user-1", "A title", ["a", "b"])
    mock_log.debug.assert_called_once_with(
        "canvas.preserve_completed_metadata_failed", todo_id="todo-1", error="boom"
    )


@pytest.mark.parametrize(
    "existing",
    [
        None,
        {"metadatas": []},
        {"metadatas": [{"title": "T"}]},
        {"metadatas": [{}]},
        {"ids": ["canvas_todo-1"]},
    ],
)
async def test_update_canvas_embedding_without_metadata_skips_restore(
    existing: dict[str, object] | None,
) -> None:
    collection = MagicMock()
    collection.get = AsyncMock(return_value=existing)
    raw_client = MagicMock()
    raw_client.get_collection = AsyncMock(return_value=collection)
    with (
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_client",
            new_callable=AsyncMock,
            return_value=raw_client,
        ),
        patch(
            "app.utils.canvas_vector_utils.delete_canvas_embedding",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.utils.canvas_vector_utils.store_canvas_embedding",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.utils.canvas_vector_utils.mark_canvas_completed",
            new_callable=AsyncMock,
        ) as mark,
        patch("app.utils.canvas_vector_utils.log") as mock_log,
    ):
        ok = await update_canvas_embedding("todo-1", "new text", "user-1")

    assert ok is True
    mark.assert_not_awaited()
    mock_log.debug.assert_not_called()


async def test_update_canvas_embedding_swallows_restore_failure() -> None:
    collection = MagicMock()
    collection.get = AsyncMock(
        return_value={"ids": ["canvas_todo-1"], "metadatas": [{"completed": True}]}
    )
    raw_client = MagicMock()
    raw_client.get_collection = AsyncMock(return_value=collection)
    with (
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_client",
            new_callable=AsyncMock,
            return_value=raw_client,
        ),
        patch(
            "app.utils.canvas_vector_utils.delete_canvas_embedding",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.utils.canvas_vector_utils.store_canvas_embedding",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.utils.canvas_vector_utils.mark_canvas_completed",
            new_callable=AsyncMock,
            side_effect=RuntimeError("mark boom"),
        ),
        patch("app.utils.canvas_vector_utils.log") as mock_log,
    ):
        ok = await update_canvas_embedding("todo-1", "new text", "user-1")

    assert ok is True
    mock_log.debug.assert_called_once_with(
        "canvas.restore_completed_status_failed", todo_id="todo-1", error="mark boom"
    )


async def test_delete_canvas_embedding_deletes_exact_id() -> None:
    collection = AsyncMock()
    with patch(
        "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
        new_callable=AsyncMock,
        return_value=collection,
    ) as get_client:
        deleted = await delete_canvas_embedding("todo-1")

    assert deleted is True
    get_client.assert_awaited_once_with(
        collection_name=COLLECTION_NAME, create_if_not_exists=True
    )
    collection.adelete.assert_awaited_once_with(ids=["canvas_todo-1"])


async def test_delete_canvas_embedding_failure_logs_and_returns_false() -> None:
    with (
        patch("app.utils.canvas_vector_utils.log") as mock_log,
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ),
    ):
        deleted = await delete_canvas_embedding("todo-1")

    assert deleted is False
    mock_log.error.assert_called_once_with(
        f"{LogTag.CHROMA} Failed to delete canvas index for todo",
        todo_id="todo-1",
        error="boom",
        error_type="RuntimeError",
    )


async def test_mark_canvas_completed_updates_metadata_without_mutating_input() -> None:
    existing_meta = {"user_id": "u", "todo_id": "todo-1", "title": "T", "completed": False}
    collection = MagicMock()
    collection.get = AsyncMock(
        return_value={"ids": ["canvas_todo-1"], "metadatas": [existing_meta]}
    )
    collection.update = AsyncMock()
    raw_client = MagicMock()
    raw_client.get_collection = AsyncMock(return_value=collection)
    with (
        patch("app.utils.canvas_vector_utils.datetime") as mock_datetime,
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_client",
            new_callable=AsyncMock,
            return_value=raw_client,
        ) as get_client,
    ):
        mock_datetime.now.return_value = FIXED_NOW
        marked = await mark_canvas_completed("todo-1")

    assert marked is True
    get_client.assert_awaited_once()
    raw_client.get_collection.assert_awaited_once_with(COLLECTION_NAME)
    collection.get.assert_awaited_once_with(ids=["canvas_todo-1"], include=["metadatas"])
    mock_datetime.now.assert_called_once_with(UTC)
    collection.update.assert_awaited_once_with(
        ids=["canvas_todo-1"],
        metadatas=[
            {
                "user_id": "u",
                "todo_id": "todo-1",
                "title": "T",
                "completed": True,
                "completed_at": "2026-08-10T12:00:00+00:00",
            }
        ],
    )
    assert existing_meta == {"user_id": "u", "todo_id": "todo-1", "title": "T", "completed": False}


@pytest.mark.parametrize("existing", [None, {"ids": ["canvas_todo-1"], "metadatas": []}])
async def test_mark_canvas_completed_without_existing_embedding_returns_false(
    existing: dict[str, object] | None,
) -> None:
    collection = MagicMock()
    collection.get = AsyncMock(return_value=existing)
    collection.update = AsyncMock()
    raw_client = MagicMock()
    raw_client.get_collection = AsyncMock(return_value=collection)
    with (
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_client",
            new_callable=AsyncMock,
            return_value=raw_client,
        ),
        patch("app.utils.canvas_vector_utils.log") as mock_log,
    ):
        marked = await mark_canvas_completed("todo-1")

    assert marked is False
    collection.update.assert_not_awaited()
    mock_log.warning.assert_not_called()


async def test_mark_canvas_completed_failure_logs_warning() -> None:
    raw_client = MagicMock()
    raw_client.get_collection = AsyncMock(side_effect=RuntimeError("boom"))
    with (
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_client",
            new_callable=AsyncMock,
            return_value=raw_client,
        ),
        patch("app.utils.canvas_vector_utils.log") as mock_log,
    ):
        marked = await mark_canvas_completed("todo-1")

    assert marked is False
    mock_log.warning.assert_called_once_with(
        "canvas.mark_completed_failed", todo_id="todo-1", error="boom"
    )


async def test_search_canvas_context_uses_defaults_for_top_k_and_completed() -> None:
    collection = AsyncMock()
    collection.asimilarity_search_with_score.return_value = []
    with patch(
        "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
        new_callable=AsyncMock,
        return_value=collection,
    ) as get_client:
        matches = await search_canvas_context("query", "user-1")

    assert matches == []
    get_client.assert_awaited_once_with(
        collection_name=COLLECTION_NAME, create_if_not_exists=True
    )
    collection.asimilarity_search_with_score.assert_awaited_once_with(
        query="query", k=10, filter={"user_id": "user-1"}
    )


async def test_search_canvas_context_excludes_completed_when_requested() -> None:
    collection = AsyncMock()
    doc = SimpleNamespace(metadata={"todo_id": "todo-1", "title": "T"}, page_content="snippet")
    collection.asimilarity_search_with_score.return_value = [(doc, 0.95)]
    with patch(
        "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
        new_callable=AsyncMock,
        return_value=collection,
    ) as get_client:
        matches = await search_canvas_context("query", "user-1", top_k=3, include_completed=False)

    assert matches == [
        {"todo_id": "todo-1", "title": "T", "score": 0.95, "snippet": "snippet", "completed": False}
    ]
    get_client.assert_awaited_once_with(
        collection_name=COLLECTION_NAME, create_if_not_exists=True
    )
    collection.asimilarity_search_with_score.assert_awaited_once_with(
        query="query",
        k=3,
        filter={"$and": [{"user_id": "user-1"}, {"completed": False}]},
    )


async def test_search_canvas_context_returns_rounded_scores_and_defaults() -> None:
    collection = AsyncMock()
    long_content = "x" * 600
    full_doc = SimpleNamespace(
        metadata={"todo_id": "todo-9", "title": "My canvas", "completed": True},
        page_content=long_content,
    )
    bare_doc = SimpleNamespace()
    collection.asimilarity_search_with_score.return_value = [(full_doc, 0.12345), (bare_doc, 1.5)]
    with patch(
        "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
        new_callable=AsyncMock,
        return_value=collection,
    ):
        matches = await search_canvas_context("query", "user-1")

    assert matches == [
        {
            "todo_id": "todo-9",
            "title": "My canvas",
            "score": 0.123,
            "snippet": long_content[:500],
            "completed": True,
        },
        {"todo_id": "", "title": "", "score": 1.5, "snippet": "", "completed": False},
    ]


async def test_search_canvas_context_coerces_user_id_to_str() -> None:
    collection = AsyncMock()
    collection.asimilarity_search_with_score.return_value = []
    with patch(
        "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
        new_callable=AsyncMock,
        return_value=collection,
    ):
        matches = await search_canvas_context("query", 456)

    assert matches == []
    collection.asimilarity_search_with_score.assert_awaited_once_with(
        query="query", k=10, filter={"user_id": "456"}
    )


async def test_search_canvas_context_failure_logs_and_returns_empty() -> None:
    with (
        patch("app.utils.canvas_vector_utils.log") as mock_log,
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ),
    ):
        matches = await search_canvas_context("query", "user-1")

    assert matches == []
    mock_log.error.assert_called_once_with(
        f"{LogTag.CHROMA} Canvas search failed for user",
        user_id="user-1",
        error="boom",
        error_type="RuntimeError",
    )
