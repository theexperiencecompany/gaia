"""Unit tests for canvas embedding storage (app.utils.canvas_vector_utils).

ChromaDB is the seam: get_langchain_client / get_client are mocked, and the
tests pin the metadata shape, the id scheme, the completion filter, and the
fail-loud error path (returns False, never raises).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
            "todo-1",
            "canvas text",
            "user-1",
            title="T",
            labels=["a", "b"],
            revision="2026-09-12T13:00:00+00:00",
        )

    assert ok is True
    get_client.assert_awaited_once_with(collection_name=COLLECTION_NAME, create_if_not_exists=True)
    args, kwargs = collection.aadd_texts.await_args
    assert kwargs["texts"] == ["canvas text"]
    assert kwargs["ids"] == ["canvas_todo-1"]
    meta = kwargs["metadatas"][0]
    assert meta["user_id"] == "user-1"
    assert meta["todo_id"] == "todo-1"
    assert meta["title"] == "T"
    assert meta["labels"] == "a, b"
    assert meta["revision"] == "2026-09-12T13:00:00+00:00"
    assert meta["completed"] is False
    # A fresh timestamp is stamped on every write; assert it is present so a
    # dropped `updated_at` key is caught (the value is now()).
    assert meta["updated_at"]


async def test_store_canvas_embedding_omits_optional_metadata_when_absent() -> None:
    """No labels / revision means the keys are absent, not blank — the
    `if labels:` / `if revision is not None:` guards both matter."""
    collection = AsyncMock()
    with patch(
        "app.utils.canvas_vector_utils.ChromaClient.get_langchain_client",
        new_callable=AsyncMock,
        return_value=collection,
    ):
        await store_canvas_embedding("todo-1", "x", "user-1")

    meta = collection.aadd_texts.await_args.kwargs["metadatas"][0]
    assert "labels" not in meta
    assert "revision" not in meta
    assert meta["title"] == ""


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
        ok = await update_canvas_embedding("todo-1", "new text", "user-1")

    assert ok is True
    delete.assert_awaited_once_with("todo-1")
    store.assert_awaited_once_with("todo-1", "new text", "user-1", "", None, revision=None)


def _revision_collection(revision: str | None) -> MagicMock:
    collection = MagicMock()
    collection.get = AsyncMock(
        return_value={
            "ids": ["canvas_todo-1"],
            "metadatas": [{"completed": False, "revision": revision}],
        }
    )
    return collection


@pytest.mark.regression
async def test_update_skips_write_when_newer_revision_stored() -> None:
    """An older reindex finishing last must not clobber a newer embedding."""
    raw_client = MagicMock()
    raw_client.get_collection = AsyncMock(
        return_value=_revision_collection("2026-09-12T12:00:00+00:00")
    )
    with (
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_client",
            new_callable=AsyncMock,
            return_value=raw_client,
        ),
        patch(
            "app.utils.canvas_vector_utils.delete_canvas_embedding",
            new_callable=AsyncMock,
        ) as delete,
        patch(
            "app.utils.canvas_vector_utils.store_canvas_embedding",
            new_callable=AsyncMock,
        ) as store,
    ):
        ok = await update_canvas_embedding(
            "todo-1", "stale text", "user-1", revision="2026-09-12T11:00:00+00:00"
        )

    assert ok is True
    delete.assert_not_awaited()
    store.assert_not_awaited()


@pytest.mark.regression
async def test_update_skips_write_when_equal_revision_stored() -> None:
    """A retried reindex for the same write is already satisfied — skip it."""
    raw_client = MagicMock()
    raw_client.get_collection = AsyncMock(
        return_value=_revision_collection("2026-09-12T12:00:00+00:00")
    )
    with (
        patch(
            "app.utils.canvas_vector_utils.ChromaClient.get_client",
            new_callable=AsyncMock,
            return_value=raw_client,
        ),
        patch(
            "app.utils.canvas_vector_utils.delete_canvas_embedding",
            new_callable=AsyncMock,
        ) as delete,
        patch(
            "app.utils.canvas_vector_utils.store_canvas_embedding",
            new_callable=AsyncMock,
        ) as store,
    ):
        ok = await update_canvas_embedding(
            "todo-1", "same text", "user-1", revision="2026-09-12T12:00:00+00:00"
        )

    assert ok is True
    delete.assert_not_awaited()
    store.assert_not_awaited()


@pytest.mark.regression
async def test_update_writes_when_revision_newer_and_stores_it() -> None:
    raw_client = MagicMock()
    raw_client.get_collection = AsyncMock(
        return_value=_revision_collection("2026-09-12T12:00:00+00:00")
    )
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
        ) as delete,
        patch(
            "app.utils.canvas_vector_utils.store_canvas_embedding",
            new_callable=AsyncMock,
            return_value=True,
        ) as store,
    ):
        ok = await update_canvas_embedding(
            "todo-1", "new text", "user-1", revision="2026-09-12T13:00:00+00:00"
        )

    assert ok is True
    delete.assert_awaited_once_with("todo-1")
    store.assert_awaited_once_with(
        "todo-1", "new text", "user-1", "", None, revision="2026-09-12T13:00:00+00:00"
    )


async def test_update_canvas_embedding_stores_new_content_when_metadata_lookup_fails() -> None:
    """A Chroma metadata-read failure (collection missing / offline) must not
    skip the rebuild: with no stored revision there is nothing to compare
    against, so the write proceeds and carries the new revision."""
    raw_client = MagicMock()
    raw_client.get_collection = AsyncMock(side_effect=RuntimeError("collection missing"))
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
        ) as delete,
        patch(
            "app.utils.canvas_vector_utils.store_canvas_embedding",
            new_callable=AsyncMock,
            return_value=True,
        ) as store,
    ):
        ok = await update_canvas_embedding(
            "todo-1", "new text", "user-1", revision="2026-09-12T13:00:00+00:00"
        )

    assert ok is True
    delete.assert_awaited_once_with("todo-1")
    store.assert_awaited_once_with(
        "todo-1", "new text", "user-1", "", None, revision="2026-09-12T13:00:00+00:00"
    )


async def test_update_canvas_embedding_forwards_title_and_labels() -> None:
    """Every forwarded argument is pinned: title and labels reach the store
    unchanged (dropping either was previously invisible)."""
    raw_client = MagicMock()
    raw_client.get_collection = AsyncMock(side_effect=RuntimeError("collection missing"))
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
    ):
        await update_canvas_embedding(
            "todo-1", "new text", "user-1", "Ship it", ["a", "b"], revision="r1"
        )

    store.assert_awaited_once_with(
        "todo-1", "new text", "user-1", "Ship it", ["a", "b"], revision="r1"
    )


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
