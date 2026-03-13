"""
VFS Command Parser - Parse and execute shell-like VFS commands.

Uses argparse for robust command-line parsing of each command.
Supports Unix-like commands for navigating and searching the virtual filesystem.

Supported commands:
  ls, tree, find, grep, cat, pwd, stat, echo, mv

  ls supports: -l (long), -a (hidden), -R (recursive)

Blocked commands (for safety):
  rm, cp, mkdir, chmod, chown, touch, rmdir
"""

import argparse
import asyncio
import contextlib
import fnmatch
import re
import shlex
from dataclasses import dataclass
from typing import Any, NoReturn, Optional

from app.agents.tools.vfs_constants import (
    USER_VISIBLE_FOLDER,
    detect_artifact_content_type,
    is_user_visible_path,
)
from app.constants.summarization import MAX_GREP_OUTPUT_CHARS
from app.services.vfs import MongoVFS, VFSAccessError, get_vfs
from shared.py.wide_events import log
from app.services.vfs.path_resolver import (
    get_agent_root,
    normalize_path,
    validate_user_access,
)
from app.utils.command_parsing import extract_output_redirect
from langgraph.config import get_stream_writer


class CommandParseError(Exception):
    """Raised when command parsing fails."""

    pass


class _VFSArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:  # type: ignore[override]
        raise CommandParseError(message)

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:  # type: ignore[override]
        if message:
            raise CommandParseError(message.strip())
        raise CommandParseError("Invalid arguments")


@dataclass
class RedirectInfo:
    """Redirect operator info."""

    mode: str  # '>' or '>>'
    filepath: str


