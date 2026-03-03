"""Tests for VFS Tools.

Tests the VFS tools: vfs_read, vfs_write, vfs_cmd.
"""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.runnables import RunnableConfig

from app.models.payment_models import PlanType


@pytest.fixture
def mock_config() -> RunnableConfig:
    """Create a mock RunnableConfig with user context."""
    return {
        "metadata": {
            "user_id": "user123",
            "thread_id": "conv1",
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
        with patch("app.agents.tools.vfs_tools.get_vfs", return_value=mock_vfs):
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

        with patch("app.agents.tools.vfs_tools.get_vfs", return_value=mock_vfs):
            from app.agents.tools.vfs_tools import vfs_read

            result = await vfs_read.ainvoke(
                {"path": "nonexistent.txt"},
                config=mock_config,
            )

            assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_read_requires_user_id(self, mock_vfs):
        """Read tool returns error when user_id is missing."""
        empty_config = cast(RunnableConfig, {"metadata": {}})

        with patch("app.agents.tools.vfs_tools.get_vfs", return_value=mock_vfs):
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
        rate_limit_mock = AsyncMock(return_value={})
        with (
            patch("app.agents.tools.vfs_tools.get_vfs", return_value=mock_vfs),
            patch(
                "app.decorators.rate_limiting._get_cached_subscription",
                new=AsyncMock(return_value=SimpleNamespace(plan_type=PlanType.FREE)),
            ),
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new=rate_limit_mock,
            ),
        ):
            from app.agents.tools.vfs_tools import vfs_write

            result = await vfs_write.ainvoke(
                {"path": "notes/test.txt", "content": "hello world"},
                config=mock_config,
            )

            assert "Wrote" in result
            assert "11 characters" in result
            mock_vfs.write.assert_called_once()
            rate_limit_mock.assert_awaited_once()
            assert rate_limit_mock.call_args.kwargs.get("feature_key") == "vfs_write"

    @pytest.mark.asyncio
    async def test_write_append_mode(self, mock_config, mock_vfs):
        """Write tool appends when append=True."""
        rate_limit_mock = AsyncMock(return_value={})
        with (
            patch("app.agents.tools.vfs_tools.get_vfs", return_value=mock_vfs),
            patch(
                "app.decorators.rate_limiting._get_cached_subscription",
                new=AsyncMock(return_value=SimpleNamespace(plan_type=PlanType.FREE)),
            ),
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new=rate_limit_mock,
            ),
        ):
            from app.agents.tools.vfs_tools import vfs_write

            result = await vfs_write.ainvoke(
                {
                    "path": "notes/log.txt",
                    "content": "new line\n",
                    "append": True,
                },
                config=mock_config,
            )

            assert "Appended" in result
            mock_vfs.append.assert_called_once()
            rate_limit_mock.assert_awaited_once()
            assert rate_limit_mock.call_args.kwargs.get("feature_key") == "vfs_write"

    @pytest.mark.asyncio
    async def test_write_requires_user_id(self, mock_vfs):
        """Write tool returns error when user_id is missing."""
        empty_config = cast(RunnableConfig, {"metadata": {}})

        with patch("app.agents.tools.vfs_tools.get_vfs", return_value=mock_vfs):
            from app.agents.tools.vfs_tools import vfs_write

            result = await vfs_write.ainvoke(
                {"path": "test.txt", "content": "hello"},
                config=empty_config,
            )

            assert "Error" in result

    @pytest.mark.asyncio
    async def test_write_user_visible_emits_artifact_event(self, mock_config, mock_vfs):
        """Writing to .user-visible emits artifact_data for the UI."""
        rate_limit_mock = AsyncMock(return_value={})
        writer = MagicMock()
        mock_vfs.info = AsyncMock(return_value=SimpleNamespace(size_bytes=42))

        with (
            patch("app.agents.tools.vfs_tools.get_vfs", return_value=mock_vfs),
            patch("app.agents.tools.vfs_tools.get_stream_writer", return_value=writer),
            patch(
                "app.decorators.rate_limiting._get_cached_subscription",
                new=AsyncMock(return_value=SimpleNamespace(plan_type=PlanType.FREE)),
            ),
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new=rate_limit_mock,
            ),
        ):
            from app.agents.tools.vfs_tools import vfs_write

            await vfs_write.ainvoke(
                {
                    "path": ".user-visible/report.md",
                    "content": "# Final report",
                },
                config=mock_config,
            )

            writer.assert_called_once()
            payload = writer.call_args.args[0]
            artifact_data = payload["artifact_data"]
            assert artifact_data["filename"] == "report.md"
            assert "/sessions/conv1/.user-visible/report.md" in artifact_data["path"]
            assert artifact_data["content_type"] == "text/markdown"

    @pytest.mark.asyncio
    async def test_write_private_file_does_not_emit_artifact_event(
        self, mock_config, mock_vfs
    ):
        """Writing outside .user-visible should not emit artifact events."""
        rate_limit_mock = AsyncMock(return_value={})
        mock_get_stream_writer = MagicMock()

        with (
            patch("app.agents.tools.vfs_tools.get_vfs", return_value=mock_vfs),
            patch(
                "app.agents.tools.vfs_tools.get_stream_writer", mock_get_stream_writer
            ),
            patch(
                "app.decorators.rate_limiting._get_cached_subscription",
                new=AsyncMock(return_value=SimpleNamespace(plan_type=PlanType.FREE)),
            ),
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new=rate_limit_mock,
            ),
        ):
            from app.agents.tools.vfs_tools import vfs_write

            await vfs_write.ainvoke(
                {
                    "path": "files/draft.md",
                    "content": "draft",
                },
                config=mock_config,
            )

            mock_get_stream_writer.assert_not_called()


