"""Canonical `/workspace` layout + path classification.

Pure functions, no I/O. Everything that needs to reason about where a file
lives inside the sandbox imports from here — never hardcode `artifacts`
or `sessions/` anywhere else.
"""

from __future__ import annotations

from enum import StrEnum
import re

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

# Small textual artifacts ride the SSE event (and the Mongo conversation)
# inline so the side-panel preview is instant and survives reload without
# an extra round-trip. 64 KB covers virtually every agent-written
# HTML/MD/code file while keeping per-message documents bounded.
INLINE_ARTIFACT_MAX_BYTES = 64 * 1024

_INLINEABLE_APPLICATION_TYPES = frozenset(
    {
        "application/json",
        "application/xml",
        "application/yaml",
        "application/x-yaml",
        "application/javascript",
        "application/x-sh",
        "image/svg+xml",
    }
)


def is_inlineable_content_type(content_type: str | None) -> bool:
    """Whether the content type is safe to ship as a UTF-8 string inline."""
    if not content_type:
        return False
    return content_type.startswith("text/") or content_type in _INLINEABLE_APPLICATION_TYPES


WORKSPACE_ROOT = "/workspace"
ARTIFACTS_DIRNAME = "artifacts"
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
    ARTIFACTS = "artifacts"
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


def session_artifacts(conv_id: str) -> str:
    return f"{session_dir(conv_id)}/{ARTIFACTS_DIRNAME}"


def runs_log_dir() -> str:
    return f"{WORKSPACE_ROOT}/{GAIA_RUNTIME_DIRNAME}/{RUNS_DIRNAME}"


def is_under_workspace(abs_path: str) -> bool:
    return abs_path == WORKSPACE_ROOT or abs_path.startswith(WORKSPACE_ROOT + "/")


def classify(abs_path: str) -> tuple[MountRole, str | None]:
    """Return (role, conv_id_or_None). Used to route writes + emit events.

    Examples:
        "/workspace/sessions/abc/scratch/foo.py"        -> (SCRATCH, "abc")
        "/workspace/sessions/abc/artifacts/x.html"  -> (ARTIFACTS, "abc")
        "/workspace/sessions/abc/user-uploaded/d.csv"   -> (USER_UPLOADED, "abc")
        "/workspace/skills/my-skill/main.py"            -> (SKILLS, None)
        "/workspace/.gaia/runs/abc.log"                 -> (GAIA_RUNTIME, None)
    """
    if not is_under_workspace(abs_path):
        return MountRole.UNKNOWN, None
    rest = abs_path[len(WORKSPACE_ROOT) + 1 :].split("/") if abs_path != WORKSPACE_ROOT else []
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
        if sub == ARTIFACTS_DIRNAME:
            return MountRole.ARTIFACTS, conv
        return MountRole.SCRATCH, conv  # tolerate session subroots
    return MountRole.UNKNOWN, None


def detect_content_type(path: str) -> str | None:
    """Best-effort MIME type from extension. Returns None if unknown."""
    _, _, ext = path.rpartition(".")
    return _EXT_CONTENT_TYPES.get(ext.lower())


def safe_upload_filename(filename: str) -> str:
    """Slugify an uploaded filename for safe use as a session FS path.

    Strips directory separators, control chars and leading dots; collapses
    whitespace; restricts to [A-Za-z0-9._-]. Raises ValueError if nothing
    usable remains. Single source of truth for the on-disk name an upload
    lands at — both the upload pipeline and the file-context formatter call
    this so the agent always sees the exact path it can read.
    """
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in base if ch.isprintable() and ch not in "/\0").strip()
    cleaned = re.sub(r"\s+", "_", cleaned).lstrip(".")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", cleaned)
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("filename is empty after sanitization")
    return cleaned[:255]
