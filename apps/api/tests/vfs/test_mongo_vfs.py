"""
Tests for MongoVFS - MongoDB-backed Virtual Filesystem.

These tests use mocked MongoDB collections to test VFS operations
without requiring a real database connection.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.models.vfs_models import VFSNodeType


@pytest.fixture
def mock_vfs_collection():
    """Create a mock VFS nodes collection."""
    mock = AsyncMock()
    mock.find_one = AsyncMock(return_value=None)
    mock.update_one = AsyncMock()
    mock.insert_one = AsyncMock()
    mock.delete_one = AsyncMock()
    mock.delete_many = AsyncMock()
    mock.find = MagicMock()
    return mock


@pytest.fixture
def mock_gridfs_bucket():
    """Create a mock GridFS bucket."""
    mock = AsyncMock()
    mock.upload_from_stream = AsyncMock(return_value="gridfs_123")
    mock.open_download_stream = AsyncMock()
    mock.delete = AsyncMock()
    return mock


class TestMongoVFSWrite:
    """Tests for MongoVFS write operations."""

    @pytest.mark.asyncio
    async def test_write_system_path_denied_for_non_system_user(
        self, mock_vfs_collection
    ):
        """Non-system users must never be able to write under /system/."""
        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS, VFSAccessError

            vfs = MongoVFS()
            with pytest.raises(VFSAccessError):
                await vfs.write(
                    "/system/test.txt",
                    "content",
                    user_id="user123",
                )

    @pytest.mark.asyncio
    async def test_allow_system_write_flag_still_blocks_non_system_user(
        self, mock_vfs_collection
    ):
        """Even with allow_system_write, only user_id='system' can write /system/."""
        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS, VFSAccessError

            vfs = MongoVFS(allow_system_write=True)

            with pytest.raises(VFSAccessError):
                await vfs.write(
                    "/system/test.txt",
                    "content",
                    user_id="user123",
                )

            # System user is allowed (used by seeding scripts)
            await vfs.write(
                "/system/test.txt",
                "content",
                user_id="system",
            )
            mock_vfs_collection.update_one.assert_called()

    @pytest.mark.asyncio
    async def test_write_small_file_inline(self, mock_vfs_collection):
        """Small files should be stored inline."""
        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            content = "Hello, World!"

            result = await vfs.write(
                "/users/user123/global/executor/files/test.txt",
                content,
                user_id="user123",
            )

            assert result == "/users/user123/global/executor/files/test.txt"
            mock_vfs_collection.update_one.assert_called()

            # Verify the call arguments
            call_args = mock_vfs_collection.update_one.call_args
            update_doc = call_args[0][1]["$set"]

            assert update_doc["content"] == content
            assert update_doc["gridfs_id"] is None
            assert update_doc["size_bytes"] == len(content.encode("utf-8"))

    @pytest.mark.asyncio
    async def test_write_creates_parent_directories(self, mock_vfs_collection):
        """Write should auto-create parent directories."""
        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()

            await vfs.write(
                "/users/user123/global/executor/files/subdir/test.txt",
                "content",
                user_id="user123",
            )

            # Parent directories are created via upserts
            assert mock_vfs_collection.update_one.call_count > 1

            called_paths = [
                c.args[0].get("path")
                for c in mock_vfs_collection.update_one.call_args_list
                if c.args and isinstance(c.args[0], dict)
            ]
            assert "/users" in called_paths
            assert "/users/user123" in called_paths
            assert "/users/user123/global" in called_paths
            assert "/users/user123/global/executor" in called_paths
            assert "/users/user123/global/executor/files" in called_paths
            assert "/users/user123/global/executor/files/subdir" in called_paths

    @pytest.mark.asyncio
    async def test_write_with_metadata(self, mock_vfs_collection):
        """Write should attach provided metadata."""
        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            metadata = {"tool_call_id": "tc_001", "agent_name": "gmail"}

            await vfs.write(
                "/users/user123/global/test.txt",
                "content",
                user_id="user123",
                metadata=metadata,
            )

            call_args = mock_vfs_collection.update_one.call_args
            update_doc = call_args[0][1]["$set"]
            assert update_doc["metadata"] == metadata


class TestMongoVFSRead:
    """Tests for MongoVFS read operations."""

    @pytest.mark.asyncio
    async def test_read_inline_file(self, mock_vfs_collection):
        """Reading inline file returns content directly."""
        mock_vfs_collection.find_one = AsyncMock(
            return_value={
                "path": "/users/user123/global/test.txt",
                "node_type": "file",
                "content": "Hello, World!",
                "gridfs_id": None,
            }
        )

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            result = await vfs.read("/users/user123/global/test.txt", user_id="user123")

            assert result == "Hello, World!"

    @pytest.mark.asyncio
    async def test_read_system_path_uses_system_user_id_filter(
        self, mock_vfs_collection
    ):
        """System paths must be queried with user_id='system' to avoid shadowing."""
        mock_vfs_collection.find_one = AsyncMock(
            return_value={
                "path": "/system/test.txt",
                "user_id": "system",
                "node_type": "file",
                "content": "system content",
                "gridfs_id": None,
            }
        )

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            result = await vfs.read("/system/test.txt", user_id="user123")

            assert result == "system content"
            mock_vfs_collection.find_one.assert_called_with(
                {"path": "/system/test.txt", "user_id": "system"}
            )
            update_call = mock_vfs_collection.update_one.call_args
            assert update_call is not None
            update_args, _update_kwargs = update_call
            assert update_args[0] == {"path": "/system/test.txt", "user_id": "system"}
            assert "$set" in update_args[1]
            assert "accessed_at" in update_args[1]["$set"]

    @pytest.mark.asyncio
    async def test_read_nonexistent_file_returns_none(self, mock_vfs_collection):
        """Reading nonexistent file returns None."""
        mock_vfs_collection.find_one = AsyncMock(return_value=None)

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            result = await vfs.read(
                "/users/user123/global/nonexistent.txt", user_id="user123"
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_read_folder_returns_none(self, mock_vfs_collection):
        """Reading a folder (not a file) returns None."""
        mock_vfs_collection.find_one = AsyncMock(
            return_value={
                "path": "/users/user123/global/folder",
                "node_type": "folder",
            }
        )

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            result = await vfs.read("/users/user123/global/folder", user_id="user123")

            assert result is None


class TestMongoVFSExists:
    """Tests for MongoVFS exists operation."""

    @pytest.mark.asyncio
    async def test_exists_returns_true_for_existing_path(self, mock_vfs_collection):
        """Exists returns True when path exists."""
        mock_vfs_collection.find_one = AsyncMock(return_value={"_id": "123"})

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            result = await vfs.exists(
                "/users/user123/global/test.txt", user_id="user123"
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_exists_returns_false_for_missing_path(self, mock_vfs_collection):
        """Exists returns False when path doesn't exist."""
        mock_vfs_collection.find_one = AsyncMock(return_value=None)

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            result = await vfs.exists(
                "/users/user123/global/nonexistent.txt", user_id="user123"
            )

            assert result is False


