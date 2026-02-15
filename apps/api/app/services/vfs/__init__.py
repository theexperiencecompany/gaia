"""
Virtual Filesystem (VFS) Service.

A MongoDB-backed virtual filesystem for storing agent outputs,
notes, and files with proper user isolation and context tracking.

Folder Structure:
/users/{user_id}/
└── global/
    ├── skills/
    │   ├── learned/
    │   └── custom/
    ├── executor/                      # Main agent workspace
    │   ├── sessions/{conversation_id}/{agent_name}/
    │   ├── notes/
    │   └── files/
    └── subagents/{agent_name}/        # Per-subagent workspace
        ├── notes/
        └── files/

Usage:
    from app.services.vfs import get_vfs

    vfs = await get_vfs()
    await vfs.write("/users/123/global/executor/notes/meeting.txt", content, user_id="123")
    content = await vfs.read("/users/123/global/executor/notes/meeting.txt", user_id="123")

SECURITY:
    All VFS operations REQUIRE user_id parameter.
    Users can ONLY access paths under /users/{their_user_id}/.
    Cross-user access raises VFSAccessError.
"""

from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.services.vfs.mongo_vfs import MongoVFS, VFSAccessError
from app.services.vfs.path_resolver import (
    EXECUTOR_AGENT,
    build_path,
    get_agent_root,
    get_files_path,
    get_notes_path,
    get_parent_path,
    get_session_path,
    get_skills_path,
    get_tool_output_path,
    get_user_root,
    join_path,
    normalize_path,
    parse_path,
    validate_user_access,
)


async def get_vfs():
    """
    Get the VFS service instance.

    Returns:
        MongoVFS: The VFS service instance

    Raises:
        RuntimeError: If VFS is not available
    """
    vfs = await providers.aget("vfs")
    if vfs is None:
        raise RuntimeError("VFS service is not available")
    return vfs


@lazy_provider(
    name="vfs",
    required_keys=[],
    strategy=MissingKeyStrategy.ERROR,
    auto_initialize=True,
)
async def init_vfs():
    """Initialize the VFS service."""
    vfs = MongoVFS()
    return vfs


__all__ = [
    "get_vfs",
    "init_vfs",
    "VFSAccessError",
    "EXECUTOR_AGENT",
    "normalize_path",
    "validate_user_access",
    "get_user_root",
    "get_skills_path",
    "get_session_path",
    "get_tool_output_path",
    "get_notes_path",
    "get_files_path",
    "get_agent_root",
    "parse_path",
    "build_path",
    "get_parent_path",
    "join_path",
]
