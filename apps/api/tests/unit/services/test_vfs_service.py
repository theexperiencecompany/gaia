"""Comprehensive tests for app/services/vfs/mongo_vfs.py."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.vfs_models import VFSNodeType
from app.services.vfs.mongo_vfs import MongoVFS, VFSAccessError, _escape_mongo_regex

USER_ID = "user123"
OTHER_USER = "other456"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(
    path: str,
    node_type: str = "file",
    content: str | None = "hello",
    gridfs_id: str | None = None,
    user_id: str = USER_ID,
    **extra,
) -> dict:
    """Build a fake MongoDB VFS node document."""
    return {
        "_id": "fake_id",
        "path": path,
        "name": path.rsplit("/", 1)[-1],
        "node_type": node_type,
        "parent_path": "/".join(path.rsplit("/", 1)[:-1]) or "/",
        "content": content,
        "gridfs_id": gridfs_id,
        "content_type": "text/plain",
        "size_bytes": len(content.encode()) if content else 0,
        "metadata": {},
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        **extra,
    }


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------


class TestEscapeMongoRegex:
    def test_escapes_special_chars(self):
        assert _escape_mongo_regex("foo.bar") == r"foo\.bar"
        assert _escape_mongo_regex("a+b*c") == r"a\+b\*c"

    def test_plain_string_unchanged(self):
        assert _escape_mongo_regex("hello") == "hello"


# ---------------------------------------------------------------------------
# VFSAccessError
# ---------------------------------------------------------------------------


class TestVFSAccessError:
    def test_default_message(self):
        err = VFSAccessError("/users/other/file.txt", USER_ID)
        assert "Access denied" in str(err)
        assert err.path == "/users/other/file.txt"
        assert err.user_id == USER_ID

    def test_custom_message(self):
        err = VFSAccessError("/system/x", USER_ID, message="custom msg")
        assert str(err) == "custom msg"


# ---------------------------------------------------------------------------
# Synchronous / non-IO methods
# ---------------------------------------------------------------------------


class TestMongoVFSSyncMethods:
    def setup_method(self):
        self.vfs = MongoVFS()

    # _validate_access ---------------------------------------------------

    def test_validate_access_empty_user_id_raises(self):
        with pytest.raises(ValueError, match="user_id is required"):
            self.vfs._validate_access("/users/u/file.txt", "")

    def test_validate_access_other_user_raises(self):
        with pytest.raises(VFSAccessError):
            self.vfs._validate_access(f"/users/{OTHER_USER}/x", USER_ID)

    def test_validate_access_own_path(self):
        result = self.vfs._validate_access(f"/users/{USER_ID}/file.txt", USER_ID)
        assert result == f"/users/{USER_ID}/file.txt"

    def test_validate_access_system_path_allowed(self):
        result = self.vfs._validate_access("/system/skills/x", USER_ID)
        assert result == "/system/skills/x"

    # _validate_write_access ---------------------------------------------

    def test_write_access_system_path_denied(self):
        with pytest.raises(VFSAccessError, match="read-only"):
            self.vfs._validate_write_access(
                "/system/skills/x", USER_ID, original_path="/system/skills/x"
            )

    def test_write_access_system_path_normalized_denied(self):
        with pytest.raises(VFSAccessError, match="read-only"):
            self.vfs._validate_write_access(
                "/system/skills/x", USER_ID, original_path=None
            )

    def test_write_access_allow_system_flag(self):
        # Should not raise
        self.vfs._validate_write_access(
            "/system/skills/x",
            USER_ID,
            original_path="/system/skills/x",
            allow_system=True,
        )

    def test_write_access_allow_system_write_instance_flag(self):
        vfs = MongoVFS(allow_system_write=True)
        # system user can write
        vfs._validate_write_access("/system/skills/x", "system")

    def test_write_access_allow_system_write_non_system_user_raises(self):
        vfs = MongoVFS(allow_system_write=True)
        with pytest.raises(VFSAccessError, match="read-only"):
            vfs._validate_write_access(
                "/system/skills/x", USER_ID, original_path="/system/skills/x"
            )

    def test_write_access_user_path_ok(self):
        self.vfs._validate_write_access(
            f"/users/{USER_ID}/file.txt",
            USER_ID,
            original_path=f"/users/{USER_ID}/file.txt",
        )

    # _auto_prefix_path --------------------------------------------------

    def test_auto_prefix_path_already_scoped(self):
        result = self.vfs._auto_prefix_path(f"/users/{USER_ID}/file.txt", USER_ID)
        assert result == f"/users/{USER_ID}/file.txt"

    def test_auto_prefix_path_unscoped(self):
        result = self.vfs._auto_prefix_path("myfile.txt", USER_ID)
        assert result == f"/users/{USER_ID}/global/myfile.txt"

    def test_auto_prefix_system_path_preserved(self):
        result = self.vfs._auto_prefix_path("/system/skills/x", USER_ID)
        assert result == "/system/skills/x"

    def test_auto_prefix_traversal_outside_users_raises(self):
        with pytest.raises(VFSAccessError, match="traversal"):
            self.vfs._auto_prefix_path("/users/../../etc/passwd", USER_ID)

    def test_auto_prefix_traversal_outside_system_raises(self):
        with pytest.raises(VFSAccessError, match="traversal"):
            self.vfs._auto_prefix_path("/system/../../etc/passwd", USER_ID)

    # _is_system_path ----------------------------------------------------

    def test_is_system_path_true(self):
        assert self.vfs._is_system_path("/system/skills/x") is True

    def test_is_system_path_false(self):
        assert self.vfs._is_system_path(f"/users/{USER_ID}/file.txt") is False

    # _build_query -------------------------------------------------------

    def test_build_query_user_path(self):
        q = self.vfs._build_query(f"/users/{USER_ID}/file.txt", USER_ID)
        assert q == {"path": f"/users/{USER_ID}/file.txt", "user_id": USER_ID}

    def test_build_query_system_path(self):
        q = self.vfs._build_query("/system/skills/x", USER_ID)
        assert q == {"path": "/system/skills/x", "user_id": "system"}

    # _get_query_user_id -------------------------------------------------

    def test_get_query_user_id_system(self):
        assert self.vfs._get_query_user_id("/system/x", USER_ID) == "system"

    def test_get_query_user_id_user(self):
        assert self.vfs._get_query_user_id(f"/users/{USER_ID}/x", USER_ID) == USER_ID

    # _detect_content_type -----------------------------------------------

    def test_detect_json(self):
        assert self.vfs._detect_content_type("data.json") == "application/json"

    def test_detect_markdown(self):
        assert self.vfs._detect_content_type("README.md") == "text/markdown"

    def test_detect_python(self):
        assert self.vfs._detect_content_type("main.py") == "text/x-python"

    def test_detect_unknown(self):
        assert self.vfs._detect_content_type("file.xyz") == "text/plain"

    def test_detect_yaml(self):
        assert self.vfs._detect_content_type("config.yml") == "application/yaml"

    # _classify_file_type ------------------------------------------------

    def test_classify_json_by_ext(self):
        assert self.vfs._classify_file_type("json", "") == "json"

    def test_classify_yaml_by_ext(self):
        assert self.vfs._classify_file_type("yaml", "") == "yaml"
        assert self.vfs._classify_file_type("yml", "") == "yaml"

    def test_classify_csv_by_ext(self):
        assert self.vfs._classify_file_type("csv", "") == "csv"

    def test_classify_markdown_by_ext(self):
        assert self.vfs._classify_file_type("md", "") == "markdown"
        assert self.vfs._classify_file_type("markdown", "") == "markdown"

    def test_classify_json_by_content(self):
        assert self.vfs._classify_file_type("txt", '{"key":"val"}') == "json"

    def test_classify_json_array_by_content(self):
        assert self.vfs._classify_file_type("txt", "[1,2,3]") == "json"

    def test_classify_invalid_json_content(self):
        assert self.vfs._classify_file_type("txt", "{not json}") == "text"

    def test_classify_plain_text(self):
        assert self.vfs._classify_file_type("txt", "hello world") == "text"

    # _format_size -------------------------------------------------------

    def test_format_size_bytes(self):
        assert self.vfs._format_size(512) == "512.0 B"

    def test_format_size_kb(self):
        assert self.vfs._format_size(2048) == "2.0 KB"

    def test_format_size_mb(self):
        assert self.vfs._format_size(1_048_576) == "1.0 MB"

    def test_format_size_gb(self):
        assert self.vfs._format_size(1_073_741_824) == "1.0 GB"

    def test_format_size_tb(self):
        assert self.vfs._format_size(1_099_511_627_776) == "1.0 TB"

    # _analyze_json ------------------------------------------------------

    def test_analyze_json_dict(self):
        result = self.vfs._analyze_json({"a": 1, "b": "hello"})
        assert result["schema"]["type"] == "object"
        assert result["field_count"] == 2
        assert result["nested_depth"] >= 1

    def test_analyze_json_array(self):
        result = self.vfs._analyze_json([1, 2, 3])
        assert result["schema"]["type"] == "array"
        assert "root" in result["array_lengths"]

    def test_analyze_json_empty_array(self):
        result = self.vfs._analyze_json([])
        assert result["schema"]["items"] == {}

    def test_analyze_json_nested(self):
        result = self.vfs._analyze_json({"a": {"b": {"c": 1}}})
        assert result["nested_depth"] >= 3

    def test_analyze_json_scalar_types(self):
        result = self.vfs._analyze_json({"a": None, "b": True, "c": 1.5})
        types = result["value_types"]
        assert types.get("a") == "null"
        assert types.get("b") == "boolean"
        assert types.get("c") == "number"

    def test_analyze_json_sample_values(self):
        result = self.vfs._analyze_json({"x": "val"}, sample_size=3)
        assert "x" in result["sample_values"]

    def test_analyze_json_zero_sample(self):
        result = self.vfs._analyze_json({"x": "val"}, sample_size=0)
        assert len(result["sample_values"]) == 0


# ---------------------------------------------------------------------------
# Async operations (mock MongoDB / GridFS)
# ---------------------------------------------------------------------------

MOCK_COLLECTION = "app.services.vfs.mongo_vfs.vfs_nodes_collection"


@pytest.mark.asyncio
class TestMongoVFSWrite:
    async def test_write_inline_file(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/file.txt"
        content = "hello"

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=None)
            col.update_one = AsyncMock()

            result = await vfs.write(path, content, USER_ID)

        assert result == path
        assert col.update_one.call_count >= 1

    async def test_write_large_file_uses_gridfs(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/big.txt"
        content = "x" * (MongoVFS.INLINE_SIZE_LIMIT + 1)

        mock_bucket = AsyncMock()
        mock_bucket.upload_from_stream = AsyncMock(return_value="gridfs_id_123")
        mock_bucket.delete = AsyncMock()

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "_get_gridfs", return_value=mock_bucket),
        ):
            col.find_one = AsyncMock(return_value=None)
            col.update_one = AsyncMock()

            result = await vfs.write(path, content, USER_ID)

        assert result == path
        mock_bucket.upload_from_stream.assert_called_once()

    async def test_write_replaces_existing_gridfs(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/big.txt"
        content = "x" * (MongoVFS.INLINE_SIZE_LIMIT + 1)

        existing = _make_node(path, gridfs_id="aabbccddeeff112233445566", content=None)
        mock_bucket = AsyncMock()
        mock_bucket.upload_from_stream = AsyncMock(return_value="new_gridfs_id")
        mock_bucket.delete = AsyncMock()

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "_get_gridfs", return_value=mock_bucket),
            patch.object(vfs, "_ensure_directories", new_callable=AsyncMock),
        ):
            col.find_one = AsyncMock(side_effect=[existing, existing])
            col.update_one = AsyncMock()

            await vfs.write(path, content, USER_ID)

        mock_bucket.delete.assert_called_once()

    async def test_write_inline_cleans_up_old_gridfs(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/small.txt"
        content = "short"

        existing = _make_node(path, gridfs_id="aabbccddeeff112233445566", content=None)
        mock_bucket = AsyncMock()
        mock_bucket.delete = AsyncMock()

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "_get_gridfs", return_value=mock_bucket),
            patch.object(vfs, "_ensure_directories", new_callable=AsyncMock),
        ):
            col.find_one = AsyncMock(side_effect=[existing, existing])
            col.update_one = AsyncMock()

            await vfs.write(path, content, USER_ID)

        mock_bucket.delete.assert_called_once()

    async def test_write_to_folder_path_raises(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/myfolder"

        folder_node = _make_node(path, node_type="folder", content=None)

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "_ensure_directories", new_callable=AsyncMock),
        ):
            col.find_one = AsyncMock(side_effect=[None, folder_node])
            col.update_one = AsyncMock()

            with pytest.raises(ValueError, match="already exists as a folder"):
                await vfs.write(path, "content", USER_ID)

    async def test_write_access_denied(self):
        vfs = MongoVFS()
        with pytest.raises(VFSAccessError):
            await vfs.write(f"/users/{OTHER_USER}/file.txt", "x", USER_ID)


@pytest.mark.asyncio
class TestMongoVFSMkdir:
    async def test_mkdir_basic(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/mydir"

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=None)
            col.update_one = AsyncMock()

            result = await vfs.mkdir(path, USER_ID)

        assert result == path

    async def test_mkdir_on_existing_file_raises(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/mydir"
        file_node = _make_node(path, node_type="file")

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "_ensure_directories", new_callable=AsyncMock),
        ):
            col.find_one = AsyncMock(return_value=file_node)
            col.update_one = AsyncMock()

            with pytest.raises(ValueError, match="already exists as a file"):
                await vfs.mkdir(path, USER_ID)


@pytest.mark.asyncio
class TestMongoVFSRead:
    async def test_read_inline_content(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/file.txt"
        node = _make_node(path, content="hello world")

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=node)
            col.update_one = AsyncMock()

            result = await vfs.read(path, USER_ID)

        assert result == "hello world"

    async def test_read_gridfs_content(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/file.txt"
        node = _make_node(path, content=None, gridfs_id="aabbccddeeff112233445566")

        mock_stream = AsyncMock()
        mock_stream.read = AsyncMock(return_value=b"gridfs content")
        mock_bucket = AsyncMock()
        mock_bucket.open_download_stream = AsyncMock(return_value=mock_stream)

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "_get_gridfs", return_value=mock_bucket),
        ):
            col.find_one = AsyncMock(return_value=node)
            col.update_one = AsyncMock()

            result = await vfs.read(path, USER_ID)

        assert result == "gridfs content"

    async def test_read_gridfs_error_returns_none(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/file.txt"
        node = _make_node(path, content=None, gridfs_id="aabbccddeeff112233445566")

        mock_bucket = AsyncMock()
        mock_bucket.open_download_stream = AsyncMock(side_effect=Exception("oops"))

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "_get_gridfs", return_value=mock_bucket),
        ):
            col.find_one = AsyncMock(return_value=node)
            col.update_one = AsyncMock()

            result = await vfs.read(path, USER_ID)

        assert result is None

    async def test_read_not_found(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/missing.txt"

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=None)

            result = await vfs.read(path, USER_ID)

        assert result is None

    async def test_read_folder_returns_none(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/mydir"
        folder = _make_node(path, node_type="folder", content=None)

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=folder)

            result = await vfs.read(path, USER_ID)

        assert result is None

    async def test_read_no_content_no_gridfs_returns_none(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/empty.txt"
        node = _make_node(path, content=None, gridfs_id=None)

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=node)
            col.update_one = AsyncMock()

            result = await vfs.read(path, USER_ID)

        assert result is None


@pytest.mark.asyncio
class TestMongoVFSAppend:
    async def test_append_to_existing_inline(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/log.txt"
        existing = _make_node(path, content="line1\n")

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "write", new_callable=AsyncMock) as mock_write,
        ):
            col.find_one = AsyncMock(return_value=existing)
            col.update_one = AsyncMock()

            await vfs.append(path, "line2\n", USER_ID)

        mock_write.assert_called_once()
        written_content = mock_write.call_args[0][1]
        assert written_content == "line1\nline2\n"

    async def test_append_to_gridfs_file(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/log.txt"
        existing = _make_node(path, content=None, gridfs_id="aabbccddeeff112233445566")

        mock_stream = AsyncMock()
        mock_stream.read = AsyncMock(return_value=b"old content")
        mock_bucket = AsyncMock()
        mock_bucket.open_download_stream = AsyncMock(return_value=mock_stream)

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "_get_gridfs", return_value=mock_bucket),
            patch.object(vfs, "write", new_callable=AsyncMock) as mock_write,
        ):
            col.find_one = AsyncMock(return_value=existing)
            col.update_one = AsyncMock()

            await vfs.append(path, " new", USER_ID)

        written_content = mock_write.call_args[0][1]
        assert written_content == "old content new"

    async def test_append_creates_new_file(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/new.txt"

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "write", new_callable=AsyncMock) as mock_write,
        ):
            col.find_one = AsyncMock(return_value=None)
            col.update_one = AsyncMock()

            await vfs.append(path, "first line", USER_ID)

        written_content = mock_write.call_args[0][1]
        assert written_content == "first line"


@pytest.mark.asyncio
class TestMongoVFSExists:
    async def test_exists_true(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/file.txt"

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value={"_id": "x"})

            assert await vfs.exists(path, USER_ID) is True

    async def test_exists_false(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/missing.txt"

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=None)

            assert await vfs.exists(path, USER_ID) is False


@pytest.mark.asyncio
class TestMongoVFSInfo:
    async def test_info_found(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/file.txt"
        node = _make_node(path)

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=node)

            result = await vfs.info(path, USER_ID)

        assert result is not None
        assert result.path == path
        assert result.node_type == VFSNodeType.FILE

    async def test_info_not_found(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/missing.txt"

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=None)

            assert await vfs.info(path, USER_ID) is None


@pytest.mark.asyncio
class TestMongoVFSListDir:
    async def test_list_dir_non_recursive(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global"
        child = _make_node(f"{path}/file.txt")

        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=[child])

        with patch(MOCK_COLLECTION) as col:
            col.find = MagicMock(return_value=mock_cursor)

            result = await vfs.list_dir(path, USER_ID)

        assert result.total_count == 1
        assert result.items[0].name == "file.txt"

    async def test_list_dir_recursive(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global"
        children = [
            _make_node(f"{path}/a.txt"),
            _make_node(f"{path}/sub/b.txt"),
        ]

        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=children)

        with patch(MOCK_COLLECTION) as col:
            col.find = MagicMock(return_value=mock_cursor)

            result = await vfs.list_dir(path, USER_ID, recursive=True)

        assert result.total_count == 2


@pytest.mark.asyncio
class TestMongoVFSTree:
    async def test_tree_not_found_returns_virtual_root(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global"

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=None)

            result = await vfs.tree(path, USER_ID)

        assert result.node_type == VFSNodeType.FOLDER
        assert result.children == []

    async def test_tree_with_children(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global"
        root_node = _make_node(path, node_type="folder", content=None)
        child_node = _make_node(f"{path}/file.txt")

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[child_node])

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=root_node)
            col.find = MagicMock(return_value=mock_cursor)

            result = await vfs.tree(path, USER_ID, depth=1)

        assert len(result.children) == 1


@pytest.mark.asyncio
class TestMongoVFSSearch:
    async def test_search_no_user_id_raises(self):
        vfs = MongoVFS()
        with pytest.raises(ValueError, match="user_id is required"):
            await vfs.search("*.txt", "")

    async def test_search_default_base_path(self):
        vfs = MongoVFS()
        node = _make_node(f"/users/{USER_ID}/global/data.json")

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[node])

        with patch(MOCK_COLLECTION) as col:
            col.find = MagicMock(return_value=mock_cursor)

            result = await vfs.search("*.json", USER_ID)

        assert result.total_count == 1
        assert result.base_path == f"/users/{USER_ID}"

    async def test_search_with_base_path(self):
        vfs = MongoVFS()
        node = _make_node(f"/users/{USER_ID}/global/sub/data.txt")

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[node])

        with patch(MOCK_COLLECTION) as col:
            col.find = MagicMock(return_value=mock_cursor)

            result = await vfs.search(
                "*.txt", USER_ID, base_path=f"/users/{USER_ID}/global/sub"
            )

        assert result.total_count == 1

    async def test_search_no_matches(self):
        vfs = MongoVFS()
        node = _make_node(f"/users/{USER_ID}/global/data.json")

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[node])

        with patch(MOCK_COLLECTION) as col:
            col.find = MagicMock(return_value=mock_cursor)

            result = await vfs.search("*.py", USER_ID)

        assert result.total_count == 0


@pytest.mark.asyncio
class TestMongoVFSDelete:
    async def test_delete_file(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/file.txt"
        node = _make_node(path)

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=node)
            col.delete_one = AsyncMock()

            result = await vfs.delete(path, USER_ID)

        assert result is True

    async def test_delete_not_found(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/missing.txt"

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=None)

            result = await vfs.delete(path, USER_ID)

        assert result is False

    async def test_delete_nonempty_folder_without_recursive_raises(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/mydir"
        folder = _make_node(path, node_type="folder", content=None)
        child = _make_node(f"{path}/file.txt")

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(side_effect=[folder, child])

            with pytest.raises(ValueError, match="not empty"):
                await vfs.delete(path, USER_ID, recursive=False)

    async def test_delete_folder_recursive(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/mydir"
        folder = _make_node(path, node_type="folder", content=None)

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_bucket = AsyncMock()

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "_get_gridfs", return_value=mock_bucket),
        ):
            col.find_one = AsyncMock(return_value=folder)
            col.find = MagicMock(return_value=mock_cursor)
            col.delete_many = AsyncMock()
            col.delete_one = AsyncMock()

            result = await vfs.delete(path, USER_ID, recursive=True)

        assert result is True

    async def test_delete_folder_recursive_with_gridfs_children(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/mydir"
        folder = _make_node(path, node_type="folder", content=None)
        child = _make_node(
            f"{path}/big.bin", content=None, gridfs_id="ccddee112233aabbff445566"
        )

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[child])
        mock_bucket = AsyncMock()
        mock_bucket.delete = AsyncMock()

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "_get_gridfs", return_value=mock_bucket),
        ):
            col.find_one = AsyncMock(return_value=folder)
            col.find = MagicMock(return_value=mock_cursor)
            col.delete_many = AsyncMock()
            col.delete_one = AsyncMock()

            result = await vfs.delete(path, USER_ID, recursive=True)

        assert result is True
        mock_bucket.delete.assert_called_once()

    async def test_delete_file_with_gridfs(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/big.txt"
        node = _make_node(path, content=None, gridfs_id="aabbccddeeff112233445566")

        mock_bucket = AsyncMock()
        mock_bucket.delete = AsyncMock()

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "_get_gridfs", return_value=mock_bucket),
        ):
            col.find_one = AsyncMock(return_value=node)
            col.delete_one = AsyncMock()

            result = await vfs.delete(path, USER_ID)

        assert result is True
        mock_bucket.delete.assert_called_once()

    async def test_delete_gridfs_error_continues(self):
        vfs = MongoVFS()
        path = f"/users/{USER_ID}/global/big.txt"
        node = _make_node(path, content=None, gridfs_id="aabbccddeeff112233445566")

        mock_bucket = AsyncMock()
        mock_bucket.delete = AsyncMock(side_effect=Exception("gridfs error"))

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "_get_gridfs", return_value=mock_bucket),
        ):
            col.find_one = AsyncMock(return_value=node)
            col.delete_one = AsyncMock()

            result = await vfs.delete(path, USER_ID)

        assert result is True


@pytest.mark.asyncio
class TestMongoVFSMove:
    async def test_move_file(self):
        vfs = MongoVFS()
        src = f"/users/{USER_ID}/global/a.txt"
        dest = f"/users/{USER_ID}/global/b.txt"
        node = _make_node(src)

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "_ensure_directories", new_callable=AsyncMock),
        ):
            col.find_one = AsyncMock(return_value=node)
            col.update_one = AsyncMock()

            result = await vfs.move(src, dest, USER_ID)

        assert result == dest

    async def test_move_source_not_found(self):
        vfs = MongoVFS()
        src = f"/users/{USER_ID}/global/missing.txt"
        dest = f"/users/{USER_ID}/global/b.txt"

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "_ensure_directories", new_callable=AsyncMock),
        ):
            col.find_one = AsyncMock(return_value=None)
            col.update_one = AsyncMock()

            with pytest.raises(FileNotFoundError):
                await vfs.move(src, dest, USER_ID)

    async def test_move_folder_with_children(self):
        vfs = MongoVFS()
        src = f"/users/{USER_ID}/global/dir1"
        dest = f"/users/{USER_ID}/global/dir2"
        folder_node = _make_node(src, node_type="folder", content=None)
        child = _make_node(f"{src}/file.txt")

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[child])

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "_ensure_directories", new_callable=AsyncMock),
        ):
            col.find_one = AsyncMock(return_value=folder_node)
            col.find = MagicMock(return_value=mock_cursor)
            col.update_one = AsyncMock()

            result = await vfs.move(src, dest, USER_ID)

        assert result == dest
        # At least 2 update_one calls: child + parent
        assert col.update_one.call_count >= 2


@pytest.mark.asyncio
class TestMongoVFSCopy:
    async def test_copy_file(self):
        vfs = MongoVFS()
        src = f"/users/{USER_ID}/global/a.txt"
        dest = f"/users/{USER_ID}/global/b.txt"
        node = _make_node(src, content="data")

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "read", new_callable=AsyncMock, return_value="data"),
            patch.object(
                vfs, "write", new_callable=AsyncMock, return_value=dest
            ) as mock_write,
        ):
            col.find_one = AsyncMock(return_value=node)

            result = await vfs.copy(src, dest, USER_ID)

        assert result == dest
        mock_write.assert_called_once()
        # metadata should include copied_from
        written_meta = mock_write.call_args[0][3]
        assert written_meta["copied_from"] == src

    async def test_copy_source_not_found(self):
        vfs = MongoVFS()
        src = f"/users/{USER_ID}/global/missing.txt"
        dest = f"/users/{USER_ID}/global/b.txt"

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=None)

            with pytest.raises(FileNotFoundError):
                await vfs.copy(src, dest, USER_ID)

    async def test_copy_folder_raises(self):
        vfs = MongoVFS()
        src = f"/users/{USER_ID}/global/mydir"
        dest = f"/users/{USER_ID}/global/mydir2"
        folder = _make_node(src, node_type="folder", content=None)

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=folder)

            with pytest.raises(ValueError, match="Directory copy not supported"):
                await vfs.copy(src, dest, USER_ID)

    async def test_copy_unreadable_source_raises(self):
        vfs = MongoVFS()
        src = f"/users/{USER_ID}/global/a.txt"
        dest = f"/users/{USER_ID}/global/b.txt"
        node = _make_node(src)

        with (
            patch(MOCK_COLLECTION) as col,
            patch.object(vfs, "read", new_callable=AsyncMock, return_value=None),
        ):
            col.find_one = AsyncMock(return_value=node)

            with pytest.raises(FileNotFoundError, match="Could not read"):
                await vfs.copy(src, dest, USER_ID)


@pytest.mark.asyncio
class TestMongoVFSEnsureDirectories:
    async def test_ensure_directories_root_noop(self):
        vfs = MongoVFS()
        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=None)
            col.update_one = AsyncMock()

            await vfs._ensure_directories("/", USER_ID)

        col.update_one.assert_not_called()

    async def test_ensure_directories_creates_parents(self):
        vfs = MongoVFS()
        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=None)
            col.update_one = AsyncMock()

            await vfs._ensure_directories(f"/users/{USER_ID}/global/sub", USER_ID)

        # Should create: /users, /users/{USER_ID}, /users/{USER_ID}/global, /users/{USER_ID}/global/sub
        assert col.update_one.call_count == 4

    async def test_ensure_directories_conflict_raises(self):
        vfs = MongoVFS()
        file_node = _make_node("/users", node_type="file")

        with patch(MOCK_COLLECTION) as col:
            col.find_one = AsyncMock(return_value=file_node)

            with pytest.raises(ValueError, match="already exists as a file"):
                await vfs._ensure_directories(f"/users/{USER_ID}/global", USER_ID)


@pytest.mark.asyncio
class TestMongoVFSGetGridFS:
    async def test_lazy_loads_gridfs_bucket(self):
        vfs = MongoVFS()
        mock_db = MagicMock()

        with patch(
            "app.services.vfs.mongo_vfs._get_mongodb_instance"
        ) as mock_get_mongo:
            mock_mongo = MagicMock()
            mock_mongo.database = mock_db
            mock_get_mongo.return_value = mock_mongo

            with patch(
                "app.services.vfs.mongo_vfs.AsyncIOMotorGridFSBucket"
            ) as mock_bucket_cls:
                mock_bucket_cls.return_value = "bucket_instance"

                result = await vfs._get_gridfs()

        assert result == "bucket_instance"

    async def test_gridfs_cached_after_first_call(self):
        vfs = MongoVFS()
        vfs._gridfs_bucket = "cached_bucket"

        result = await vfs._get_gridfs()
        assert result == "cached_bucket"
