"""
VFS User Isolation Security Tests.

CRITICAL: These tests verify that users CANNOT access other users' files.
All tests MUST pass to ensure proper security.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.vfs.mongo_vfs import MongoVFS, VFSAccessError
from app.services.vfs.path_resolver import validate_user_access, normalize_path


class TestVFSAccessError:
    """Test VFSAccessError exception."""

    def test_error_message_contains_path_and_user(self):
        """Error message should clearly indicate what access was denied."""
        error = VFSAccessError("/users/user2/global/secret.txt", "user1")
        assert "user1" in str(error)
        assert "/users/user2/global/secret.txt" in str(error)
        assert "Access denied" in str(error)

    def test_error_is_permission_error(self):
        """VFSAccessError should be a PermissionError subclass."""
        error = VFSAccessError("/path", "user")
        assert isinstance(error, PermissionError)


class TestValidateUserAccess:
    """Test the validate_user_access function."""

    def test_valid_user_path(self):
        """User should have access to their own paths."""
        assert validate_user_access("/users/user123/global/files", "user123") is True
        assert validate_user_access("/users/user123/global/notes", "user123") is True
        assert validate_user_access("/users/user123/global/executor", "user123") is True

    def test_invalid_user_path(self):
        """User should NOT have access to other users' paths."""
        assert validate_user_access("/users/user456/global/files", "user123") is False
        assert validate_user_access("/users/other/global/notes", "user123") is False

    def test_partial_user_id_match_fails(self):
        """Partial user ID matches should fail (user12 != user123)."""
        assert validate_user_access("/users/user12/global", "user123") is False
        assert validate_user_access("/users/user1234/global", "user123") is False

    def test_path_traversal_normalized_correctly(self):
        """Path traversal attempts should be normalized to safe paths."""
        # After normalization, .. is removed which COULD still be in user's space
        # The key is that we can't escape OUT of the user's root
        normalized = normalize_path("/users/user123/../user456/global")
        # This becomes /users/user123/user456/global (.. removed, not escaped)
        # which IS under user123's space - this is safe
        assert normalized.startswith("/users/user123")

        # The dangerous case is trying to escape the users folder entirely
        normalized2 = normalize_path("/../../../etc/passwd")
        # This becomes /etc/passwd - NOT under any user
        assert not validate_user_access(normalized2, "user123")

    def test_root_path_access_denied(self):
        """Users should not access system root paths."""
        assert validate_user_access("/", "user123") is False
        assert validate_user_access("/users", "user123") is False

    def test_user_root_access_allowed(self):
        """User should access their own root."""
        assert validate_user_access("/users/user123", "user123") is True
        assert validate_user_access("/users/user123/", "user123") is True


class TestNormalizePath:
    """Test path normalization security."""

    def test_removes_path_traversal(self):
        """Path traversal (..) should be removed."""
        assert ".." not in normalize_path("/users/../etc/passwd")
        assert ".." not in normalize_path("/users/user1/../user2/secret")
        assert ".." not in normalize_path("../../../etc/passwd")

    def test_normalizes_double_slashes(self):
        """Double slashes should be collapsed."""
        assert "//" not in normalize_path("/users//user1//global")

    def test_handles_backslashes(self):
        """Backslashes should be converted to forward slashes."""
        assert "\\" not in normalize_path("\\users\\user1\\global")


@pytest.fixture
def mock_vfs_collection():
    """Mock the vfs_nodes_collection for testing."""
    with patch("app.services.vfs.mongo_vfs.vfs_nodes_collection") as mock:
        mock.find_one = AsyncMock(return_value=None)
        mock.update_one = AsyncMock()
        mock.insert_one = AsyncMock()
        mock.delete_one = AsyncMock()
        mock.delete_many = AsyncMock()

        # Create a proper async cursor mock for find()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock.find = MagicMock(return_value=mock_cursor)

        yield mock


@pytest.fixture
def vfs():
    """Create a MongoVFS instance."""
    return MongoVFS()