class VFSCommandParser:
    """Parse and execute VFS shell commands using argparse."""

    ALLOWED_COMMANDS = {
        "ls",
        "tree",
        "find",
        "grep",
        "cat",
        "pwd",
        "stat",
        "echo",
        "mv",
    }
    BLOCKED_COMMANDS = {
        "rm",
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
    MAX_GREP_FILES = 50
    MAX_GREP_FILE_CHARS = 200_000
    MAX_LINE_LENGTH = 200
    MAX_LS_ITEMS = 100
    DEFAULT_TREE_DEPTH = 3
    MAX_COMMAND_LENGTH = 8192

    def __init__(self) -> None:
        self._vfs: MongoVFS | None = None
        self._parsers = self._create_parsers()

    def _create_parsers(self) -> dict[str, argparse.ArgumentParser]:
        """Create argparse parsers for each command."""
        parsers: dict[str, argparse.ArgumentParser] = {}

        # ls parser
        ls_parser = _VFSArgumentParser(prog="ls", add_help=False, exit_on_error=False)
        ls_parser.add_argument("path", nargs="?", default=".")
        ls_parser.add_argument("-l", "--long", action="store_true", help="Long format")
        ls_parser.add_argument(
            "-a", "--all", action="store_true", help="Show hidden files"
        )
        ls_parser.add_argument(
            "-R", "--recursive", action="store_true", help="Recursive listing"
        )
        parsers["ls"] = ls_parser

        # tree parser
        tree_parser = _VFSArgumentParser(
            prog="tree", add_help=False, exit_on_error=False
        )
        tree_parser.add_argument("path", nargs="?", default=".")
        tree_parser.add_argument("-L", "--level", type=int, default=3, help="Max depth")
        parsers["tree"] = tree_parser

        # find parser
        find_parser = _VFSArgumentParser(
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
        grep_parser = _VFSArgumentParser(
            prog="grep", add_help=False, exit_on_error=False
        )
        grep_parser.add_argument(
            "pattern", nargs="?", default=None, help="Search pattern"
        )
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
        grep_parser.add_argument(
            "-v", "--invert-match", action="store_true", help="Invert match"
        )
        grep_parser.add_argument(
            "-w", "--word-regexp", action="store_true", help="Match whole words only"
        )
        grep_parser.add_argument(
            "-o",
            "--only-matching",
            action="store_true",
            help="Show only matching parts",
        )
        grep_parser.add_argument(
            "-e",
            "--regexp",
            action="append",
            dest="patterns",
            help="Additional pattern (can be repeated)",
        )
        grep_parser.add_argument(
            "-A",
            "--after-context",
            type=int,
            default=0,
            help="Lines after match",
        )
        grep_parser.add_argument(
            "-B",
            "--before-context",
            type=int,
            default=0,
            help="Lines before match",
        )
        grep_parser.add_argument(
            "-C",
            "--context",
            type=int,
            default=0,
            help="Lines before and after match",
        )
        grep_parser.add_argument(
            "--include",
            action="append",
            dest="include_globs",
            help="Only search files matching glob",
        )
        grep_parser.add_argument(
            "--exclude",
            action="append",
            dest="exclude_globs",
            help="Skip files matching glob",
        )
        parsers["grep"] = grep_parser

        # cat parser
        cat_parser = _VFSArgumentParser(prog="cat", add_help=False, exit_on_error=False)
        cat_parser.add_argument("path", help="File to display")
        cat_parser.add_argument(
            "-n", "--number", action="store_true", help="Number lines"
        )
        parsers["cat"] = cat_parser

        # pwd parser
        pwd_parser = _VFSArgumentParser(prog="pwd", add_help=False, exit_on_error=False)
        parsers["pwd"] = pwd_parser

        # stat parser
        stat_parser = _VFSArgumentParser(
            prog="stat", add_help=False, exit_on_error=False
        )
        stat_parser.add_argument("path", help="File to stat")
        parsers["stat"] = stat_parser

        # echo parser - simple, we handle redirect separately
        echo_parser = _VFSArgumentParser(
            prog="echo", add_help=False, exit_on_error=False
        )
        echo_parser.add_argument("text", nargs="*", help="Text to echo")
        parsers["echo"] = echo_parser

        # mv parser
        mv_parser = _VFSArgumentParser(prog="mv", add_help=False, exit_on_error=False)
        mv_parser.add_argument("source", help="Source file or directory path")
        mv_parser.add_argument("dest", help="Destination path")
        parsers["mv"] = mv_parser

        return parsers

    async def _get_vfs(self) -> MongoVFS:
        """Lazy load VFS."""
        if self._vfs is None:
            self._vfs = await get_vfs()
        return self._vfs

    def _extract_redirect(self, command_str: str) -> tuple[str, Optional[RedirectInfo]]:
        """
        Extract redirect operator from command string.

        Returns (command_without_redirect, redirect_info or None)
        """
        command_without_redirect, redirect = extract_output_redirect(command_str)
        if not redirect:
            return command_str, None

        mode, filepath = redirect
        return command_without_redirect, RedirectInfo(mode=mode, filepath=filepath)

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
        if len(command_str) > self.MAX_COMMAND_LENGTH:
            raise CommandParseError("Command too long")

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
            parsed = parser.parse_args(args)
        except SystemExit as e:
            raise CommandParseError(f"Invalid arguments for '{cmd}': {e}")
        except argparse.ArgumentError as e:
            raise CommandParseError(f"Argument error: {e}")

        return cmd, parsed, redirect

    async def execute(
        self,
        command_str: str,
        user_id: str,
        agent_name: str = "executor",
        conversation_id: str | None = None,
        written_by: str | None = None,
        agent_thread_id: str | None = None,
        vfs_session_id: str | None = None,
    ) -> str:
        """
        Parse and execute a VFS command.

        Args:
            command_str: The command string to execute
            user_id: User ID for path resolution
            agent_name: Agent name for workspace root
            conversation_id: Session anchor for path resolution
            written_by: Actual agent writing the file (for provenance metadata)
            agent_thread_id: Writer's own thread_id (for provenance metadata)
            vfs_session_id: Shared session anchor (for provenance metadata)

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
            result = await handler(
                args,
                redirect,
                user_id,
                agent_name,
                conversation_id,
                written_by,
                agent_thread_id,
                vfs_session_id,
            )
            return result
        except Exception as e:
            log.error(f"VFS command error ({cmd}): {e}")
            return f"Error: {e}"

    def _resolve_path(
        self,
        path: str,
        user_id: str,
        agent_name: str,
        conversation_id: str | None = None,
    ) -> str:
        """Resolve a relative path to absolute VFS path."""
        path = path.strip()

        # Handle empty path or current directory
        if not path or path == ".":
            return get_agent_root(user_id, agent_name)

        # System paths pass through directly (read-only, accessible to all users)
        if path.startswith("/system/"):
            return normalize_path(path)

        # If already absolute with proper user scope, validate and return
        if path.startswith("/users/"):
            normalized = normalize_path(path)
            if validate_user_access(normalized, user_id):
                return normalized
            # Redirect to user's space if invalid
            log.warning(f"Access denied: {path} not in user {user_id} scope")

        # .user-visible/ paths map to the current session
        if path.startswith(f"{USER_VISIBLE_FOLDER}/") or path == USER_VISIBLE_FOLDER:
            if not conversation_id:
                log.warning(
                    "No conversation_id for .user-visible path, falling back to files/"
                )
                agent_root = get_agent_root(user_id, agent_name)
                relative = (
                    path[len(f"{USER_VISIBLE_FOLDER}/") :]
                    if path.startswith(f"{USER_VISIBLE_FOLDER}/")
                    else ""
                )
                if relative:
                    return normalize_path(f"{agent_root}/files/{relative}")
                return normalize_path(f"{agent_root}/files")

            agent_root = get_agent_root(user_id, agent_name)
            relative = (
                path[len(USER_VISIBLE_FOLDER) :]
                if len(path) > len(USER_VISIBLE_FOLDER)
                else ""
            )
            return normalize_path(
                f"{agent_root}/sessions/{conversation_id}/{USER_VISIBLE_FOLDER}{relative}"
            )

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
        conversation_id: str | None = None,
        written_by: str | None = None,
        agent_thread_id: str | None = None,
        vfs_session_id: str | None = None,
    ) -> str:
        """Show current working directory."""
        result = get_agent_root(user_id, agent_name)

        if redirect:
            return await self._handle_redirect(
                result,
                redirect,
                user_id,
                agent_name,
                conversation_id,
                written_by,
                agent_thread_id,
                vfs_session_id,
            )

        return result

    async def _cmd_ls(
        self,
        args: argparse.Namespace,
        redirect: Optional[RedirectInfo],
        user_id: str,
        agent_name: str,
        conversation_id: str | None = None,
        written_by: str | None = None,
        agent_thread_id: str | None = None,
        vfs_session_id: str | None = None,
    ) -> str:
        """List directory contents."""
        vfs = await self._get_vfs()

        resolved_path = self._resolve_path(
            args.path,
            user_id,
            agent_name,
            conversation_id,
        )

        if getattr(args, "recursive", False):
            output = await self._ls_recursive(
                vfs,
                resolved_path,
                args.path,
                user_id,
                show_all=args.all,
                long_format=args.long,
            )
        else:
            output = await self._ls_single(
                vfs,
                resolved_path,
                args.path,
                user_id,
                show_all=args.all,
                long_format=args.long,
            )

        if redirect:
            return await self._handle_redirect(
                output,
                redirect,
                user_id,
                agent_name,
                conversation_id,
                written_by,
                agent_thread_id,
                vfs_session_id,
            )

        return output

    async def _ls_single(
        self,
        vfs: Any,
        resolved_path: str,
        display_path: str,
        user_id: str,
        *,
        show_all: bool,
        long_format: bool,
    ) -> str:
        """List a single directory."""
        try:
            result = await vfs.list_dir(resolved_path, user_id=user_id)
        except Exception as e:
            return f"ls: cannot access '{display_path}': {e}"

        if not result.items:
            return "(empty directory)"

        items = result.items
        if not show_all:
            items = [item for item in items if not item.name.startswith(".")]

        truncated = len(items) > self.MAX_LS_ITEMS
        if truncated:
            items = items[: self.MAX_LS_ITEMS]

        lines = []
        if long_format:
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
            names = []
            for item in items:
                name = item.name + ("/" if item.node_type.value == "folder" else "")
                names.append(name)
            lines.append("  ".join(names))

        if truncated:
            lines.append(f"... and {result.total_count - self.MAX_LS_ITEMS} more items")

        return "\n".join(lines)

    async def _ls_recursive(
        self,
        vfs: Any,
        resolved_path: str,
        display_path: str,
        user_id: str,
        *,
        show_all: bool,
        long_format: bool,
        _depth: int = 0,
        _max_depth: int = 6,
        _total_lines: list[int] | None = None,
        _max_lines: int = 500,
    ) -> str:
        """Recursively list directories, mirroring Unix `ls -R` output format."""
        if _total_lines is None:
            _total_lines = [0]

        lines: list[str] = []

        # Header: "path/to/dir:"
        lines.append(f"{display_path}:")

        try:
            result = await vfs.list_dir(resolved_path, user_id=user_id)
        except Exception as e:
            lines.append(f"ls: cannot access '{display_path}': {e}")
            return "\n".join(lines)

        items = result.items or []
        if not show_all:
            items = [item for item in items if not item.name.startswith(".")]

        if not items:
            lines.append("(empty directory)")
        elif long_format:
            lines.append(f"total {len(items)}")
            for item in items:
                type_char = "d" if item.node_type.value == "folder" else "-"
                perms = "rwxr-xr-x" if item.node_type.value == "folder" else "rw-r--r--"
                size = self._format_size(item.size_bytes or 0)
                date = (
                    item.updated_at.strftime("%Y-%m-%d %H:%M")
                    if item.updated_at
                    else ""
                )
                name = item.name + ("/" if item.node_type.value == "folder" else "")
                lines.append(f"{type_char}{perms}  {size:>8}  {date}  {name}")
        else:
            names = [
                item.name + ("/" if item.node_type.value == "folder" else "")
                for item in items
            ]
            lines.append("  ".join(names))

        _total_lines[0] += len(lines)

        # Recurse into subdirectories
        if _depth < _max_depth and _total_lines[0] < _max_lines:
            subdirs = [item for item in items if item.node_type.value == "folder"]
            for subdir in subdirs:
                if _total_lines[0] >= _max_lines:
                    lines.append(f"... output truncated at {_max_lines} lines")
                    break
                child_display = display_path.rstrip("/") + "/" + subdir.name
                child_resolved = resolved_path.rstrip("/") + "/" + subdir.name
                lines.append("")  # blank separator like real ls -R
                child_output = await self._ls_recursive(
                    vfs,
                    child_resolved,
                    child_display,
                    user_id,
                    show_all=show_all,
                    long_format=long_format,
                    _depth=_depth + 1,
                    _max_depth=_max_depth,
                    _total_lines=_total_lines,
                    _max_lines=_max_lines,
                )
                lines.append(child_output)

        return "\n".join(lines)

    async def _cmd_tree(
        self,
        args: argparse.Namespace,
        redirect: Optional[RedirectInfo],
        user_id: str,
        agent_name: str,
        conversation_id: str | None = None,
        written_by: str | None = None,
        agent_thread_id: str | None = None,
        vfs_session_id: str | None = None,
    ) -> str:
        """Show directory tree."""
        vfs = await self._get_vfs()

        resolved_path = self._resolve_path(
            args.path,
            user_id,
            agent_name,
            conversation_id,
        )

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
            return await self._handle_redirect(
                output,
                redirect,
                user_id,
                agent_name,
                conversation_id,
                written_by,
                agent_thread_id,
                vfs_session_id,
            )

        return output

    async def _cmd_find(
        self,
        args: argparse.Namespace,
        redirect: Optional[RedirectInfo],
        user_id: str,
        agent_name: str,
        conversation_id: str | None = None,
        written_by: str | None = None,
        agent_thread_id: str | None = None,
        vfs_session_id: str | None = None,
    ) -> str:
        """Find files by pattern."""
        vfs = await self._get_vfs()

        # Determine pattern
        pattern = args.name or args.iname or "*"

        resolved_path = self._resolve_path(
            args.path,
            user_id,
            agent_name,
            conversation_id,
        )

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
            return await self._handle_redirect(
                output,
                redirect,
                user_id,
                agent_name,
                conversation_id,
                written_by,
                agent_thread_id,
                vfs_session_id,
            )

        return output

    @staticmethod
    def _prepare_grep_pattern(args: argparse.Namespace) -> str | None:
        """
        Build a single regex pattern from args.pattern and args.patterns (-e).

        Applies -w (whole word) wrapping. Returns None if no pattern provided.
        """
        all_patterns: list[str] = []
        if args.pattern:
            all_patterns.append(args.pattern)
        if args.patterns:
            all_patterns.extend(args.patterns)

        if not all_patterns:
            return None

        if len(all_patterns) > 1:
            combined = "|".join(f"(?:{p})" for p in all_patterns)
        else:
            combined = all_patterns[0]

        if args.word_regexp:
            combined = rf"\b(?:{combined})\b"

        return combined

    @staticmethod
    def _matches_glob_filters(
        filename: str,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
    ) -> bool:
        """Check if a filename passes include/exclude glob filters."""
        if include_globs:
            if not any(fnmatch.fnmatch(filename, g) for g in include_globs):
                return False
        if exclude_globs:
            if any(fnmatch.fnmatch(filename, g) for g in exclude_globs):
                return False
        return True

    async def _cmd_grep(
        self,
        args: argparse.Namespace,
        redirect: Optional[RedirectInfo],
        user_id: str,
        agent_name: str,
        conversation_id: str | None = None,
        written_by: str | None = None,
        agent_thread_id: str | None = None,
        vfs_session_id: str | None = None,
    ) -> str:
        """Search file contents using server-side MongoDB regex where possible."""
        pattern = self._prepare_grep_pattern(args)
        if pattern is None:
            return "grep: no pattern provided (use positional arg or -e)"

        vfs = await self._get_vfs()

        resolved_path = self._resolve_path(
            args.path,
            user_id,
            agent_name,
            conversation_id,
        )

        try:
            info = await vfs.info(resolved_path, user_id=user_id)
            if info is None:
                return f"grep: {args.path}: No such file or directory"

            if info.node_type.value == "file":
                # Apply glob filters to single file
                filename = resolved_path.rsplit("/", 1)[-1]
                if not self._matches_glob_filters(
                    filename, args.include_globs, args.exclude_globs
                ):
                    return "(no matches — file excluded by filter)"

                # Single file: client-side search (one read, no benefit from $regex)
                content = await vfs.read(resolved_path, user_id=user_id)
                if content is None:
                    return f"grep: {args.path}: Could not read file"
                if len(content) > self.MAX_GREP_FILE_CHARS:
                    content = content[: self.MAX_GREP_FILE_CHARS]
                output = self._search_single_file(
                    content, pattern, resolved_path, resolved_path, args
                )
            else:
                # Directory: server-side search for inline files + GridFS fallback
                server_results, gridfs_results, has_gridfs = await self._grep_directory(
                    vfs, pattern, resolved_path, user_id, args
                )
                output = self._format_grep_output(
                    server_results, gridfs_results, pattern, args, has_gridfs
                )
        except Exception as e:
            return f"grep: error accessing '{args.path}': {e}"

        # Truncate oversized grep output to avoid blowing up context window
        if len(output) > MAX_GREP_OUTPUT_CHARS:
            output = (
                f"{output[:MAX_GREP_OUTPUT_CHARS]}\n\n"
                f"--- TRUNCATED ({len(output) - MAX_GREP_OUTPUT_CHARS} chars remaining) ---\n"
                f"Refine your grep pattern or target a specific file."
            )

        if redirect:
            return await self._handle_redirect(
                output,
                redirect,
                user_id,
                agent_name,
                conversation_id,
                written_by,
                agent_thread_id,
                vfs_session_id,
            )

        return output

    async def _grep_directory(
        self,
        vfs: MongoVFS,
        pattern: str,
        resolved_path: str,
        user_id: str,
        args: argparse.Namespace,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
        """
        Grep a directory using server-side search for inline files
        and client-side fallback for GridFS files.

        Returns (server_results, gridfs_results, has_gridfs).
        """
        # Run server-side grep for inline files and GridFS path listing in parallel
        server_task = vfs.grep_content(
            pattern,
            user_id=user_id,
            base_path=resolved_path,
            case_insensitive=args.ignore_case,
            recursive=args.recursive,
            max_files=self.MAX_GREP_FILES,
            max_matches_per_file=self.MAX_GREP_MATCHES,
            max_line_length=self.MAX_LINE_LENGTH,
            include_globs=args.include_globs,
            exclude_globs=args.exclude_globs,
            before_context=getattr(args, "context", 0)
            or getattr(args, "before_context", 0),
            after_context=getattr(args, "context", 0)
            or getattr(args, "after_context", 0),
            invert=getattr(args, "invert_match", False),
            only_matching=getattr(args, "only_matching", False),
        )
        gridfs_task = vfs.get_gridfs_file_paths(
            user_id=user_id,
            base_path=resolved_path,
            recursive=args.recursive,
            limit=20,
        )

        gathered = await asyncio.gather(
            server_task, gridfs_task, return_exceptions=True
        )
        server_results = (
            gathered[0] if not isinstance(gathered[0], BaseException) else []
        )
        gridfs_paths = gathered[1] if not isinstance(gathered[1], BaseException) else []
        for i, res in enumerate(gathered):
            if isinstance(res, BaseException):
                log.warning(f"grep gather task {i} failed: {res}")

        # Apply glob filters to GridFS paths
        if args.include_globs or args.exclude_globs:
            gridfs_paths = [
                fp
                for fp in gridfs_paths
                if self._matches_glob_filters(
                    fp.rsplit("/", 1)[-1], args.include_globs, args.exclude_globs
                )
            ]

        # Client-side search for GridFS files (they can't use $regex on content)
        gridfs_results: list[dict[str, Any]] = []
        if gridfs_paths:
            gridfs_search_tasks = [
                self._grep_gridfs_file(vfs, fp, pattern, resolved_path, user_id, args)
                for fp in gridfs_paths
            ]
            raw_results = await asyncio.gather(
                *gridfs_search_tasks, return_exceptions=True
            )
            for res in raw_results:
                if isinstance(res, BaseException):
                    continue
                if res is not None:
                    gridfs_results.append(res)

        return server_results, gridfs_results, len(gridfs_paths) > 0

    async def _grep_gridfs_file(
        self,
        vfs: MongoVFS,
        file_path: str,
        pattern: str,
        base_path: str,
        user_id: str,
        args: argparse.Namespace,
    ) -> dict[str, Any] | None:
        """Read and search a single GridFS file client-side."""
        content = await vfs.read(file_path, user_id=user_id)
        if content is None:
            return None
        if len(content) > self.MAX_GREP_FILE_CHARS:
            content = content[: self.MAX_GREP_FILE_CHARS]
        return self._search_content(content, pattern, file_path, base_path, args)

    def _search_content(
        self,
        content: str,
        pattern: str,
        file_path: str,
        base_path: str,
        args: argparse.Namespace,
    ) -> dict[str, Any] | None:
        """
        Search a single file's content client-side.

        Returns a match dict {"path": str, "name": str, "matches": [...]}
        or None if no matches.

        Each match entry has:
          - line_num: int
          - line: str (the display line)
          - is_context: bool (True if this is a context line, not a match)
        """
        flags = re.IGNORECASE if args.ignore_case else 0
        try:
            compiled = re.compile(pattern, flags)
        except re.error:
            compiled = re.compile(re.escape(pattern), flags)

        invert = getattr(args, "invert_match", False)
        only_matching = getattr(args, "only_matching", False)
        after_ctx = getattr(args, "context", 0) or getattr(args, "after_context", 0)
        before_ctx = getattr(args, "context", 0) or getattr(args, "before_context", 0)
        wants_context = (after_ctx > 0 or before_ctx > 0) and not invert

        lines = content.split("\n")

        # First pass: find matching line indices
        match_indices: list[int] = []
        for i, line in enumerate(lines):
            hit = compiled.search(line) is not None
            if hit != invert:
                match_indices.append(i)
                if len(match_indices) >= self.MAX_GREP_MATCHES:
                    break

        if not match_indices:
            return None

        # Build output entries (matches + optional context lines)
        file_matches: list[dict[str, Any]] = []

        if wants_context:
            include_set: set[int] = set()
            for idx in match_indices:
                start = max(0, idx - before_ctx)
                end = min(len(lines) - 1, idx + after_ctx)
                for j in range(start, end + 1):
                    include_set.add(j)
            match_set = set(match_indices)

            prev_idx = -2
            for idx in sorted(include_set):
                if prev_idx >= 0 and idx > prev_idx + 1:
                    file_matches.append(
                        {"line_num": 0, "line": "--", "is_context": False}
                    )
                prev_idx = idx
                line = lines[idx]
                is_match = idx in match_set

                if is_match and only_matching:
                    for m in compiled.finditer(line):
                        file_matches.append(
                            {
                                "line_num": idx + 1,
                                "line": m.group(),
                                "is_context": False,
                            }
                        )
                else:
                    display_line = line[: self.MAX_LINE_LENGTH]
                    if len(line) > self.MAX_LINE_LENGTH:
                        display_line += "..."
                    file_matches.append(
                        {
                            "line_num": idx + 1,
                            "line": display_line,
                            "is_context": not is_match,
                        }
                    )
        else:
            for idx in match_indices:
                line = lines[idx]
                if only_matching and not invert:
                    for m in compiled.finditer(line):
                        file_matches.append(
                            {
                                "line_num": idx + 1,
                                "line": m.group(),
                                "is_context": False,
                            }
                        )
                else:
                    display_line = line[: self.MAX_LINE_LENGTH]
                    if len(line) > self.MAX_LINE_LENGTH:
                        display_line += "..."
                    file_matches.append(
                        {"line_num": idx + 1, "line": display_line, "is_context": False}
                    )

        if not file_matches:
            return None

        # Compute relative path from base_path for display
        if base_path and file_path.startswith(base_path.rstrip("/") + "/"):
            rel_name = file_path[len(base_path.rstrip("/")) + 1 :]
        else:
            rel_name = file_path.rsplit("/", 1)[-1]
        return {"path": file_path, "name": rel_name, "matches": file_matches}

    def _search_single_file(
        self,
        content: str,
        pattern: str,
        file_path: str,
        base_path: str,
        args: argparse.Namespace,
    ) -> str:
        """Search a single file's content and format the output string."""
        result = self._search_content(content, pattern, file_path, base_path, args)

        # Compute relative path from base_path for display
        if base_path and file_path.startswith(base_path.rstrip("/") + "/"):
            rel_path = file_path[len(base_path.rstrip("/")) + 1 :]
        else:
            rel_path = file_path.rsplit("/", 1)[-1]

        if result is None:
            return f"(no matches for '{pattern}')"

        matches = result["matches"]
        real_matches = [m for m in matches if not m.get("is_context")]

        if args.files_with_matches:
            return rel_path

        if args.count:
            return (
                f"{rel_path}: {len(real_matches)}\n"
                f"Total: {len(real_matches)} matches in 1 files"
            )

        lines: list[str] = []
        for m in matches:
            if m["line"] == "--" and m["line_num"] == 0:
                lines.append("--")
                continue
            sep = "-" if m.get("is_context") else ":"
            if args.line_number:
                lines.append(f"{rel_path}{sep}{m['line_num']}{sep} {m['line']}")
            else:
                lines.append(f"{rel_path}{sep} {m['line']}")

        if len(real_matches) >= self.MAX_GREP_MATCHES:
            lines.append(f"... truncated at {self.MAX_GREP_MATCHES} matches")

        return "\n".join(lines)

    def _format_grep_output(
        self,
        server_results: list[dict[str, Any]],
        gridfs_results: list[dict[str, Any]],
        pattern: str,
        args: argparse.Namespace,
        has_gridfs: bool,
    ) -> str:
        """Combine server-side and GridFS grep results into formatted output."""
        all_results = server_results + gridfs_results

        if not all_results:
            return f"(no matches for '{pattern}')"

        def rel_path(result: dict[str, Any]) -> str:
            return result.get("name", result["path"].rsplit("/", 1)[-1])

        if args.files_with_matches:
            paths = sorted({rel_path(r) for r in all_results})
            return "\n".join(paths)

        def real_match_count(r: dict[str, Any]) -> int:
            return sum(1 for m in r["matches"] if not m.get("is_context"))

        if args.count:
            lines: list[str] = []
            total = 0
            for r in all_results:
                count = real_match_count(r)
                total += count
                lines.append(f"{rel_path(r)}: {count}")
            lines.append(f"Total: {total} matches in {len(all_results)} files")
            return "\n".join(lines)

        # Standard output with matching lines and context
        output_lines: list[str] = []
        total_matches = 0
        multi_file = len(all_results) > 1

        for file_idx, r in enumerate(all_results):
            rp = rel_path(r)
            file_match_count = real_match_count(r)
            total_matches += file_match_count

            if multi_file and file_idx > 0 and output_lines:
                output_lines.append("--")

            for m in r["matches"]:
                if total_matches > self.MAX_GREP_MATCHES and not m.get("is_context"):
                    break
                if m["line"] == "--" and m["line_num"] == 0:
                    output_lines.append("--")
                    continue
                sep = "-" if m.get("is_context") else ":"
                if args.line_number:
                    output_lines.append(f"{rp}{sep}{m['line_num']}{sep} {m['line']}")
                else:
                    output_lines.append(f"{rp}{sep} {m['line']}")

        if total_matches > self.MAX_GREP_MATCHES:
            output_lines.append(
                f"... and {total_matches - self.MAX_GREP_MATCHES} more matches"
            )

        if has_gridfs:
            output_lines.append("(note: large GridFS files searched with fallback)")

        return "\n".join(output_lines)

    async def _cmd_cat(
        self,
        args: argparse.Namespace,
        redirect: Optional[RedirectInfo],
        user_id: str,
        agent_name: str,
        conversation_id: str | None = None,
        written_by: str | None = None,
        agent_thread_id: str | None = None,
        vfs_session_id: str | None = None,
    ) -> str:
        """Display file content."""
        vfs = await self._get_vfs()

        resolved_path = self._resolve_path(
            args.path,
            user_id,
            agent_name,
            conversation_id,
        )

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
                    content,
                    redirect,
                    user_id,
                    agent_name,
                    conversation_id,
                    written_by,
                    agent_thread_id,
                    vfs_session_id,
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
        conversation_id: str | None = None,
        written_by: str | None = None,
        agent_thread_id: str | None = None,
        vfs_session_id: str | None = None,
    ) -> str:
        """Show file metadata."""
        vfs = await self._get_vfs()

        resolved_path = self._resolve_path(
            args.path,
            user_id,
            agent_name,
            conversation_id,
        )

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
                    output,
                    redirect,
                    user_id,
                    agent_name,
                    conversation_id,
                    written_by,
                    agent_thread_id,
                    vfs_session_id,
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
        conversation_id: str | None = None,
        written_by: str | None = None,
        agent_thread_id: str | None = None,
        vfs_session_id: str | None = None,
    ) -> str:
        """Echo text, optionally to a file."""
        content = " ".join(args.text) if args.text else ""

        if redirect:
            return await self._handle_redirect(
                content,
                redirect,
                user_id,
                agent_name,
                conversation_id,
                written_by,
                agent_thread_id,
                vfs_session_id,
            )

        return content

    async def _cmd_mv(
        self,
        args: argparse.Namespace,
        redirect: Optional[RedirectInfo],
        user_id: str,
        agent_name: str,
        conversation_id: str | None = None,
        written_by: str | None = None,
        agent_thread_id: str | None = None,
        vfs_session_id: str | None = None,
    ) -> str:
        """Move/rename a file or directory."""
        if redirect:
            return "mv: output redirection is not supported"

        uses_user_visible = any(
            value == USER_VISIBLE_FOLDER or value.startswith(f"{USER_VISIBLE_FOLDER}/")
            for value in (args.source, args.dest)
        )
        if uses_user_visible and not conversation_id:
            return "mv: .user-visible requires an active conversation session"

        vfs = await self._get_vfs()

        resolved_source = self._resolve_path(
            args.source,
            user_id,
            agent_name,
            conversation_id,
        )
        resolved_dest = self._resolve_path(
            args.dest,
            user_id,
            agent_name,
            conversation_id,
        )

        if not conversation_id and (
            "/sessions/" in resolved_source or "/sessions/" in resolved_dest
        ):
            return "mv: session paths require an active conversation session"

        if conversation_id:
            agent_root = get_agent_root(user_id, agent_name)
            current_session_root = normalize_path(
                f"{agent_root}/sessions/{conversation_id}"
            )

            for label, candidate in (
                ("source", resolved_source),
                ("destination", resolved_dest),
            ):
                if "/sessions/" in candidate and not (
                    candidate == current_session_root
                    or candidate.startswith(f"{current_session_root}/")
                ):
                    return f"mv: {label} cannot escape the current session"

        try:
            new_path = await vfs.move(resolved_source, resolved_dest, user_id=user_id)

            if is_user_visible_path(new_path):
                await self._emit_artifact_event(new_path, user_id)

            return f"Moved '{args.source}' -> '{args.dest}'"
        except FileNotFoundError:
            return f"mv: cannot stat '{args.source}': No such file or directory"
        except VFSAccessError as e:
            return f"mv: permission denied: {e}"
        except Exception as e:
            return f"mv: {e}"

    async def _emit_artifact_event(self, path: str, user_id: str) -> None:
        """Emit artifact_data custom event for files in .user-visible/."""
        if not is_user_visible_path(path):
            return

        vfs = await self._get_vfs()
        filename = path.rsplit("/", 1)[-1]
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        size_bytes = 0
        with contextlib.suppress(Exception):
            info = await vfs.info(path, user_id=user_id)
            if info and info.size_bytes is not None:
                size_bytes = info.size_bytes

        try:
            writer = get_stream_writer()
        except Exception:
            return

        writer(
            {
                "artifact_data": {
                    "path": path,
                    "filename": filename,
                    "content_type": detect_artifact_content_type(ext),
                    "size_bytes": size_bytes,
                }
            }
        )

    async def _handle_redirect(
        self,
        content: str,
        redirect: RedirectInfo,
        user_id: str,
        agent_name: str,
        conversation_id: str | None = None,
        written_by: str | None = None,
        agent_thread_id: str | None = None,
        vfs_session_id: str | None = None,
    ) -> str:
        """Handle redirect to file."""
        vfs = await self._get_vfs()

        resolved_path = self._resolve_path(
            redirect.filepath,
            user_id,
            agent_name,
            conversation_id,
        )

        try:
            if redirect.mode == ">>":
                await vfs.append(resolved_path, content, user_id=user_id)
                if is_user_visible_path(resolved_path):
                    await self._emit_artifact_event(resolved_path, user_id)
                return f"Appended to {redirect.filepath}"
            else:
                # Provenance metadata for writes via echo redirect
                if not written_by:
                    raise ValueError(
                        "VFS redirect write requires 'written_by' (subagent_id or agent_name)"
                    )
                metadata: dict[str, Any] = {
                    "agent_name": agent_name,
                    "written_by": written_by,
                }
                if conversation_id:
                    metadata["conversation_id"] = conversation_id
                if agent_thread_id:
                    metadata["agent_thread_id"] = agent_thread_id
                if vfs_session_id:
                    metadata["vfs_session_id"] = vfs_session_id
                await vfs.write(
                    resolved_path, content, user_id=user_id, metadata=metadata
                )
                if is_user_visible_path(resolved_path):
                    await self._emit_artifact_event(resolved_path, user_id)
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
