"""Unit tests for canvas embedding storage (app.utils.canvas_vector_utils).

ChromaDB is the seam: get_langchain_client / get_client are mocked, and the
tests pin the metadata shape, the id scheme, the completion filter, and the
fail-loud error path (returns False, never raises).
"""

from unittest.mock import AsyncMock, MagicMock, patch

from app.utils.canvas_vector_utils import (
    COLLECTION_NAME,
    delete_canvas_embedding,
    mark_canvas_completed,
    search_canvas_context,
    store_canvas_embedding,
    update_canvas_embedding,
)


async def test_store_canvas_embedding_indexes_content() -> None:
    collection = AsyncMock()
    with patch(
        "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
        new_callable=AsyncMock,
        return_value=collection,
    ) as get_client:
        ok = await store_canvas_embedding(
            "todo-1", "canvas text", "user-1", title="T", labels=["a", "b"]
        )

    assert ok is True
    get_client.assert_awaited_once_with(collection_name=COLLECTION_NAME, create_if_not_exists=True)
    args, kwargs = collection.aadd_texts.await_args
    assert kwargs["texts"] == ["canvas text"]
    assert kwargs["ids"] == ["canvas_todo-1"]
    meta = kwargs["metadatas"][0]
    assert meta["user_id"] == "user-1"
    assert meta["todo_id"] == "todo-1"
    assert meta["labels"] == "a, b"
    assert meta["completed"] is False


async def test_store_canvas_embedding_failure_returns_false() -> None:
    with patch(
        "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
        new_callable=AsyncMock,
        side_effect=RuntimeError("chroma down"),
    ):
        ok = await store_canvas_embedding("todo-1", "x", "user-1")

    assert ok is False


async def test_update_canvas_embedding_reindexes() -> None:
    with (
        patch(
            "app.utils.canvas_vector_utils.delete_canvas_embedding",
            new_callable=AsyncMock,
            return_value=True,
        ) as delete,
        patch(
            "app.utils.canvas_vector_utils.store_canvas_embedding",
            new_callable=AsyncMock,
            return_value=True,
        ) as store,
    ):
        ok = await update_canvas_embedding("todo-1", "new text", "user-1", title="T", labels=["a"])

    assert ok is True
    delete.assert_awaited_once_with("todo-1")
    # Every argument, not just the call: a re-index that drops the title, the
    # labels or the owning user re-indexes the todo under a different identity,
    # and the todo silently stops coming back from canvas search.
    store.assert_awaited_once_with("todo-1", "new text", "user-1", "T", ["a"])


async def test_delete_canvas_embedding() -> None:
    collection = AsyncMock()
    with patch(
        "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
        new_callable=AsyncMock,
        return_value=collection,
    ):
        deleted = await delete_canvas_embedding("todo-1")

    assert deleted is True
    collection.adelete.assert_awaited_once_with(ids=["canvas_todo-1"])


async def test_mark_canvas_completed() -> None:
    collection = MagicMock()
    collection.get = AsyncMock(
        return_value={"ids": ["canvas_todo-1"], "metadatas": [{"completed": False}]}
    )
    collection.update = AsyncMock()
    raw_client = MagicMock()
    raw_client.get_collection = AsyncMock(return_value=collection)
    with patch(
        "app.utils.canvas_vector_utils.ChromaClient.get_client",
        new_callable=AsyncMock,
        return_value=raw_client,
    ) as get_client:
        marked = await mark_canvas_completed("todo-1")

    assert marked is True
    get_client.assert_awaited_once()
    args, kwargs = collection.update.await_args
    assert kwargs["ids"] == ["canvas_todo-1"]
    assert kwargs["metadatas"][0]["completed"] is True


async def test_search_canvas_context_excludes_completed_when_requested() -> None:
    collection = AsyncMock()
    doc = MagicMock()
    doc.metadata = {"todo_id": "todo-1", "title": "T"}
    doc.page_content = "snippet"
    collection.asimilarity_search_with_score.return_value = [(doc, 0.95)]
    with patch(
        "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
        new_callable=AsyncMock,
        return_value=collection,
    ):
        matches = await search_canvas_context("query", "user-1", top_k=3, include_completed=False)

    assert matches == [
        {"todo_id": "todo-1", "title": "T", "score": 0.95, "snippet": "snippet", "completed": False}
    ]
    args, kwargs = collection.asimilarity_search_with_score.await_args
    assert kwargs["k"] == 3
    assert kwargs["filter"] == {"$and": [{"user_id": "user-1"}, {"completed": False}]}
