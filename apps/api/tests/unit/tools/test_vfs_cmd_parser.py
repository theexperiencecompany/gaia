"""Unit tests for VFS Command Parser.

Tests parsing and execution of shell-like VFS commands including
ls, tree, find, grep, cat, pwd, stat, echo, mv.
"""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.vfs_cmd_parser import (
    CommandParseError,
    RedirectInfo,
    VFSCommandParser,
    _VFSArgumentParser,
    get_vfs_command_parser,
)
from app.models.vfs_models import (
    VFSListResponse,
    VFSNodeResponse,
    VFSNodeType,
    VFSSearchResult,
    VFSTreeNode,
)
from app.services.vfs import VFSAccessError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = "test_user_123"
AGENT_NAME = "executor"
CONVERSATION_ID = "conv_abc"
AGENT_ROOT = f"/users/{USER_ID}/global/executor"


def _node(
    name: str,
    node_type: VFSNodeType = VFSNodeType.FILE,
    size_bytes: int = 100,
    updated_at: datetime | None = None,
    path: str | None = None,
    content_type: str = "text/plain",
    metadata: dict[str, Any] | None = None,
) -> VFSNodeResponse:
    return VFSNodeResponse(
        path=path or f"{AGENT_ROOT}/{name}",
        name=name,
        node_type=node_type,
        size_bytes=size_bytes,
        content_type=content_type,
        created_at=updated_at or datetime(2025, 1, 1, tzinfo=timezone.utc),
        updated_at=updated_at or datetime(2025, 1, 1, tzinfo=timezone.utc),
        metadata=metadata or {},
    )


def _folder(name: str, **kwargs: Any) -> VFSNodeResponse:
    return _node(name, node_type=VFSNodeType.FOLDER, **kwargs)


def _list_response(
    items: list[VFSNodeResponse], path: str = AGENT_ROOT
) -> VFSListResponse:
    return VFSListResponse(path=path, items=items, total_count=len(items))


def _search_result(
    matches: list[VFSNodeResponse], pattern: str = "*"
) -> VFSSearchResult:
    return VFSSearchResult(
        matches=matches,
        total_count=len(matches),
        pattern=pattern,
        base_path=AGENT_ROOT,
    )


# ---------------------------------------------------------------------------
# _VFSArgumentParser
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVFSArgumentParser:
    def test_error_raises_command_parse_error(self) -> None:
        parser = _VFSArgumentParser(prog="test", add_help=False)
        with pytest.raises(CommandParseError, match="bad arg"):
            parser.error("bad arg")

    def test_exit_with_message_raises(self) -> None:
        parser = _VFSArgumentParser(prog="test", add_help=False)
        with pytest.raises(CommandParseError, match="something went wrong"):
            parser.exit(status=1, message="something went wrong")

    def test_exit_without_message_raises_generic(self) -> None:
        parser = _VFSArgumentParser(prog="test", add_help=False)
        with pytest.raises(CommandParseError, match="Invalid arguments"):
            parser.exit(status=0, message=None)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetVfsCommandParser:
    def test_returns_singleton(self) -> None:
        # Reset module-level singleton
        import app.agents.tools.vfs_cmd_parser as mod

        mod._parser = None
        p1 = get_vfs_command_parser()
        p2 = get_vfs_command_parser()
        assert p1 is p2
        mod._parser = None  # cleanup