class TestCrossUserAccessPrevention:
    """CRITICAL: Test that cross-user access is prevented on ALL operations."""

    @pytest.mark.asyncio
    async def test_read_other_user_file_raises_error(self, vfs, mock_vfs_collection):
        """User1 should NOT be able to read User2's files."""
        # User2's path, but User1 is requesting
        with pytest.raises(VFSAccessError) as exc_info:
            await vfs.read("/users/user2/global/secret.txt", user_id="user1")

        assert "user1" in str(exc_info.value)
        assert "Access denied" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_write_to_other_user_path_raises_error(
        self, vfs, mock_vfs_collection
    ):
        """User1 should NOT be able to write to User2's paths."""
        with pytest.raises(VFSAccessError):
            await vfs.write(
                "/users/user2/global/malicious.txt",
                "hacked!",
                user_id="user1",
            )

    @pytest.mark.asyncio
    async def test_delete_other_user_file_raises_error(self, vfs, mock_vfs_collection):
        """User1 should NOT be able to delete User2's files."""
        with pytest.raises(VFSAccessError):
            await vfs.delete("/users/user2/global/important.txt", user_id="user1")

    @pytest.mark.asyncio
    async def test_move_to_other_user_path_raises_error(self, vfs, mock_vfs_collection):
        """User1 should NOT be able to move files to User2's paths."""
        # Source is valid, destination is not
        mock_vfs_collection.find_one.return_value = {
            "path": "/users/user1/global/file.txt",
            "node_type": "file",
            "user_id": "user1",
        }
        with pytest.raises(VFSAccessError):
            await vfs.move(
                "/users/user1/global/file.txt",
                "/users/user2/global/stolen.txt",
                user_id="user1",
            )

    @pytest.mark.asyncio
    async def test_move_from_other_user_path_raises_error(
        self, vfs, mock_vfs_collection
    ):
        """User1 should NOT be able to move files FROM User2's paths."""
        with pytest.raises(VFSAccessError):
            await vfs.move(
                "/users/user2/global/secret.txt",
                "/users/user1/global/stolen.txt",
                user_id="user1",
            )

    @pytest.mark.asyncio
    async def test_copy_from_other_user_raises_error(self, vfs, mock_vfs_collection):
        """User1 should NOT be able to copy User2's files."""
        with pytest.raises(VFSAccessError):
            await vfs.copy(
                "/users/user2/global/secret.txt",
                "/users/user1/global/copy.txt",
                user_id="user1",
            )

    @pytest.mark.asyncio
    async def test_copy_to_other_user_raises_error(self, vfs, mock_vfs_collection):
        """User1 should NOT be able to copy files TO User2's paths."""
        mock_vfs_collection.find_one.return_value = {
            "path": "/users/user1/global/file.txt",
            "node_type": "file",
            "user_id": "user1",
        }
        with pytest.raises(VFSAccessError):
            await vfs.copy(
                "/users/user1/global/file.txt",
                "/users/user2/global/stolen.txt",
                user_id="user1",
            )

    @pytest.mark.asyncio
    async def test_list_other_user_directory_raises_error(
        self, vfs, mock_vfs_collection
    ):
        """User1 should NOT be able to list User2's directories."""
        with pytest.raises(VFSAccessError):
            await vfs.list_dir("/users/user2/global", user_id="user1")

    @pytest.mark.asyncio
    async def test_tree_other_user_directory_raises_error(
        self, vfs, mock_vfs_collection
    ):
        """User1 should NOT be able to get tree of User2's directories."""
        with pytest.raises(VFSAccessError):
            await vfs.tree("/users/user2/global", user_id="user1")

    @pytest.mark.asyncio
    async def test_info_other_user_file_raises_error(self, vfs, mock_vfs_collection):
        """User1 should NOT be able to get info on User2's files."""
        with pytest.raises(VFSAccessError):
            await vfs.info("/users/user2/global/secret.txt", user_id="user1")

    @pytest.mark.asyncio
    async def test_exists_other_user_file_raises_error(self, vfs, mock_vfs_collection):
        """User1 should NOT be able to check if User2's files exist."""
        with pytest.raises(VFSAccessError):
            await vfs.exists("/users/user2/global/secret.txt", user_id="user1")

    @pytest.mark.asyncio
    async def test_append_to_other_user_file_raises_error(
        self, vfs, mock_vfs_collection
    ):
        """User1 should NOT be able to append to User2's files."""
        with pytest.raises(VFSAccessError):
            await vfs.append(
                "/users/user2/global/file.txt",
                "malicious content",
                user_id="user1",
            )

    @pytest.mark.asyncio
    async def test_mkdir_in_other_user_path_raises_error(
        self, vfs, mock_vfs_collection
    ):
        """User1 should NOT be able to create directories in User2's space."""
        with pytest.raises(VFSAccessError):
            await vfs.mkdir("/users/user2/global/hacked", user_id="user1")

    @pytest.mark.asyncio
    async def test_analyze_other_user_file_raises_error(self, vfs, mock_vfs_collection):
        """User1 should NOT be able to analyze User2's files."""
        with pytest.raises(VFSAccessError):
            await vfs.analyze("/users/user2/global/secret.json", user_id="user1")

    @pytest.mark.asyncio
    async def test_search_in_other_user_path_raises_error(
        self, vfs, mock_vfs_collection
    ):
        """User1 should NOT be able to search in User2's directories."""
        with pytest.raises(VFSAccessError):
            await vfs.search("*.txt", user_id="user1", base_path="/users/user2/global")


