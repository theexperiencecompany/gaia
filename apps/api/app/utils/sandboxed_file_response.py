"""Serve an agent-written file over HTTP without letting it run on our origin.

Agent-generated artifacts are untrusted content served from the API origin,
which holds the session cookie. The owner's session-file endpoints stream them
through here so the stored-XSS fence lives in one place. A shared link's bytes
never come from this origin: app/services/links/serving.py serves them from the
content origin.
"""

from pathlib import Path

from fastapi.responses import FileResponse

from app.agents.workspace.paths import detect_content_type

_DOWNLOAD_OCTET = "application/octet-stream"
# Content types a browser executes script from when navigated to top-level;
# served with a sandbox CSP so artifacts can't run JS on the API origin
# (which holds the session cookie). Covers every XML flavour detect_content_type emits.
_ACTIVE_CONTENT_TYPES = (
    "text/html",
    "image/svg+xml",
    "application/xhtml+xml",
    "application/xml",
)
_SANDBOX_CSP = {"Content-Security-Policy": "sandbox"}
# The owner's inline types; the rest download. HTML previews in a srcDoc iframe instead,
# and a PDF carries no sandbox CSP, which would block the browser's viewer.
_SAFE_INLINE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf")


def _file_response(
    host_path: Path,
    content_type: str,
    *,
    inline: bool,
    cache_control: str,
    headers: dict[str, str],
) -> FileResponse:
    # filename= emits an RFC-encoded Content-Disposition: attachment, so a
    # quoted/CR-LF filename can't inject the header. FileResponse handles Range / 206.
    return FileResponse(
        path=str(host_path),
        media_type=content_type,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": cache_control, **headers},
        filename=None if inline else host_path.name,
    )


def _content_type(host_path: Path) -> str:
    """Type the file from its own name on disk, so every route types it identically."""
    return detect_content_type(host_path.name) or _DOWNLOAD_OCTET


def sandboxed_file_response(host_path: Path, *, cache_control: str) -> FileResponse:
    """Serve an owner's session file: known-safe types inline, active content sandboxed."""
    content_type = _content_type(host_path)
    return _file_response(
        host_path,
        content_type,
        inline=content_type in _SAFE_INLINE_TYPES,
        cache_control=cache_control,
        headers=_SANDBOX_CSP if content_type in _ACTIVE_CONTENT_TYPES else {},
    )