# ---------------------------------------------------------------------------
# Command Parsing  (_parse_command)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseCommand:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()

    def test_empty_command(self) -> None:
        with pytest.raises(CommandParseError, match="Empty command"):
            self.parser._parse_command("")

    def test_command_too_long(self) -> None:
        long_cmd = "ls " + "a" * VFSCommandParser.MAX_COMMAND_LENGTH
        with pytest.raises(CommandParseError, match="Command too long"):
            self.parser._parse_command(long_cmd)

    def test_blocked_command_rm(self) -> None:
        with pytest.raises(CommandParseError, match="not supported"):
            self.parser._parse_command("rm -rf /")

    def test_blocked_command_mkdir(self) -> None:
        with pytest.raises(CommandParseError, match="not supported"):
            self.parser._parse_command("mkdir /foo")

    def test_blocked_command_sudo(self) -> None:
        with pytest.raises(CommandParseError, match="not supported"):
            self.parser._parse_command("sudo ls")

    def test_unknown_command(self) -> None:
        with pytest.raises(CommandParseError, match="Unknown command.*Supported"):
            self.parser._parse_command("wget http://example.com")

    def test_parse_ls_default(self) -> None:
        cmd, args, redirect = self.parser._parse_command("ls")
        assert cmd == "ls"
        assert args.path == "."
        assert not args.long
        assert not args.all
        assert not args.recursive

    def test_parse_ls_with_flags(self) -> None:
        cmd, args, redirect = self.parser._parse_command("ls -laR /some/path")
        assert cmd == "ls"
        assert args.path == "/some/path"
        assert args.long
        assert args.all
        assert args.recursive

    def test_parse_cat(self) -> None:
        cmd, args, redirect = self.parser._parse_command("cat notes/readme.txt")
        assert cmd == "cat"
        assert args.path == "notes/readme.txt"
        assert not args.number

    def test_parse_cat_with_number(self) -> None:
        cmd, args, redirect = self.parser._parse_command("cat -n myfile.py")
        assert cmd == "cat"
        assert args.number

    def test_parse_grep(self) -> None:
        cmd, args, redirect = self.parser._parse_command(
            "grep -ri 'hello world' notes/"
        )
        assert cmd == "grep"
        assert args.pattern == "hello world"
        assert args.path == "notes/"
        assert args.ignore_case
        assert args.recursive

    def test_parse_grep_count(self) -> None:
        cmd, args, redirect = self.parser._parse_command("grep -c error logs/")
        assert cmd == "grep"
        assert args.count
        assert args.pattern == "error"

    def test_parse_grep_files_with_matches(self) -> None:
        cmd, args, redirect = self.parser._parse_command("grep -l TODO .")
        assert cmd == "grep"
        assert args.files_with_matches

    def test_parse_find(self) -> None:
        cmd, args, redirect = self.parser._parse_command("find . -name '*.py' -type f")
        assert cmd == "find"
        assert args.name == "*.py"
        assert args.type == "f"

    def test_parse_find_iname(self) -> None:
        cmd, args, redirect = self.parser._parse_command("find / -iname '*.MD'")
        assert cmd == "find"
        assert args.iname == "*.MD"

    def test_parse_tree(self) -> None:
        cmd, args, redirect = self.parser._parse_command("tree -L 5 /some/dir")
        assert cmd == "tree"
        assert args.level == 5
        assert args.path == "/some/dir"

    def test_parse_tree_default_depth(self) -> None:
        cmd, args, redirect = self.parser._parse_command("tree")
        assert args.level == 3

    def test_parse_stat(self) -> None:
        cmd, args, redirect = self.parser._parse_command("stat notes/readme.txt")
        assert cmd == "stat"
        assert args.path == "notes/readme.txt"

    def test_parse_echo(self) -> None:
        cmd, args, redirect = self.parser._parse_command("echo hello world")
        assert cmd == "echo"
        assert args.text == ["hello", "world"]

    def test_parse_echo_empty(self) -> None:
        cmd, args, redirect = self.parser._parse_command("echo")
        assert cmd == "echo"
        assert args.text == []

    def test_parse_mv(self) -> None:
        cmd, args, redirect = self.parser._parse_command("mv old.txt new.txt")
        assert cmd == "mv"
        assert args.source == "old.txt"
        assert args.dest == "new.txt"

    def test_parse_pwd(self) -> None:
        cmd, args, redirect = self.parser._parse_command("pwd")
        assert cmd == "pwd"

    def test_redirect_extraction(self) -> None:
        cmd, args, redirect = self.parser._parse_command("echo hello > output.txt")
        assert cmd == "echo"
        assert redirect is not None
        assert redirect.mode == ">"
        assert redirect.filepath == "output.txt"

    def test_append_redirect(self) -> None:
        cmd, args, redirect = self.parser._parse_command("echo hello >> output.txt")
        assert redirect is not None
        assert redirect.mode == ">>"

    def test_no_redirect(self) -> None:
        cmd, args, redirect = self.parser._parse_command("ls -l")
        assert redirect is None

    def test_case_insensitive_command_name(self) -> None:
        cmd, args, redirect = self.parser._parse_command("LS -l")
        assert cmd == "ls"

    def test_quoted_strings(self) -> None:
        cmd, args, redirect = self.parser._parse_command(
            'grep "hello world" myfile.txt'
        )
        assert args.pattern == "hello world"

    def test_invalid_syntax_unmatched_quote(self) -> None:
        with pytest.raises(CommandParseError, match="Invalid command syntax"):
            self.parser._parse_command('grep "unmatched')


