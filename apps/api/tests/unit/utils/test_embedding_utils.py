"""Unit tests for app.utils.embedding_utils — embedding cache and similarity search."""

from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from langchain_core.documents import Document

from app.utils.embedding_utils import (
    get_or_compute_embeddings,
    search_by_similarity,
    search_documents_by_similarity,
    search_notes_by_similarity,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_tool(
    name: str = "my_tool",
    description: str = "does stuff",
    func: Any = None,
    callable_self: bool = True,
) -> MagicMock:
    """Create a mock tool with configurable attributes."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    if func is not None:
        tool.func = func
    else:
        # Remove the func attribute so hasattr returns False
        del tool.func
    # By default tools are callable; override when needed
    if not callable_self:
        tool.__call__ = None  # type: ignore[method-assign, assignment]
        tool.configure_mock(**{"__call__": None})
    return tool


def _make_document(
    page_content: str,
    metadata: Dict[str, Any],
) -> Document:
    return Document(page_content=page_content, metadata=metadata)


@pytest.fixture()
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def mock_embeddings() -> MagicMock:
    emb = MagicMock()
    emb.embed_documents = MagicMock(return_value=[[0.1, 0.2], [0.3, 0.4]])
    return emb


@pytest.fixture()
def mock_chroma_collection() -> AsyncMock:
    return AsyncMock()


# ---------------------------------------------------------------------------
# get_or_compute_embeddings
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetOrComputeEmbeddings:
    """Tests for get_or_compute_embeddings."""

    async def test_cache_hit_returns_cached_embeddings(
        self, mock_redis: AsyncMock, mock_embeddings: MagicMock
    ) -> None:
        """When Redis has cached embeddings, return them without computing."""
        cached = [[0.5, 0.6], [0.7, 0.8]]
        mock_redis.get = AsyncMock(return_value=cached)

        tool = _make_tool(name="alpha", description="do alpha things")

        with patch("app.utils.embedding_utils.redis_cache", mock_redis):
            result_embeddings, result_descriptions = await get_or_compute_embeddings(
                [tool], mock_embeddings
            )

        assert result_embeddings == cached
        assert len(result_descriptions) == 1
        assert "alpha" in result_descriptions[0]
        # embed_documents should NOT have been called
        mock_embeddings.embed_documents.assert_not_called()

    async def test_cache_miss_computes_and_caches(
        self, mock_redis: AsyncMock, mock_embeddings: MagicMock
    ) -> None:
        """When cache is empty, compute embeddings and store them."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        tool = _make_tool(name="beta", description="do beta things")

        with patch("app.utils.embedding_utils.redis_cache", mock_redis):
            result_embeddings, result_descriptions = await get_or_compute_embeddings(
                [tool], mock_embeddings
            )

        # Should return the freshly computed embeddings
        assert result_embeddings == [[0.1, 0.2], [0.3, 0.4]]
        mock_embeddings.embed_documents.assert_called_once()
        # Should cache with 7-day TTL
        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.call_args
        assert (
            call_args[1].get("ttl", call_args[0][2] if len(call_args[0]) > 2 else None)
            == 604800
        )

    async def test_tool_with_no_name_uses_fallback(
        self, mock_redis: AsyncMock, mock_embeddings: MagicMock
    ) -> None:
        """A tool missing the 'name' attr should fall back to empty string for sorting."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        tool = MagicMock(spec=[])  # no attributes at all
        tool.description = "anonymous"
        # getattr(tool, "name", ...) will use fallback since spec=[] has no name
        # But the production code accesses tool.name directly in the description line,
        # so we need name to exist to avoid AttributeError
        tool.name = None  # exists but is None-ish

        # The sorted() key uses getattr(t, "name", "") — None is valid
        # But description line does f"{tool.name}: {tool.description}"
        with patch("app.utils.embedding_utils.redis_cache", mock_redis):
            result_embeddings, result_descriptions = await get_or_compute_embeddings(
                [tool], mock_embeddings
            )

        assert len(result_descriptions) == 1
        assert "anonymous" in result_descriptions[0]

    async def test_getsource_fails_uses_no_source_fallback(
        self, mock_redis: AsyncMock, mock_embeddings: MagicMock
    ) -> None:
        """When inspect.getsource raises OSError, tool hash uses 'no_source' fallback."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        tool = _make_tool(name="builtin_tool", description="a built-in")

        with (
            patch("app.utils.embedding_utils.redis_cache", mock_redis),
            patch(
                "app.utils.embedding_utils.inspect.getsource",
                side_effect=OSError("cannot get source"),
            ),
        ):
            result_embeddings, result_descriptions = await get_or_compute_embeddings(
                [tool], mock_embeddings
            )

        assert result_embeddings == [[0.1, 0.2], [0.3, 0.4]]
        assert "builtin_tool" in result_descriptions[0]

    async def test_getsource_type_error_uses_no_source_fallback(
        self, mock_redis: AsyncMock, mock_embeddings: MagicMock
    ) -> None:
        """When inspect.getsource raises TypeError, tool hash uses 'no_source' fallback."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        tool = _make_tool(name="lambda_tool", description="a lambda")

        with (
            patch("app.utils.embedding_utils.redis_cache", mock_redis),
            patch(
                "app.utils.embedding_utils.inspect.getsource",
                side_effect=TypeError("not a module"),
            ),
        ):
            result_embeddings, _ = await get_or_compute_embeddings(
                [tool], mock_embeddings
            )

        assert result_embeddings == [[0.1, 0.2], [0.3, 0.4]]

    async def test_empty_tools_list_returns_empty(
        self, mock_redis: AsyncMock, mock_embeddings: MagicMock
    ) -> None:
        """An empty tools list should return empty embeddings and descriptions."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        # embed_documents returns [] for empty input
        mock_embeddings.embed_documents = MagicMock(return_value=[])

        with patch("app.utils.embedding_utils.redis_cache", mock_redis):
            result_embeddings, result_descriptions = await get_or_compute_embeddings(
                [], mock_embeddings
            )

        assert result_embeddings == []
        assert result_descriptions == []

    async def test_tools_sorted_deterministically(
        self, mock_redis: AsyncMock, mock_embeddings: MagicMock
    ) -> None:
        """Tools should be sorted by name so the cache key is deterministic."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        tool_a = _make_tool(name="aaa", description="first")
        tool_b = _make_tool(name="zzz", description="last")

        with (
            patch("app.utils.embedding_utils.redis_cache", mock_redis),
            patch(
                "app.utils.embedding_utils.inspect.getsource",
                return_value="def f(): pass",
            ),
        ):
            # Pass in reverse order — should still produce same cache key
            await get_or_compute_embeddings([tool_b, tool_a], mock_embeddings)
            call1_cache_key = mock_redis.set.call_args[0][0]

            mock_redis.set.reset_mock()
            mock_redis.get.return_value = None

            # Pass in sorted order
            await get_or_compute_embeddings([tool_a, tool_b], mock_embeddings)
            call2_cache_key = mock_redis.set.call_args[0][0]

        assert call1_cache_key == call2_cache_key

    async def test_tool_with_func_attribute_gets_source_from_func(
        self, mock_redis: AsyncMock, mock_embeddings: MagicMock
    ) -> None:
        """When tool has a callable .func, inspect.getsource is called on tool.func."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        inner_func = MagicMock()
        inner_func.__name__ = "inner"
        tool = _make_tool(name="wrapper", description="wraps", func=inner_func)

        with (
            patch("app.utils.embedding_utils.redis_cache", mock_redis),
            patch(
                "app.utils.embedding_utils.inspect.getsource",
                return_value="def inner(): pass",
            ) as mock_getsource,
        ):
            await get_or_compute_embeddings([tool], mock_embeddings)

        # getsource should be called with tool.func, not tool itself
        mock_getsource.assert_called_once_with(inner_func)

    async def test_non_callable_tool_uses_str_representation(
        self, mock_redis: AsyncMock, mock_embeddings: MagicMock
    ) -> None:
        """A tool without .func and not callable uses str(tool) as code_source."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        tool = MagicMock()
        tool.name = "static_tool"
        tool.description = "not callable"
        # Remove func attribute
        del tool.func
        # Make tool not callable
        tool.__class__ = type(
            "NonCallable",
            (),
            {
                "name": "static_tool",
                "description": "not callable",
                "__str__": lambda self: "static_repr",
            },
        )

        with (
            patch("app.utils.embedding_utils.redis_cache", mock_redis),
        ):
            result_embeddings, _ = await get_or_compute_embeddings(
                [tool], mock_embeddings
            )

        assert result_embeddings == [[0.1, 0.2], [0.3, 0.4]]


# ---------------------------------------------------------------------------
# search_by_similarity
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchBySimilarity:
    """Tests for search_by_similarity."""

    async def test_success_with_results(self) -> None:
        """Returns formatted list of items when ChromaDB returns results."""
        doc = _make_document(
            page_content="my note content",
            metadata={"note_id": "abc123", "user_id": "user1"},
        )
        mock_collection = AsyncMock()
        mock_collection.asimilarity_search_with_score = AsyncMock(
            return_value=[(doc, 0.25)]
        )

        with (
            patch(
                "app.utils.embedding_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                return_value=mock_collection,
            ),
            patch("app.utils.embedding_utils.log"),
        ):
            results = await search_by_similarity(
                input_text="search query",
                user_id="user1",
                collection_name="notes",
            )

        assert len(results) == 1
        assert results[0]["id"] == "abc123"
        assert results[0]["similarity_score"] == pytest.approx(0.25)
        assert results[0]["content"] == "my note content"
        assert results[0]["user_id"] == "user1"

    async def test_no_results_returns_empty_list(self) -> None:
        """Returns empty list when ChromaDB has no matches."""
        mock_collection = AsyncMock()
        mock_collection.asimilarity_search_with_score = AsyncMock(return_value=[])

        with (
            patch(
                "app.utils.embedding_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                return_value=mock_collection,
            ),
            patch("app.utils.embedding_utils.log"),
        ):
            results = await search_by_similarity(
                input_text="nothing matches",
                user_id="user1",
                collection_name="notes",
            )

        assert results == []

    async def test_additional_filters_applied_with_and(self) -> None:
        """When additional_filters are provided, they are combined with $and."""
        doc = _make_document(
            page_content="filtered content",
            metadata={"note_id": "f1", "user_id": "user1"},
        )
        mock_collection = AsyncMock()
        mock_collection.asimilarity_search_with_score = AsyncMock(
            return_value=[(doc, 0.1)]
        )

        with (
            patch(
                "app.utils.embedding_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                return_value=mock_collection,
            ),
            patch("app.utils.embedding_utils.log"),
        ):
            await search_by_similarity(
                input_text="query",
                user_id="user1",
                collection_name="notes",
                additional_filters={"conversation_id": "conv1"},
            )

        # Verify the filter passed to asimilarity_search_with_score
        call_kwargs = mock_collection.asimilarity_search_with_score.call_args[1]
        where_filter = call_kwargs["filter"]
        assert "$and" in where_filter
        and_clauses = where_filter["$and"]
        assert {"user_id": "user1"} in and_clauses
        assert {"conversation_id": "conv1"} in and_clauses

    async def test_no_additional_filters_uses_simple_where(self) -> None:
        """Without additional_filters, the where clause is just {user_id: ...}."""
        mock_collection = AsyncMock()
        mock_collection.asimilarity_search_with_score = AsyncMock(return_value=[])

        with (
            patch(
                "app.utils.embedding_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                return_value=mock_collection,
            ),
            patch("app.utils.embedding_utils.log"),
        ):
            await search_by_similarity(
                input_text="query",
                user_id="user1",
                collection_name="notes",
            )

        call_kwargs = mock_collection.asimilarity_search_with_score.call_args[1]
        assert call_kwargs["filter"] == {"user_id": "user1"}

    async def test_fetch_mongo_details_true_includes_mongodb_data(self) -> None:
        """When fetch_mongo_details=True, result is enriched with MongoDB fields."""
        note_id = str(ObjectId())
        doc = _make_document(
            page_content="note body",
            metadata={"note_id": note_id, "user_id": "user1"},
        )
        mock_collection = AsyncMock()
        mock_collection.asimilarity_search_with_score = AsyncMock(
            return_value=[(doc, 0.15)]
        )

        created = datetime(2026, 1, 1, 12, 0, 0)
        updated = datetime(2026, 1, 2, 12, 0, 0)
        mock_mongo_cursor = AsyncMock()
        mock_mongo_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "_id": ObjectId(note_id),
                    "user_id": "user1",
                    "title": "My Note",
                    "created_at": created,
                    "updated_at": updated,
                }
            ]
        )
        mock_notes_col = MagicMock()
        mock_notes_col.find = MagicMock(return_value=mock_mongo_cursor)

        with (
            patch(
                "app.utils.embedding_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                return_value=mock_collection,
            ),
            patch(
                "app.utils.embedding_utils.notes_collection",
                mock_notes_col,
            ),
            patch("app.utils.embedding_utils.log"),
        ):
            results = await search_by_similarity(
                input_text="query",
                user_id="user1",
                collection_name="notes",
                fetch_mongo_details=True,
            )

        assert len(results) == 1
        assert results[0]["id"] == note_id
        assert results[0]["created_at"] == created.isoformat()
        assert results[0]["updated_at"] == updated.isoformat()

    async def test_fetch_mongo_details_false_returns_chroma_data_only(self) -> None:
        """When fetch_mongo_details=False (default), only ChromaDB data is returned."""
        doc = _make_document(
            page_content="basic content",
            metadata={"note_id": "n1", "user_id": "user1"},
        )
        mock_collection = AsyncMock()
        mock_collection.asimilarity_search_with_score = AsyncMock(
            return_value=[(doc, 0.3)]
        )

        with (
            patch(
                "app.utils.embedding_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                return_value=mock_collection,
            ),
            patch("app.utils.embedding_utils.log"),
        ):
            results = await search_by_similarity(
                input_text="query",
                user_id="user1",
                collection_name="notes",
                fetch_mongo_details=False,
            )

        assert len(results) == 1
        assert results[0]["id"] == "n1"
        assert results[0]["content"] == "basic content"
        # Should NOT have timestamp fields from MongoDB
        assert "created_at" not in results[0]
        assert "updated_at" not in results[0]

    async def test_exception_returns_empty_list(self) -> None:
        """Any exception during search returns [] and logs the error."""
        with (
            patch(
                "app.utils.embedding_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                side_effect=RuntimeError("ChromaDB unavailable"),
            ),
            patch("app.utils.embedding_utils.log") as mock_log,
        ):
            results = await search_by_similarity(
                input_text="query",
                user_id="user1",
                collection_name="notes",
            )

        assert results == []
        mock_log.error.assert_called_once()

    async def test_results_sorted_by_similarity_score(self) -> None:
        """Results are sorted by similarity score ascending (lower = better)."""
        doc_high = _make_document(
            page_content="far",
            metadata={"note_id": "far1", "user_id": "user1"},
        )
        doc_low = _make_document(
            page_content="close",
            metadata={"note_id": "close1", "user_id": "user1"},
        )
        mock_collection = AsyncMock()
        # Return in worst-first order
        mock_collection.asimilarity_search_with_score = AsyncMock(
            return_value=[(doc_high, 0.9), (doc_low, 0.1)]
        )

        with (
            patch(
                "app.utils.embedding_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                return_value=mock_collection,
            ),
            patch("app.utils.embedding_utils.log"),
        ):
            results = await search_by_similarity(
                input_text="query",
                user_id="user1",
                collection_name="notes",
                top_k=5,
            )

        assert results[0]["id"] == "close1"
        assert results[1]["id"] == "far1"

    async def test_results_limited_to_top_k(self) -> None:
        """Only the top_k results are returned even if more exist."""
        docs_with_scores = [
            (
                _make_document(
                    page_content=f"content_{i}",
                    metadata={"note_id": f"id_{i}", "user_id": "user1"},
                ),
                float(i) * 0.1,
            )
            for i in range(10)
        ]
        mock_collection = AsyncMock()
        mock_collection.asimilarity_search_with_score = AsyncMock(
            return_value=docs_with_scores
        )

        with (
            patch(
                "app.utils.embedding_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                return_value=mock_collection,
            ),
            patch("app.utils.embedding_utils.log"),
        ):
            results = await search_by_similarity(
                input_text="query",
                user_id="user1",
                collection_name="notes",
                top_k=3,
            )

        assert len(results) == 3

    async def test_item_without_id_field_is_skipped(self) -> None:
        """Documents missing the expected ID field (note_id/file_id) are skipped."""
        doc_valid = _make_document(
            page_content="has id",
            metadata={"note_id": "valid1", "user_id": "user1"},
        )
        doc_no_id = _make_document(
            page_content="no id",
            metadata={"user_id": "user1"},  # missing note_id
        )
        mock_collection = AsyncMock()
        mock_collection.asimilarity_search_with_score = AsyncMock(
            return_value=[(doc_valid, 0.1), (doc_no_id, 0.2)]
        )

        with (
            patch(
                "app.utils.embedding_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                return_value=mock_collection,
            ),
            patch("app.utils.embedding_utils.log"),
        ):
            results = await search_by_similarity(
                input_text="query",
                user_id="user1",
                collection_name="notes",
            )

        assert len(results) == 1
        assert results[0]["id"] == "valid1"

    async def test_files_collection_uses_file_id_field(self) -> None:
        """When collection_name is 'files', the id_field should be 'file_id'."""
        file_id = str(ObjectId())
        doc = _make_document(
            page_content="file content",
            metadata={"file_id": file_id, "user_id": "user1"},
        )
        mock_collection = AsyncMock()
        mock_collection.asimilarity_search_with_score = AsyncMock(
            return_value=[(doc, 0.2)]
        )

        mock_mongo_cursor = AsyncMock()
        mock_mongo_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "_id": ObjectId(file_id),
                    "user_id": "user1",
                    "folder": "/docs",
                    "tags": ["important"],
                    "created_at": datetime(2026, 3, 1),
                }
            ]
        )
        mock_files_col = MagicMock()
        mock_files_col.find = MagicMock(return_value=mock_mongo_cursor)

        with (
            patch(
                "app.utils.embedding_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                return_value=mock_collection,
            ),
            patch(
                "app.utils.embedding_utils.files_collection",
                mock_files_col,
            ),
            patch("app.utils.embedding_utils.log"),
        ):
            results = await search_by_similarity(
                input_text="query",
                user_id="user1",
                collection_name="files",
                fetch_mongo_details=True,
            )

        assert len(results) == 1
        assert results[0]["id"] == file_id
        assert results[0]["folder"] == "/docs"
        assert results[0]["tags"] == ["important"]

    async def test_files_collection_folder_and_tags_defaults(self) -> None:
        """Files results default to empty folder/tags when mongo doc lacks them."""
        file_id = str(ObjectId())
        doc = _make_document(
            page_content="file content",
            metadata={"file_id": file_id, "user_id": "user1"},
        )
        mock_collection = AsyncMock()
        mock_collection.asimilarity_search_with_score = AsyncMock(
            return_value=[(doc, 0.2)]
        )

        mock_mongo_cursor = AsyncMock()
        mock_mongo_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "_id": ObjectId(file_id),
                    "user_id": "user1",
                    # no folder or tags keys
                }
            ]
        )
        mock_files_col = MagicMock()
        mock_files_col.find = MagicMock(return_value=mock_mongo_cursor)

        with (
            patch(
                "app.utils.embedding_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                return_value=mock_collection,
            ),
            patch(
                "app.utils.embedding_utils.files_collection",
                mock_files_col,
            ),
            patch("app.utils.embedding_utils.log"),
        ):
            results = await search_by_similarity(
                input_text="query",
                user_id="user1",
                collection_name="files",
                fetch_mongo_details=True,
            )

        assert results[0]["folder"] == ""
        assert results[0]["tags"] == []

    async def test_mongo_item_not_found_does_not_crash(self) -> None:
        """If MongoDB returns no match for a ChromaDB ID, the item is still returned."""
        note_id = str(ObjectId())
        doc = _make_document(
            page_content="orphan",
            metadata={"note_id": note_id, "user_id": "user1"},
        )
        mock_collection = AsyncMock()
        mock_collection.asimilarity_search_with_score = AsyncMock(
            return_value=[(doc, 0.1)]
        )

        mock_mongo_cursor = AsyncMock()
        mock_mongo_cursor.to_list = AsyncMock(return_value=[])  # nothing found
        mock_notes_col = MagicMock()
        mock_notes_col.find = MagicMock(return_value=mock_mongo_cursor)

        with (
            patch(
                "app.utils.embedding_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                return_value=mock_collection,
            ),
            patch(
                "app.utils.embedding_utils.notes_collection",
                mock_notes_col,
            ),
            patch("app.utils.embedding_utils.log"),
        ):
            results = await search_by_similarity(
                input_text="query",
                user_id="user1",
                collection_name="notes",
                fetch_mongo_details=True,
            )

        # Item should still be present, just without mongo enrichment
        assert len(results) == 1
        assert results[0]["id"] == note_id
        assert "created_at" not in results[0]

    async def test_mongo_item_without_timestamps_no_isoformat(self) -> None:
        """MongoDB doc without created_at/updated_at doesn't add those fields."""
        note_id = str(ObjectId())
        doc = _make_document(
            page_content="no dates",
            metadata={"note_id": note_id, "user_id": "user1"},
        )
        mock_collection = AsyncMock()
        mock_collection.asimilarity_search_with_score = AsyncMock(
            return_value=[(doc, 0.1)]
        )

        mock_mongo_cursor = AsyncMock()
        mock_mongo_cursor.to_list = AsyncMock(
            return_value=[
                {"_id": ObjectId(note_id), "user_id": "user1", "title": "No Dates"}
            ]
        )
        mock_notes_col = MagicMock()
        mock_notes_col.find = MagicMock(return_value=mock_mongo_cursor)

        with (
            patch(
                "app.utils.embedding_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                return_value=mock_collection,
            ),
            patch(
                "app.utils.embedding_utils.notes_collection",
                mock_notes_col,
            ),
            patch("app.utils.embedding_utils.log"),
        ):
            results = await search_by_similarity(
                input_text="query",
                user_id="user1",
                collection_name="notes",
                fetch_mongo_details=True,
            )

        assert "created_at" not in results[0]
        assert "updated_at" not in results[0]

    async def test_multiple_additional_filters(self) -> None:
        """Multiple additional_filters entries each become a separate $and clause."""
        mock_collection = AsyncMock()
        mock_collection.asimilarity_search_with_score = AsyncMock(return_value=[])

        with (
            patch(
                "app.utils.embedding_utils.ChromaClient.get_langchain_client",
                new_callable=AsyncMock,
                return_value=mock_collection,
            ),
            patch("app.utils.embedding_utils.log"),
        ):
            await search_by_similarity(
                input_text="query",
                user_id="user1",
                collection_name="notes",
                additional_filters={"tag": "work", "priority": "high"},
            )

        call_kwargs = mock_collection.asimilarity_search_with_score.call_args[1]
        where_filter = call_kwargs["filter"]
        and_clauses = where_filter["$and"]
        assert len(and_clauses) == 3  # user_id + tag + priority
        assert {"user_id": "user1"} in and_clauses
        assert {"tag": "work"} in and_clauses
        assert {"priority": "high"} in and_clauses


# ---------------------------------------------------------------------------
# search_notes_by_similarity
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchNotesBySimilarity:
    """Tests for search_notes_by_similarity wrapper."""

    async def test_delegates_to_search_by_similarity(self) -> None:
        """Calls search_by_similarity with collection='notes' and fetch_mongo_details=True."""
        expected: List[Dict[str, Any]] = [{"id": "n1", "content": "note"}]

        with patch(
            "app.utils.embedding_utils.search_by_similarity",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_search:
            result = await search_notes_by_similarity(
                input_text="find notes",
                user_id="user1",
            )

        mock_search.assert_awaited_once_with(
            input_text="find notes",
            user_id="user1",
            collection_name="notes",
            fetch_mongo_details=True,
        )
        assert result == expected


# ---------------------------------------------------------------------------
# search_documents_by_similarity
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchDocumentsBySimilarity:
    """Tests for search_documents_by_similarity wrapper."""

    async def test_without_conversation_id(self) -> None:
        """Without conversation_id, additional_filters is None."""
        expected: List[Dict[str, Any]] = [{"id": "d1", "content": "doc"}]

        with patch(
            "app.utils.embedding_utils.search_by_similarity",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_search:
            result = await search_documents_by_similarity(
                input_text="find docs",
                user_id="user1",
            )

        mock_search.assert_awaited_once_with(
            input_text="find docs",
            user_id="user1",
            collection_name="documents",
            top_k=5,
            additional_filters=None,
            fetch_mongo_details=True,
        )
        assert result == expected

    async def test_with_conversation_id(self) -> None:
        """With conversation_id, additional_filters includes the conversation_id."""
        expected: List[Dict[str, Any]] = [{"id": "d2", "content": "doc in convo"}]

        with patch(
            "app.utils.embedding_utils.search_by_similarity",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_search:
            result = await search_documents_by_similarity(
                input_text="find docs",
                user_id="user1",
                conversation_id="conv99",
            )

        mock_search.assert_awaited_once_with(
            input_text="find docs",
            user_id="user1",
            collection_name="documents",
            top_k=5,
            additional_filters={"conversation_id": "conv99"},
            fetch_mongo_details=True,
        )
        assert result == expected

    async def test_custom_top_k(self) -> None:
        """Custom top_k is forwarded to search_by_similarity."""
        with patch(
            "app.utils.embedding_utils.search_by_similarity",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_search:
            await search_documents_by_similarity(
                input_text="query",
                user_id="user1",
                top_k=20,
            )

        mock_search.assert_awaited_once_with(
            input_text="query",
            user_id="user1",
            collection_name="documents",
            top_k=20,
            additional_filters=None,
            fetch_mongo_details=True,
        )

    async def test_conversation_id_none_explicitly(self) -> None:
        """Passing conversation_id=None explicitly results in no additional_filters."""
        with patch(
            "app.utils.embedding_utils.search_by_similarity",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_search:
            await search_documents_by_similarity(
                input_text="query",
                user_id="user1",
                conversation_id=None,
            )

        call_kwargs = mock_search.call_args[1]
        assert call_kwargs["additional_filters"] is None