# ==================== vfs_cmd Tests ====================


class TestVfsCmd:
    """Tests for vfs_cmd tool."""

    @pytest.mark.asyncio
    async def test_cmd_pwd(self, mock_config):
        """pwd command returns working directory."""
        with (
            patch("app.agents.tools.vfs_tools.get_vfs_command_parser") as mock_parser,
            patch(
                "app.decorators.rate_limiting._get_cached_subscription",
                new=AsyncMock(return_value=SimpleNamespace(plan_type=PlanType.FREE)),
            ),
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new=AsyncMock(return_value={}),
            ),
        ):
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
            mock_instance.execute.assert_awaited_once()
            assert mock_instance.execute.call_args.kwargs["conversation_id"] == "conv1"

    @pytest.mark.asyncio
    async def test_cmd_blocked_command(self, mock_config):
        """Blocked commands return error."""
        with (
            patch("app.agents.tools.vfs_tools.get_vfs_command_parser") as mock_parser,
            patch(
                "app.decorators.rate_limiting._get_cached_subscription",
                new=AsyncMock(return_value=SimpleNamespace(plan_type=PlanType.FREE)),
            ),
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new=AsyncMock(return_value={}),
            ),
        ):
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
        empty_config = cast(RunnableConfig, {"metadata": {}})

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
        assert redirect is not None
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

    def test_user_visible_path_scoped_to_session(self):
        """.user-visible paths resolve under the current session."""
        from app.agents.tools.vfs_tools import _resolve_path

        result = _resolve_path(
            ".user-visible/final.md",
            "user123",
            "executor",
            "conv1",
        )
        assert (
            result
            == "/users/user123/global/executor/sessions/conv1/.user-visible/final.md"
        )

    def test_user_visible_without_session_falls_back_to_files(self):
        """Without a session, .user-visible writes stay private in files/."""
        from app.agents.tools.vfs_tools import _resolve_path

        result = _resolve_path(
            ".user-visible/final.md",
            "user123",
            "executor",
            None,
        )
        assert result == "/users/user123/global/executor/files/final.md"


# ==================== Tool Export Tests ====================


class TestToolExports:
    """Test that tools are properly exported."""

    def test_tools_list_contains_four_tools(self):
        """Tools list should contain exactly 3 tools."""
        from app.agents.tools.vfs_tools import tools

        assert len(tools) == 3

    def test_tool_names(self):
        """Tools should have correct names."""
        from app.agents.tools.vfs_tools import tools

        names = [t.name for t in tools]
        assert "vfs_read" in names
        assert "vfs_write" in names
        assert "vfs_cmd" in names
