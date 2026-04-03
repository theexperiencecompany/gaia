"""Integration tests for VFS (Virtual Filesystem) Operations.

Tests exercise the MongoDB-backed VFS service: write/read, path resolution,
nested paths, missing paths, large output compaction, archiving thresholds,
content integrity, artifact metadata, delete/cleanup, and summarization
middleware.

Key production modules under test
----------------------------------
- app.services.vfs.mongo_vfs.MongoVFS
- app.services.vfs.mongo_vfs.VFSAccessError
- app.services.vfs.path_resolver (normalize_path, parse_path, build_path, etc.)
- app.models.vfs_models (VFSNode, VFSNodeType, VFSListResponse, etc.)
- app.agents.middleware.vfs_compaction.VFSCompactionMiddleware
- app.agents.middleware.vfs_summarization.VFSArchivingSummarizationMiddleware
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from app.agents.middleware.vfs_compaction import VFSCompactionMiddleware
from app.agents.middleware.vfs_summarization import (
    VFSArchivingSummarizationMiddleware,
)
from app.constants.summarization import MIN_COMPACTION_SIZE
from app.models.vfs_models import VFSNodeType
from app.services.vfs.mongo_vfs import MongoVFS, VFSAccessError
from app.services.vfs.path_resolver import (
    build_path,
    get_parent_path,
    get_session_path,
    get_tool_output_path,
    normalize_path,
    parse_path,
    validate_user_access,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_USER_ID = "user_abc123"
TEST_USER_ID_2 = "user_def456"
TEST_CONVERSATION_ID = "conv_001"

# ---------------------------------------------------------------------------
# In-memory MongoDB mock that simulates a real collection
# ---------------------------------------------------------------------------


class FakeMongoCollection:
    """In-memory MongoDB collection mock that supports the subset of Motor
    operations used by MongoVFS: find_one, find, update_one, delete_one,
    delete_many with upsert, $set, $setOnInsert, $regex, and projections.
    """

    def __init__(self) -> None:
        self._docs: list[dict[str, Any]] = []
        self._id_counter = 0

    def _next_id(self) -> str:
        self._id_counter += 1
        return f"fake_id_{self._id_counter}"

    def _match(self, doc: dict[str, Any], query: dict[str, Any]) -> bool:
        for key, condition in query.items():
            if isinstance(condition, dict):
                if "$regex" in condition:
                    import re

                    if not re.search(condition["$regex"], doc.get(key, "")):
                        return False
                else:
                    return False
            else:
                if doc.get(key) != condition:
                    return False
        return True

    def _project(
        self, doc: dict[str, Any], projection: dict[str, Any] | None
    ) -> dict[str, Any]:
        if projection is None:
            return dict(doc)
        result = dict(doc)
        for field, include in projection.items():
            if include == 0 and field in result:
                del result[field]
        return result

    async def find_one(
        self, query: dict[str, Any], projection: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        for doc in self._docs:
            if self._match(doc, query):
                return self._project(doc, projection)
        return None

    def find(
        self, query: dict[str, Any], projection: dict[str, Any] | None = None
    ) -> FakeCursor:
        results = [
            self._project(d, projection) for d in self._docs if self._match(d, query)
        ]
        return FakeCursor(results)

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False
    ) -> MagicMock:
        target = None
        for doc in self._docs:
            if self._match(doc, query):
                target = doc
                break

        result = MagicMock()
        if target is not None:
            if "$set" in update:
                target.update(update["$set"])
            result.matched_count = 1
            result.modified_count = 1
            result.upserted_id = None
        elif upsert:
            new_doc: dict[str, Any] = {"_id": self._next_id()}
            new_doc.update(query)
            if "$setOnInsert" in update:
                new_doc.update(update["$setOnInsert"])
            if "$set" in update:
                new_doc.update(update["$set"])
            self._docs.append(new_doc)
            result.matched_count = 0
            result.modified_count = 0
            result.upserted_id = new_doc["_id"]
        else:
            result.matched_count = 0
            result.modified_count = 0
            result.upserted_id = None

        return result

    async def delete_one(self, query: dict[str, Any]) -> MagicMock:
        for i, doc in enumerate(self._docs):
            if self._match(doc, query):
                self._docs.pop(i)
                result = MagicMock()
                result.deleted_count = 1
                return result
        result = MagicMock()
        result.deleted_count = 0
        return result

    async def delete_many(self, query: dict[str, Any]) -> MagicMock:
        before = len(self._docs)
        self._docs = [d for d in self._docs if not self._match(d, query)]
        result = MagicMock()
        result.deleted_count = before - len(self._docs)
        return result


class FakeCursor:
    """Fake async Motor cursor supporting sort() and to_list()."""

    def __init__(self, results: list[dict[str, Any]]) -> None:
        self._results = results

    def sort(self, key: str, direction: int = 1) -> FakeCursor:
        self._results.sort(key=lambda d: d.get(key, ""), reverse=(direction == -1))
        return self

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        if length is not None:
            return self._results[:length]
        return self._results


class FakeGridFSBucket:
    """Minimal fake GridFS bucket."""

    async def upload_from_stream(
        self, filename: str, data: bytes, metadata: dict | None = None
    ) -> str:
        return "fake_gridfs_id"

    async def delete(self, file_id: Any) -> None:
        pass

    async def open_download_stream(self, file_id: Any) -> MagicMock:
        stream = MagicMock()
        stream.read = AsyncMock(return_value=b"gridfs content")
        return stream


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_collection() -> FakeMongoCollection:
    return FakeMongoCollection()


@pytest.fixture
def fake_gridfs() -> FakeGridFSBucket:
    return FakeGridFSBucket()


@pytest.fixture
def vfs(
    fake_collection: FakeMongoCollection, fake_gridfs: FakeGridFSBucket
) -> MongoVFS:
    """Create a MongoVFS instance with the MongoDB collection and GridFS bucket
    replaced by in-memory fakes."""
    with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
        instance = MongoVFS()
        instance._gridfs_bucket = fake_gridfs  # type: ignore[assignment]
        yield instance  # type: ignore[misc]


@pytest.fixture
def user_path() -> str:
    """Canonical user path prefix."""
    return f"/users/{TEST_USER_ID}"


# ---------------------------------------------------------------------------
# TEST 1: Write and read
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWriteAndRead:
    """Write artifact to VFS, read it back, verify content matches exactly."""

    async def test_write_then_read_returns_exact_content(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            content = "Hello, this is a VFS test artifact."
            path = f"/users/{TEST_USER_ID}/global/executor/notes/test.txt"

            written_path = await vfs.write(path, content, user_id=TEST_USER_ID)
            read_content = await vfs.read(path, user_id=TEST_USER_ID)

            assert written_path == normalize_path(path)
            assert read_content == content

    async def test_write_overwrites_existing_content(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            path = f"/users/{TEST_USER_ID}/global/executor/notes/overwrite.txt"

            await vfs.write(path, "original content", user_id=TEST_USER_ID)
            await vfs.write(path, "updated content", user_id=TEST_USER_ID)
            read_content = await vfs.read(path, user_id=TEST_USER_ID)

            assert read_content == "updated content"

    async def test_write_creates_parent_directories(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            path = f"/users/{TEST_USER_ID}/global/executor/sessions/conv1/agent1/deep/nested/file.json"
            await vfs.write(path, '{"key": "value"}', user_id=TEST_USER_ID)

            # Verify parent directories were created
            parent = f"/users/{TEST_USER_ID}/global/executor/sessions/conv1/agent1/deep/nested"
            parent_doc = await fake_collection.find_one(
                {"path": parent, "user_id": TEST_USER_ID}
            )
            assert parent_doc is not None
            assert parent_doc["node_type"] == VFSNodeType.FOLDER.value


# ---------------------------------------------------------------------------
# TEST 2: Path resolution
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPathResolution:
    """Write to a deep path, resolve it, verify correct document returned."""

    async def test_write_to_deep_path_and_resolve(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            path = f"/users/{TEST_USER_ID}/global/executor/sessions/{TEST_CONVERSATION_ID}/emails/thread_123.json"
            content = '{"subject": "Re: Meeting", "body": "Confirmed"}'
            await vfs.write(path, content, user_id=TEST_USER_ID)

            info = await vfs.info(path, user_id=TEST_USER_ID)
            assert info is not None
            assert info.path == normalize_path(path)
            assert info.name == "thread_123.json"
            assert info.node_type == VFSNodeType.FILE
            assert info.content_type == "application/json"

    def test_normalize_path_removes_traversal(self) -> None:
        assert normalize_path("/users/abc/../def/file.txt") == "/users/def/file.txt"
        assert normalize_path("/users/abc/./file.txt") == "/users/abc/file.txt"
        assert normalize_path("//double//slash//") == "/double/slash"

    def test_validate_user_access_blocks_other_users(self) -> None:
        assert (
            validate_user_access(f"/users/{TEST_USER_ID}/global/notes", TEST_USER_ID)
            is True
        )
        assert (
            validate_user_access(f"/users/{TEST_USER_ID_2}/global/notes", TEST_USER_ID)
            is False
        )

    def test_validate_user_access_allows_system_paths(self) -> None:
        assert (
            validate_user_access("/system/skills/github_agent/create-pr", TEST_USER_ID)
            is True
        )

    def test_parse_path_extracts_components(self) -> None:
        parsed = parse_path(f"/users/{TEST_USER_ID}/global/executor/sessions/conv1")
        assert parsed["user_id"] == TEST_USER_ID
        assert parsed["is_global"] is True
        assert parsed["agent_name"] == "executor"
        assert parsed["folder_type"] == "sessions"
        assert parsed["conversation_id"] == "conv1"

    def test_build_path_constructs_correctly(self) -> None:
        path = build_path(
            TEST_USER_ID,
            agent_name="executor",
            folder_type="sessions",
            conversation_id="conv1",
            filename="output.json",
        )
        assert path == normalize_path(
            f"/users/{TEST_USER_ID}/global/executor/sessions/conv1/output.json"
        )

    def test_get_session_path(self) -> None:
        path = get_session_path(TEST_USER_ID, TEST_CONVERSATION_ID)
        assert (
            path
            == f"/users/{TEST_USER_ID}/global/executor/sessions/{TEST_CONVERSATION_ID}"
        )

    def test_get_tool_output_path(self) -> None:
        path = get_tool_output_path(
            TEST_USER_ID,
            TEST_CONVERSATION_ID,
            "gmail_agent",
            "call_123",
            "search_emails",
        )
        assert (
            f"/users/{TEST_USER_ID}/global/executor/sessions/{TEST_CONVERSATION_ID}"
            in path
        )
        assert "gmail_agent" in path
        assert "search_emails" in path


# ---------------------------------------------------------------------------
# TEST 3: Nested paths
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestNestedPaths:
    """Write artifacts at multiple nested levels, list contents of parent."""

    async def test_list_children_of_parent(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            base = f"/users/{TEST_USER_ID}/global/executor/notes"
            await vfs.write(f"{base}/note1.txt", "Note 1", user_id=TEST_USER_ID)
            await vfs.write(f"{base}/note2.txt", "Note 2", user_id=TEST_USER_ID)
            await vfs.write(
                f"{base}/subfolder/note3.txt", "Note 3", user_id=TEST_USER_ID
            )

            listing = await vfs.list_dir(base, user_id=TEST_USER_ID)

            names = {item.name for item in listing.items}
            assert "note1.txt" in names
            assert "note2.txt" in names
            assert "subfolder" in names
            assert listing.total_count == 3

    async def test_recursive_listing(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            base = f"/users/{TEST_USER_ID}/global/executor/files"
            await vfs.write(f"{base}/a.txt", "A", user_id=TEST_USER_ID)
            await vfs.write(f"{base}/sub/b.txt", "B", user_id=TEST_USER_ID)
            await vfs.write(f"{base}/sub/deep/c.txt", "C", user_id=TEST_USER_ID)

            listing = await vfs.list_dir(base, user_id=TEST_USER_ID, recursive=True)

            paths = {item.path for item in listing.items}
            # Recursive should include all descendants (files and folders)
            assert any("a.txt" in p for p in paths)
            assert any("b.txt" in p for p in paths)
            assert any("c.txt" in p for p in paths)
            assert listing.total_count >= 3


# ---------------------------------------------------------------------------
# TEST 4: Missing path
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMissingPath:
    """Read from non-existent path, verify clear error handling."""

    async def test_read_nonexistent_returns_none(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            result = await vfs.read(
                f"/users/{TEST_USER_ID}/global/executor/notes/does_not_exist.txt",
                user_id=TEST_USER_ID,
            )
            assert result is None

    async def test_info_nonexistent_returns_none(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            info = await vfs.info(
                f"/users/{TEST_USER_ID}/global/executor/notes/ghost.txt",
                user_id=TEST_USER_ID,
            )
            assert info is None

    async def test_exists_returns_false_for_missing(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            exists = await vfs.exists(
                f"/users/{TEST_USER_ID}/global/executor/notes/nope.txt",
                user_id=TEST_USER_ID,
            )
            assert exists is False

    async def test_access_other_user_path_raises(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            with pytest.raises(VFSAccessError):
                await vfs.read(
                    f"/users/{TEST_USER_ID_2}/global/executor/notes/secret.txt",
                    user_id=TEST_USER_ID,
                )

    async def test_delete_nonexistent_returns_false(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            deleted = await vfs.delete(
                f"/users/{TEST_USER_ID}/global/executor/notes/nope.txt",
                user_id=TEST_USER_ID,
            )
            assert deleted is False


# ---------------------------------------------------------------------------
# TEST 5: Large output archiving (VFS Compaction Middleware)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLargeOutputArchiving:
    """Import VFS compaction middleware, pass large output, verify archiving."""

    def _make_middleware(
        self, vfs: MongoVFS, max_output_chars: int = 100
    ) -> VFSCompactionMiddleware:
        mw = VFSCompactionMiddleware(
            max_output_chars=max_output_chars,
            compaction_threshold=0.65,
            context_window=128000,
        )
        mw._vfs = vfs
        return mw

    def _make_request(self, tool_name: str = "search_emails") -> MagicMock:
        request = MagicMock()
        request.tool_call = {
            "name": tool_name,
            "args": {"query": "test"},
            "id": "call_abc123",
        }
        request.state = {"messages": []}
        config = {
            "configurable": {
                "user_id": TEST_USER_ID,
                "vfs_session_id": TEST_CONVERSATION_ID,
                "thread_id": "thread_001",
                "subagent_id": "executor",
            },
            "metadata": {"agent_name": "executor"},
        }
        request.runtime = MagicMock()
        request.runtime.config = config
        return request

    async def test_large_output_gets_compacted(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            mw = self._make_middleware(vfs, max_output_chars=100)
            request = self._make_request()
            large_content = (
                "x" * 500
            )  # Above both MIN_COMPACTION_SIZE and max_output_chars

            original_result = ToolMessage(
                content=large_content, tool_call_id="call_abc123", name="search_emails"
            )

            async def handler(req: Any) -> ToolMessage:
                return original_result

            result = await mw.awrap_tool_call(request, handler)

            assert isinstance(result, ToolMessage)
            assert "stored at:" in result.content
            assert result.additional_kwargs.get("compacted") is True
            assert result.additional_kwargs.get("original_length") == len(large_content)
            assert "vfs_path" in result.additional_kwargs

    async def test_compaction_stores_in_vfs(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            mw = self._make_middleware(vfs, max_output_chars=100)
            request = self._make_request()
            large_content = json.dumps({"results": [{"id": i} for i in range(100)]})

            original_result = ToolMessage(
                content=large_content, tool_call_id="call_abc123", name="search_emails"
            )

            async def handler(req: Any) -> ToolMessage:
                return original_result

            result = await mw.awrap_tool_call(request, handler)

            vfs_path = result.additional_kwargs["vfs_path"]
            stored = await vfs.read(vfs_path, user_id=TEST_USER_ID)
            assert stored is not None

            stored_data = json.loads(stored)
            assert stored_data["tool_name"] == "search_emails"
            assert stored_data["content"] == large_content
            assert stored_data["compaction_reason"].startswith("large_output")


# ---------------------------------------------------------------------------
# TEST 6: Archiving threshold (below threshold, NOT archived)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestArchivingThreshold:
    """Pass output below threshold, verify it is returned as-is."""

    async def test_small_output_not_compacted(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            mw = VFSCompactionMiddleware(
                max_output_chars=20000,
                compaction_threshold=0.65,
                context_window=128000,
            )
            mw._vfs = vfs

            request = MagicMock()
            request.tool_call = {"name": "get_time", "args": {}, "id": "call_small"}
            request.state = {"messages": []}
            request.runtime = MagicMock()
            request.runtime.config = {
                "configurable": {
                    "user_id": TEST_USER_ID,
                    "thread_id": "thread_001",
                    "subagent_id": "executor",
                },
                "metadata": {},
            }

            small_content = "The time is 3:00 PM"
            original_result = ToolMessage(
                content=small_content, tool_call_id="call_small", name="get_time"
            )

            async def handler(req: Any) -> ToolMessage:
                return original_result

            result = await mw.awrap_tool_call(request, handler)

            assert result.content == small_content
            assert not result.additional_kwargs.get("compacted", False)

    def test_should_compact_logic_below_min_size(self) -> None:
        mw = VFSCompactionMiddleware(max_output_chars=20000)
        result = ToolMessage(content="short", tool_call_id="x", name="tool")
        should, reason = mw._should_compact(result, "tool", 0.0)
        assert should is False

    def test_should_compact_logic_above_max_output(self) -> None:
        mw = VFSCompactionMiddleware(max_output_chars=100)
        big_content = "a" * (MIN_COMPACTION_SIZE + 200)
        result = ToolMessage(content=big_content, tool_call_id="x", name="tool")
        should, reason = mw._should_compact(result, "tool", 0.0)
        assert should is True
        assert "large_output" in reason

    def test_should_compact_context_threshold(self) -> None:
        mw = VFSCompactionMiddleware(max_output_chars=100000, compaction_threshold=0.65)
        content = "a" * (MIN_COMPACTION_SIZE + 10)
        result = ToolMessage(content=content, tool_call_id="x", name="tool")
        should, reason = mw._should_compact(result, "tool", 0.70)
        assert should is True
        assert "context_threshold" in reason

    def test_excluded_tools_never_compacted(self) -> None:
        mw = VFSCompactionMiddleware(max_output_chars=10, excluded_tools={"safe_tool"})
        big_content = "a" * 50000
        result = ToolMessage(content=big_content, tool_call_id="x", name="safe_tool")
        should, _ = mw._should_compact(result, "safe_tool", 0.99)
        assert should is False

    def test_always_persist_tools(self) -> None:
        mw = VFSCompactionMiddleware(
            max_output_chars=100000,
            always_persist_tools=["important_tool"],
        )
        result = ToolMessage(content="tiny", tool_call_id="x", name="important_tool")
        should, reason = mw._should_compact(result, "important_tool", 0.0)
        assert should is True
        assert reason == "always_persist_tool"


# ---------------------------------------------------------------------------
# TEST 7: Content integrity (unicode / special characters)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestContentIntegrity:
    """Write unicode and special content, read back, verify no corruption."""

    async def test_unicode_content_roundtrip(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            path = f"/users/{TEST_USER_ID}/global/executor/notes/unicode.txt"
            content = "Hello \u4e16\u754c \U0001f30d \u00e9\u00e0\u00fc\u00f1 \u0410\u0411\u0412 \u3053\u3093\u306b\u3061\u306f"

            await vfs.write(path, content, user_id=TEST_USER_ID)
            read_back = await vfs.read(path, user_id=TEST_USER_ID)

            assert read_back == content

    async def test_json_content_roundtrip(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            path = f"/users/{TEST_USER_ID}/global/executor/files/data.json"
            data = {
                "nested": {"key": "value", "list": [1, 2, 3]},
                "unicode": "\u00e9\u00e0\u00fc",
                "special": "quotes \"here\" and 'there'",
                "newlines": "line1\nline2\nline3",
            }
            content = json.dumps(data, ensure_ascii=False, indent=2)

            await vfs.write(path, content, user_id=TEST_USER_ID)
            read_back = await vfs.read(path, user_id=TEST_USER_ID)

            assert read_back == content
            assert json.loads(read_back) == data

    async def test_empty_content(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            path = f"/users/{TEST_USER_ID}/global/executor/notes/empty.txt"

            await vfs.write(path, "", user_id=TEST_USER_ID)
            read_back = await vfs.read(path, user_id=TEST_USER_ID)

            assert read_back == ""

    async def test_multiline_content(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            path = f"/users/{TEST_USER_ID}/global/executor/notes/multiline.txt"
            content = "line1\nline2\r\nline3\ttabbed\x00null"

            await vfs.write(path, content, user_id=TEST_USER_ID)
            read_back = await vfs.read(path, user_id=TEST_USER_ID)

            assert read_back == content


# ---------------------------------------------------------------------------
# TEST 8: Artifact metadata
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestArtifactMetadata:
    """Write artifact with metadata, read back, verify metadata preserved."""

    async def test_metadata_preserved_on_write(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            path = f"/users/{TEST_USER_ID}/global/executor/sessions/conv1/output.json"
            metadata = {
                "type": "tool_output",
                "tool_name": "search_emails",
                "agent_name": "gmail_agent",
                "conversation_id": TEST_CONVERSATION_ID,
                "compacted": True,
            }
            await vfs.write(
                path, '{"result": "ok"}', user_id=TEST_USER_ID, metadata=metadata
            )

            info = await vfs.info(path, user_id=TEST_USER_ID)
            assert info is not None
            assert info.metadata["type"] == "tool_output"
            assert info.metadata["tool_name"] == "search_emails"
            assert info.metadata["agent_name"] == "gmail_agent"
            assert info.metadata["compacted"] is True
            # user_id is always injected by write()
            assert info.metadata["user_id"] == TEST_USER_ID

    async def test_size_bytes_tracked(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            path = f"/users/{TEST_USER_ID}/global/executor/notes/sized.txt"
            content = "Hello, world!"

            await vfs.write(path, content, user_id=TEST_USER_ID)
            info = await vfs.info(path, user_id=TEST_USER_ID)

            assert info is not None
            assert info.size_bytes == len(content.encode("utf-8"))

    async def test_content_type_detected_from_extension(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            base = f"/users/{TEST_USER_ID}/global/executor/files"

            await vfs.write(f"{base}/data.json", "{}", user_id=TEST_USER_ID)
            info_json = await vfs.info(f"{base}/data.json", user_id=TEST_USER_ID)
            assert info_json is not None
            assert info_json.content_type == "application/json"

            await vfs.write(f"{base}/notes.md", "# Title", user_id=TEST_USER_ID)
            info_md = await vfs.info(f"{base}/notes.md", user_id=TEST_USER_ID)
            assert info_md is not None
            assert info_md.content_type == "text/markdown"

            await vfs.write(f"{base}/data.csv", "a,b,c", user_id=TEST_USER_ID)
            info_csv = await vfs.info(f"{base}/data.csv", user_id=TEST_USER_ID)
            assert info_csv is not None
            assert info_csv.content_type == "text/csv"

    async def test_timestamps_set_on_creation(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            path = f"/users/{TEST_USER_ID}/global/executor/notes/timestamped.txt"

            await vfs.write(path, "content", user_id=TEST_USER_ID)

            info = await vfs.info(path, user_id=TEST_USER_ID)
            assert info is not None
            assert info.created_at is not None
            assert info.updated_at is not None


# ---------------------------------------------------------------------------
# TEST 9: Delete / cleanup
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteCleanup:
    """Write artifact, delete, verify gone and path no longer resolves."""

    async def test_delete_file(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            path = f"/users/{TEST_USER_ID}/global/executor/notes/to_delete.txt"

            await vfs.write(path, "delete me", user_id=TEST_USER_ID)
            assert await vfs.exists(path, user_id=TEST_USER_ID) is True

            deleted = await vfs.delete(path, user_id=TEST_USER_ID)
            assert deleted is True

            assert await vfs.exists(path, user_id=TEST_USER_ID) is False
            assert await vfs.read(path, user_id=TEST_USER_ID) is None

    async def test_delete_directory_recursive(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            base = f"/users/{TEST_USER_ID}/global/executor/sessions/conv_to_delete"
            await vfs.write(f"{base}/file1.txt", "content1", user_id=TEST_USER_ID)
            await vfs.write(f"{base}/sub/file2.txt", "content2", user_id=TEST_USER_ID)

            # Ensure the folder itself exists as a node
            await vfs.mkdir(base, user_id=TEST_USER_ID)

            deleted = await vfs.delete(base, user_id=TEST_USER_ID, recursive=True)
            assert deleted is True

            assert await vfs.exists(f"{base}/file1.txt", user_id=TEST_USER_ID) is False
            assert (
                await vfs.exists(f"{base}/sub/file2.txt", user_id=TEST_USER_ID) is False
            )

    async def test_delete_nonempty_dir_without_recursive_raises(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            base = f"/users/{TEST_USER_ID}/global/executor/files/nonempty"
            await vfs.mkdir(base, user_id=TEST_USER_ID)
            await vfs.write(f"{base}/child.txt", "child", user_id=TEST_USER_ID)

            with pytest.raises(ValueError, match="not empty"):
                await vfs.delete(base, user_id=TEST_USER_ID, recursive=False)

    async def test_info_returns_none_after_delete(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            path = f"/users/{TEST_USER_ID}/global/executor/notes/info_delete.txt"
            await vfs.write(path, "will be deleted", user_id=TEST_USER_ID)

            info = await vfs.info(path, user_id=TEST_USER_ID)
            assert info is not None

            await vfs.delete(path, user_id=TEST_USER_ID)
            info_after = await vfs.info(path, user_id=TEST_USER_ID)
            assert info_after is None


# ---------------------------------------------------------------------------
# TEST 10: Summarization middleware
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSummarizationMiddleware:
    """Import summarization middleware, verify archive + summary logic."""

    def test_serialize_messages_preserves_structure(self) -> None:

        # Instantiate with a mock model to avoid real LLM init
        with patch(
            "app.agents.middleware.vfs_summarization.SummarizationMiddleware.__init__",
            return_value=None,
        ):
            mw = VFSArchivingSummarizationMiddleware.__new__(
                VFSArchivingSummarizationMiddleware
            )
            mw.vfs_enabled = True
            mw.excluded_tools = set()

            messages = [
                HumanMessage(content="Hello"),
                ToolMessage(
                    content="Result data", tool_call_id="call_1", name="search"
                ),
            ]

            serialized = mw._serialize_messages(messages)

            assert len(serialized) == 2
            assert serialized[0]["type"] == "HumanMessage"
            assert serialized[0]["content"] == "Hello"
            assert serialized[1]["type"] == "ToolMessage"
            assert serialized[1]["tool_call_id"] == "call_1"
            assert serialized[1]["name"] == "search"

    def test_inject_archive_path_modifies_summary(self) -> None:

        with patch(
            "app.agents.middleware.vfs_summarization.SummarizationMiddleware.__init__",
            return_value=None,
        ):
            mw = VFSArchivingSummarizationMiddleware.__new__(
                VFSArchivingSummarizationMiddleware
            )

            summary_msg = HumanMessage(
                content="Summary of conversation",
                additional_kwargs={"is_summary": True},
            )
            result = {"messages": [summary_msg]}

            archive_path = "/users/test/global/executor/sessions/conv1/archives/pre_summary_20260401.json"
            modified = mw._inject_archive_path(result, archive_path)

            assert archive_path in modified["messages"][0].content
            assert (
                modified["messages"][0].additional_kwargs["archive_path"]
                == archive_path
            )

    def test_inject_archive_path_no_summary_message_is_noop(self) -> None:

        with patch(
            "app.agents.middleware.vfs_summarization.SummarizationMiddleware.__init__",
            return_value=None,
        ):
            mw = VFSArchivingSummarizationMiddleware.__new__(
                VFSArchivingSummarizationMiddleware
            )

            regular_msg = HumanMessage(content="Just a message")
            result = {"messages": [regular_msg]}

            modified = mw._inject_archive_path(result, "/some/path")
            assert "archived at" not in modified["messages"][0].content

    async def test_archive_to_vfs_stores_history(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:

        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            with patch(
                "app.agents.middleware.vfs_summarization.SummarizationMiddleware.__init__",
                return_value=None,
            ):
                mw = VFSArchivingSummarizationMiddleware.__new__(
                    VFSArchivingSummarizationMiddleware
                )
                mw.vfs_enabled = True
                mw.excluded_tools = set()
                mw._vfs = vfs

                state = {
                    "messages": [
                        HumanMessage(content="What is the weather?"),
                        ToolMessage(
                            content="72F and sunny",
                            tool_call_id="call_w",
                            name="weather",
                        ),
                    ]
                }

                runtime = MagicMock()
                runtime.config = {
                    "configurable": {
                        "user_id": TEST_USER_ID,
                        "vfs_session_id": TEST_CONVERSATION_ID,
                        "thread_id": "thread_001",
                        "subagent_id": "executor",
                    },
                    "metadata": {"agent_name": "executor"},
                }

                archive_path = await mw._archive_to_vfs(state, runtime)

                assert "archives" in archive_path
                assert "pre_summary" in archive_path

                stored = await vfs.read(archive_path, user_id=TEST_USER_ID)
                assert stored is not None

                history = json.loads(stored)
                assert len(history) == 2
                assert history[0]["type"] == "HumanMessage"
                assert history[1]["type"] == "ToolMessage"

    def test_should_trigger_with_excluded_tools(self) -> None:

        with patch(
            "app.agents.middleware.vfs_summarization.SummarizationMiddleware.__init__",
            return_value=None,
        ):
            mw = VFSArchivingSummarizationMiddleware.__new__(
                VFSArchivingSummarizationMiddleware
            )
            mw.vfs_enabled = True
            mw.excluded_tools = {"noisy_tool"}
            mw.trigger = ("messages", 2)

            # The state has 3 messages total but one is from an excluded tool
            state = {
                "messages": [
                    HumanMessage(content="msg1"),
                    ToolMessage(content="noise", tool_call_id="c1", name="noisy_tool"),
                    HumanMessage(content="msg2"),
                ]
            }

            # Mock token_counter so it doesn't fail
            mw.token_counter = lambda msgs: len(msgs) * 100

            should = mw._should_trigger_summarization(state)
            # 2 messages after filtering (below the trigger of 2), so should NOT trigger
            assert should is False


# ---------------------------------------------------------------------------
# Additional edge case tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEdgeCases:
    """Additional edge cases: auto-prefix, system path writes, search."""

    async def test_auto_prefix_relative_path(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            # Writing to a relative path should auto-prefix with user scope
            path = "notes/my_note.txt"
            written = await vfs.write(path, "auto-prefixed", user_id=TEST_USER_ID)

            assert written.startswith(f"/users/{TEST_USER_ID}/global/")
            content = await vfs.read(written, user_id=TEST_USER_ID)
            assert content == "auto-prefixed"

    async def test_system_path_write_denied(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            with pytest.raises(VFSAccessError):
                await vfs.write("/system/skills/evil.txt", "hack", user_id=TEST_USER_ID)

    async def test_search_finds_matching_files(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            base = f"/users/{TEST_USER_ID}/global/executor/files"
            await vfs.write(f"{base}/report.json", '{"data": 1}', user_id=TEST_USER_ID)
            await vfs.write(f"{base}/report.txt", "text report", user_id=TEST_USER_ID)
            await vfs.write(f"{base}/image.png", "fake png", user_id=TEST_USER_ID)

            results = await vfs.search("*.json", user_id=TEST_USER_ID, base_path=base)
            json_names = [m.name for m in results.matches]
            assert "report.json" in json_names
            assert "report.txt" not in json_names

    async def test_move_file(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            src = f"/users/{TEST_USER_ID}/global/executor/notes/moveme.txt"
            dst = f"/users/{TEST_USER_ID}/global/executor/files/moved.txt"

            await vfs.write(src, "moving", user_id=TEST_USER_ID)
            new_path = await vfs.move(src, dst, user_id=TEST_USER_ID)

            assert new_path == normalize_path(dst)
            assert await vfs.exists(dst, user_id=TEST_USER_ID) is True

    async def test_copy_file(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            src = f"/users/{TEST_USER_ID}/global/executor/notes/copyme.txt"
            dst = f"/users/{TEST_USER_ID}/global/executor/files/copied.txt"

            await vfs.write(src, "copy content", user_id=TEST_USER_ID)
            copied_path = await vfs.copy(src, dst, user_id=TEST_USER_ID)

            src_content = await vfs.read(src, user_id=TEST_USER_ID)
            dst_content = await vfs.read(copied_path, user_id=TEST_USER_ID)
            assert src_content == dst_content == "copy content"

    async def test_append_creates_if_not_exists(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            path = f"/users/{TEST_USER_ID}/global/executor/notes/appended.txt"

            await vfs.append(path, "first line\n", user_id=TEST_USER_ID)
            await vfs.append(path, "second line\n", user_id=TEST_USER_ID)

            content = await vfs.read(path, user_id=TEST_USER_ID)
            assert content == "first line\nsecond line\n"

    def test_get_parent_path(self) -> None:
        assert (
            get_parent_path("/users/abc/global/executor/notes/file.txt")
            == "/users/abc/global/executor/notes"
        )
        assert get_parent_path("/users/abc") == "/users"
        assert get_parent_path("/") == "/"

    async def test_empty_user_id_raises(
        self, vfs: MongoVFS, fake_collection: FakeMongoCollection
    ) -> None:
        with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection", fake_collection):
            with pytest.raises(ValueError, match="user_id is required"):
                await vfs.read(f"/users/{TEST_USER_ID}/global/notes/x.txt", user_id="")
