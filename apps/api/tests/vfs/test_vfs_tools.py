"""
Tests for VFS Tools - New focused tool set.

Tests the 4 VFS tools: vfs_read, vfs_write, vfs_cmd
"""

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.runnables import RunnableConfig


@pytest.fixture
def mock_config() -> RunnableConfig:
    """Create a mock RunnableConfig with user context."""
    return {
        "metadata": {
            "user_id": "user123",
            "conversation_id": "conv1",
            "agent_name": "executor",
        }
    }


@pytest.fixture
def mock_vfs():
    """Create a mock VFS instance."""
    mock = AsyncMock()
    mock.read = AsyncMock(return_value="file content")
    mock.write = AsyncMock(return_value="/users/user123/global/executor/files/test.txt")
    mock.append = AsyncMock(
        return_value="/users/user123/global/executor/files/test.txt"
    )
    mock.analyze = AsyncMock()
    mock.list_dir = AsyncMock()
    mock.tree = AsyncMock()
    mock.search = AsyncMock()
    mock.info = AsyncMock()
    return mock


# ==================== vfs_read Tests ====================


class TestVfsRead:
    """Tests for vfs_read tool."""

    @pytest.mark.asyncio
    async def test_read_file(self, mock_config, mock_vfs):
        """Read tool returns file content."""
        with patch("app.services.vfs.get_vfs", return_value=mock_vfs):
            from app.agents.tools.vfs_tools import vfs_read

            result = await vfs_read.ainvoke(
                {"path": "notes/test.txt"},
                config=mock_config,
            )

            assert result == "file content"
            mock_vfs.read.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, mock_config, mock_vfs):
        """Read tool returns error for missing file."""
        mock_vfs.read = AsyncMock(return_value=None)

        with patch("app.services.vfs.get_vfs", return_value=mock_vfs):
            from app.agents.tools.vfs_tools import vfs_read

            result = await vfs_read.ainvoke(
                {"path": "nonexistent.txt"},
                config=mock_config,
            )

            assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_read_requires_user_id(self, mock_vfs):
        """Read tool returns error when user_id is missing."""
        empty_config = {"metadata": {}}

        with patch("app.services.vfs.get_vfs", return_value=mock_vfs):
            from app.agents.tools.vfs_tools import vfs_read

            result = await vfs_read.ainvoke(
                {"path": "test.txt"},
                config=empty_config,
            )

            assert "Error" in result


# ==================== vfs_write Tests ====================


class TestVfsWrite:
    """Tests for vfs_write tool."""

    @pytest.mark.asyncio
    async def test_write_file(self, mock_config, mock_vfs):
        """Write tool creates/overwrites a file."""
        with patch("app.services.vfs.get_vfs", return_value=mock_vfs):
            from app.agents.tools.vfs_tools import vfs_write

            result = await vfs_write.ainvoke(
                {"path": "notes/test.txt", "content": "hello world"},
                config=mock_config,
            )

            assert "Wrote" in result
            assert "11 characters" in result
            mock_vfs.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_append_mode(self, mock_config, mock_vfs):
        """Write tool appends when append=True."""
        with patch("app.services.vfs.get_vfs", return_value=mock_vfs):
            from app.agents.tools.vfs_tools import vfs_write

            result = await vfs_write.ainvoke(
                {"path": "notes/log.txt", "content": "new line\n", "append": True},
                config=mock_config,
            )

            assert "Appended" in result
            mock_vfs.append.assert_called_once()
            mock_vfs.write.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_requires_user_id(self, mock_vfs):
        """Write tool returns error when user_id is missing."""
        empty_config = {"metadata": {}}

        with patch("app.services.vfs.get_vfs", return_value=mock_vfs):
            from app.agents.tools.vfs_tools import vfs_write

            result = await vfs_write.ainvoke(
                {"path": "test.txt", "content": "hello"},
                config=empty_config,
            )

            assert "Error" in result


# ==================== vfs_cmd Tests ====================


class TestVfsCmd:
    """Tests for vfs_cmd tool."""

    @pytest.mark.asyncio
    async def test_cmd_pwd(self, mock_config):
        """pwd command returns working directory."""
        with patch(
            "app.agents.tools.vfs_cmd_parser.get_vfs_command_parser"
        ) as mock_parser:
            mock_instance = AsyncMock()
            mock_instance.execute = AsyncMock(
                return_value="/users/user123/global/executor"
            )
            mock_parser.return_value = mock_instance

            from app.agents.tools.vfs_tools import vfs_cmd

            result = await vfs_cmd.ainvoke(
                {"command": "pwd"},
                config=mock_config,
            )

            assert "/users/user123" in result

    @pytest.mark.asyncio
    async def test_cmd_blocked_command(self, mock_config):
        """Blocked commands return error."""
        with patch(
            "app.agents.tools.vfs_cmd_parser.get_vfs_command_parser"
        ) as mock_parser:
            mock_instance = AsyncMock()
            mock_instance.execute = AsyncMock(
                return_value="Error: 'rm' is not supported."
            )
            mock_parser.return_value = mock_instance

            from app.agents.tools.vfs_tools import vfs_cmd

            result = await vfs_cmd.ainvoke(
                {"command": "rm file.txt"},
                config=mock_config,
            )

            assert "not supported" in result.lower()

    @pytest.mark.asyncio
    async def test_cmd_requires_user_id(self):
        """vfs_cmd returns error when user_id is missing."""
        empty_config = {"metadata": {}}

        from app.agents.tools.vfs_tools import vfs_cmd

        result = await vfs_cmd.ainvoke(
            {"command": "ls"},
            config=empty_config,
        )

        assert "Error" in result


