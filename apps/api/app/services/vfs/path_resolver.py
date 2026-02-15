"""
VFS Path Resolver - Path resolution utilities for the Virtual Filesystem.

Implements the folder structure:

/users/{user_id}/
└── global/
    ├── skills/
    │   ├── learned/
    │   └── custom/
    ├── executor/                      # Special: executor at same level as skills
    │   ├── sessions/{conversation_id}/{agent_name}/
    │   ├── notes/
    │   └── files/
    └── subagents/{agent_name}/
        ├── notes/
        └── files/
"""

import re
from typing import Optional

# Special agent name for the executor
EXECUTOR_AGENT = "executor"

# Reserved folder names that can't be used as agent names
RESERVED_NAMES = {"skills", "executor", "subagents", "global", "users"}


def normalize_path(path: str) -> str:
    """
    Normalize a VFS path.

    - Converts backslashes to forward slashes
    - Removes double slashes
    - Ensures leading slash
    - Removes trailing slash (except for root)
    - Removes any path traversal attempts (..)

    Args:
        path: The path to normalize

    Returns:
        Normalized path string
    """
    # Convert backslashes and remove path traversal
    path = path.replace("\\", "/")
    path = re.sub(r"\.\./?", "", path)

    # Remove double slashes
    while "//" in path:
        path = path.replace("//", "/")

    # Ensure leading slash
    if not path.startswith("/"):
        path = "/" + path

    # Remove trailing slash (except for root)
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    return path


def validate_user_access(path: str, user_id: str) -> bool:
    """
    Validate that a path belongs to the specified user.

    Args:
        path: The normalized path to check
        user_id: The user ID to validate against

    Returns:
        True if the user has access to this path
    """
    path = normalize_path(path)
    expected_prefix = f"/users/{user_id}/"
    return path.startswith(expected_prefix) or path == f"/users/{user_id}"


def get_user_root(user_id: str) -> str:
    """Get the root path for a user's VFS."""
    return f"/users/{user_id}/global"


def get_skills_path(user_id: str, skill_type: str = "learned") -> str:
    """
    Get the path to a user's skills folder.

    Args:
        user_id: The user ID
        skill_type: Either "learned" or "custom"

    Returns:
        Path to the skills subfolder
    """
    if skill_type not in ("learned", "custom"):
        raise ValueError(
            f"Invalid skill_type: {skill_type}. Must be 'learned' or 'custom'"
        )

    return f"/users/{user_id}/global/skills/{skill_type}"


def get_custom_skill_path(
    user_id: str,
    target: str,
    skill_name: str,
) -> str:
    """
    Get the VFS path for an installable custom skill.

    Skills are scoped by target:
      /users/{user_id}/global/skills/custom/global/{skill_name}/
      /users/{user_id}/global/skills/custom/executor/{skill_name}/
      /users/{user_id}/global/skills/custom/subagents/{agent_name}/{skill_name}/

    Args:
        user_id: The user ID
        target: Skill target scope (global, executor, or subagent ID)
        skill_name: The skill name (kebab-case)

    Returns:
        Full VFS directory path for the skill
    """
    safe_name = _sanitize_name(skill_name)
    safe_target = _sanitize_name(target)

    if safe_target in ("global", "executor"):
        return f"/users/{user_id}/global/skills/custom/{safe_target}/{safe_name}"
    else:
        # Subagent-scoped: target is the subagent ID (gmail, github, slack, etc.)
        return (
            f"/users/{user_id}/global/skills/custom/subagents/{safe_target}/{safe_name}"
        )


def get_session_path(user_id: str, conversation_id: str) -> str:
    """
    Get the path to a conversation session folder.

    Sessions are stored under executor since it's the main orchestrator.

    Args:
        user_id: The user ID
        conversation_id: The conversation/thread ID

    Returns:
        Path to the session folder
    """
    return f"/users/{user_id}/global/executor/sessions/{conversation_id}"


def get_tool_output_path(
    user_id: str,
    conversation_id: str,
    agent_name: str,
    tool_call_id: str,
    tool_name: str,
) -> str:
    """
    Get the path for a compacted tool output file.

    Tool outputs are stored in the session folder, organized by agent:
    /users/{user_id}/global/executor/sessions/{conversation_id}/{agent_name}/{tool_call_id}_{tool_name}.json

    Args:
        user_id: The user ID
        conversation_id: The conversation/thread ID
        agent_name: The agent that produced the output (executor, gmail, github, etc.)
        tool_call_id: The unique tool call ID
        tool_name: The name of the tool that was called

    Returns:
        Full path to the tool output file
    """
    # Sanitize agent name and tool name for filesystem safety
    safe_agent = _sanitize_name(agent_name)
    safe_tool = _sanitize_name(tool_name)
    safe_call_id = _sanitize_name(tool_call_id)

    session_path = get_session_path(user_id, conversation_id)
    return f"{session_path}/{safe_agent}/{safe_call_id}_{safe_tool}.json"


def get_notes_path(user_id: str, agent_name: str) -> str:
    """
    Get the path to an agent's notes folder.

    Notes are persistent across sessions.
    - Executor notes: /users/{user_id}/global/executor/notes/
    - Subagent notes: /users/{user_id}/global/subagents/{agent_name}/notes/

    Args:
        user_id: The user ID
        agent_name: The agent name

    Returns:
        Path to the notes folder
    """
    safe_agent = _sanitize_name(agent_name)

    if safe_agent == EXECUTOR_AGENT:
        return f"/users/{user_id}/global/executor/notes"
    else:
        return f"/users/{user_id}/global/subagents/{safe_agent}/notes"


