"""Integration tests for Tool Registry & Semantic Retrieval (ChromaDB).

Tests exercise the end-to-end flow of tool indexing into ChromaDB and
semantic retrieval back out. Uses an ephemeral in-memory ChromaDB client
with a deterministic embedding function to avoid external dependencies.

Key production modules under test
----------------------------------
- app.db.chroma.chroma_store.ChromaStore
- app.db.chroma.chroma_tools_store.index_tools_to_store
- app.db.chroma.chroma_tools_store._compute_tool_diff
- app.db.chroma.chroma_tools_store._build_put_operations
- app.db.chroma.chroma_tools_store._get_existing_tools_from_chroma
- app.agents.tools.core.registry.ToolRegistry
- app.agents.tools.core.registry.ToolCategory
- app.agents.tools.core.registry.Tool
"""

from unittest.mock import AsyncMock, MagicMock, patch

import chromadb
import numpy as np
import pytest
from langchain_core.embeddings import Embeddings
from langchain_core.tools import BaseTool, tool
from langgraph.store.base import GetOp, PutOp, SearchOp

from app.agents.tools.core.registry import ToolCategory, ToolRegistry
from app.db.chroma.chroma_store import ChromaStore
from app.db.chroma.chroma_tools_store import (
    _build_put_operations,
    _compute_tool_diff,
    _get_existing_tools_from_chroma,
    index_tools_to_store,
)


# ---------------------------------------------------------------------------
# Deterministic embedding function for semantic retrieval tests
# ---------------------------------------------------------------------------