# ==================== Command Parser Basic Tests ====================
# (Comprehensive parser tests are in test_vfs_cmd_parser.py)


class TestVfsCommandParserBasic:
    """Basic tests for VFSCommandParser using new argparse API."""

    def test_parse_ls_with_flags(self):
        """Parse ls command with flags."""
        from app.agents.tools.vfs_cmd_parser import VFSCommandParser

        parser = VFSCommandParser()
        cmd, args, redirect = parser._parse_command("ls -la notes/")

        assert cmd == "ls"
        assert args.path == "notes/"
        assert args.long is True
        assert args.all is True

    def test_parse_find_with_name(self):
        """Parse find command with -name flag."""
        from app.agents.tools.vfs_cmd_parser import VFSCommandParser

        parser = VFSCommandParser()
        cmd, args, redirect = parser._parse_command('find . -name "*.json"')

        assert cmd == "find"
        assert args.path == "."
        assert args.name == "*.json"

    def test_parse_echo_with_redirect(self):
        """Parse echo command with redirect."""
        from app.agents.tools.vfs_cmd_parser import VFSCommandParser

        parser = VFSCommandParser()
        cmd, args, redirect = parser._parse_command('echo "hello" > test.txt')

        assert cmd == "echo"
        assert "hello" in args.text
        assert redirect is not None
        assert redirect.mode == ">"
        assert redirect.filepath == "test.txt"

    def test_parse_echo_with_append_redirect(self):
        """Parse echo command with append redirect."""
        from app.agents.tools.vfs_cmd_parser import VFSCommandParser

        parser = VFSCommandParser()
        cmd, args, redirect = parser._parse_command('echo "hello" >> test.txt')

        assert cmd == "echo"
        assert redirect.mode == ">>"
        assert redirect.filepath == "test.txt"

    def test_parse_grep_with_flags(self):
        """Parse grep command with flags."""
        from app.agents.tools.vfs_cmd_parser import VFSCommandParser

        parser = VFSCommandParser()
        cmd, args, redirect = parser._parse_command('grep -i -r "pattern" .')

        assert cmd == "grep"
        assert args.pattern == "pattern"
        assert args.path == "."
        assert args.ignore_case is True
        assert args.recursive is True

    def test_parse_tree_with_depth(self):
        """Parse tree command with depth flag."""
        from app.agents.tools.vfs_cmd_parser import VFSCommandParser

        parser = VFSCommandParser()
        cmd, args, redirect = parser._parse_command("tree sessions/ -L 2")

        assert cmd == "tree"
        assert args.path == "sessions/"
        assert args.level == 2


# ==================== Path Resolution Tests ====================


class TestPathResolution:
    """Tests for path resolution in VFS tools."""

    def test_relative_path_notes(self):
        """Notes paths resolve correctly."""
        from app.agents.tools.vfs_tools import _resolve_path

        result = _resolve_path("notes/meeting.txt", "user123", "executor")
        assert result == "/users/user123/global/executor/notes/meeting.txt"

    def test_relative_path_files(self):
        """Files paths resolve correctly."""
        from app.agents.tools.vfs_tools import _resolve_path

        result = _resolve_path("files/data.json", "user123", "executor")
        assert result == "/users/user123/global/executor/files/data.json"

    def test_filename_only(self):
        """Filename only resolves to files folder."""
        from app.agents.tools.vfs_tools import _resolve_path

        result = _resolve_path("data.json", "user123", "executor")
        assert result == "/users/user123/global/executor/files/data.json"

    def test_absolute_path_preserved(self):
        """Absolute paths are preserved if valid."""
        from app.agents.tools.vfs_tools import _resolve_path

        result = _resolve_path(
            "/users/user123/global/executor/notes/test.txt", "user123", "executor"
        )
        assert result == "/users/user123/global/executor/notes/test.txt"


# ==================== Tool Export Tests ====================


class TestToolExports:
    """Test that tools are properly exported."""

    def test_tools_list_contains_four_tools(self):
        """Tools list should contain exactly 4 tools."""
        from app.agents.tools.vfs_tools import tools

        assert len(tools) == 4

    def test_tool_names(self):
        """Tools should have correct names."""
        from app.agents.tools.vfs_tools import tools

        names = [t.name for t in tools]
        assert "vfs_read" in names
        assert "vfs_write" in names
        assert "vfs_cmd" in names