class TestPathTraversalAttacks:
    """Test that path traversal attacks are safely neutralized.

    SECURITY NOTE: Our normalize_path() removes '..' patterns entirely,
    so '/users/user1/../user2/' becomes '/users/user1/user2/' which stays
    WITHIN user1's space. This is secure by design - traversal cannot escape.
    """

    @pytest.mark.asyncio
    async def test_traversal_stays_in_user_space(self, vfs, mock_vfs_collection):
        """Path traversal attempts are neutralized and stay in user's space."""
        mock_vfs_collection.find_one.return_value = None

        # /users/user1/../user2/ normalizes to /users/user1/user2/ - still in user1's space
        # This should NOT raise - the path is safe after normalization
        result = await vfs.read(
            "/users/user1/../user2/global/secret.txt",
            user_id="user1",
        )
        # No error - file just doesn't exist (returns None)
        assert result is None

    @pytest.mark.asyncio
    async def test_write_traversal_stays_in_user_space(self, vfs, mock_vfs_collection):
        """Write with traversal is neutralized to user's space."""
        mock_vfs_collection.find_one.return_value = None

        # /users/user1/../../user2/ normalizes to /users/user1/user2/
        result = await vfs.write(
            "/users/user1/../../user2/global/hacked.txt",
            "content",
            user_id="user1",
        )
        # Path was normalized to user1's space
        assert result.startswith("/users/user1/")

    @pytest.mark.asyncio
    async def test_delete_traversal_stays_in_user_space(self, vfs, mock_vfs_collection):
        """Delete with traversal is neutralized to user's space."""
        mock_vfs_collection.find_one.return_value = None

        # The traversal is neutralized, path stays in user1's space
        # Returns False because file doesn't exist (not because of access error)
        result = await vfs.delete(
            "/users/user1/../user2/global/important.txt",
            user_id="user1",
        )
        assert result is False  # File doesn't exist

    @pytest.mark.asyncio
    async def test_absolute_paths_outside_users_get_prefixed(
        self, vfs, mock_vfs_collection
    ):
        """Absolute paths not under /users/ get auto-prefixed for safety."""
        mock_vfs_collection.find_one.return_value = None

        # /etc/passwd gets prefixed to /users/user1/global/etc/passwd - this is safe
        result = await vfs.read("/etc/passwd", user_id="user1")
        # No error - just returns None because file doesn't exist
        assert result is None

    @pytest.mark.asyncio
    async def test_system_paths_get_prefixed(self, vfs, mock_vfs_collection):
        """System paths like /root get prefixed to user's space."""
        mock_vfs_collection.find_one.return_value = None

        # /root/.bashrc becomes /users/user1/global/root/.bashrc
        result = await vfs.read("/root/.bashrc", user_id="user1")
        assert result is None  # File doesn't exist, but no access error