# Keyword-to-vector mapping for deterministic semantic similarity.
# Tools with overlapping keywords will have closer embeddings.
_KEYWORD_VECTORS = {
    "email": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "send": [0.8, 0.3, 0.0, 0.0, 0.0, 0.0, 0.2, 0.0],
    "message": [0.7, 0.4, 0.0, 0.0, 0.0, 0.0, 0.3, 0.0],
    "slack": [0.3, 0.9, 0.0, 0.0, 0.0, 0.0, 0.2, 0.0],
    "calendar": [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "event": [0.0, 0.0, 0.9, 0.2, 0.0, 0.0, 0.0, 0.0],
    "create": [0.0, 0.0, 0.3, 0.3, 0.0, 0.0, 0.3, 0.0],
    "todo": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
    "weather": [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
    "search": [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
    "web": [0.0, 0.0, 0.0, 0.0, 0.0, 0.9, 0.0, 0.1],
    "colleague": [0.6, 0.5, 0.0, 0.0, 0.0, 0.0, 0.3, 0.0],
    "post": [0.3, 0.5, 0.0, 0.0, 0.0, 0.0, 0.4, 0.0],
    "notification": [0.2, 0.3, 0.0, 0.0, 0.0, 0.0, 0.5, 0.3],
    "file": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
    "upload": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.1, 0.9],
    "download": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.1, 0.8],
    "delete": [0.0, 0.0, 0.0, 0.2, 0.0, 0.0, 0.1, 0.1],
    "reminder": [0.0, 0.0, 0.2, 0.3, 0.0, 0.0, 0.5, 0.0],
    "image": [0.0, 0.0, 0.0, 0.0, 0.0, 0.3, 0.0, 0.6],
    "generate": [0.0, 0.0, 0.0, 0.0, 0.0, 0.2, 0.3, 0.3],
}

EMBEDDING_DIMS = 8


def _text_to_embedding(text: str) -> list[float]:
    """Convert text to a deterministic embedding by averaging keyword vectors."""
    words = text.lower().replace(",", " ").replace(".", " ").split()
    vectors = [_KEYWORD_VECTORS.get(w, [0.0] * EMBEDDING_DIMS) for w in words]
    if not vectors:
        return [0.0] * EMBEDDING_DIMS
    arr = np.mean(vectors, axis=0)
    # Normalize to unit vector for cosine similarity
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm
    return arr.tolist()


class _DeterministicEmbeddings(Embeddings):
    """Mock embeddings extending langchain Embeddings for compatibility.

    langgraph's ensure_embeddings() checks isinstance(embed, Embeddings)
    and returns it as-is. Without this base class, it wraps the object
    in EmbeddingsLambda which expects a callable, causing failures.
    """

    def embed_query(self, text: str) -> list[float]:
        return _text_to_embedding(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [_text_to_embedding(t) for t in texts]

    async def aembed_query(self, text: str) -> list[float]:
        return _text_to_embedding(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [_text_to_embedding(t) for t in texts]


# ---------------------------------------------------------------------------
# Async wrapper for synchronous EphemeralClient (same pattern as test_chroma_store.py)
# ---------------------------------------------------------------------------


class _NoOpEmbeddingFunction:
    def __call__(self, input: list[str]) -> list[list[float]]:
        return [[0.0] * 384 for _ in input]


_NOOP_EF = _NoOpEmbeddingFunction()


class _AsyncCollectionWrapper:
    """Thin async wrapper around a synchronous chromadb Collection."""

    def __init__(self, sync_col):
        self._sync = sync_col
        self.name = sync_col.name

    async def upsert(self, *args, **kwargs):
        return self._sync.upsert(*args, **kwargs)

    async def get(self, *args, **kwargs):
        return self._sync.get(*args, **kwargs)

    async def delete(self, *args, **kwargs):
        return self._sync.delete(*args, **kwargs)

    async def query(self, *args, **kwargs):
        return self._sync.query(*args, **kwargs)

    async def count(self, *args, **kwargs):
        return self._sync.count(*args, **kwargs)


class _AsyncEphemeralWrapper:
    """Async interface backed by a synchronous chromadb.EphemeralClient."""

    def __init__(self):
        self._sync = chromadb.EphemeralClient()

    async def list_collections(self):
        return self._sync.list_collections()

    async def create_collection(self, name, metadata=None, **kwargs):
        kwargs.setdefault("embedding_function", _NOOP_EF)
        col = self._sync.create_collection(name, metadata=metadata, **kwargs)
        return _AsyncCollectionWrapper(col)

    async def get_collection(self, name, **kwargs):
        kwargs.setdefault("embedding_function", _NOOP_EF)
        col = self._sync.get_collection(name, **kwargs)
        return _AsyncCollectionWrapper(col)

    async def get_or_create_collection(self, name, metadata=None, **kwargs):
        kwargs.setdefault("embedding_function", _NOOP_EF)
        col = self._sync.get_or_create_collection(name, metadata=metadata, **kwargs)
        return _AsyncCollectionWrapper(col)

    async def delete_collection(self, name):
        return self._sync.delete_collection(name)

    async def reset(self):
        return self._sync.reset()


# ---------------------------------------------------------------------------
# Helper: create mock LangChain tools with known schemas
# ---------------------------------------------------------------------------


def _make_tool(name: str, description: str) -> BaseTool:
    """Create a minimal BaseTool with a given name and description."""

    @tool(name, description=description)
    def _dummy_tool(input_text: str) -> str:
        return f"{name}: {input_text}"

    return _dummy_tool  # type: ignore[return-value]


# Pre-built tool set for semantic retrieval tests
TOOL_DEFS = {
    "send_email": "Send an email message to a recipient",
    "create_calendar_event": "Create a new calendar event or meeting",
    "post_slack_message": "Post a message to a Slack channel",
    "create_todo": "Create a new todo task item",
    "get_weather": "Get the current weather forecast",
    "web_search": "Search the web for information",
    "upload_file": "Upload a file to cloud storage",
    "download_file": "Download a file from cloud storage",
    "generate_image": "Generate an image from a text description",
    "create_reminder": "Create a reminder notification",
    "send_notification": "Send a push notification message",
    "delete_todo": "Delete an existing todo task",
    "search_emails": "Search through email messages",
    "reply_email": "Reply to an email message",
    "schedule_meeting": "Schedule a calendar meeting event",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ephemeral_client():
    """Return a fresh async-wrapped ephemeral ChromaDB client per test."""
    client = _AsyncEphemeralWrapper()
    yield client
    collections = client._sync.list_collections()
    for col in collections:
        client._sync.delete_collection(col.name)


@pytest.fixture
async def semantic_store(ephemeral_client):
    """Return a ChromaStore with deterministic embeddings for semantic search."""
    embeddings = _DeterministicEmbeddings()
    store = ChromaStore(
        client=ephemeral_client,
        collection_name="test_tools_semantic",
        index={
            "embed": embeddings,
            "dims": EMBEDDING_DIMS,
            "fields": ["description"],
        },
    )
    return store


@pytest.fixture
def tool_set() -> dict[str, BaseTool]:
    """Build a dict of named tools from TOOL_DEFS."""
    return {name: _make_tool(name, desc) for name, desc in TOOL_DEFS.items()}


@pytest.fixture
async def indexed_store(semantic_store, tool_set):
    """Return a semantic store pre-indexed with all tools from TOOL_DEFS."""
    put_ops = [
        PutOp(
            namespace=("general",),
            key=name,
            value={"description": t.description, "tool_hash": f"hash_{name}"},
            index=["description"],
        )
        for name, t in tool_set.items()
    ]
    await semantic_store.abatch(put_ops)
    return semantic_store


# ---------------------------------------------------------------------------
# TEST 1: Tool Indexing
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestToolIndexing:
    """Register tools with known schemas and verify they are stored in ChromaDB."""

    async def test_tools_stored_after_put(self, semantic_store, tool_set):
        """PutOp with tool descriptions should store tools retrievable by GetOp."""
        tools_to_index = ["send_email", "create_calendar_event", "post_slack_message"]
        put_ops = [
            PutOp(
                namespace=("general",),
                key=name,
                value={
                    "description": tool_set[name].description,
                    "tool_hash": f"hash_{name}",
                },
                index=["description"],
            )
            for name in tools_to_index
        ]
        await semantic_store.abatch(put_ops)

        # Verify each tool is retrievable
        for name in tools_to_index:
            results = await semantic_store.abatch(
                [GetOp(namespace=("general",), key=name)]
            )
            assert results[0] is not None, f"Tool '{name}' was not stored"
            assert results[0].key == name
            assert results[0].value["description"] == tool_set[name].description

    async def test_index_tools_to_store_production_function(self, ephemeral_client):
        """index_tools_to_store should write tools into the ChromaStore."""
        embeddings = _DeterministicEmbeddings()
        store = ChromaStore(
            client=ephemeral_client,
            collection_name="index_test_col",
            index={
                "embed": embeddings,
                "dims": EMBEDDING_DIMS,
                "fields": ["description"],
            },
        )

        tools = [
            _make_tool("tool_a", "Tool A description"),
            _make_tool("tool_b", "Tool B description"),
        ]
        tools_with_space = [(t, "general") for t in tools]

        with (
            patch(
                "app.db.chroma.chroma_tools_store.providers.aget",
                new_callable=AsyncMock,
                return_value=store,
            ),
            patch(
                "app.db.chroma.chroma_tools_store.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.db.chroma.chroma_tools_store.set_cache",
                new_callable=AsyncMock,
            ),
        ):
            await index_tools_to_store(tools_with_space)

        # Verify tools are in the store
        result_a = await store.abatch([GetOp(namespace=("general",), key="tool_a")])
        result_b = await store.abatch([GetOp(namespace=("general",), key="tool_b")])
        assert result_a[0] is not None
        assert result_b[0] is not None
        assert result_a[0].value["description"] == "Tool A description"
        assert result_b[0].value["description"] == "Tool B description"

    async def test_index_tools_to_store_skips_on_cache_hit(self, ephemeral_client):
        """index_tools_to_store should skip indexing when Redis cache matches."""
        embeddings = _DeterministicEmbeddings()
        store = ChromaStore(
            client=ephemeral_client,
            collection_name="cache_test_col",
            index={
                "embed": embeddings,
                "dims": EMBEDDING_DIMS,
                "fields": ["description"],
            },
        )

        tools = [_make_tool("cached_tool", "A cached tool")]
        tools_with_space = [(t, "testns") for t in tools]

        # Compute the expected hash to simulate a cache hit
        import hashlib

        tools_signature = "|".join(
            f"{t.name}:{getattr(t, 'description', '')[:200]}"
            for t, _ in tools_with_space
        )
        expected_hash = hashlib.sha256(tools_signature.encode()).hexdigest()[:16]

        with (
            patch(
                "app.db.chroma.chroma_tools_store.providers.aget",
                new_callable=AsyncMock,
                return_value=store,
            ),
            patch(
                "app.db.chroma.chroma_tools_store.get_cache",
                new_callable=AsyncMock,
                return_value=expected_hash,
            ),
            patch(
                "app.db.chroma.chroma_tools_store.set_cache",
                new_callable=AsyncMock,
            ) as mock_set_cache,
        ):
            await index_tools_to_store(tools_with_space)

        # set_cache should not be called because we skipped indexing
        mock_set_cache.assert_not_called()

        # Tool should NOT be in the store (indexing was skipped)
        result = await store.abatch([GetOp(namespace=("testns",), key="cached_tool")])
        assert result[0] is None


# ---------------------------------------------------------------------------
# TEST 2: Semantic Retrieval Accuracy
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSemanticRetrievalAccuracy:
    """Index tools and query semantically to verify ranking accuracy."""

    async def test_message_query_returns_communication_tools(self, indexed_store):
        """Query 'send a message to my colleague' should rank communication tools highest."""
        results = await indexed_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("general",),
                    query="send a message to my colleague",
                    limit=5,
                    offset=0,
                )
            ]
        )

        items = results[0]
        assert isinstance(items, list)
        assert len(items) > 0

        top_tool_names = [item.key for item in items[:5]]
        # At least one communication tool should be in top results
        communication_tools = {
            "send_email",
            "post_slack_message",
            "send_notification",
        }
        found_communication = set(top_tool_names) & communication_tools
        assert len(found_communication) > 0, (
            f"Expected communication tools in top 5, got: {top_tool_names}"
        )

    async def test_calendar_query_returns_calendar_tools(self, indexed_store):
        """Query 'schedule a meeting' should rank calendar tools highly."""
        results = await indexed_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("general",),
                    query="create a calendar event",
                    limit=5,
                    offset=0,
                )
            ]
        )

        items = results[0]
        assert len(items) > 0
        top_tool_names = [item.key for item in items[:5]]
        calendar_tools = {"create_calendar_event", "schedule_meeting"}
        found_calendar = set(top_tool_names) & calendar_tools
        assert len(found_calendar) > 0, (
            f"Expected calendar tools in top 5, got: {top_tool_names}"
        )

    async def test_file_query_returns_file_tools(self, indexed_store):
        """Query 'upload a file' should rank file-related tools highest."""
        results = await indexed_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("general",),
                    query="upload a file",
                    limit=5,
                    offset=0,
                )
            ]
        )

        items = results[0]
        assert len(items) > 0
        top_tool_names = [item.key for item in items[:3]]
        file_tools = {"upload_file", "download_file"}
        found_file = set(top_tool_names) & file_tools
        assert len(found_file) > 0, (
            f"Expected file tools in top 3, got: {top_tool_names}"
        )