# ---------------------------------------------------------------------------
# Path Resolution (_resolve_path)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolvePath:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()

    def test_empty_path(self) -> None:
        result = self.parser._resolve_path("", USER_ID, AGENT_NAME)
        assert result == AGENT_ROOT

    def test_dot_path(self) -> None:
        result = self.parser._resolve_path(".", USER_ID, AGENT_NAME)
        assert result == AGENT_ROOT

    def test_system_path(self) -> None:
        result = self.parser._resolve_path("/system/skills", USER_ID, AGENT_NAME)
        assert result == "/system/skills"

    def test_valid_user_path(self) -> None:
        path = f"/users/{USER_ID}/global/executor/notes"
        result = self.parser._resolve_path(path, USER_ID, AGENT_NAME)
        assert result == path

    def test_invalid_user_path_falls_through(self) -> None:
        # Path belonging to another user should fall through to default handling
        path = "/users/other_user/global/executor/notes"
        result = self.parser._resolve_path(path, USER_ID, AGENT_NAME)
        # Falls through because validate_user_access fails, ends up as relative to agent root
        assert result.startswith(AGENT_ROOT)

    def test_user_visible_with_conversation_id(self) -> None:
        result = self.parser._resolve_path(
            ".user-visible/report.md", USER_ID, AGENT_NAME, CONVERSATION_ID
        )
        assert f"/sessions/{CONVERSATION_ID}/.user-visible/report.md" in result

    def test_user_visible_folder_only_with_conversation_id(self) -> None:
        result = self.parser._resolve_path(
            ".user-visible", USER_ID, AGENT_NAME, CONVERSATION_ID
        )
        assert f"/sessions/{CONVERSATION_ID}/.user-visible" in result

    def test_user_visible_without_conversation_id_fallback(self) -> None:
        result = self.parser._resolve_path(
            ".user-visible/report.md", USER_ID, AGENT_NAME, None
        )
        assert "/files/report.md" in result

    def test_user_visible_folder_without_conversation_id(self) -> None:
        result = self.parser._resolve_path(".user-visible", USER_ID, AGENT_NAME, None)
        assert result.endswith("/files")

    def test_absolute_path_relative_to_agent_root(self) -> None:
        result = self.parser._resolve_path("/notes/readme.txt", USER_ID, AGENT_NAME)
        assert result == f"{AGENT_ROOT}/notes/readme.txt"

    def test_parent_directory(self) -> None:
        result = self.parser._resolve_path("../some/path", USER_ID, AGENT_NAME)
        # normalize_path resolves .. so it goes up from agent_root
        assert "/users/" in result

    def test_known_folder_notes(self) -> None:
        result = self.parser._resolve_path("notes/readme.txt", USER_ID, AGENT_NAME)
        assert result == f"{AGENT_ROOT}/notes/readme.txt"

    def test_known_folder_files(self) -> None:
        result = self.parser._resolve_path("files/data.csv", USER_ID, AGENT_NAME)
        assert result == f"{AGENT_ROOT}/files/data.csv"

    def test_known_folder_sessions(self) -> None:
        result = self.parser._resolve_path("sessions/abc/foo", USER_ID, AGENT_NAME)
        assert result == f"{AGENT_ROOT}/sessions/abc/foo"

    def test_relative_arbitrary_path(self) -> None:
        result = self.parser._resolve_path("somefile.txt", USER_ID, AGENT_NAME)
        assert result == f"{AGENT_ROOT}/somefile.txt"

    def test_subagent_root(self) -> None:
        result = self.parser._resolve_path(".", USER_ID, "github_agent")
        assert result == f"/users/{USER_ID}/global/subagents/github_agent"


# ---------------------------------------------------------------------------
# Format Size
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatSize:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()

    def test_bytes(self) -> None:
        assert self.parser._format_size(500) == "500B"

    def test_kilobytes(self) -> None:
        assert self.parser._format_size(2048) == "2.0KB"

    def test_megabytes(self) -> None:
        assert self.parser._format_size(2 * 1024 * 1024) == "2.0MB"

    def test_gigabytes(self) -> None:
        assert self.parser._format_size(3 * 1024 * 1024 * 1024) == "3.0GB"

    def test_zero_bytes(self) -> None:
        assert self.parser._format_size(0) == "0B"


# ---------------------------------------------------------------------------
# Command Execution (execute + command handlers)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecute:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()
        self.mock_vfs = AsyncMock()
        self.parser._vfs = self.mock_vfs

    async def test_execute_invalid_command_returns_error(self) -> None:
        result = await self.parser.execute("invalidcmd", USER_ID)
        assert result.startswith("Error:")

    async def test_execute_blocked_command_returns_error(self) -> None:
        result = await self.parser.execute("rm file.txt", USER_ID)
        assert "Error:" in result

    async def test_execute_unimplemented_handler(self) -> None:
        # Patch _parsers to include a command with no handler
        with patch.object(
            self.parser, "_parse_command", return_value=("fakecmd", MagicMock(), None)
        ):
            result = await self.parser.execute("fakecmd", USER_ID)
            assert "not implemented" in result

    async def test_execute_handler_exception(self) -> None:
        # Make _cmd_pwd raise an exception
        with patch.object(self.parser, "_cmd_pwd", side_effect=RuntimeError("boom")):
            result = await self.parser.execute("pwd", USER_ID)
            assert "Error:" in result
            assert "boom" in result


# ---------------------------------------------------------------------------
# pwd
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCmdPwd:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()
        self.parser._vfs = AsyncMock()

    async def test_pwd(self) -> None:
        result = await self.parser.execute("pwd", USER_ID, agent_name=AGENT_NAME)
        assert result == AGENT_ROOT

    async def test_pwd_subagent(self) -> None:
        result = await self.parser.execute("pwd", USER_ID, agent_name="my_agent")
        assert result == f"/users/{USER_ID}/global/subagents/my_agent"


