"""Serve an agent-written file over HTTP without letting it run on our origin.

Agent-generated artifacts are untrusted content served from the API origin,
which holds the session cookie. Every route that streams one (the owner's
session-file endpoints and the public heygaia.link file route) goes through
sandboxed_file_response so the stored-XSS fence lives in one place.
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
# Known-safe types rendered inline via the served URL; everything else is
# force-downloaded so a direct/shared link can't execute on the API origin.
# HTML is deliberately absent: its preview renders in a sandboxed srcDoc iframe.
_SAFE_INLINE_TYPES = (
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/pdf",
)


def sandboxed_file_response(host_path: Path, *, filename: str, cache_control: str) -> FileResponse:
    """FileResponse with content-type, sandboxing + cache headers.

    FileResponse natively handles Range / 206 / Accept-Ranges.
    """
    content_type = detect_content_type(filename) or _DOWNLOAD_OCTET
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": cache_control}
    if content_type in _ACTIVE_CONTENT_TYPES:
        # Agent-generated HTML/SVG/XML is untrusted — neuter scripts/same-origin.
        headers["Content-Security-Policy"] = "sandbox"
    # Force download for anything not a known-safe inline type so a shared link
    # can't execute JS on the API origin. filename= emits an RFC-encoded
    # Content-Disposition, so a quoted/CR-LF filename can't inject the header.
    force_download = content_type not in _SAFE_INLINE_TYPES
    return FileResponse(
        path=str(host_path),
        media_type=content_type,
        headers=headers,
        filename=filename if force_download else None,
    )
