"""
Comprehensive tests for VFSCommandParser - argparse-based VFS command parser.

Tests cover:
  - Parsing: tokenization, flags, arguments, quotes, redirects
  - Edge cases: empty commands, special chars, unicode
  - Error handling: blocked commands, unknown commands, invalid syntax
  - Command-specific: ls, tree, find, grep, cat, pwd, stat, echo
  - Integration: mocked VFS execution
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agents.tools.vfs_cmd_parser import (
    VFSCommandParser,
    CommandParseError,
    RedirectInfo,
    get_vfs_command_parser,
)


# ==================== Fixtures ====================


@pytest.fixture
def parser():
    """Create a fresh parser instance."""
    return VFSCommandParser()


@pytest.fixture
def mock_vfs():
    """Create a mock VFS with common methods."""
    mock = AsyncMock()
    mock.read = AsyncMock(return_value="file content")
    mock.write = AsyncMock(return_value="/path/to/file")
    mock.append = AsyncMock(return_value="/path/to/file")
    mock.list_dir = AsyncMock()
    mock.tree = AsyncMock()
    mock.search = AsyncMock()
    mock.info = AsyncMock()
    return mock


# ==================== Basic Parsing Tests ====================


class TestBasicParsing:
    """Test basic command parsing functionality."""

    def test_parse_simple_command(self, parser):
        """Parse a simple command with no flags."""
        cmd, args, redirect = parser._parse_command("pwd")
        assert cmd == "pwd"
        assert redirect is None

    def test_parse_command_with_path(self, parser):
        """Parse command with a path argument."""
        cmd, args, redirect = parser._parse_command("ls notes/")
        assert cmd == "ls"
        assert args.path == "notes/"

    def test_parse_command_lowercase(self, parser):
        """Commands are normalized to lowercase."""
        cmd, args, redirect = parser._parse_command("LS")
        assert cmd == "ls"

    def test_parse_command_mixed_case(self, parser):
        """Mixed case commands are normalized."""
        cmd, args, redirect = parser._parse_command("Cat file.txt")
        assert cmd == "cat"

    def test_parse_with_leading_whitespace(self, parser):
        """Leading whitespace is ignored."""
        cmd, args, redirect = parser._parse_command("   pwd")
        assert cmd == "pwd"

    def test_parse_with_trailing_whitespace(self, parser):
        """Trailing whitespace is ignored."""
        cmd, args, redirect = parser._parse_command("pwd   ")
        assert cmd == "pwd"


# ==================== Flag Parsing Tests ====================


class TestFlagParsing:
    """Test parsing of command flags."""

    def test_ls_long_flag(self, parser):
        """Parse -l flag for ls."""
        cmd, args, redirect = parser._parse_command("ls -l")
        assert cmd == "ls"
        assert args.long is True
        assert args.all is False

    def test_ls_all_flag(self, parser):
        """Parse -a flag for ls."""
        cmd, args, redirect = parser._parse_command("ls -a")
        assert args.all is True
        assert args.long is False

    def test_ls_combined_flags(self, parser):
        """Parse combined -la flags."""
        cmd, args, redirect = parser._parse_command("ls -la")
        assert args.long is True
        assert args.all is True

    def test_ls_separate_flags(self, parser):
        """Parse separate -l -a flags."""
        cmd, args, redirect = parser._parse_command("ls -l -a")
        assert args.long is True
        assert args.all is True

    def test_ls_long_flag_name(self, parser):
        """Parse --long flag for ls."""
        cmd, args, redirect = parser._parse_command("ls --long")
        assert args.long is True

    def test_ls_all_flag_name(self, parser):
        """Parse --all flag for ls."""
        cmd, args, redirect = parser._parse_command("ls --all")
        assert args.all is True

    def test_ls_flags_with_path(self, parser):
        """Parse flags followed by path."""
        cmd, args, redirect = parser._parse_command("ls -la notes/")
        assert args.long is True
        assert args.all is True
        assert args.path == "notes/"

    def test_tree_level_flag(self, parser):
        """Parse -L flag for tree."""
        cmd, args, redirect = parser._parse_command("tree -L 2")
        assert args.level == 2

    def test_tree_default_level(self, parser):
        """Tree defaults to level 3."""
        cmd, args, redirect = parser._parse_command("tree")
        assert args.level == 3

    def test_tree_level_with_path(self, parser):
        """Parse tree with path and level."""
        cmd, args, redirect = parser._parse_command("tree sessions/ -L 2")
        assert args.path == "sessions/"
        assert args.level == 2

    def test_grep_ignore_case(self, parser):
        """Parse -i flag for grep."""
        cmd, args, redirect = parser._parse_command("grep -i pattern file.txt")
        assert args.ignore_case is True

    def test_grep_recursive(self, parser):
        """Parse -r flag for grep."""
        cmd, args, redirect = parser._parse_command("grep -r pattern .")
        assert args.recursive is True

    def test_grep_count(self, parser):
        """Parse -c flag for grep."""
        cmd, args, redirect = parser._parse_command("grep -c pattern file.txt")
        assert args.count is True

    def test_grep_files_with_matches(self, parser):
        """Parse -l flag for grep."""
        cmd, args, redirect = parser._parse_command("grep -l pattern .")
        assert args.files_with_matches is True

    def test_grep_multiple_flags(self, parser):
        """Parse multiple grep flags."""
        cmd, args, redirect = parser._parse_command("grep -i -r -n pattern .")
        assert args.ignore_case is True
        assert args.recursive is True
        assert args.line_number is True

    def test_cat_number_lines(self, parser):
        """Parse -n flag for cat."""
        cmd, args, redirect = parser._parse_command("cat -n file.txt")
        assert args.number is True

    def test_find_name_pattern(self, parser):
        """Parse -name for find."""
        cmd, args, redirect = parser._parse_command('find . -name "*.json"')
        assert args.name == "*.json"
        assert args.iname is None

    def test_find_iname_pattern(self, parser):
        """Parse -iname for find."""
        cmd, args, redirect = parser._parse_command('find . -iname "*.JSON"')
        assert args.iname == "*.JSON"
        assert args.name is None

    def test_find_type_file(self, parser):
        """Parse -type f for find."""
        cmd, args, redirect = parser._parse_command("find . -type f")
        assert args.type == "f"

    def test_find_type_directory(self, parser):
        """Parse -type d for find."""
        cmd, args, redirect = parser._parse_command("find . -type d")
        assert args.type == "d"


# ==================== Quoted String Tests ====================


class TestQuotedStrings:
    """Test handling of quoted strings."""

    def test_double_quoted_pattern(self, parser):
        """Parse double-quoted pattern."""
        cmd, args, redirect = parser._parse_command('grep "hello world" file.txt')
        assert args.pattern == "hello world"

    def test_single_quoted_pattern(self, parser):
        """Parse single-quoted pattern."""
        cmd, args, redirect = parser._parse_command("grep 'hello world' file.txt")
        assert args.pattern == "hello world"

    def test_double_quoted_path(self, parser):
        """Parse double-quoted path."""
        cmd, args, redirect = parser._parse_command('cat "notes/my file.txt"')
        assert args.path == "notes/my file.txt"

    def test_single_quoted_path(self, parser):
        """Parse single-quoted path."""
        cmd, args, redirect = parser._parse_command("cat 'notes/my file.txt'")
        assert args.path == "notes/my file.txt"

    def test_echo_double_quoted(self, parser):
        """Parse echo with double-quoted text."""
        cmd, args, redirect = parser._parse_command('echo "hello world"')
        # shlex.split keeps quoted string together
        assert args.text == ["hello world"]

    def test_echo_preserves_quoted_text(self, parser):
        """Echo args should include all words."""
        cmd, args, redirect = parser._parse_command('echo "hello world" more text')
        # shlex.split('echo "hello world" more text') -> ['echo', 'hello world', 'more', 'text']
        assert "hello world" in args.text
        assert "more" in args.text
        assert "text" in args.text

    def test_quoted_glob_pattern(self, parser):
        """Glob patterns in quotes are preserved."""
        cmd, args, redirect = parser._parse_command('find . -name "*.txt"')
        assert args.name == "*.txt"

    def test_malformed_quotes_handled(self, parser):
        """Malformed quotes may be handled by shlex differently."""
        # shlex handles some malformed quotes, so we just verify it doesn't crash
        # or that it raises CommandParseError for truly invalid ones
        try:
            cmd, args, redirect = parser._parse_command('echo "hello')
            # If it doesn't raise, that's unexpected for unclosed quote
            assert False, "Expected CommandParseError for unclosed quote"
        except CommandParseError:
            pass  # Expected


# ==================== Redirect Parsing Tests ====================


class TestRedirectParsing:
    """Test parsing of redirect operators."""

    def test_redirect_write(self, parser):
        """Parse > redirect operator."""
        cmd, args, redirect = parser._parse_command("echo hello > file.txt")
        assert redirect is not None
        assert redirect.mode == ">"
        assert redirect.filepath == "file.txt"

    def test_redirect_append(self, parser):
        """Parse >> redirect operator."""
        cmd, args, redirect = parser._parse_command("echo hello >> file.txt")
        assert redirect is not None
        assert redirect.mode == ">>"
        assert redirect.filepath == "file.txt"

    def test_redirect_no_space(self, parser):
        """Redirect with no space before filename."""
        cmd, args, redirect = parser._parse_command("echo hello >file.txt")
        assert redirect.filepath == "file.txt"

    def test_redirect_quoted_path(self, parser):
        """Redirect to quoted filepath."""
        cmd, args, redirect = parser._parse_command('echo hello > "my file.txt"')
        assert redirect.filepath == "my file.txt"

    def test_redirect_single_quoted_path(self, parser):
        """Redirect to single-quoted filepath."""
        cmd, args, redirect = parser._parse_command("echo hello > 'my file.txt'")
        assert redirect.filepath == "my file.txt"

    def test_pwd_with_redirect(self, parser):
        """pwd can redirect output."""
        cmd, args, redirect = parser._parse_command("pwd > current_dir.txt")
        assert cmd == "pwd"
        assert redirect.mode == ">"
        assert redirect.filepath == "current_dir.txt"

    def test_ls_with_redirect(self, parser):
        """ls can redirect output."""
        cmd, args, redirect = parser._parse_command("ls -la > listing.txt")
        assert cmd == "ls"
        assert args.long is True
        assert redirect.filepath == "listing.txt"

    def test_no_redirect(self, parser):
        """Commands without redirect return None."""
        cmd, args, redirect = parser._parse_command("ls -la")
        assert redirect is None

    def test_grep_result_redirect(self, parser):
        """grep output can be redirected."""
        cmd, args, redirect = parser._parse_command(
            "grep pattern file.txt > results.txt"
        )
        assert cmd == "grep"
        assert redirect.filepath == "results.txt"


# ==================== Error Handling Tests ====================


class TestErrorHandling:
    """Test error handling for invalid commands."""

    def test_empty_command(self, parser):
        """Empty command raises error."""
        with pytest.raises(CommandParseError, match="Empty command"):
            parser._parse_command("")

    def test_whitespace_only_command(self, parser):
        """Whitespace-only command raises error."""
        with pytest.raises(CommandParseError, match="Empty command"):
            parser._parse_command("   ")

    def test_blocked_command_rm(self, parser):
        """rm command is blocked."""
        with pytest.raises(CommandParseError, match="not supported"):
            parser._parse_command("rm file.txt")

    def test_blocked_command_mv(self, parser):
        """mv command is blocked."""
        with pytest.raises(CommandParseError, match="not supported"):
            parser._parse_command("mv old.txt new.txt")

    def test_blocked_command_cp(self, parser):
        """cp command is blocked."""
        with pytest.raises(CommandParseError, match="not supported"):
            parser._parse_command("cp file.txt backup.txt")

    def test_blocked_command_mkdir(self, parser):
        """mkdir command is blocked."""
        with pytest.raises(CommandParseError, match="not supported"):
            parser._parse_command("mkdir newdir")

    def test_blocked_command_rmdir(self, parser):
        """rmdir command is blocked."""
        with pytest.raises(CommandParseError, match="not supported"):
            parser._parse_command("rmdir olddir")

    def test_blocked_command_chmod(self, parser):
        """chmod command is blocked."""
        with pytest.raises(CommandParseError, match="not supported"):
            parser._parse_command("chmod 755 file.txt")

    def test_blocked_command_chown(self, parser):
        """chown command is blocked."""
        with pytest.raises(CommandParseError, match="not supported"):
            parser._parse_command("chown user file.txt")

    def test_blocked_command_sudo(self, parser):
        """sudo command is blocked."""
        with pytest.raises(CommandParseError, match="not supported"):
            parser._parse_command("sudo ls")

    def test_unknown_command(self, parser):
        """Unknown command raises error with helpful message."""
        with pytest.raises(CommandParseError, match="Unknown command"):
            parser._parse_command("unknown_cmd arg1")

    def test_unknown_command_shows_supported(self, parser):
        """Unknown command error shows supported commands."""
        with pytest.raises(CommandParseError, match="Supported:"):
            parser._parse_command("badcmd arg1")

    def test_unclosed_quote(self, parser):
        """Unclosed quote raises error."""
        with pytest.raises(CommandParseError, match="Invalid command syntax"):
            parser._parse_command('echo "hello')

    def test_cat_missing_path(self, parser):
        """cat without path raises error."""
        with pytest.raises(CommandParseError):
            parser._parse_command("cat")

    def test_stat_missing_path(self, parser):
        """stat without path raises error."""
        with pytest.raises(CommandParseError):
            parser._parse_command("stat")

    def test_grep_missing_pattern(self, parser):
        """grep without pattern raises error."""
        with pytest.raises(CommandParseError):
            parser._parse_command("grep")


# ==================== Command-Specific Defaults Tests ====================


class TestCommandDefaults:
    """Test default values for command arguments."""

    def test_ls_default_path(self, parser):
        """ls defaults to current directory."""
        cmd, args, redirect = parser._parse_command("ls")
        assert args.path == "."

    def test_tree_default_path(self, parser):
        """tree defaults to current directory."""
        cmd, args, redirect = parser._parse_command("tree")
        assert args.path == "."

    def test_find_default_path(self, parser):
        """find defaults to current directory."""
        cmd, args, redirect = parser._parse_command("find -name '*.txt'")
        assert args.path == "."

    def test_grep_default_path(self, parser):
        """grep defaults to current directory."""
        cmd, args, redirect = parser._parse_command("grep pattern")
        assert args.path == "."

    def test_ls_default_no_long(self, parser):
        """ls defaults to short format."""
        cmd, args, redirect = parser._parse_command("ls")
        assert args.long is False

    def test_ls_default_no_hidden(self, parser):
        """ls defaults to hiding hidden files."""
        cmd, args, redirect = parser._parse_command("ls")
        assert args.all is False

    def test_grep_default_line_numbers(self, parser):
        """grep defaults to showing line numbers."""
        cmd, args, redirect = parser._parse_command("grep pattern file.txt")
        assert args.line_number is True


# ==================== Edge Cases Tests ====================


class TestEdgeCases:
    """Test edge cases and unusual inputs."""

    def test_path_with_dots(self, parser):
        """Path with dots is valid."""
        cmd, args, redirect = parser._parse_command("ls ../parent/")
        assert args.path == "../parent/"

    def test_path_with_multiple_slashes(self, parser):
        """Path with multiple slashes is preserved."""
        cmd, args, redirect = parser._parse_command("cat notes//file.txt")
        assert args.path == "notes//file.txt"

    def test_very_long_pattern(self, parser):
        """Long patterns are handled."""
        long_pattern = "a" * 100
        cmd, args, redirect = parser._parse_command(f'grep "{long_pattern}" file.txt')
        assert args.pattern == long_pattern

    def test_special_chars_in_pattern(self, parser):
        """Special regex chars in pattern."""
        cmd, args, redirect = parser._parse_command(r'grep "test\s+\w+" file.txt')
        assert args.pattern == r"test\s+\w+"

    def test_dollar_sign_in_pattern(self, parser):
        """Dollar sign in pattern."""
        cmd, args, redirect = parser._parse_command('grep "$100" file.txt')
        assert args.pattern == "$100"

    def test_asterisk_in_pattern(self, parser):
        """Asterisk in pattern."""
        cmd, args, redirect = parser._parse_command('find . -name "*.json"')
        assert args.name == "*.json"

    def test_question_mark_in_pattern(self, parser):
        """Question mark in pattern."""
        cmd, args, redirect = parser._parse_command('find . -name "file?.txt"')
        assert args.name == "file?.txt"

    def test_unicode_in_path(self, parser):
        """Unicode characters in path."""
        cmd, args, redirect = parser._parse_command("cat notes/cafe.txt")
        assert "cafe" in args.path

    def test_unicode_in_pattern(self, parser):
        """Unicode characters in pattern."""
        cmd, args, redirect = parser._parse_command('grep "cafe" file.txt')
        assert "cafe" in args.pattern

    def test_hyphen_in_filename(self, parser):
        """Hyphen in filename is valid."""
        cmd, args, redirect = parser._parse_command("cat my-file.txt")
        assert args.path == "my-file.txt"

    def test_underscore_in_filename(self, parser):
        """Underscore in filename is valid."""
        cmd, args, redirect = parser._parse_command("cat my_file.txt")
        assert args.path == "my_file.txt"


# ==================== Singleton Tests ====================


class TestSingleton:
    """Test singleton pattern for parser."""

    def test_get_parser_returns_instance(self):
        """get_vfs_command_parser returns a parser."""
        parser = get_vfs_command_parser()
        assert isinstance(parser, VFSCommandParser)

    def test_get_parser_returns_same_instance(self):
        """get_vfs_command_parser returns same instance."""
        parser1 = get_vfs_command_parser()
        parser2 = get_vfs_command_parser()
        assert parser1 is parser2


# ==================== RedirectInfo Tests ====================


class TestRedirectInfo:
    """Test RedirectInfo dataclass."""

    def test_redirect_info_write_mode(self):
        """RedirectInfo for write mode."""
        info = RedirectInfo(mode=">", filepath="output.txt")
        assert info.mode == ">"
        assert info.filepath == "output.txt"

    def test_redirect_info_append_mode(self):
        """RedirectInfo for append mode."""
        info = RedirectInfo(mode=">>", filepath="log.txt")
        assert info.mode == ">>"
        assert info.filepath == "log.txt"


# ==================== Extract Redirect Tests ====================


class TestExtractRedirect:
    """Test redirect extraction method."""

    def test_extract_write_redirect(self, parser):
        """Extract > redirect."""
        cmd, redirect = parser._extract_redirect("echo hello > file.txt")
        assert cmd == "echo hello"
        assert redirect.mode == ">"
        assert redirect.filepath == "file.txt"

    def test_extract_append_redirect(self, parser):
        """Extract >> redirect."""
        cmd, redirect = parser._extract_redirect("pwd >> log.txt")
        assert cmd == "pwd"
        assert redirect.mode == ">>"
        assert redirect.filepath == "log.txt"

    def test_extract_no_redirect(self, parser):
        """No redirect returns None."""
        cmd, redirect = parser._extract_redirect("ls -la")
        assert cmd == "ls -la"
        assert redirect is None

    def test_extract_redirect_quoted_path(self, parser):
        """Extract redirect with quoted path."""
        cmd, redirect = parser._extract_redirect('echo hello > "my file.txt"')
        assert redirect.filepath == "my file.txt"


# ==================== Tokenize Tests ====================


class TestTokenize:
    """Test tokenization method."""

    def test_tokenize_simple(self, parser):
        """Tokenize simple command."""
        tokens = parser._tokenize("ls -la")
        assert tokens == ["ls", "-la"]

    def test_tokenize_quoted(self, parser):
        """Tokenize with quoted string."""
        tokens = parser._tokenize('echo "hello world"')
        assert tokens == ["echo", "hello world"]

    def test_tokenize_single_quoted(self, parser):
        """Tokenize with single-quoted string."""
        tokens = parser._tokenize("grep 'hello world' file.txt")
        assert tokens == ["grep", "hello world", "file.txt"]

    def test_tokenize_mixed_quotes(self, parser):
        """Tokenize with mixed quote styles."""
        tokens = parser._tokenize("echo 'hello' \"world\"")
        assert tokens == ["echo", "hello", "world"]

    def test_tokenize_unclosed_quote_error(self, parser):
        """Tokenize unclosed quote raises error."""
        with pytest.raises(CommandParseError, match="Invalid command syntax"):
            parser._tokenize('echo "hello')


# ==================== Format Size Tests ====================


class TestFormatSize:
    """Test size formatting helper."""

    def test_format_bytes(self, parser):
        """Format bytes."""
        assert parser._format_size(100) == "100B"

    def test_format_kilobytes(self, parser):
        """Format kilobytes."""
        assert parser._format_size(1536) == "1.5KB"

    def test_format_megabytes(self, parser):
        """Format megabytes."""
        assert parser._format_size(1572864) == "1.5MB"

    def test_format_gigabytes(self, parser):
        """Format gigabytes."""
        assert parser._format_size(1610612736) == "1.5GB"

    def test_format_zero(self, parser):
        """Format zero bytes."""
        assert parser._format_size(0) == "0B"


# ==================== Path Resolution Tests ====================


class TestPathResolution:
    """Test path resolution method."""

    def test_resolve_empty_path(self, parser):
        """Empty path resolves to agent root."""
        result = parser._resolve_path("", "user123", "executor")
        assert "/users/user123/global/executor" in result

    def test_resolve_dot_path(self, parser):
        """Dot path resolves to agent root."""
        result = parser._resolve_path(".", "user123", "executor")
        assert "/users/user123/global/executor" in result

    def test_resolve_relative_notes(self, parser):
        """Relative notes path."""
        result = parser._resolve_path("notes/file.txt", "user123", "executor")
        assert "/users/user123/global/executor/notes/file.txt" in result

    def test_resolve_relative_files(self, parser):
        """Relative files path."""
        result = parser._resolve_path("files/data.json", "user123", "executor")
        assert "/users/user123/global/executor/files/data.json" in result

    def test_resolve_absolute_valid(self, parser):
        """Valid absolute path is preserved."""
        result = parser._resolve_path(
            "/users/user123/global/executor/notes/test.txt", "user123", "executor"
        )
        assert result == "/users/user123/global/executor/notes/test.txt"


# ==================== Command Execution Tests ====================


class TestCommandExecution:
    """Test command execution with mocked VFS."""

    @pytest.mark.asyncio
    async def test_execute_pwd(self, parser):
        """Execute pwd command."""
        result = await parser.execute("pwd", "user123", "executor")
        assert "/users/user123/global/executor" in result

    @pytest.mark.asyncio
    async def test_execute_blocked_command(self, parser):
        """Execute blocked command returns error."""
        result = await parser.execute("rm file.txt", "user123", "executor")
        assert "Error" in result
        assert "not supported" in result

    @pytest.mark.asyncio
    async def test_execute_unknown_command(self, parser):
        """Execute unknown command returns error."""
        result = await parser.execute("badcmd arg", "user123", "executor")
        assert "Error" in result
        assert "Unknown command" in result

    @pytest.mark.asyncio
    async def test_execute_empty_command(self, parser):
        """Execute empty command returns error."""
        result = await parser.execute("", "user123", "executor")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_execute_ls_with_mock(self, parser, mock_vfs):
        """Execute ls with mocked VFS."""
        # Setup mock response
        mock_item = MagicMock()
        mock_item.name = "test.txt"
        mock_item.node_type = MagicMock()
        mock_item.node_type.value = "file"
        mock_item.size_bytes = 100
        mock_item.updated_at = None

        mock_result = MagicMock()
        mock_result.items = [mock_item]
        mock_result.total_count = 1

        mock_vfs.list_dir.return_value = mock_result
        parser._vfs = mock_vfs

        result = await parser.execute("ls", "user123", "executor")
        assert "test.txt" in result

    @pytest.mark.asyncio
    async def test_execute_cat_with_mock(self, parser, mock_vfs):
        """Execute cat with mocked VFS."""
        mock_vfs.read.return_value = "file contents here"
        parser._vfs = mock_vfs

        result = await parser.execute("cat notes/file.txt", "user123", "executor")
        assert "file contents here" in result

    @pytest.mark.asyncio
    async def test_execute_cat_with_line_numbers(self, parser, mock_vfs):
        """Execute cat -n with mocked VFS."""
        mock_vfs.read.return_value = "line1\nline2\nline3"
        parser._vfs = mock_vfs

        result = await parser.execute("cat -n notes/file.txt", "user123", "executor")
        assert "1" in result
        assert "line1" in result
        assert "line2" in result

    @pytest.mark.asyncio
    async def test_execute_echo_with_redirect(self, parser, mock_vfs):
        """Execute echo with redirect."""
        mock_vfs.write.return_value = "/path/to/file.txt"
        parser._vfs = mock_vfs

        result = await parser.execute(
            'echo "hello world" > notes/file.txt', "user123", "executor"
        )
        assert "Wrote" in result

    @pytest.mark.asyncio
    async def test_execute_echo_with_append(self, parser, mock_vfs):
        """Execute echo with append redirect."""
        mock_vfs.append.return_value = "/path/to/file.txt"
        parser._vfs = mock_vfs

        result = await parser.execute(
            'echo "new line" >> notes/log.txt', "user123", "executor"
        )
        assert "Appended" in result

    @pytest.mark.asyncio
    async def test_execute_stat_with_mock(self, parser, mock_vfs):
        """Execute stat with mocked VFS."""
        from datetime import datetime

        mock_info = MagicMock()
        mock_info.path = "/users/user123/global/executor/notes/file.txt"
        mock_info.size_bytes = 1234
        mock_info.node_type = MagicMock()
        mock_info.node_type.value = "file"
        mock_info.content_type = "text/plain"
        mock_info.created_at = datetime.now()
        mock_info.updated_at = datetime.now()
        mock_info.metadata = {}

        mock_vfs.info.return_value = mock_info
        parser._vfs = mock_vfs

        result = await parser.execute("stat notes/file.txt", "user123", "executor")
        assert "1234 bytes" in result
        assert "file" in result

    @pytest.mark.asyncio
    async def test_execute_stat_not_found(self, parser, mock_vfs):
        """Execute stat on non-existent file."""
        mock_vfs.info.return_value = None
        parser._vfs = mock_vfs

        result = await parser.execute("stat missing.txt", "user123", "executor")
        assert "No such file" in result

    @pytest.mark.asyncio
    async def test_execute_ls_empty_dir(self, parser, mock_vfs):
        """Execute ls on empty directory."""
        mock_result = MagicMock()
        mock_result.items = []

        mock_vfs.list_dir.return_value = mock_result
        parser._vfs = mock_vfs

        result = await parser.execute("ls", "user123", "executor")
        assert "empty" in result.lower()


# ==================== Grep Execution Tests ====================


class TestGrepExecution:
    """Test grep command execution."""

    @pytest.mark.asyncio
    async def test_grep_file_content(self, parser, mock_vfs):
        """Grep searches file content."""
        mock_info = MagicMock()
        mock_info.node_type = MagicMock()
        mock_info.node_type.value = "file"

        mock_vfs.info.return_value = mock_info
        mock_vfs.read.return_value = "line 1\npattern here\nline 3"
        parser._vfs = mock_vfs

        result = await parser.execute(
            "grep pattern notes/file.txt", "user123", "executor"
        )
        assert "pattern here" in result

    @pytest.mark.asyncio
    async def test_grep_no_matches(self, parser, mock_vfs):
        """Grep with no matches."""
        mock_info = MagicMock()
        mock_info.node_type = MagicMock()
        mock_info.node_type.value = "file"

        mock_vfs.info.return_value = mock_info
        mock_vfs.read.return_value = "line 1\nline 2\nline 3"
        parser._vfs = mock_vfs

        result = await parser.execute(
            "grep notfound notes/file.txt", "user123", "executor"
        )
        assert "no matches" in result.lower()

    @pytest.mark.asyncio
    async def test_grep_invalid_pattern(self, parser, mock_vfs):
        """Grep with invalid regex pattern."""
        mock_info = MagicMock()
        mock_info.node_type = MagicMock()
        mock_info.node_type.value = "file"

        mock_vfs.info.return_value = mock_info
        parser._vfs = mock_vfs

        result = await parser.execute(
            "grep '[invalid' notes/file.txt", "user123", "executor"
        )
        assert "invalid pattern" in result.lower()


# ==================== Tree Execution Tests ====================


class TestTreeExecution:
    """Test tree command execution."""

    @pytest.mark.asyncio
    async def test_tree_output(self, parser, mock_vfs):
        """Tree shows directory structure."""
        mock_root = MagicMock()
        mock_root.name = "executor"
        mock_root.node_type = MagicMock()
        mock_root.node_type.value = "folder"

        mock_child = MagicMock()
        mock_child.name = "notes"
        mock_child.node_type = MagicMock()
        mock_child.node_type.value = "folder"
        mock_child.children = []

        mock_root.children = [mock_child]

        mock_vfs.tree.return_value = mock_root
        parser._vfs = mock_vfs

        result = await parser.execute("tree", "user123", "executor")
        assert "executor/" in result
        assert "notes/" in result


# ==================== Find Execution Tests ====================


class TestFindExecution:
    """Test find command execution."""

    @pytest.mark.asyncio
    async def test_find_by_name(self, parser, mock_vfs):
        """Find files by name pattern."""
        mock_match = MagicMock()
        mock_match.path = "/users/user123/global/executor/notes/test.json"
        mock_match.node_type = MagicMock()
        mock_match.node_type.value = "file"

        mock_result = MagicMock()
        mock_result.matches = [mock_match]

        mock_vfs.search.return_value = mock_result
        parser._vfs = mock_vfs

        result = await parser.execute('find . -name "*.json"', "user123", "executor")
        assert "test.json" in result

    @pytest.mark.asyncio
    async def test_find_no_matches(self, parser, mock_vfs):
        """Find with no matches."""
        mock_result = MagicMock()
        mock_result.matches = []

        mock_vfs.search.return_value = mock_result
        parser._vfs = mock_vfs

        result = await parser.execute('find . -name "*.xyz"', "user123", "executor")
        assert "no files" in result.lower()