# ---------------------------------------------------------------------------
# ls
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCmdLs:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()
        self.mock_vfs = AsyncMock()
        self.parser._vfs = self.mock_vfs

    async def test_ls_empty_directory(self) -> None:
        self.mock_vfs.list_dir.return_value = _list_response([])
        result = await self.parser.execute("ls", USER_ID, agent_name=AGENT_NAME)
        assert result == "(empty directory)"

    async def test_ls_files(self) -> None:
        items = [_node("readme.txt"), _node("data.csv")]
        self.mock_vfs.list_dir.return_value = _list_response(items)
        result = await self.parser.execute("ls", USER_ID, agent_name=AGENT_NAME)
        assert "readme.txt" in result
        assert "data.csv" in result

    async def test_ls_hidden_files_filtered(self) -> None:
        items = [_node(".hidden"), _node("visible.txt")]
        self.mock_vfs.list_dir.return_value = _list_response(items)
        result = await self.parser.execute("ls", USER_ID, agent_name=AGENT_NAME)
        assert ".hidden" not in result
        assert "visible.txt" in result

    async def test_ls_all_shows_hidden(self) -> None:
        items = [_node(".hidden"), _node("visible.txt")]
        self.mock_vfs.list_dir.return_value = _list_response(items)
        result = await self.parser.execute("ls -a", USER_ID, agent_name=AGENT_NAME)
        assert ".hidden" in result
        assert "visible.txt" in result

    async def test_ls_long_format(self) -> None:
        ts = datetime(2025, 6, 15, 10, 30, tzinfo=timezone.utc)
        items = [
            _node("readme.txt", size_bytes=1024, updated_at=ts),
            _folder("subdir", size_bytes=0, updated_at=ts),
        ]
        self.mock_vfs.list_dir.return_value = _list_response(items)
        result = await self.parser.execute("ls -l", USER_ID, agent_name=AGENT_NAME)
        assert "total 2" in result
        assert "rw-r--r--" in result
        assert "rwxr-xr-x" in result
        assert "readme.txt" in result
        assert "subdir/" in result
        assert "2025-06-15 10:30" in result

    async def test_ls_folder_suffix(self) -> None:
        items = [_folder("mydir")]
        self.mock_vfs.list_dir.return_value = _list_response(items)
        result = await self.parser.execute("ls", USER_ID, agent_name=AGENT_NAME)
        assert "mydir/" in result

    async def test_ls_error(self) -> None:
        self.mock_vfs.list_dir.side_effect = Exception("permission denied")
        result = await self.parser.execute("ls /bad", USER_ID, agent_name=AGENT_NAME)
        assert "cannot access" in result

    async def test_ls_truncation(self) -> None:
        items = [_node(f"file_{i}.txt") for i in range(150)]
        self.mock_vfs.list_dir.return_value = VFSListResponse(
            path=AGENT_ROOT, items=items, total_count=150
        )
        result = await self.parser.execute("ls", USER_ID, agent_name=AGENT_NAME)
        assert "more items" in result

    async def test_ls_long_no_date(self) -> None:
        items = [_node("nodate.txt", updated_at=None)]
        # VFSNodeResponse has Optional[datetime], set to None
        items[0].updated_at = None
        self.mock_vfs.list_dir.return_value = _list_response(items)
        result = await self.parser.execute("ls -l", USER_ID, agent_name=AGENT_NAME)
        assert "nodate.txt" in result

    async def test_ls_recursive(self) -> None:
        # Root listing
        root_items = [_folder("subdir"), _node("file.txt")]
        root_response = _list_response(root_items)
        # Subdir listing
        sub_items = [_node("nested.txt")]
        sub_response = _list_response(sub_items)
        self.mock_vfs.list_dir.side_effect = [root_response, sub_response]

        result = await self.parser.execute("ls -R", USER_ID, agent_name=AGENT_NAME)
        assert "subdir" in result
        assert "file.txt" in result
        assert "nested.txt" in result

    async def test_ls_recursive_error_in_subdir(self) -> None:
        root_items = [_folder("bad_dir")]
        self.mock_vfs.list_dir.side_effect = [
            _list_response(root_items),
            Exception("access denied"),
        ]
        result = await self.parser.execute("ls -R", USER_ID, agent_name=AGENT_NAME)
        assert "cannot access" in result

    async def test_ls_recursive_empty_subdir(self) -> None:
        root_items = [_folder("empty_dir")]
        self.mock_vfs.list_dir.side_effect = [
            _list_response(root_items),
            _list_response([]),
        ]
        result = await self.parser.execute("ls -R", USER_ID, agent_name=AGENT_NAME)
        assert "empty directory" in result


# ---------------------------------------------------------------------------
# tree
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCmdTree:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()
        self.mock_vfs = AsyncMock()
        self.parser._vfs = self.mock_vfs

    async def test_tree_basic(self) -> None:
        tree = VFSTreeNode(
            name="executor",
            path=AGENT_ROOT,
            node_type=VFSNodeType.FOLDER,
            children=[
                VFSTreeNode(
                    name="notes",
                    path=f"{AGENT_ROOT}/notes",
                    node_type=VFSNodeType.FOLDER,
                    children=[
                        VFSTreeNode(
                            name="readme.txt",
                            path=f"{AGENT_ROOT}/notes/readme.txt",
                            node_type=VFSNodeType.FILE,
                        ),
                    ],
                ),
                VFSTreeNode(
                    name="data.csv",
                    path=f"{AGENT_ROOT}/data.csv",
                    node_type=VFSNodeType.FILE,
                ),
            ],
        )
        self.mock_vfs.tree.return_value = tree
        result = await self.parser.execute("tree", USER_ID, agent_name=AGENT_NAME)
        assert "executor/" in result
        assert "notes/" in result
        assert "readme.txt" in result
        assert "data.csv" in result

    async def test_tree_error(self) -> None:
        self.mock_vfs.tree.side_effect = Exception("not found")
        result = await self.parser.execute("tree /bad", USER_ID, agent_name=AGENT_NAME)
        assert "cannot access" in result

    async def test_tree_with_depth(self) -> None:
        tree = VFSTreeNode(
            name="root",
            path=AGENT_ROOT,
            node_type=VFSNodeType.FOLDER,
            children=[],
        )
        self.mock_vfs.tree.return_value = tree
        await self.parser.execute("tree -L 5", USER_ID, agent_name=AGENT_NAME)
        self.mock_vfs.tree.assert_called_once()
        call_kwargs = self.mock_vfs.tree.call_args
        assert call_kwargs.kwargs["depth"] == 5