# ---------------------------------------------------------------------------
# TEST 3: Tool Deduplication
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestToolDeduplication:
    """Register same tool twice and verify no duplicates in retrieval."""

    async def test_double_put_does_not_create_duplicates(self, semantic_store):
        """Upserting the same tool key twice should result in a single entry."""
        put_op = PutOp(
            namespace=("general",),
            key="send_email",
            value={"description": "Send an email message", "tool_hash": "hash_v1"},
            index=["description"],
        )
        await semantic_store.abatch([put_op])
        await semantic_store.abatch([put_op])

        # Search should return only one result for this key
        results = await semantic_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("general",),
                    query="send email",
                    limit=10,
                    offset=0,
                )
            ]
        )

        items = results[0]
        keys = [item.key for item in items]
        assert keys.count("send_email") == 1, (
            f"Expected exactly 1 'send_email', got {keys.count('send_email')} in {keys}"
        )

    async def test_compute_tool_diff_marks_same_hash_as_unchanged(self):
        """_compute_tool_diff should not upsert a tool with the same hash."""
        mock_tool = MagicMock()
        mock_tool.name = "dup_tool"
        mock_tool.description = "A tool"

        current = {
            "general::dup_tool": {
                "hash": "same_hash",
                "namespace": "general",
                "tool": mock_tool,
            }
        }
        existing = {"general::dup_tool": {"hash": "same_hash", "namespace": "general"}}

        to_upsert, to_delete = _compute_tool_diff(current, existing)
        assert len(to_upsert) == 0
        assert len(to_delete) == 0


