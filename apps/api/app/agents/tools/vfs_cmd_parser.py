"""
VFS Command Parser - Parse and execute shell-like VFS commands.

Uses argparse for robust command-line parsing of each command.
Supports Unix-like commands for navigating and searching the virtual filesystem.

Supported commands:
  ls, tree, find, grep, cat, pwd, stat, echo

Blocked commands (for safety):
  rm, mv, cp, mkdir, chmod, chown, touch, rmdir
"""

import argparse
import asyncio
import io
import re
import shlex
import sys
from dataclasses import dataclass
from typing import Optional

from app.config.loggers import app_logger as logger
from app.services.vfs.path_resolver import get_agent_root


class CommandParseError(Exception):
    """Raised when command parsing fails."""

    pass


@dataclass
class RedirectInfo:
    """Redirect operator info."""

    mode: str  # '>' or '>>'
    filepath: str


class VFSCommandParser:
    """Parse and execute VFS shell commands using argparse."""

    ALLOWED_COMMANDS = {"ls", "tree", "find", "grep", "cat", "pwd", "stat", "echo"}
    BLOCKED_COMMANDS = {
        "rm",
        "mv",
        "cp",
        "mkdir",
        "chmod",
        "chown",
        "touch",
        "rmdir",
        "sudo",
        "su",
        "dd",
        "mkfs",
        "fdisk",
    }

    # Output limits
    MAX_GREP_MATCHES = 50
    MAX_LINE_LENGTH = 200
    MAX_LS_ITEMS = 100
    DEFAULT_TREE_DEPTH = 3

    def __init__(self):
        self._vfs = None
        self._parsers = self._create_parsers()

    def _create_parsers(self) -> dict[str, argparse.ArgumentParser]:
        """Create argparse parsers for each command."""
        parsers = {}

        # ls parser
        ls_parser = argparse.ArgumentParser(
            prog="ls", add_help=False, exit_on_error=False
        )
        ls_parser.add_argument("path", nargs="?", default=".")
        ls_parser.add_argument("-l", "--long", action="store_true", help="Long format")
        ls_parser.add_argument(
            "-a", "--all", action="store_true", help="Show hidden files"
        )
        parsers["ls"] = ls_parser

        # tree parser
        tree_parser = argparse.ArgumentParser(
            prog="tree", add_help=False, exit_on_error=False
        )
        tree_parser.add_argument("path", nargs="?", default=".")
        tree_parser.add_argument("-L", "--level", type=int, default=3, help="Max depth")
        parsers["tree"] = tree_parser

        # find parser
        find_parser = argparse.ArgumentParser(
            prog="find", add_help=False, exit_on_error=False
        )
        find_parser.add_argument("path", nargs="?", default=".")
        find_parser.add_argument("-name", dest="name", help="Name pattern")
        find_parser.add_argument(
            "-iname", dest="iname", help="Case-insensitive name pattern"
        )
        find_parser.add_argument(
            "-type", dest="type", choices=["f", "d"], help="File type"
        )
        parsers["find"] = find_parser

        # grep parser
        grep_parser = argparse.ArgumentParser(
            prog="grep", add_help=False, exit_on_error=False
        )
        grep_parser.add_argument("pattern", help="Search pattern")
        grep_parser.add_argument("path", nargs="?", default=".", help="Path to search")
        grep_parser.add_argument(
            "-i", "--ignore-case", action="store_true", help="Case insensitive"
        )
        grep_parser.add_argument(
            "-r", "--recursive", action="store_true", help="Recursive search"
        )
        grep_parser.add_argument(
            "-n",
            "--line-number",
            action="store_true",
            default=True,
            help="Show line numbers",
        )
        grep_parser.add_argument(
            "-c", "--count", action="store_true", help="Count matches only"
        )
        grep_parser.add_argument(
            "-l",
            "--files-with-matches",
            action="store_true",
            help="Only show filenames",
        )
        parsers["grep"] = grep_parser

        # cat parser
        cat_parser = argparse.ArgumentParser(
            prog="cat", add_help=False, exit_on_error=False
        )
        cat_parser.add_argument("path", help="File to display")
        cat_parser.add_argument(
            "-n", "--number", action="store_true", help="Number lines"
        )
        parsers["cat"] = cat_parser

        # pwd parser
        pwd_parser = argparse.ArgumentParser(
            prog="pwd", add_help=False, exit_on_error=False
        )
        parsers["pwd"] = pwd_parser

        # stat parser
        stat_parser = argparse.ArgumentParser(
            prog="stat", add_help=False, exit_on_error=False
        )
        stat_parser.add_argument("path", help="File to stat")
        parsers["stat"] = stat_parser

        # echo parser - simple, we handle redirect separately
        echo_parser = argparse.ArgumentParser(
            prog="echo", add_help=False, exit_on_error=False
        )
        echo_parser.add_argument("text", nargs="*", help="Text to echo")
        parsers["echo"] = echo_parser

        return parsers

    async def _get_vfs(self):
        """Lazy load VFS."""
        if self._vfs is None:
            from app.services.vfs import get_vfs

            self._vfs = await get_vfs()
        return self._vfs

    def _extract_redirect(self, command_str: str) -> tuple[str, Optional[RedirectInfo]]:
        """
        Extract redirect operator from command string.

        Returns (command_without_redirect, redirect_info or None)
        """
        # Handle different redirect patterns:
        # 1. > "path with spaces"
        # 2. > 'path with spaces'
        # 3. > path_no_spaces

        # First try: quoted paths with spaces
        pattern_quoted = r'\s*(>>|>)\s*"([^"]+)"\s*$'
        match = re.search(pattern_quoted, command_str)
        if match:
            mode = match.group(1)
            filepath = match.group(2)
            command_without_redirect = command_str[: match.start()].strip()
            return command_without_redirect, RedirectInfo(mode=mode, filepath=filepath)

        # Second try: single-quoted paths with spaces
        pattern_single_quoted = r"\s*(>>|>)\s*'([^']+)'\s*$"
        match = re.search(pattern_single_quoted, command_str)
        if match:
            mode = match.group(1)
            filepath = match.group(2)
            command_without_redirect = command_str[: match.start()].strip()
            return command_without_redirect, RedirectInfo(mode=mode, filepath=filepath)

        # Third try: unquoted path (no spaces)
        pattern_unquoted = r'\s*(>>|>)\s*([^\s"\']+)\s*$'
        match = re.search(pattern_unquoted, command_str)
        if match:
            mode = match.group(1)
            filepath = match.group(2)
            command_without_redirect = command_str[: match.start()].strip()
            return command_without_redirect, RedirectInfo(mode=mode, filepath=filepath)

        return command_str, None

    def _tokenize(self, command_str: str) -> list[str]:
        """
        Tokenize command string using shlex.

        Handles quoted strings properly.
        """
        try:
            return shlex.split(command_str)
        except ValueError as e:
            raise CommandParseError(f"Invalid command syntax: {e}")

    def _parse_command(
        self, command_str: str
    ) -> tuple[str, argparse.Namespace, Optional[RedirectInfo]]:
        """
        Parse a command string into command name, args namespace, and redirect.

        Returns (command_name, parsed_args, redirect_info)
        """
        # Extract redirect first
        command_str, redirect = self._extract_redirect(command_str)

        # Tokenize
        tokens = self._tokenize(command_str)

        if not tokens:
            raise CommandParseError("Empty command")

        cmd = tokens[0].lower()
        args = tokens[1:]

        # Check blocked commands
        if cmd in self.BLOCKED_COMMANDS:
            raise CommandParseError(f"'{cmd}' is not supported.")

        # Check allowed commands
        if cmd not in self.ALLOWED_COMMANDS:
            supported = ", ".join(sorted(self.ALLOWED_COMMANDS))
            raise CommandParseError(f"Unknown command '{cmd}'. Supported: {supported}")

        # Get parser for this command
        parser = self._parsers.get(cmd)
        if not parser:
            raise CommandParseError(f"No parser for command '{cmd}'")

        # Parse arguments
        try:
            # Capture stderr to get error messages
            old_stderr = sys.stderr
            sys.stderr = io.StringIO()
            try:
                parsed = parser.parse_args(args)
            finally:
                error_output = sys.stderr.getvalue()
                sys.stderr = old_stderr

            if error_output:
                # There was an error message
                raise CommandParseError(error_output.strip())

        except SystemExit:
            # argparse calls sys.exit on error
            raise CommandParseError(f"Invalid arguments for '{cmd}'")
        except argparse.ArgumentError as e:
            raise CommandParseError(f"Argument error: {e}")

        return cmd, parsed, redirect

    async def execute(
        self,
        command_str: str,
        user_id: str,
        agent_name: str = "executor",
    ) -> str:
        """
        Parse and execute a VFS command.

        Args:
            command_str: The command string to execute
            user_id: User ID for path resolution
            agent_name: Agent name for workspace root

        Returns:
            Command output as string
        """
        try:
            cmd, args, redirect = self._parse_command(command_str)
        except CommandParseError as e:
            return f"Error: {e}"

        # Get handler and execute
        handler = getattr(self, f"_cmd_{cmd}", None)
        if not handler:
            return f"Error: Command '{cmd}' not implemented."

        try:
            result = await handler(args, redirect, user_id, agent_name)
            return result
        except Exception as e:
            logger.error(f"VFS command error ({cmd}): {e}")
            return f"Error: {e}"

    def _resolve_path(self, path: str, user_id: str, agent_name: str) -> str:
        """Resolve a relative path to absolute VFS path."""
        from app.services.vfs.path_resolver import (
            get_agent_root,
            normalize_path,
            validate_user_access,
        )

        path = path.strip()

        # Handle empty path or current directory
        if not path or path == ".":
            return get_agent_root(user_id, agent_name)

        # If already absolute with proper user scope, validate and return
        if path.startswith("/users/"):
            normalized = normalize_path(path)
            if validate_user_access(normalized, user_id):
                return normalized
            # Redirect to user's space if invalid
            logger.warning(f"Access denied: {path} not in user {user_id} scope")

        # If starts with /, treat as relative to agent root
        if path.startswith("/"):
            agent_root = get_agent_root(user_id, agent_name)
            return normalize_path(f"{agent_root}{path}")

        # Handle parent directory references
        if path.startswith("../"):
            agent_root = get_agent_root(user_id, agent_name)
            return normalize_path(f"{agent_root}/{path}")

        # Check if path starts with a known folder type
        parts = path.split("/", 1)
        if parts[0] in ("notes", "files", "sessions"):
            agent_root = get_agent_root(user_id, agent_name)
            return normalize_path(f"{agent_root}/{path}")

        # Default: treat as relative to agent root
        agent_root = get_agent_root(user_id, agent_name)
        return normalize_path(f"{agent_root}/{path}")

    # ==================== Command Handlers ====================

    async def _cmd_pwd(
        self,
        args: argparse.Namespace,
        redirect: Optional[RedirectInfo],
        user_id: str,
        agent_name: str,
    ) -> str:
        """Show current working directory."""
        result = get_agent_root(user_id, agent_name)

        if redirect:
            return await self._handle_redirect(result, redirect, user_id, agent_name)

        return result

    async def _cmd_ls(
        self,
        args: argparse.Namespace,
        redirect: Optional[RedirectInfo],
        user_id: str,
        agent_name: str,
    ) -> str:
        """List directory contents."""
        vfs = await self._get_vfs()

        resolved_path = self._resolve_path(args.path, user_id, agent_name)

        try:
            result = await vfs.list_dir(resolved_path, user_id=user_id)
        except Exception as e:
            return f"ls: cannot access '{args.path}': {e}"

        if not result.items:
            return "(empty directory)"

        # Filter hidden files unless -a
        items = result.items
        if not args.all:
            items = [item for item in items if not item.name.startswith(".")]

        # Limit output
        truncated = len(items) > self.MAX_LS_ITEMS
        if truncated:
            items = items[: self.MAX_LS_ITEMS]

        # Format output
        lines = []

        if args.long:
            lines.append(f"total {len(items)}")
            for item in items:
                type_char = "d" if item.node_type.value == "folder" else "-"
                perms = "rwxr-xr-x" if item.node_type.value == "folder" else "rw-r--r--"
                size = self._format_size(item.size_bytes or 0)
                date = ""
                if item.updated_at:
                    date = item.updated_at.strftime("%Y-%m-%d %H:%M")
                name = item.name + ("/" if item.node_type.value == "folder" else "")
                lines.append(f"{type_char}{perms}  {size:>8}  {date}  {name}")
        else:
            # Simple format - names in columns
            names = []
            for item in items:
                name = item.name + ("/" if item.node_type.value == "folder" else "")
                names.append(name)
            lines.append("  ".join(names))

        if truncated:
            lines.append(f"... and {result.total_count - self.MAX_LS_ITEMS} more items")

        output = "\n".join(lines)

        if redirect:
            return await self._handle_redirect(output, redirect, user_id, agent_name)

        return output

    async def _cmd_tree(
        self,
        args: argparse.Namespace,
        redirect: Optional[RedirectInfo],
        user_id: str,
        agent_name: str,
    ) -> str:
        """Show directory tree."""
        vfs = await self._get_vfs()

        resolved_path = self._resolve_path(args.path, user_id, agent_name)

        try:
            tree = await vfs.tree(resolved_path, user_id=user_id, depth=args.level)
        except Exception as e:
            return f"tree: cannot access '{args.path}': {e}"

        # Format tree output
        def format_node(node, prefix="", is_last=True) -> list[str]:
            lines = []
            connector = "└── " if is_last else "├── "
            suffix = "/" if node.node_type.value == "folder" else ""
            lines.append(f"{prefix}{connector}{node.name}{suffix}")

            if node.children:
                child_prefix = prefix + ("    " if is_last else "│   ")
                for i, child in enumerate(node.children):
                    is_child_last = i == len(node.children) - 1
                    lines.extend(format_node(child, child_prefix, is_child_last))

            return lines

        # Start from root
        result_lines = [f"{tree.name}/"]
        for i, child in enumerate(tree.children):
            is_last = i == len(tree.children) - 1
            result_lines.extend(format_node(child, "", is_last))

        output = "\n".join(result_lines)

        if redirect:
            return await self._handle_redirect(output, redirect, user_id, agent_name)

        return output

    async def _cmd_find(
        self,
        args: argparse.Namespace,
        redirect: Optional[RedirectInfo],
        user_id: str,
        agent_name: str,
    ) -> str:
        """Find files by pattern."""
        vfs = await self._get_vfs()

        # Determine pattern
        pattern = args.name or args.iname or "*"

        resolved_path = self._resolve_path(args.path, user_id, agent_name)

        try:
            result = await vfs.search(pattern, user_id=user_id, base_path=resolved_path)
        except Exception as e:
            return f"find: error: {e}"

        # Filter by type if specified
        matches = result.matches
        if args.type:
            if args.type == "f":
                matches = [m for m in matches if m.node_type.value == "file"]
            elif args.type == "d":
                matches = [m for m in matches if m.node_type.value == "folder"]

        if not matches:
            return f"(no files matching '{pattern}')"

        # Format output - show relative paths from search base
        lines = []
        for match in matches[: self.MAX_LS_ITEMS]:
            rel_path = match.path
            if rel_path.startswith(resolved_path):
                rel_path = "." + rel_path[len(resolved_path) :]
            lines.append(rel_path)

        if len(matches) > self.MAX_LS_ITEMS:
            lines.append(f"... and {len(matches) - self.MAX_LS_ITEMS} more matches")

        output = "\n".join(lines)

        if redirect:
            return await self._handle_redirect(output, redirect, user_id, agent_name)

        return output

    async def _cmd_grep(
        self,
        args: argparse.Namespace,
        redirect: Optional[RedirectInfo],
        user_id: str,
        agent_name: str,
    ) -> str:
        """Search file contents."""
        vfs = await self._get_vfs()

        resolved_path = self._resolve_path(args.path, user_id, agent_name)

        # Compile regex
        try:
            flags = re.IGNORECASE if args.ignore_case else 0
            regex = re.compile(args.pattern, flags)
        except re.error as e:
            return f"grep: invalid pattern: {e}"

        # Get list of files to search
        files_to_search = []

        try:
            info = await vfs.info(resolved_path, user_id=user_id)
            if info is None:
                return f"grep: {args.path}: No such file or directory"

            if info.node_type.value == "file":
                files_to_search = [resolved_path]
            else:
                # It's a directory
                if args.recursive:
                    search_result = await vfs.search(
                        "*", user_id=user_id, base_path=resolved_path
                    )
                    files_to_search = [
                        m.path
                        for m in search_result.matches
                        if m.node_type.value == "file"
                    ]
                else:
                    list_result = await vfs.list_dir(resolved_path, user_id=user_id)
                    files_to_search = [
                        f"{resolved_path}/{item.name}"
                        for item in list_result.items
                        if item.node_type.value == "file"
                    ]
        except Exception as e:
            return f"grep: error accessing '{args.path}': {e}"

        # Search files in parallel
        async def search_file(file_path: str) -> tuple[str, list[str], int]:
            """Search a single file and return (rel_path, matches, count)."""
            try:
                content = await vfs.read(file_path, user_id=user_id)
                if content is None:
                    return "", [], 0

                # Make path relative for output
                rel_path = file_path
                if file_path.startswith(resolved_path):
                    rel_path = file_path[len(resolved_path) :].lstrip("/")
                if not rel_path:
                    rel_path = file_path.rsplit("/", 1)[-1]

                file_matches: list[str] = []
                file_match_count = 0

                for line_num, line in enumerate(content.split("\n"), 1):
                    if regex.search(line):
                        file_match_count += 1

                        if not args.count and not args.files_with_matches:
                            # Truncate long lines
                            display_line = line[: self.MAX_LINE_LENGTH]
                            if len(line) > self.MAX_LINE_LENGTH:
                                display_line += "..."

                            if args.line_number:
                                file_matches.append(
                                    f"{rel_path}:{line_num}: {display_line}"
                                )
                            else:
                                file_matches.append(f"{rel_path}: {display_line}")

                return rel_path, file_matches, file_match_count
            except Exception:
                return "", [], 0

        # Run searches in parallel
        results = await asyncio.gather(
            *[search_file(fp) for fp in files_to_search], return_exceptions=True
        )

        # Aggregate results
        matches: list[str] = []
        match_counts: dict[str, int] = {}
        files_with_matches: set[str] = set()

        for res in results:
            if isinstance(res, BaseException):
                continue
            rel_path, file_matches, file_match_count = res
            if file_match_count > 0:
                files_with_matches.add(rel_path)
                match_counts[rel_path] = file_match_count
                # Only add up to MAX_GREP_MATCHES
                for m in file_matches:
                    if len(matches) < self.MAX_GREP_MATCHES:
                        matches.append(m)

        # Format output based on flags
        if args.files_with_matches:
            if not files_with_matches:
                return f"(no matches for '{args.pattern}')"
            output = "\n".join(sorted(files_with_matches))
        elif args.count:
            lines = [f"{path}: {count}" for path, count in match_counts.items()]
            total = sum(match_counts.values())
            lines.append(f"Total: {total} matches in {len(match_counts)} files")
            output = "\n".join(lines)
        else:
            if not matches:
                return f"(no matches for '{args.pattern}')"

            result_lines = matches
            total_matches = sum(match_counts.values())
            if total_matches > self.MAX_GREP_MATCHES:
                result_lines.append(
                    f"... and {total_matches - self.MAX_GREP_MATCHES} more matches"
                )
            output = "\n".join(result_lines)

        if redirect:
            return await self._handle_redirect(output, redirect, user_id, agent_name)

        return output

    async def _cmd_cat(
        self,
        args: argparse.Namespace,
        redirect: Optional[RedirectInfo],
        user_id: str,
        agent_name: str,
    ) -> str:
        """Display file content."""
        vfs = await self._get_vfs()

        resolved_path = self._resolve_path(args.path, user_id, agent_name)

        try:
            content = await vfs.read(resolved_path, user_id=user_id)
            if content is None:
                return f"cat: {args.path}: No such file"

            if args.number:
                lines = content.split("\n")
                numbered = [f"{i:6d}  {line}" for i, line in enumerate(lines, 1)]
                content = "\n".join(numbered)

            if redirect:
                return await self._handle_redirect(
                    content, redirect, user_id, agent_name
                )

            return content
        except Exception as e:
            return f"cat: {args.path}: {e}"

    async def _cmd_stat(
        self,
        args: argparse.Namespace,
        redirect: Optional[RedirectInfo],
        user_id: str,
        agent_name: str,
    ) -> str:
        """Show file metadata."""
        vfs = await self._get_vfs()

        resolved_path = self._resolve_path(args.path, user_id, agent_name)

        try:
            info = await vfs.info(resolved_path, user_id=user_id)
            if info is None:
                return f"stat: {args.path}: No such file or directory"

            lines = [
                f"  File: {info.path}",
                f"  Size: {info.size_bytes} bytes ({self._format_size(info.size_bytes or 0)})",
                f"  Type: {info.node_type.value}",
            ]

            if info.content_type:
                lines.append(f"  Mime: {info.content_type}")
            if info.created_at:
                lines.append(f"Created: {info.created_at.isoformat()}")
            if info.updated_at:
                lines.append(f"Modified: {info.updated_at.isoformat()}")
            if info.metadata:
                lines.append(f"Metadata: {info.metadata}")

            output = "\n".join(lines)

            if redirect:
                return await self._handle_redirect(
                    output, redirect, user_id, agent_name
                )

            return output
        except Exception as e:
            return f"stat: {args.path}: {e}"

    async def _cmd_echo(
        self,
        args: argparse.Namespace,
        redirect: Optional[RedirectInfo],
        user_id: str,
        agent_name: str,
    ) -> str:
        """Echo text, optionally to a file."""
        content = " ".join(args.text) if args.text else ""

        if redirect:
            return await self._handle_redirect(content, redirect, user_id, agent_name)

        return content

    async def _handle_redirect(
        self,
        content: str,
        redirect: RedirectInfo,
        user_id: str,
        agent_name: str,
    ) -> str:
        """Handle redirect to file."""
        vfs = await self._get_vfs()

        resolved_path = self._resolve_path(redirect.filepath, user_id, agent_name)

        try:
            if redirect.mode == ">>":
                await vfs.append(resolved_path, content, user_id=user_id)
                return f"Appended to {redirect.filepath}"
            else:
                await vfs.write(resolved_path, content, user_id=user_id)
                return f"Wrote to {redirect.filepath}"
        except Exception as e:
            return f"Error writing to '{redirect.filepath}': {e}"

    # ==================== Helpers ====================

    def _format_size(self, size_bytes: int) -> str:
        """Format size in human-readable form."""
        if size_bytes < 1024:
            return f"{size_bytes}B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f}KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f}MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"


# Singleton instance
_parser: Optional[VFSCommandParser] = None


def get_vfs_command_parser() -> VFSCommandParser:
    """Get or create the VFS command parser singleton."""
    global _parser
    if _parser is None:
        _parser = VFSCommandParser()
    return _parser