# ---------------------------------------------------------------------------
# find
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCmdFind:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()
        self.mock_vfs = AsyncMock()
        self.parser._vfs = self.mock_vfs

    async def test_find_no_matches(self) -> None:
        self.mock_vfs.search.return_value = _search_result([])
        result = await self.parser.execute(
            "find . -name '*.py'", USER_ID, agent_name=AGENT_NAME
        )
        assert "no files matching" in result

    async def test_find_with_matches(self) -> None:
        matches = [
            _node("app.py", path=f"{AGENT_ROOT}/app.py"),
            _node("test.py", path=f"{AGENT_ROOT}/test.py"),
        ]
        self.mock_vfs.search.return_value = _search_result(matches, "*.py")
        result = await self.parser.execute(
            "find . -name '*.py'", USER_ID, agent_name=AGENT_NAME
        )
        assert "app.py" in result
        assert "test.py" in result

    async def test_find_type_filter_files(self) -> None:
        matches = [
            _node("app.py", path=f"{AGENT_ROOT}/app.py"),
            _folder("dir1", path=f"{AGENT_ROOT}/dir1"),
        ]
        self.mock_vfs.search.return_value = _search_result(matches)
        result = await self.parser.execute(
            "find . -name '*' -type f", USER_ID, agent_name=AGENT_NAME
        )
        assert "app.py" in result
        assert "dir1" not in result

    async def test_find_type_filter_dirs(self) -> None:
        matches = [
            _node("app.py", path=f"{AGENT_ROOT}/app.py"),
            _folder("dir1", path=f"{AGENT_ROOT}/dir1"),
        ]
        self.mock_vfs.search.return_value = _search_result(matches)
        result = await self.parser.execute(
            "find . -type d", USER_ID, agent_name=AGENT_NAME
        )
        assert "dir1" in result
        assert "app.py" not in result

    async def test_find_error(self) -> None:
        self.mock_vfs.search.side_effect = Exception("boom")
        result = await self.parser.execute(
            "find . -name '*'", USER_ID, agent_name=AGENT_NAME
        )
        assert "error" in result

    async def test_find_truncation(self) -> None:
        matches = [
            _node(f"f{i}.txt", path=f"{AGENT_ROOT}/f{i}.txt") for i in range(150)
        ]
        self.mock_vfs.search.return_value = _search_result(matches)
        result = await self.parser.execute(
            "find . -name '*'", USER_ID, agent_name=AGENT_NAME
        )
        assert "more matches" in result

    async def test_find_default_pattern(self) -> None:
        """find without -name or -iname defaults to *."""
        matches = [_node("a.txt", path=f"{AGENT_ROOT}/a.txt")]
        self.mock_vfs.search.return_value = _search_result(matches, "*")
        result = await self.parser.execute("find .", USER_ID, agent_name=AGENT_NAME)
        assert "a.txt" in result

    async def test_find_iname(self) -> None:
        matches = [_node("README.MD", path=f"{AGENT_ROOT}/README.MD")]
        self.mock_vfs.search.return_value = _search_result(matches, "*.MD")
        result = await self.parser.execute(
            "find . -iname '*.MD'", USER_ID, agent_name=AGENT_NAME
        )
        assert "README.MD" in result