class TestMongoVFSMkdir:
    """Tests for MongoVFS mkdir operation."""

    @pytest.mark.asyncio
    async def test_mkdir_creates_directory(self, mock_vfs_collection):
        """Mkdir creates a directory node."""
        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            result = await vfs.mkdir(
                "/users/user123/global/executor/files/newdir", user_id="user123"
            )

            assert result == "/users/user123/global/executor/files/newdir"


class TestMongoVFSDelete:
    """Tests for MongoVFS delete operation."""

    @pytest.mark.asyncio
    async def test_delete_file(self, mock_vfs_collection):
        """Deleting a file removes it."""
        mock_vfs_collection.find_one = AsyncMock(
            return_value={
                "path": "/users/user123/global/test.txt",
                "node_type": "file",
                "gridfs_id": None,
            }
        )

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            result = await vfs.delete(
                "/users/user123/global/test.txt", user_id="user123"
            )

            assert result is True
            mock_vfs_collection.delete_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, mock_vfs_collection):
        """Deleting nonexistent path returns False."""
        mock_vfs_collection.find_one = AsyncMock(return_value=None)

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            result = await vfs.delete(
                "/users/user123/global/nonexistent.txt", user_id="user123"
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_delete_nonempty_folder_without_recursive_raises(
        self, mock_vfs_collection
    ):
        """Deleting non-empty folder without recursive flag raises error."""
        mock_vfs_collection.find_one = AsyncMock(
            side_effect=[
                # First call: the folder itself
                {"path": "/folder", "node_type": "folder"},
                # Second call: check for children
                {"path": "/folder/child.txt", "node_type": "file"},
            ]
        )

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            with pytest.raises(ValueError, match="not empty"):
                await vfs.delete(
                    "/users/user123/global/folder", user_id="user123", recursive=False
                )


class TestMongoVFSListDir:
    """Tests for MongoVFS list_dir operation."""

    @pytest.mark.asyncio
    async def test_list_dir_returns_children(self, mock_vfs_collection):
        """List directory returns direct children."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "path": "/users/user123/global/files/file1.txt",
                    "name": "file1.txt",
                    "node_type": "file",
                    "size_bytes": 100,
                },
                {
                    "path": "/users/user123/global/files/folder1",
                    "name": "folder1",
                    "node_type": "folder",
                    "size_bytes": 0,
                },
            ]
        )
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_vfs_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            result = await vfs.list_dir(
                "/users/user123/global/files", user_id="user123"
            )

            assert result.total_count == 2
            assert len(result.items) == 2
            assert result.items[0].name == "file1.txt"
            assert result.items[1].name == "folder1"


class TestMongoVFSInfo:
    """Tests for MongoVFS info operation."""

    @pytest.mark.asyncio
    async def test_info_returns_metadata(self, mock_vfs_collection):
        """Info returns file metadata without content."""
        now = datetime.now(timezone.utc)
        mock_vfs_collection.find_one = AsyncMock(
            return_value={
                "path": "/users/user123/global/test.txt",
                "name": "test.txt",
                "node_type": "file",
                "size_bytes": 100,
                "content_type": "text/plain",
                "created_at": now,
                "updated_at": now,
                "metadata": {"agent_name": "executor"},
            }
        )

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            result = await vfs.info("/users/user123/global/test.txt", user_id="user123")

            assert result is not None
            assert result.name == "test.txt"
            assert result.node_type == VFSNodeType.FILE
            assert result.size_bytes == 100
            assert result.metadata == {"agent_name": "executor"}


class TestMongoVFSSearch:
    """Tests for MongoVFS search operation."""

    @pytest.mark.asyncio
    async def test_search_with_glob_pattern(self, mock_vfs_collection):
        """Search finds files matching glob pattern."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "path": "/users/user123/global/files/data.json",
                    "name": "data.json",
                    "node_type": "file",
                    "size_bytes": 50,
                },
                {
                    "path": "/users/user123/global/files/config.json",
                    "name": "config.json",
                    "node_type": "file",
                    "size_bytes": 30,
                },
            ]
        )
        mock_vfs_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            result = await vfs.search(
                "*.json", user_id="user123", base_path="/users/user123/global/files"
            )

            assert result.total_count == 2
            assert result.pattern == "*.json"