def get_files_path(user_id: str, agent_name: str) -> str:
    """
    Get the path to an agent's free-form files folder.

    Files are persistent across sessions.
    - Executor files: /users/{user_id}/global/executor/files/
    - Subagent files: /users/{user_id}/global/subagents/{agent_name}/files/

    Args:
        user_id: The user ID
        agent_name: The agent name

    Returns:
        Path to the files folder
    """
    safe_agent = _sanitize_name(agent_name)

    if safe_agent == EXECUTOR_AGENT:
        return f"/users/{user_id}/global/executor/files"
    else:
        return f"/users/{user_id}/global/subagents/{safe_agent}/files"


def get_agent_root(user_id: str, agent_name: str) -> str:
    """
    Get the root path for an agent's workspace.

    Args:
        user_id: The user ID
        agent_name: The agent name

    Returns:
        Root path for the agent
    """
    safe_agent = _sanitize_name(agent_name)

    if safe_agent == EXECUTOR_AGENT:
        return f"/users/{user_id}/global/executor"
    else:
        return f"/users/{user_id}/global/subagents/{safe_agent}"


def parse_path(path: str) -> dict:
    """
    Parse a VFS path into its components.

    Args:
        path: The normalized VFS path

    Returns:
        Dictionary with parsed components:
        - user_id: The user ID (or None)
        - is_global: Whether this is under /global/
        - agent_name: The agent name (executor or subagent name)
        - folder_type: The folder type (sessions, notes, files, skills)
        - conversation_id: The conversation ID (for sessions)
        - remaining: Remaining path components
    """
    path = normalize_path(path)
    parts = [p for p in path.split("/") if p]

    result: dict[str, str | bool | list[str] | None] = {
        "user_id": None,
        "is_global": False,
        "agent_name": None,
        "folder_type": None,
        "conversation_id": None,
        "remaining": [],
    }

    if len(parts) < 2 or parts[0] != "users":
        return result

    result["user_id"] = parts[1]

    if len(parts) < 3 or parts[2] != "global":
        result["remaining"] = parts[2:] if len(parts) > 2 else []
        return result

    result["is_global"] = True

    if len(parts) < 4:
        return result

    # Determine what's at the third level
    level3 = parts[3]

    if level3 == "skills":
        result["folder_type"] = "skills"
        result["remaining"] = parts[4:]

    elif level3 == "executor":
        result["agent_name"] = "executor"
        if len(parts) > 4:
            level4 = parts[4]
            if level4 in ("sessions", "notes", "files"):
                result["folder_type"] = level4
                if level4 == "sessions" and len(parts) > 5:
                    result["conversation_id"] = parts[5]
                    result["remaining"] = parts[6:]
                else:
                    result["remaining"] = parts[5:]
            else:
                result["remaining"] = parts[4:]

    elif level3 == "subagents":
        if len(parts) > 4:
            result["agent_name"] = parts[4]
            if len(parts) > 5:
                level5 = parts[5]
                if level5 in ("notes", "files"):
                    result["folder_type"] = level5
                    result["remaining"] = parts[6:]
                else:
                    result["remaining"] = parts[5:]

    else:
        result["remaining"] = parts[3:]

    return result


def build_path(
    user_id: str,
    *,
    agent_name: Optional[str] = None,
    folder_type: Optional[str] = None,
    conversation_id: Optional[str] = None,
    filename: Optional[str] = None,
) -> str:
    """
    Build a VFS path from components.

    Args:
        user_id: The user ID (required)
        agent_name: The agent name (executor or subagent name)
        folder_type: The folder type (sessions, notes, files, skills)
        conversation_id: The conversation ID (required for sessions)
        filename: Optional filename to append

    Returns:
        Constructed VFS path
    """
    if folder_type == "skills":
        path = f"/users/{user_id}/global/skills"
    elif agent_name:
        path = get_agent_root(user_id, agent_name)
        if folder_type:
            path = f"{path}/{folder_type}"
            if folder_type == "sessions" and conversation_id:
                path = f"{path}/{conversation_id}"
    else:
        path = get_user_root(user_id)

    if filename:
        path = f"{path}/{_sanitize_name(filename)}"

    return normalize_path(path)


def _sanitize_name(name: str) -> str:
    """
    Sanitize a name for use in paths.

    Removes or replaces characters that could cause issues.
    """
    if not name:
        return "unknown"

    # Replace problematic characters with underscores
    safe = re.sub(r"[/\\:*?\"<>|]", "_", name)

    # Remove leading/trailing whitespace and dots
    safe = safe.strip(". ")

    # Collapse multiple underscores
    safe = re.sub(r"_+", "_", safe)

    return safe or "unknown"


def get_parent_path(path: str) -> str:
    """Get the parent directory path."""
    path = normalize_path(path)
    parts = path.rsplit("/", 1)
    return parts[0] if len(parts) > 1 and parts[0] else "/"


def join_path(*parts: str) -> str:
    """Join path parts and normalize."""
    joined = "/".join(p.strip("/") for p in parts if p)
    return normalize_path(joined)


def get_filename(path: str) -> str:
    """Extract the filename from a path."""
    path = normalize_path(path)
    return path.rsplit("/", 1)[-1]


def get_extension(path: str) -> str:
    """Extract the file extension from a path."""
    filename = get_filename(path)
    if "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    return ""
