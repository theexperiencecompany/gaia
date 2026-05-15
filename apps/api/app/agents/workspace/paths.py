"""Canonical `/workspace` layout + path classification.

Pure functions, no I/O. Everything that needs to reason about where a file
lives inside the sandbox imports from here — never hardcode `.user-visible`
or `sessions/` anywhere else.
"""

from __future__ import annotations

from enum import StrEnum

_EXT_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "pdf": "application/pdf",
    "json": "application/json",
    "md": "text/markdown",
    "txt": "text/plain",
    "csv": "text/csv",
    "html": "text/html",
}

WORKSPACE_ROOT = "/workspace"
USER_VISIBLE_DIRNAME = ".user-visible"
USER_UPLOADED_DIRNAME = "user-uploaded"
SCRATCH_DIRNAME = "scratch"
GAIA_RUNTIME_DIRNAME = ".gaia"
RUNS_DIRNAME = "runs"
SESSIONS_DIRNAME = "sessions"
SKILLS_DIRNAME = "skills"
SETTINGS_DIRNAME = "settings"
PINNED_DIRNAME = "pinned"


class MountRole(StrEnum):
    SCRATCH = "scratch"
    USER_UPLOADED = "user-uploaded"
    USER_VISIBLE = ".user-visible"
    GAIA_RUNTIME = ".gaia"
    SKILLS = "skills"
    SETTINGS = "settings"
    PINNED = "pinned"
    UNKNOWN = "unknown"


def session_dir(conv_id: str) -> str:
    return f"{WORKSPACE_ROOT}/{SESSIONS_DIRNAME}/{conv_id}"


def session_scratch(conv_id: str) -> str:
    return f"{session_dir(conv_id)}/{SCRATCH_DIRNAME}"


def session_user_uploaded(conv_id: str) -> str:
    return f"{session_dir(conv_id)}/{USER_UPLOADED_DIRNAME}"


def session_user_visible(conv_id: str) -> str:
    return f"{session_dir(conv_id)}/{USER_VISIBLE_DIRNAME}"


def runs_log_dir() -> str:
    return f"{WORKSPACE_ROOT}/{GAIA_RUNTIME_DIRNAME}/{RUNS_DIRNAME}"


def is_under_workspace(abs_path: str) -> bool:
    return abs_path == WORKSPACE_ROOT or abs_path.startswith(WORKSPACE_ROOT + "/")


def classify(abs_path: str) -> tuple[MountRole, str | None]:
    """Return (role, conv_id_or_None). Used to route writes + emit events.

    Examples:
        "/workspace/sessions/abc/scratch/foo.py"        -> (SCRATCH, "abc")
        "/workspace/sessions/abc/.user-visible/x.html"  -> (USER_VISIBLE, "abc")
        "/workspace/sessions/abc/user-uploaded/d.csv"   -> (USER_UPLOADED, "abc")
        "/workspace/skills/my-skill/main.py"            -> (SKILLS, None)
        "/workspace/.gaia/runs/abc.log"                 -> (GAIA_RUNTIME, None)
    """
    if not is_under_workspace(abs_path):
        return MountRole.UNKNOWN, None
    rest = (
        abs_path[len(WORKSPACE_ROOT) + 1 :].split("/")
        if abs_path != WORKSPACE_ROOT
        else []
    )
    if not rest:
        return MountRole.UNKNOWN, None
    head = rest[0]
    if head == SKILLS_DIRNAME:
        return MountRole.SKILLS, None
    if head == SETTINGS_DIRNAME:
        return MountRole.SETTINGS, None
    if head == PINNED_DIRNAME:
        return MountRole.PINNED, None
    if head == GAIA_RUNTIME_DIRNAME:
        return MountRole.GAIA_RUNTIME, None
    if head == SESSIONS_DIRNAME and len(rest) >= 3:
        conv = rest[1]
        sub = rest[2]
        if sub == SCRATCH_DIRNAME:
            return MountRole.SCRATCH, conv
        if sub == USER_UPLOADED_DIRNAME:
            return MountRole.USER_UPLOADED, conv
        if sub == USER_VISIBLE_DIRNAME:
            return MountRole.USER_VISIBLE, conv
        return MountRole.SCRATCH, conv  # tolerate session subroots
    return MountRole.UNKNOWN, None


def detect_content_type(path: str) -> str | None:
    """Best-effort MIME type from extension. Returns None if unknown."""
    _, _, ext = path.rpartition(".")
    return _EXT_CONTENT_TYPES.get(ext.lower())