# ---------------------------------------------------------------------------
# TEST 4: Retrieval After Additions
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRetrievalAfterAdditions:
    """Index tools, add more, verify all are searchable."""

    async def test_original_tools_still_searchable_after_additions(
        self, semantic_store, tool_set
    ):
        """Index 10 tools, add 5 more, verify all 15 are in the store and searchable."""
        tool_names = list(tool_set.keys())
        first_batch = tool_names[:10]
        second_batch = tool_names[10:15]

        # Index first batch
        first_ops = [
            PutOp(
                namespace=("general",),
                key=name,
                value={
                    "description": tool_set[name].description,
                    "tool_hash": f"hash_{name}",
                },
                index=["description"],
            )
            for name in first_batch
        ]
        await semantic_store.abatch(first_ops)

        # Verify first batch tools are retrievable
        for name in first_batch:
            result = await semantic_store.abatch(
                [GetOp(namespace=("general",), key=name)]
            )
            assert result[0] is not None, f"Tool '{name}' missing after first batch"

        # Index second batch
        second_ops = [
            PutOp(
                namespace=("general",),
                key=name,
                value={
                    "description": tool_set[name].description,
                    "tool_hash": f"hash_{name}",
                },
                index=["description"],
            )
            for name in second_batch
        ]
        await semantic_store.abatch(second_ops)

        # Verify ALL tools are still retrievable (originals not degraded)
        for name in first_batch + second_batch:
            result = await semantic_store.abatch(
                [GetOp(namespace=("general",), key=name)]
            )
            assert result[0] is not None, f"Tool '{name}' missing after second batch"

        # Verify semantic search returns results from both batches
        results = await semantic_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("general",),
                    query="send email message",
                    limit=15,
                    offset=0,
                )
            ]
        )
        items = results[0]
        assert len(items) > 0, "Semantic search returned no results after additions"

    async def test_search_covers_newly_added_tools(self, semantic_store):
        """A tool added after the initial batch should be findable via semantic search."""
        # Add initial tool
        await semantic_store.abatch(
            [
                PutOp(
                    namespace=("general",),
                    key="get_weather",
                    value={
                        "description": "Get the current weather forecast",
                        "tool_hash": "hash_weather",
                    },
                    index=["description"],
                )
            ]
        )

        # Add a new tool
        await semantic_store.abatch(
            [
                PutOp(
                    namespace=("general",),
                    key="create_todo",
                    value={
                        "description": "Create a new todo task item",
                        "tool_hash": "hash_todo",
                    },
                    index=["description"],
                )
            ]
        )

        # Search for the newly added tool
        results = await semantic_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("general",),
                    query="create a todo task",
                    limit=5,
                    offset=0,
                )
            ]
        )
        items = results[0]
        tool_keys = [item.key for item in items]
        assert "create_todo" in tool_keys, (
            f"Newly added 'create_todo' not found in search results: {tool_keys}"
        )


