"""Shared constants and helpers for VFS tools."""

USER_VISIBLE_FOLDER = ".user-visible"

ARTIFACT_CONTENT_TYPE_MAP: dict[str, str] = {
    "md": "text/markdown",
    "html": "text/html",
    "htm": "text/html",
    "txt": "text/plain",
    "json": "application/json",
    "py": "text/x-python",
    "js": "text/javascript",
    "ts": "text/typescript",
    "tsx": "text/typescript",
    "jsx": "text/javascript",
    "css": "text/css",
    "csv": "text/csv",
    "xml": "text/xml",
    "yaml": "text/yaml",
    "yml": "text/yaml",
    "tex": "text/x-latex",
    "sql": "text/x-sql",
    "sh": "text/x-shellscript",
    "rs": "text/x-rust",
    "go": "text/x-go",
    "java": "text/x-java",
    "rb": "text/x-ruby",
    "php": "text/x-php",
    "swift": "text/x-swift",
    "kt": "text/x-kotlin",
    "c": "text/x-c",
    "cpp": "text/x-c++",
    "h": "text/x-c",
}


def detect_artifact_content_type(ext: str) -> str:
    """Map extension to content type for artifact events."""
    return ARTIFACT_CONTENT_TYPE_MAP.get(ext, "text/plain")


def is_user_visible_path(path: str) -> bool:
    """Return True when a VFS path is inside the user-visible folder."""
    return f"/{USER_VISIBLE_FOLDER}/" in path
