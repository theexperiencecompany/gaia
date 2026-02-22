"""
Virtual Filesystem (VFS) LangChain Tools.

These tools allow agents to read, write, and manage files in their
isolated virtual filesystem. Files persist across sessions and can
be organized into notes, free-form files, and session-specific outputs.

Tool Summary:
  - vfs_read: Read file content
  - vfs_write: Write/append content to files
  - vfs_cmd: Execute shell-like commands (ls, tree, find, grep, etc.)

Folder Structure (per user):
  - notes/       - Persistent notes across sessions
  - files/       - Persistent free-form files
  - sessions/{conv_id}/  - Per-conversation tool outputs (compacted)
  - ../skills/   - Shared skills (learned and custom)
"""

from typing import Annotated, Any, Dict

from app.config.loggers import app_logger as logger
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


def _get_context(config: RunnableConfig) -> Dict[str, Any]:
    """Extract user_id, conversation_id, and agent_name from config."""
    metadata = config.get("metadata", {}) if config else {}
    return {
        "user_id": metadata.get("user_id"),
        "conversation_id": metadata.get("conversation_id"),
        "agent_name": metadata.get("agent_name", "executor"),
    }


def _resolve_path(
    path: str,
    user_id: str,
    agent_name: str = "executor",
) -> str:
    """
    Resolve a user-provided path to an absolute VFS path.

    Users can provide:
    - Absolute paths: /users/{user_id}/global/...
    - Relative to agent workspace: notes/meeting.txt
    - Just a filename: data.json -> files/data.json
    """
    from app.services.vfs.path_resolver import (
        get_agent_root,
        get_files_path,
        normalize_path,
        validate_user_access,
    )

    path = path.strip()

    # Handle empty or current dir
    if not path or path == ".":
        return get_agent_root(user_id, agent_name)

    # If already absolute with proper user scope, validate and return
    if path.startswith("/users/"):
        normalized = normalize_path(path)
        if validate_user_access(normalized, user_id):
            return normalized
        # User tried to access another user's files - redirect to their space
        logger.warning(f"Access denied: {path} not in user {user_id} scope")

    # System paths pass through directly (read-only, accessible to all users)
    if path.startswith("/system/"):
        return normalize_path(path)

    # If starts with /, treat as relative to agent root
    if path.startswith("/"):
        agent_root = get_agent_root(user_id, agent_name)
        return normalize_path(f"{agent_root}{path}")

    # Check if path starts with a known folder type
    parts = path.split("/", 1)
    if parts[0] in ("notes", "files", "sessions"):
        agent_root = get_agent_root(user_id, agent_name)
        return normalize_path(f"{agent_root}/{path}")

    # Default: treat as file in the agent's files folder
    files_path = get_files_path(user_id, agent_name)
    return normalize_path(f"{files_path}/{path}")


@tool
async def vfs_read(
    config: RunnableConfig,
    path: Annotated[
        str,
        "File path to read. Can be relative (notes/file.txt) or absolute.",
    ],
) -> str:
    """
    Read a file from your virtual filesystem.

    Paths are relative to your workspace root (notes/, files/, sessions/).

    Examples:
      vfs_read("notes/meeting.txt")
      vfs_read("sessions/abc123/gmail/emails.json")
      vfs_read("files/data.json")
    """
    from app.services.vfs import get_vfs

    ctx = _get_context(config)
    if not ctx["user_id"]:
        return "Error: User ID not found in configuration"

    try:
        vfs = await get_vfs()
        resolved_path = _resolve_path(path, ctx["user_id"], ctx["agent_name"])
        content = await vfs.read(resolved_path, user_id=ctx["user_id"])

        if content is None:
            return f"File not found: {path}"

        return content

    except Exception as e:
        logger.error(f"VFS read error: {e}")
        return f"Error reading file: {str(e)}"


@tool
async def vfs_write(
    config: RunnableConfig,
    path: Annotated[
        str,
        "File path to write. Can be relative (notes/file.txt) or absolute.",
    ],
    content: Annotated[str, "Content to write to the file"],
    append: Annotated[
        bool,
        "If True, append to existing file instead of overwriting. Default: False",
    ] = False,
) -> str:
    """
    Write content to a file. Creates parent directories automatically.

    Use append=True to add content to an existing file without overwriting.

    Examples:
      vfs_write("notes/meeting.txt", "Meeting notes from today...")
      vfs_write("notes/log.txt", "New log entry\\n", append=True)
      vfs_write("files/data.json", '{"key": "value"}')
    """
    from app.services.vfs import get_vfs

    ctx = _get_context(config)
    if not ctx["user_id"]:
        return "Error: User ID not found in configuration"

    try:
        vfs = await get_vfs()
        resolved_path = _resolve_path(path, ctx["user_id"], ctx["agent_name"])

        # Add context metadata
        metadata = {
            "agent_name": ctx["agent_name"],
        }
        if ctx["conversation_id"]:
            metadata["conversation_id"] = ctx["conversation_id"]

        if append:
            await vfs.append(resolved_path, content, user_id=ctx["user_id"])
            return f"Appended {len(content)} characters to: {resolved_path}"
        else:
            await vfs.write(resolved_path, content, ctx["user_id"], metadata)
            return f"Wrote {len(content)} characters to: {resolved_path}"

    except Exception as e:
        logger.error(f"VFS write error: {e}")
        return f"Error writing file: {str(e)}"


@tool
async def vfs_cmd(
    config: RunnableConfig,
    command: Annotated[
        str,
        "Shell command to execute (ls, tree, find, grep, cat, pwd, stat, echo)",
    ],
) -> str:
    """
    Execute filesystem commands. Working directory is your agent's workspace.

    Supported commands:
      ls [path]              - List directory (-l for details, -a for hidden)
      tree [path] [-L n]     - Directory tree (default depth: 3)
      find [path] -name "pattern" - Find files by name pattern
      grep "pattern" [path]  - Search file contents (-i case insensitive, -r recursive)
      cat [path]             - Display file content
      pwd                    - Current working directory
      stat [path]            - File metadata
      echo "content" > file  - Write to file
      echo "content" >> file - Append to file

    Examples:
      vfs_cmd("ls -la notes/")
      vfs_cmd("tree sessions/ -L 2")
      vfs_cmd("find . -name '*.json'")
      vfs_cmd("grep 'error' notes/log.txt")
      vfs_cmd("echo 'New note' > notes/quick.txt")

    NOT supported: rm, mv, cp, mkdir, chmod, chown
    """
    from app.agents.tools.vfs_cmd_parser import get_vfs_command_parser

    ctx = _get_context(config)
    if not ctx["user_id"]:
        return "Error: User ID not found in configuration"

    try:
        parser = get_vfs_command_parser()
        result = await parser.execute(
            command_str=command,
            user_id=ctx["user_id"],
            agent_name=ctx["agent_name"],
        )
        return result

    except Exception as e:
        logger.error(f"VFS cmd error: {e}")
        return f"Error executing command: {str(e)}"


tools = [
    vfs_read,
    vfs_write,
    vfs_cmd,
]
