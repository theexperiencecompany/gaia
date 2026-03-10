"""
Virtual Filesystem (VFS) LangChain Tools.

These tools allow agents to read, write, and manage files in their
isolated virtual filesystem. Files persist across sessions and can
be organized into notes, free-form files, and session-specific outputs.

Tool Summary:
  - vfs_read: Read file content
  - vfs_write: Write content to files
  - vfs_cmd: Execute shell-like commands (ls, tree, find, grep, etc.)

Folder Structure (per user):
  - notes/       - Persistent notes across sessions
  - files/       - Persistent free-form files
  - sessions/{conv_id}/  - Per-conversation tool outputs (compacted)
  - ../skills/   - Shared skills (learned and custom)
"""

import contextlib
from typing import Annotated, Any, Dict

from app.agents.tools.vfs_cmd_parser import get_vfs_command_parser
from app.agents.tools.vfs_constants import (
    USER_VISIBLE_FOLDER,
    detect_artifact_content_type,
    is_user_visible_path,
)
from app.config.loggers import app_logger as logger
from app.decorators import with_rate_limiting
from app.services.vfs import MongoVFS, get_vfs
from app.services.vfs.path_resolver import (
    get_agent_root,
    get_files_path,
    normalize_path,
    validate_user_access,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer


def _get_context(config: RunnableConfig) -> Dict[str, Any]:
    """Extract VFS context fields from config.

    When vfs_session_id is present in configurable every agent in the chain
    (executor + all handoff subagents) shares the same VFS session and workspace
    root (executor). This keeps their file namespaces in sync so they can read
    each other's files without passing absolute paths.

    Returned keys:
        user_id           - owner of the VFS namespace
        conversation_id   - VFS session anchor (vfs_session_id in shared mode)
        agent_name        - workspace root owner ("executor" in shared mode)
        written_by        - actual agent writing the file (subagent_id or agent_name)
        agent_thread_id   - writer's own thread_id
        vfs_session_id    - shared session anchor (None when not in shared mode)
    """
    configurable = config.get("configurable", {}) if config else {}
    metadata = config.get("metadata", {}) if config else {}

    user_id: str | None = configurable.get("user_id") or metadata.get("user_id")
    vfs_session_id: str | None = configurable.get("vfs_session_id")
    thread_id: str | None = configurable.get("thread_id")
    subagent_id: str | None = configurable.get("subagent_id")

    if vfs_session_id:
        # Shared-session mode: all agents in this executor invocation use the
        # executor's workspace so they can read/write each other's files.
        agent_name_meta: str | None = metadata.get("agent_name")
        written_by = subagent_id or agent_name_meta
        if not written_by:
            raise ValueError(
                "VFS context requires 'subagent_id' in configurable or 'agent_name' in metadata"
            )
        return {
            "user_id": user_id,
            "conversation_id": vfs_session_id,
            "agent_name": "executor",
            "written_by": written_by,
            "agent_thread_id": thread_id,
            "vfs_session_id": vfs_session_id,
        }

    # Fallback for agents without a shared session (comms, standalone subagent calls).
    if not thread_id:
        raise ValueError(
            "VFS context requires either 'vfs_session_id' or 'thread_id' in configurable"
        )
    agent_name_fallback: str | None = metadata.get("agent_name")
    written_by_fallback = subagent_id or agent_name_fallback
    if not written_by_fallback:
        raise ValueError(
            "VFS context requires 'subagent_id' in configurable or 'agent_name' in metadata"
        )
    return {
        "user_id": user_id,
        "conversation_id": thread_id,
        "agent_name": written_by_fallback,
        "written_by": written_by_fallback,
        "agent_thread_id": thread_id,
        "vfs_session_id": None,
    }


def _resolve_path(
    path: str,
    user_id: str,
    agent_name: str = "executor",
    conversation_id: str | None = None,
) -> str:
    """
    Resolve a user-provided path to an absolute VFS path.

    Users can provide:
    - Absolute paths: /users/{user_id}/global/...
    - Relative to agent workspace: notes/meeting.txt
    - Just a filename: data.json -> files/data.json
    - .user-visible/file.md -> sessions/{conv_id}/.user-visible/file.md
    """
    path = path.strip()

    # Handle empty or current dir
    if not path or path == ".":
        return get_agent_root(user_id, agent_name)

    # Normalize: "users/..." without a leading slash → treat as absolute "/users/..."
    if path.startswith("users/"):
        path = "/" + path

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

    # .user-visible/ paths map to the current session
    if path.startswith(f"{USER_VISIBLE_FOLDER}/") or path == USER_VISIBLE_FOLDER:
        if not conversation_id:
            logger.warning(
                "No conversation_id for .user-visible path, falling back to files/"
            )
            files_path = get_files_path(user_id, agent_name)
            relative = (
                path[len(f"{USER_VISIBLE_FOLDER}/") :]
                if path.startswith(f"{USER_VISIBLE_FOLDER}/")
                else ""
            )
            if relative:
                return normalize_path(f"{files_path}/{relative}")
            return normalize_path(files_path)

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

    # Check if path starts with a known folder type
    parts = path.split("/", 1)
    if parts[0] in ("notes", "files", "sessions"):
        agent_root = get_agent_root(user_id, agent_name)
        return normalize_path(f"{agent_root}/{path}")

    # Default: treat as file in the agent's files folder
    files_path = get_files_path(user_id, agent_name)
    return normalize_path(f"{files_path}/{path}")


async def _emit_artifact_event(
    *,
    path: str,
    user_id: str,
    vfs: MongoVFS,
    fallback_size_bytes: int = 0,
) -> None:
    """Emit artifact_data custom event for files in .user-visible/."""
    if not is_user_visible_path(path):
        return

    try:
        writer = get_stream_writer()
    except Exception:
        logger.debug("Could not emit artifact event (no stream writer)")
        return

    filename = path.rsplit("/", 1)[-1]
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    size_bytes = fallback_size_bytes
    with contextlib.suppress(Exception):
        info = await vfs.info(path, user_id=user_id)
        if info and info.size_bytes is not None:
            size_bytes = info.size_bytes

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
    ctx = _get_context(config)
    if not ctx["user_id"]:
        return "Error: User ID not found in configuration"

    try:
        vfs = await get_vfs()
        resolved_path = _resolve_path(
            path,
            ctx["user_id"],
            ctx["agent_name"],
            ctx["conversation_id"],
        )
        content = await vfs.read(resolved_path, user_id=ctx["user_id"])

        if content is None:
            return f"File not found: {path}"

        return content

    except Exception as e:
        logger.error(f"VFS read error: {e}")
        return f"Error reading file: {str(e)}"


@tool
@with_rate_limiting("vfs_write")
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

    Examples:
      vfs_write("notes/meeting.txt", "Meeting notes from today...")
      vfs_write("notes/log.txt", "New log entry\\n", append=True)
      vfs_write("files/data.json", '{"key": "value"}')
    """
    ctx = _get_context(config)
    if not ctx["user_id"]:
        return "Error: User ID not found in configuration"

    try:
        vfs = await get_vfs()
        resolved_path = _resolve_path(
            path,
            ctx["user_id"],
            ctx["agent_name"],
            ctx["conversation_id"],
        )

        # Provenance metadata — who created this file and in which session
        metadata: Dict[str, Any] = {
            "agent_name": ctx["agent_name"],
            "written_by": ctx["written_by"],
        }
        if ctx["conversation_id"]:
            metadata["conversation_id"] = ctx["conversation_id"]
        if ctx["agent_thread_id"]:
            metadata["agent_thread_id"] = ctx["agent_thread_id"]
        if ctx["vfs_session_id"]:
            metadata["vfs_session_id"] = ctx["vfs_session_id"]

        if append:
            await vfs.append(resolved_path, content, user_id=ctx["user_id"])
            await _emit_artifact_event(
                path=resolved_path,
                user_id=ctx["user_id"],
                vfs=vfs,
                fallback_size_bytes=len(content.encode("utf-8")),
            )
            return f"Appended {len(content)} characters to: {resolved_path}"

        await vfs.write(resolved_path, content, ctx["user_id"], metadata)
        await _emit_artifact_event(
            path=resolved_path,
            user_id=ctx["user_id"],
            vfs=vfs,
            fallback_size_bytes=len(content.encode("utf-8")),
        )
        return f"Wrote {len(content)} characters to: {resolved_path}"

    except Exception as e:
        logger.error(f"VFS write error: {e}")
        return f"Error writing file: {str(e)}"


@tool
@with_rate_limiting("vfs_cmd")
async def vfs_cmd(
    config: RunnableConfig,
    command: Annotated[
        str,
        "Shell command to execute (ls, tree, find, grep, cat, pwd, stat, echo, mv)",
    ],
) -> str:
    """
    Execute filesystem commands. Working directory is your agent's workspace.

    Supported commands:
      ls [path]              - List directory (-l for details, -a for hidden, -R recursive)
      tree [path] [-L n]     - Directory tree (default depth: 3)
      find [path] -name "pattern" - Find files by name pattern
      grep "pattern" [path]  - Search file contents (-i case insensitive, -r recursive)
      cat [path]             - Display file content
      pwd                    - Current working directory
      stat [path]            - File metadata
      echo "content" > file  - Write to file
      echo "content" >> file - Append to file
      mv source dest         - Move/rename a file or directory

    Examples:
      vfs_cmd("ls -la notes/")
      vfs_cmd("ls -R")
      vfs_cmd("tree sessions/ -L 2")
      vfs_cmd("find . -name '*.json'")
      vfs_cmd("grep 'error' notes/log.txt")
      vfs_cmd("echo 'New note' > notes/quick.txt")

    NOT supported: rm, cp, mkdir, chmod, chown
    """
    ctx = _get_context(config)
    if not ctx["user_id"]:
        return "Error: User ID not found in configuration"

    try:
        parser = get_vfs_command_parser()
        result = await parser.execute(
            command_str=command,
            user_id=ctx["user_id"],
            agent_name=ctx["agent_name"],
            conversation_id=ctx["conversation_id"],
            written_by=ctx["written_by"],
            agent_thread_id=ctx["agent_thread_id"],
            vfs_session_id=ctx["vfs_session_id"],
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