# ---------------------------------------------------------------------------
# TEST 5: Ambiguous Query Handling
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAmbiguousQueryHandling:
    """Query 'send' should return multiple communication tools."""

    async def test_ambiguous_query_returns_multiple_results(self, indexed_store):
        """A broad query like 'send' should return multiple communication tools."""
        results = await indexed_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("general",),
                    query="send",
                    limit=10,
                    offset=0,
                )
            ]
        )

        items = results[0]
        assert len(items) >= 2, (
            f"Expected at least 2 results for ambiguous 'send' query, got {len(items)}"
        )

        # Verify multiple communication-related tools appear
        tool_keys = [item.key for item in items]
        communication_tools = {
            "send_email",
            "post_slack_message",
            "send_notification",
            "reply_email",
        }
        found = set(tool_keys) & communication_tools
        assert len(found) >= 2, (
            f"Expected at least 2 communication tools for 'send', got {found} from {tool_keys}"
        )

    async def test_broad_query_returns_diverse_results(self, indexed_store):
        """A query like 'create' should return tools from different domains."""
        results = await indexed_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("general",),
                    query="create",
                    limit=10,
                    offset=0,
                )
            ]
        )

        items = results[0]
        assert len(items) >= 2, (
            f"Expected at least 2 results for 'create' query, got {len(items)}"
        )