class TestUserIdRequired:
    """Test that user_id is required on all operations."""

    @pytest.mark.asyncio
    async def test_read_without_user_id_raises_error(self, vfs, mock_vfs_collection):
        """Read without user_id should raise ValueError."""
        with pytest.raises(ValueError, match="user_id is required"):
            await vfs.read("/users/user1/global/file.txt", user_id="")

    @pytest.mark.asyncio
    async def test_write_without_user_id_raises_error(self, vfs, mock_vfs_collection):
        """Write without user_id should raise ValueError."""
        with pytest.raises(ValueError, match="user_id is required"):
            await vfs.write("/users/user1/global/file.txt", "content", user_id="")

    @pytest.mark.asyncio
    async def test_delete_without_user_id_raises_error(self, vfs, mock_vfs_collection):
        """Delete without user_id should raise ValueError."""
        with pytest.raises(ValueError, match="user_id is required"):
            await vfs.delete("/users/user1/global/file.txt", user_id="")


class TestAutoPathPrefix:
    """Test that relative paths are auto-prefixed with user scope."""

    @pytest.mark.asyncio
    async def test_relative_path_gets_user_prefix(self, vfs, mock_vfs_collection):
        """Relative paths should be prefixed with user's global path."""
        mock_vfs_collection.find_one.return_value = None

        # Write to a relative path
        result = await vfs.write("notes/test.txt", "content", user_id="user123")

        # Should be prefixed with user's path
        assert result.startswith("/users/user123/global/")
        assert "notes/test.txt" in result

    @pytest.mark.asyncio
    async def test_absolute_user_path_preserved(self, vfs, mock_vfs_collection):
        """Absolute user paths should be preserved."""
        mock_vfs_collection.find_one.return_value = None

        result = await vfs.write(
            "/users/user123/global/files/doc.txt",
            "content",
            user_id="user123",
        )

        assert result == "/users/user123/global/files/doc.txt"


class TestDatabaseQueryIsolation:
    """Test that database queries include user_id for isolation."""

    @pytest.mark.asyncio
    async def test_read_query_includes_user_id(self, vfs, mock_vfs_collection):
        """Read queries should filter by user_id."""
        mock_vfs_collection.find_one.return_value = None

        await vfs.read("/users/user123/global/file.txt", user_id="user123")

        # Verify the query included user_id
        call_args = mock_vfs_collection.find_one.call_args[0][0]
        assert call_args.get("user_id") == "user123"

    @pytest.mark.asyncio
    async def test_delete_query_includes_user_id(self, vfs, mock_vfs_collection):
        """Delete queries should filter by user_id."""
        mock_vfs_collection.find_one.return_value = {
            "path": "/users/user123/global/file.txt",
            "node_type": "file",
            "user_id": "user123",
        }

        await vfs.delete("/users/user123/global/file.txt", user_id="user123")

        # Verify delete_one was called with user_id
        call_args = mock_vfs_collection.delete_one.call_args[0][0]
        assert call_args.get("user_id") == "user123"

    @pytest.mark.asyncio
    async def test_list_dir_query_includes_user_id(self, vfs, mock_vfs_collection):
        """List directory queries should filter by user_id."""
        await vfs.list_dir("/users/user123/global", user_id="user123")

        # Verify find was called with user_id filter
        find_call = mock_vfs_collection.find.call_args
        query = find_call[0][0]
        assert query.get("user_id") == "user123"


class TestConcurrentUserAccess:
    """Test isolation with concurrent user operations."""

    @pytest.mark.asyncio
    async def test_multiple_users_isolated(self, mock_vfs_collection):
        """Multiple users should have isolated VFS spaces."""
        vfs = MongoVFS()
        mock_vfs_collection.find_one.return_value = None

        # User1 writes to their space
        await vfs.write(
            "/users/user1/global/file.txt", "user1 content", user_id="user1"
        )

        # User2 writes to their space
        await vfs.write(
            "/users/user2/global/file.txt", "user2 content", user_id="user2"
        )

        # Verify both writes were called with correct user_id
        calls = mock_vfs_collection.update_one.call_args_list

        # First call should be for user1
        user1_query = calls[0][0][0]  # First argument (query) of first call
        assert user1_query.get("user_id") == "user1"

        # Second call should be for user2
        user2_query = calls[1][0][0]
        assert user2_query.get("user_id") == "user2"