# ---------------------------------------------------------------------------
# grep
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCmdGrep:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()
        self.mock_vfs = AsyncMock()
        self.parser._vfs = self.mock_vfs

    async def test_grep_no_such_file(self) -> None:
        self.mock_vfs.info.return_value = None
        result = await self.parser.execute(
            "grep pattern myfile.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "No such file or directory" in result

    async def test_grep_single_file(self) -> None:
        info = _node("myfile.txt")
        self.mock_vfs.info.return_value = info
        self.mock_vfs.read.return_value = "line1 hello\nline2\nline3 hello again"
        result = await self.parser.execute(
            "grep hello myfile.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "hello" in result
        assert ":1:" in result  # line number
        assert ":3:" in result

    async def test_grep_case_insensitive(self) -> None:
        info = _node("myfile.txt")
        self.mock_vfs.info.return_value = info
        self.mock_vfs.read.return_value = "Hello World\nhello lower"
        result = await self.parser.execute(
            "grep -i HELLO myfile.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "Hello World" in result
        assert "hello lower" in result

    async def test_grep_no_matches(self) -> None:
        info = _node("myfile.txt")
        self.mock_vfs.info.return_value = info
        self.mock_vfs.read.return_value = "no match here"
        result = await self.parser.execute(
            "grep NOTFOUND myfile.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "no matches" in result

    async def test_grep_count(self) -> None:
        info = _node("myfile.txt")
        self.mock_vfs.info.return_value = info
        self.mock_vfs.read.return_value = "match\nmatch\nnope"
        result = await self.parser.execute(
            "grep -c match myfile.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "2" in result
        assert "Total:" in result

    async def test_grep_files_with_matches(self) -> None:
        info = _folder("mydir")
        self.mock_vfs.info.return_value = info
        list_items = [_node("a.txt"), _node("b.txt")]
        self.mock_vfs.list_dir.return_value = _list_response(list_items)
        self.mock_vfs.read.side_effect = ["match here", "no match"]
        result = await self.parser.execute(
            "grep -l match mydir", USER_ID, agent_name=AGENT_NAME
        )
        assert "a.txt" in result

    async def test_grep_recursive_directory(self) -> None:
        info = _folder("mydir")
        self.mock_vfs.info.return_value = info
        search_matches = [
            _node("a.txt", path=f"{AGENT_ROOT}/mydir/a.txt"),
            _node("b.txt", path=f"{AGENT_ROOT}/mydir/b.txt"),
        ]
        self.mock_vfs.search.return_value = _search_result(search_matches)
        self.mock_vfs.read.side_effect = ["found it", "nothing here"]
        result = await self.parser.execute(
            "grep -r found mydir", USER_ID, agent_name=AGENT_NAME
        )
        assert "found" in result

    async def test_grep_directory_nonrecursive(self) -> None:
        info = _folder("mydir")
        self.mock_vfs.info.return_value = info
        list_items = [_node("a.txt"), _folder("subdir")]
        self.mock_vfs.list_dir.return_value = _list_response(list_items)
        self.mock_vfs.read.return_value = "matching line"
        result = await self.parser.execute(
            "grep matching mydir", USER_ID, agent_name=AGENT_NAME
        )
        assert "matching" in result

    async def test_grep_long_line_truncated(self) -> None:
        info = _node("big.txt")
        self.mock_vfs.info.return_value = info
        long_line = "match" + "x" * 500
        self.mock_vfs.read.return_value = long_line
        result = await self.parser.execute(
            "grep match big.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "..." in result

    async def test_grep_error_accessing_path(self) -> None:
        self.mock_vfs.info.side_effect = Exception("access error")
        result = await self.parser.execute(
            "grep pattern badpath", USER_ID, agent_name=AGENT_NAME
        )
        assert "error accessing" in result

    async def test_grep_read_returns_none(self) -> None:
        info = _node("empty.txt")
        self.mock_vfs.info.return_value = info
        self.mock_vfs.read.return_value = None
        result = await self.parser.execute(
            "grep something empty.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "no matches" in result

    async def test_grep_large_file_truncated(self) -> None:
        info = _node("huge.txt")
        self.mock_vfs.info.return_value = info
        # File larger than MAX_GREP_FILE_CHARS - the grep handler truncates it
        big_content = "match\n" * 100_000
        self.mock_vfs.read.return_value = big_content
        result = await self.parser.execute(
            "grep match huge.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "match" in result

    async def test_grep_too_many_files_truncated(self) -> None:
        info = _folder("bigdir")
        self.mock_vfs.info.return_value = info
        # More files than MAX_GREP_FILES
        many_files = [
            _node(f"f{i}.txt", path=f"{AGENT_ROOT}/bigdir/f{i}.txt") for i in range(60)
        ]
        self.mock_vfs.search.return_value = _search_result(many_files)
        self.mock_vfs.read.return_value = "matchline"
        result = await self.parser.execute(
            "grep -r matchline bigdir", USER_ID, agent_name=AGENT_NAME
        )
        assert "limit" in result

    async def test_grep_read_exception_skipped(self) -> None:
        """Files that raise on read should be silently skipped."""
        info = _node("broken.txt")
        self.mock_vfs.info.return_value = info
        self.mock_vfs.read.side_effect = RuntimeError("disk error")
        result = await self.parser.execute(
            "grep pattern broken.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "no matches" in result


# ---------------------------------------------------------------------------
# cat
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCmdCat:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()
        self.mock_vfs = AsyncMock()
        self.parser._vfs = self.mock_vfs

    async def test_cat_file(self) -> None:
        self.mock_vfs.read.return_value = "file content here"
        result = await self.parser.execute(
            "cat notes/readme.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert result == "file content here"

    async def test_cat_file_not_found(self) -> None:
        self.mock_vfs.read.return_value = None
        result = await self.parser.execute(
            "cat missing.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "No such file" in result

    async def test_cat_with_line_numbers(self) -> None:
        self.mock_vfs.read.return_value = "line1\nline2\nline3"
        result = await self.parser.execute(
            "cat -n myfile.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "1  line1" in result
        assert "2  line2" in result
        assert "3  line3" in result

    async def test_cat_error(self) -> None:
        self.mock_vfs.read.side_effect = Exception("io error")
        result = await self.parser.execute(
            "cat broken.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "io error" in result


# ---------------------------------------------------------------------------
# stat
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCmdStat:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()
        self.mock_vfs = AsyncMock()
        self.parser._vfs = self.mock_vfs

    async def test_stat_file(self) -> None:
        ts = datetime(2025, 3, 1, 12, 0, tzinfo=timezone.utc)
        info = _node(
            "readme.txt",
            size_bytes=2048,
            updated_at=ts,
            content_type="text/markdown",
            metadata={"agent_name": "executor"},
        )
        info.created_at = ts
        self.mock_vfs.info.return_value = info
        result = await self.parser.execute(
            "stat readme.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "File:" in result
        assert "2048 bytes" in result
        assert "file" in result
        assert "text/markdown" in result
        assert "2025-03-01" in result
        assert "agent_name" in result

    async def test_stat_not_found(self) -> None:
        self.mock_vfs.info.return_value = None
        result = await self.parser.execute(
            "stat missing.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "No such file or directory" in result

    async def test_stat_error(self) -> None:
        self.mock_vfs.info.side_effect = Exception("db error")
        result = await self.parser.execute(
            "stat broken.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "db error" in result

    async def test_stat_folder(self) -> None:
        info = _folder("mydir")
        info.content_type = ""
        info.metadata = {}
        info.created_at = None
        info.updated_at = None
        self.mock_vfs.info.return_value = info
        result = await self.parser.execute("stat mydir", USER_ID, agent_name=AGENT_NAME)
        assert "folder" in result
        # No Mime line when content_type is empty
        assert "Created:" not in result


# ---------------------------------------------------------------------------
# echo
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCmdEcho:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()
        self.mock_vfs = AsyncMock()
        self.parser._vfs = self.mock_vfs

    async def test_echo_text(self) -> None:
        result = await self.parser.execute(
            "echo hello world", USER_ID, agent_name=AGENT_NAME
        )
        assert result == "hello world"

    async def test_echo_empty(self) -> None:
        result = await self.parser.execute("echo", USER_ID, agent_name=AGENT_NAME)
        assert result == ""

    async def test_echo_redirect_write(self) -> None:
        self.mock_vfs.write.return_value = None
        result = await self.parser.execute(
            "echo hello > output.txt",
            USER_ID,
            agent_name=AGENT_NAME,
            written_by="executor",
        )
        assert "Wrote to" in result
        self.mock_vfs.write.assert_called_once()

    async def test_echo_redirect_append(self) -> None:
        self.mock_vfs.append.return_value = None
        result = await self.parser.execute(
            "echo more >> output.txt",
            USER_ID,
            agent_name=AGENT_NAME,
        )
        assert "Appended to" in result
        self.mock_vfs.append.assert_called_once()

    async def test_echo_redirect_write_error(self) -> None:
        self.mock_vfs.write.side_effect = Exception("disk full")
        result = await self.parser.execute(
            "echo data > output.txt",
            USER_ID,
            agent_name=AGENT_NAME,
            written_by="executor",
        )
        assert "Error writing" in result

    async def test_echo_redirect_write_missing_written_by(self) -> None:
        """write redirect requires written_by parameter."""
        result = await self.parser.execute(
            "echo data > output.txt",
            USER_ID,
            agent_name=AGENT_NAME,
            written_by=None,
        )
        assert "Error writing" in result


# ---------------------------------------------------------------------------
# mv
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCmdMv:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()
        self.mock_vfs = AsyncMock()
        self.parser._vfs = self.mock_vfs

    async def test_mv_success(self) -> None:
        self.mock_vfs.move.return_value = f"{AGENT_ROOT}/new.txt"
        result = await self.parser.execute(
            "mv old.txt new.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "Moved" in result

    async def test_mv_file_not_found(self) -> None:
        self.mock_vfs.move.side_effect = FileNotFoundError("not found")
        result = await self.parser.execute(
            "mv missing.txt dest.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "No such file or directory" in result

    async def test_mv_access_error(self) -> None:
        self.mock_vfs.move.side_effect = VFSAccessError("/bad", USER_ID)
        result = await self.parser.execute(
            "mv forbidden.txt dest.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "permission denied" in result

    async def test_mv_generic_error(self) -> None:
        self.mock_vfs.move.side_effect = Exception("unexpected")
        result = await self.parser.execute(
            "mv a.txt b.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "unexpected" in result

    async def test_mv_redirect_not_supported(self) -> None:
        result = await self.parser.execute(
            "mv a.txt b.txt > log.txt", USER_ID, agent_name=AGENT_NAME
        )
        assert "not supported" in result

    async def test_mv_user_visible_without_conversation(self) -> None:
        result = await self.parser.execute(
            "mv .user-visible/a.txt files/a.txt",
            USER_ID,
            agent_name=AGENT_NAME,
            conversation_id=None,
        )
        assert "requires an active conversation" in result

    async def test_mv_session_path_without_conversation(self) -> None:
        self.mock_vfs.move.return_value = f"{AGENT_ROOT}/sessions/abc/file.txt"
        result = await self.parser.execute(
            "mv sessions/abc/file.txt notes/file.txt",
            USER_ID,
            agent_name=AGENT_NAME,
            conversation_id=None,
        )
        assert "require an active conversation" in result

    async def test_mv_cross_session_blocked(self) -> None:
        """Moving from one session to another should be blocked."""
        result = await self.parser.execute(
            "mv sessions/other_conv/file.txt notes/file.txt",
            USER_ID,
            agent_name=AGENT_NAME,
            conversation_id=CONVERSATION_ID,
        )
        assert "cannot escape the current session" in result

    @patch("app.agents.tools.vfs_cmd_parser.is_user_visible_path", return_value=True)
    @patch.object(VFSCommandParser, "_emit_artifact_event", new_callable=AsyncMock)
    async def test_mv_to_user_visible_emits_artifact(
        self, mock_emit: AsyncMock, mock_is_visible: MagicMock
    ) -> None:
        self.mock_vfs.move.return_value = (
            f"{AGENT_ROOT}/sessions/{CONVERSATION_ID}/.user-visible/report.md"
        )
        result = await self.parser.execute(
            "mv notes/report.md .user-visible/report.md",
            USER_ID,
            agent_name=AGENT_NAME,
            conversation_id=CONVERSATION_ID,
        )
        assert "Moved" in result
        mock_emit.assert_called_once()


# ---------------------------------------------------------------------------
# _handle_redirect with provenance metadata
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleRedirect:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()
        self.mock_vfs = AsyncMock()
        self.parser._vfs = self.mock_vfs

    async def test_redirect_write_includes_metadata(self) -> None:
        self.mock_vfs.write.return_value = None
        redirect = RedirectInfo(mode=">", filepath="output.txt")
        result = await self.parser._handle_redirect(
            "content",
            redirect,
            USER_ID,
            AGENT_NAME,
            conversation_id=CONVERSATION_ID,
            written_by="executor",
            agent_thread_id="thread_123",
            vfs_session_id="session_456",
        )
        assert "Wrote to" in result
        call_kwargs = self.mock_vfs.write.call_args
        metadata = call_kwargs.kwargs["metadata"]
        assert metadata["conversation_id"] == CONVERSATION_ID
        assert metadata["agent_thread_id"] == "thread_123"
        assert metadata["vfs_session_id"] == "session_456"
        assert metadata["written_by"] == "executor"

    async def test_redirect_append(self) -> None:
        self.mock_vfs.append.return_value = None
        redirect = RedirectInfo(mode=">>", filepath="output.txt")
        result = await self.parser._handle_redirect(
            "extra content",
            redirect,
            USER_ID,
            AGENT_NAME,
        )
        assert "Appended to" in result


# ---------------------------------------------------------------------------
# _emit_artifact_event
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitArtifactEvent:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()
        self.mock_vfs = AsyncMock()
        self.parser._vfs = self.mock_vfs

    @patch("app.agents.tools.vfs_cmd_parser.is_user_visible_path", return_value=False)
    async def test_no_emit_for_non_visible_path(self, mock_check: MagicMock) -> None:
        # Should return early without calling anything
        await self.parser._emit_artifact_event("/some/path", USER_ID)

    @patch(
        "app.agents.tools.vfs_cmd_parser.get_stream_writer",
        side_effect=Exception("no writer"),
    )
    @patch("app.agents.tools.vfs_cmd_parser.is_user_visible_path", return_value=True)
    async def test_no_stream_writer_returns_silently(
        self, mock_check: MagicMock, mock_writer: MagicMock
    ) -> None:
        self.mock_vfs.info.return_value = _node("report.md", size_bytes=500)
        await self.parser._emit_artifact_event(
            f"{AGENT_ROOT}/sessions/{CONVERSATION_ID}/.user-visible/report.md",
            USER_ID,
        )

    @patch("app.agents.tools.vfs_cmd_parser.get_stream_writer")
    @patch("app.agents.tools.vfs_cmd_parser.is_user_visible_path", return_value=True)
    async def test_emit_calls_writer(
        self, mock_check: MagicMock, mock_get_writer: MagicMock
    ) -> None:
        mock_writer_fn = MagicMock()
        mock_get_writer.return_value = mock_writer_fn
        self.mock_vfs.info.return_value = _node("report.md", size_bytes=1024)

        await self.parser._emit_artifact_event(
            f"{AGENT_ROOT}/sessions/{CONVERSATION_ID}/.user-visible/report.md",
            USER_ID,
        )
        mock_writer_fn.assert_called_once()
        call_data = mock_writer_fn.call_args[0][0]
        assert "artifact_data" in call_data
        assert call_data["artifact_data"]["filename"] == "report.md"
        assert call_data["artifact_data"]["size_bytes"] == 1024


# ---------------------------------------------------------------------------
# Lazy VFS loading
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLazyVfs:
    @patch("app.agents.tools.vfs_cmd_parser.get_vfs", new_callable=AsyncMock)
    async def test_lazy_loads_vfs(self, mock_get_vfs: AsyncMock) -> None:
        mock_vfs = AsyncMock()
        mock_get_vfs.return_value = mock_vfs
        parser = VFSCommandParser()
        assert parser._vfs is None
        vfs = await parser._get_vfs()
        assert vfs is mock_vfs
        mock_get_vfs.assert_called_once()

    async def test_cached_vfs(self) -> None:
        parser = VFSCommandParser()
        mock_vfs = AsyncMock()
        parser._vfs = mock_vfs
        vfs = await parser._get_vfs()
        assert vfs is mock_vfs


# ---------------------------------------------------------------------------
# _extract_redirect
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractRedirect:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()

    def test_no_redirect(self) -> None:
        cmd, redirect = self.parser._extract_redirect("ls -l")
        assert cmd == "ls -l"
        assert redirect is None

    def test_write_redirect(self) -> None:
        cmd, redirect = self.parser._extract_redirect("echo hello > file.txt")
        assert redirect is not None
        assert redirect.mode == ">"
        assert redirect.filepath == "file.txt"

    def test_append_redirect(self) -> None:
        cmd, redirect = self.parser._extract_redirect("echo hello >> file.txt")
        assert redirect is not None
        assert redirect.mode == ">>"


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTokenize:
    def setup_method(self) -> None:
        self.parser = VFSCommandParser()

    def test_simple_tokenize(self) -> None:
        tokens = self.parser._tokenize("ls -l /path")
        assert tokens == ["ls", "-l", "/path"]

    def test_quoted_tokenize(self) -> None:
        tokens = self.parser._tokenize('echo "hello world"')
        assert tokens == ["echo", "hello world"]

    def test_invalid_syntax(self) -> None:
        with pytest.raises(CommandParseError, match="Invalid command syntax"):
            self.parser._tokenize('echo "unmatched')