# ---------------------------------------------------------------------------
# TEST 6: Empty Collection Query
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEmptyCollectionQuery:
    """Query before any tools are indexed should return empty, not error."""

    async def test_search_empty_store_returns_empty_list(self, semantic_store):
        """SearchOp on empty store should return an empty list, not raise."""
        results = await semantic_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("general",),
                    query="send email",
                    limit=10,
                    offset=0,
                )
            ]
        )

        items = results[0]
        assert isinstance(items, list)
        assert len(items) == 0

    async def test_get_from_empty_store_returns_none(self, semantic_store):
        """GetOp on empty store should return None."""
        results = await semantic_store.abatch(
            [GetOp(namespace=("general",), key="nonexistent")]
        )
        assert results[0] is None

    async def test_search_nonexistent_namespace_returns_empty(self, indexed_store):
        """Search in a namespace with no tools should return empty list."""
        results = await indexed_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("nonexistent_namespace",),
                    query="anything",
                    limit=10,
                    offset=0,
                )
            ]
        )
        items = results[0]
        assert isinstance(items, list)
        assert len(items) == 0


# ---------------------------------------------------------------------------
# TEST 7: Tool Schema Integrity
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestToolSchemaIntegrity:
    """Index a tool and verify schema fields are preserved exactly."""

    async def test_value_fields_preserved_after_roundtrip(self, semantic_store):
        """Tool description and tool_hash should survive put/get roundtrip."""
        description = "Send an email to a recipient with subject and body"
        tool_hash = "abc123def456"

        await semantic_store.abatch(
            [
                PutOp(
                    namespace=("general",),
                    key="send_email",
                    value={"description": description, "tool_hash": tool_hash},
                    index=["description"],
                )
            ]
        )

        results = await semantic_store.abatch(
            [GetOp(namespace=("general",), key="send_email")]
        )
        item = results[0]
        assert item is not None
        assert item.key == "send_email"
        assert item.namespace == ("general",)
        assert item.value["description"] == description
        assert item.value["tool_hash"] == tool_hash

    async def test_build_put_operations_preserves_description(self):
        """_build_put_operations should carry the tool description into PutOp.value."""
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A specific tool description that must be preserved"

        tools_to_upsert = [
            (
                "general::test_tool",
                {
                    "hash": "test_hash",
                    "namespace": "general",
                    "tool": mock_tool,
                },
            )
        ]
        put_ops = _build_put_operations(tools_to_upsert, [])

        assert len(put_ops) == 1
        op = put_ops[0]
        assert op.namespace == ("general",)
        assert op.key == "test_tool"
        assert (
            op.value["description"]
            == "A specific tool description that must be preserved"
        )
        assert op.value["tool_hash"] == "test_hash"

    async def test_schema_integrity_through_search(self, semantic_store):
        """Tool values should be intact when retrieved via SearchOp."""
        description = "Search the web for relevant information"
        await semantic_store.abatch(
            [
                PutOp(
                    namespace=("general",),
                    key="web_search",
                    value={
                        "description": description,
                        "tool_hash": "ws_hash_123",
                    },
                    index=["description"],
                )
            ]
        )

        results = await semantic_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("general",),
                    query="search the web",
                    limit=5,
                    offset=0,
                )
            ]
        )

        items = results[0]
        assert len(items) == 1
        assert items[0].key == "web_search"
        assert items[0].value["description"] == description
        assert items[0].value["tool_hash"] == "ws_hash_123"


