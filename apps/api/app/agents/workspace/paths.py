"""Canonical /workspace layout + path classification.

Pure functions, no I/O. Everything that needs to reason about where a file
lives inside the sandbox imports from here — never hardcode artifacts
or sessions/ anywhere else.
"""

from __future__ import annotations

from enum import StrEnum
import re

# Enumerated explicitly (not a catch-all) so binary/unknown files fall through
# to application/octet-stream instead of being base64-decoded as UTF-8.
_PLAIN_TEXT_EXTS = (
    "py",
    "pyi",
    "js",
    "mjs",
    "cjs",
    "ts",
    "tsx",
    "jsx",
    "css",
    "scss",
    "less",
    "sql",
    "sh",
    "bash",
    "zsh",
    "rs",
    "go",
    "java",
    "rb",
    "php",
    "swift",
    "kt",
    "kts",
    "scala",
    "c",
    "cc",
    "cpp",
    "cxx",
    "h",
    "hpp",
    "toml",
    "ini",
    "cfg",
    "conf",
    "env",
    "properties",
    "log",
    "text",
    "rst",
    "tsv",
    "lua",
    "r",
    "pl",
    "dart",
    "dockerfile",
    "makefile",
    "gradle",
)

_APPLICATION_YAML = "application/yaml"

_EXT_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "pdf": "application/pdf",
    "json": "application/json",
    "xml": "application/xml",
    "yaml": _APPLICATION_YAML,
    "yml": _APPLICATION_YAML,
    "md": "text/markdown",
    "txt": "text/plain",
    "csv": "text/csv",
    "html": "text/html",
    "htm": "text/html",
    "tex": "text/x-latex",
    **dict.fromkeys(_PLAIN_TEXT_EXTS, "text/plain"),
}

# Rides the SSE event + Mongo conversation inline for an instant, reload-safe
# preview. 64 KB covers virtually every agent-written HTML/MD/code file.
INLINE_ARTIFACT_MAX_BYTES = 64 * 1024

_INLINEABLE_APPLICATION_TYPES = frozenset(
    {
        "application/json",
        "application/xml",
        _APPLICATION_YAML,
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
SCREENSHOTS_DIRNAME = "screenshots"
DOWNLOADS_DIRNAME = "downloads"
GAIA_RUNTIME_DIRNAME = ".gaia"
RUNS_DIRNAME = "runs"
SESSIONS_DIRNAME = "sessions"
SKILLS_DIRNAME = "skills"
SETTINGS_DIRNAME = "settings"
PINNED_DIRNAME = "pinned"


class MountRole(StrEnum):
    """Top-level role of a workspace path, used to route writes and tag events."""

    SCRATCH = "scratch"
    USER_UPLOADED = "user-uploaded"
    ARTIFACTS = "artifacts"
    GAIA_RUNTIME = ".gaia"
    SKILLS = "skills"
    SETTINGS = "settings"
    PINNED = "pinned"
    UNKNOWN = "unknown"


def session_dir(conv_id: str) -> str:
    """Absolute workspace path of a session's root directory."""
    return f"{WORKSPACE_ROOT}/{SESSIONS_DIRNAME}/{conv_id}"


def session_scratch(conv_id: str) -> str:
    """Absolute workspace path of a session's scratch (agent working) dir."""
    return f"{session_dir(conv_id)}/{SCRATCH_DIRNAME}"


def session_user_uploaded(conv_id: str) -> str:
    """Absolute workspace path of a session's user-uploaded files dir."""
    return f"{session_dir(conv_id)}/{USER_UPLOADED_DIRNAME}"


def session_artifacts(conv_id: str) -> str:
    """Absolute workspace path of a session's agent-generated artifacts dir."""
    return f"{session_dir(conv_id)}/{ARTIFACTS_DIRNAME}"


# Deliberately not `artifacts/` — the watcher only tails that dir, so a
# screen capture never lands in the file panel or reaches a bot as an
# outbound file.
def session_screenshot_relpath(filename: str) -> str:
    """Session-relative path of a captured screenshot (what write_session_file takes)."""
    return f"{SCREENSHOTS_DIRNAME}/{filename}"


def session_download_relpath(filename: str) -> str:
    """Session-relative path of a file the download tool fetched from a URL."""
    return f"{DOWNLOADS_DIRNAME}/{filename}"


def runs_log_dir() -> str:
    """Absolute workspace path of the shared agent run-log directory."""
    return f"{WORKSPACE_ROOT}/{GAIA_RUNTIME_DIRNAME}/{RUNS_DIRNAME}"


def is_under_workspace(abs_path: str) -> bool:
    """Return True if abs_path is the workspace root or nested under it."""
    return abs_path == WORKSPACE_ROOT or abs_path.startswith(WORKSPACE_ROOT + "/")


def classify(abs_path: str) -> tuple[MountRole, str | None]:
    """Return (role, conv_id_or_None). Used to route writes + emit events."""
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
    """Best-effort MIME type from extension. Returns None if unknown.

    Dotless filenames (Dockerfile, Makefile) are matched on the whole
    basename so the plain-text entries for them actually resolve.
    """
    name = path.rsplit("/", 1)[-1].lower()
    _, dot, ext = name.rpartition(".")
    return _EXT_CONTENT_TYPES.get(ext if dot else name)


def safe_upload_filename(filename: str) -> str:
    """Slugify an uploaded filename for safe use as a session FS path.

    Restricts to [A-Za-z0-9._-]. Raises ValueError if nothing usable remains.
    """
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in base if ch.isprintable() and ch not in "/\0").strip()
    cleaned = re.sub(r"\s+", "_", cleaned).lstrip(".")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", cleaned)
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("filename is empty after sanitization")
    return cleaned[:255]