class TestMongoVFSMove:
    """Tests for MongoVFS move operation."""

    @pytest.mark.asyncio
    async def test_move_file(self, mock_vfs_collection):
        """Move renames file path."""
        # First lookup finds the source file; subsequent lookups (directory ensures)
        # should behave as if directories don't exist yet.
        mock_vfs_collection.find_one = AsyncMock(
            side_effect=[
                {"path": "/users/user123/global/old.txt", "node_type": "file"},
                *([None] * 20),
            ]
        )

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            result = await vfs.move(
                "/users/user123/global/old.txt",
                "/users/user123/global/new.txt",
                user_id="user123",
            )

            assert result == "/users/user123/global/new.txt"
            mock_vfs_collection.update_one.assert_called()

    @pytest.mark.asyncio
    async def test_move_nonexistent_raises(self, mock_vfs_collection):
        """Moving nonexistent file raises FileNotFoundError."""
        mock_vfs_collection.find_one = AsyncMock(return_value=None)

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            with pytest.raises(FileNotFoundError):
                await vfs.move(
                    "/users/user123/global/nonexistent.txt",
                    "/users/user123/global/new.txt",
                    user_id="user123",
                )


class TestMongoVFSCopy:
    """Tests for MongoVFS copy operation."""

    @pytest.mark.asyncio
    async def test_copy_file(self, mock_vfs_collection):
        """Copy duplicates file content."""
        source_node = {
            "path": "/users/user123/global/source.txt",
            "node_type": "file",
            "content": "Original content",
            "gridfs_id": None,
            "metadata": {},
        }

        # copy() looks up the node, then read() looks up the node again.
        mock_vfs_collection.find_one = AsyncMock(
            side_effect=[source_node, source_node, *([None] * 50)]
        )

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            result = await vfs.copy(
                "/users/user123/global/source.txt",
                "/users/user123/global/copy.txt",
                user_id="user123",
            )

            assert result == "/users/user123/global/copy.txt"

    @pytest.mark.asyncio
    async def test_copy_folder_raises(self, mock_vfs_collection):
        """Copying a folder raises ValueError."""
        mock_vfs_collection.find_one = AsyncMock(
            return_value={
                "path": "/folder",
                "node_type": "folder",
            }
        )

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            with pytest.raises(ValueError, match="Directory copy not supported"):
                await vfs.copy(
                    "/users/user123/global/folder",
                    "/users/user123/global/folder_copy",
                    user_id="user123",
                )


class TestMongoVFSAppend:
    """Tests for MongoVFS append operation."""

    @pytest.mark.asyncio
    async def test_append_to_existing_file(self, mock_vfs_collection):
        """Append adds content to existing file."""
        existing_node = {
            "path": "/users/user123/global/log.txt",
            "node_type": "file",
            "content": "Line 1\n",
            "gridfs_id": None,
            "metadata": {},
        }

        # append() reads existing file once; subsequent lookups are for directory
        # ensures and overwrite logic.
        mock_vfs_collection.find_one = AsyncMock(
            side_effect=[existing_node, *([None] * 50)]
        )

        with patch(
            "app.services.vfs.mongo_vfs.vfs_nodes_collection", mock_vfs_collection
        ):
            from app.services.vfs.mongo_vfs import MongoVFS

            vfs = MongoVFS()
            result = await vfs.append(
                "/users/user123/global/log.txt", "Line 2\n", user_id="user123"
            )

            assert result == "/users/user123/global/log.txt"
            # Should write combined content (find the file upsert)
            file_updates = [
                c
                for c in mock_vfs_collection.update_one.call_args_list
                if c.args
                and isinstance(c.args[0], dict)
                and c.args[0].get("path") == "/users/user123/global/log.txt"
            ]
            assert file_updates
            update_doc = file_updates[-1].args[1]["$set"]
            assert update_doc["content"] == "Line 1\nLine 2\n"