# ---------------------------------------------------------------------------
# TEST 8: Retrieval with Namespace Filtering
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRetrievalWithNamespaceFiltering:
    """Test that namespace filtering isolates tools correctly."""

    async def test_tools_in_different_namespaces_are_isolated(self, semantic_store):
        """Tools in namespace 'gmail' should not appear in 'slack' namespace search."""
        await semantic_store.abatch(
            [
                PutOp(
                    namespace=("gmail",),
                    key="send_email",
                    value={
                        "description": "Send an email via Gmail",
                        "tool_hash": "h_gmail",
                    },
                    index=["description"],
                ),
                PutOp(
                    namespace=("slack",),
                    key="post_message",
                    value={
                        "description": "Post a message to Slack",
                        "tool_hash": "h_slack",
                    },
                    index=["description"],
                ),
            ]
        )

        # Search gmail namespace
        gmail_results = await semantic_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("gmail",),
                    query="send a message",
                    limit=10,
                    offset=0,
                )
            ]
        )
        gmail_keys = [item.key for item in gmail_results[0]]
        assert "send_email" in gmail_keys
        assert "post_message" not in gmail_keys

        # Search slack namespace
        slack_results = await semantic_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("slack",),
                    query="send a message",
                    limit=10,
                    offset=0,
                )
            ]
        )
        slack_keys = [item.key for item in slack_results[0]]
        assert "post_message" in slack_keys
        assert "send_email" not in slack_keys

    async def test_get_existing_tools_filters_by_namespace(self, ephemeral_client):
        """_get_existing_tools_from_chroma should respect namespace filter."""
        col = await ephemeral_client.create_collection(
            "filter_test", metadata={"hnsw:space": "cosine"}
        )
        await col.upsert(
            ids=["general::tool_a", "gmail::tool_b", "slack::tool_c"],
            documents=["d", "d", "d"],
            metadatas=[
                {"namespace": "general", "tool_hash": "h_a"},
                {"namespace": "gmail", "tool_hash": "h_b"},
                {"namespace": "slack", "tool_hash": "h_c"},
            ],
        )

        # Filter to general only
        result = await _get_existing_tools_from_chroma(col, namespaces={"general"})
        assert "general::tool_a" in result
        assert "gmail::tool_b" not in result
        assert "slack::tool_c" not in result

        # Filter to multiple namespaces
        result = await _get_existing_tools_from_chroma(
            col, namespaces={"gmail", "slack"}
        )
        assert "general::tool_a" not in result
        assert "gmail::tool_b" in result
        assert "slack::tool_c" in result

    async def test_namespace_search_with_no_results(self, semantic_store):
        """Searching a namespace with no tools should return empty list."""
        await semantic_store.abatch(
            [
                PutOp(
                    namespace=("gmail",),
                    key="send_email",
                    value={"description": "Send email", "tool_hash": "h1"},
                    index=["description"],
                )
            ]
        )

        results = await semantic_store.abatch(
            [
                SearchOp(
                    namespace_prefix=("empty_namespace",),
                    query="send email",
                    limit=10,
                    offset=0,
                )
            ]
        )
        assert results[0] == []


# ---------------------------------------------------------------------------
# TEST: ToolRegistry and ToolCategory (unit-level, no ChromaDB)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestToolRegistryCategories:
    """Test ToolRegistry and ToolCategory organization without full setup."""

    def test_tool_category_add_and_retrieve(self):
        """ToolCategory should store tools and return them via get_tool_objects."""
        category = ToolCategory(name="test_cat", space="general")
        t1 = _make_tool("tool_a", "Tool A")
        t2 = _make_tool("tool_b", "Tool B")
        category.add_tools([t1, t2])

        tool_objects = category.get_tool_objects()
        assert len(tool_objects) == 2
        names = {t.name for t in tool_objects}
        assert names == {"tool_a", "tool_b"}

    def test_tool_category_core_tools_filtering(self):
        """ToolCategory.get_core_tools should return only core-flagged tools."""
        category = ToolCategory(name="mixed", space="general")
        core_tool = _make_tool("core_tool", "Core tool")
        regular_tool = _make_tool("regular_tool", "Regular tool")
        category.add_tool(core_tool, is_core=True)
        category.add_tool(regular_tool, is_core=False)

        core_only = category.get_core_tools()
        assert len(core_only) == 1
        assert core_only[0].name == "core_tool"

    def test_registry_add_and_get_category(self):
        """ToolRegistry._add_category should create a retrievable category."""
        registry = ToolRegistry()
        t1 = _make_tool("my_tool", "My tool")
        registry._add_category(
            name="custom",
            tools=[t1],
            space="custom_space",
        )

        category = registry.get_category("custom")
        assert category is not None
        assert category.space == "custom_space"
        assert len(category.tools) == 1

    def test_registry_get_category_by_space(self):
        """get_category_by_space should return the category matching the space."""
        registry = ToolRegistry()
        registry._add_category(name="cat_a", tools=[], space="space_a")
        registry._add_category(name="cat_b", tools=[], space="space_b")

        result = registry.get_category_by_space("space_b")
        assert result is not None
        assert result.name == "cat_b"

        assert registry.get_category_by_space("nonexistent") is None

    def test_registry_get_tool_names(self):
        """get_tool_names should return all tool names from all categories."""
        registry = ToolRegistry()
        t1 = _make_tool("alpha", "Alpha tool")
        t2 = _make_tool("beta", "Beta tool")
        t3 = _make_tool("gamma", "Gamma tool")
        registry._add_category(name="cat1", tools=[t1, t2], space="general")
        registry._add_category(name="cat2", tools=[t3], space="other")

        names = registry.get_tool_names()
        assert set(names) == {"alpha", "beta", "gamma"}

    def test_registry_get_category_of_tool(self):
        """get_category_of_tool should return the category name for a known tool."""
        registry = ToolRegistry()
        t1 = _make_tool("special_tool", "Special")
        registry._add_category(name="special_cat", tools=[t1], space="general")

        assert registry.get_category_of_tool("special_tool") == "special_cat"
        assert registry.get_category_of_tool("unknown_tool") == "unknown"

    def test_registry_delegated_tools_excluded_when_flag_false(self):
        """get_all_tools_for_search with include_delegated=False should skip delegated categories."""
        registry = ToolRegistry()
        t_regular = _make_tool("regular", "Regular tool")
        t_delegated = _make_tool("delegated", "Delegated tool")
        registry._add_category(name="reg_cat", tools=[t_regular], space="general")
        registry._add_category(
            name="del_cat",
            tools=[t_delegated],
            space="delegated_space",
            is_delegated=True,
        )

        all_tools = registry.get_all_tools_for_search(include_delegated=True)
        assert len(all_tools) == 2

        non_delegated = registry.get_all_tools_for_search(include_delegated=False)
        assert len(non_delegated) == 1
        assert non_delegated[0].name == "regular"
