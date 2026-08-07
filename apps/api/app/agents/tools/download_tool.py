"""`download` — pull a file off a public URL into the workspace for the agent to read.

The general form of the workspace-as-I/O-surface pattern: anything the model needs
to look at becomes a file, and `read` is the one lens onto it. This runs host-side
(straight to JuiceFS, no sandbox spin-up) and hands the SSRF + size guarding to
`url_download`; per-lane image delivery is `read`'s job downstream.
"""

from typing import Annotated
from urllib.parse import urlparse

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.coding._context import get_session_id, get_user_id
from app.agents.workspace.paths import session_download_relpath
from app.constants.download import DOWNLOAD_HTML_REJECTED, HTML_CONTENT_TYPES
from app.constants.log_tags import LogTag
from app.decorators import with_doc, with_rate_limiting
from app.services.storage import write_session_file
from app.templates.docstrings.download_tool_docs import DOWNLOAD_TOOL
from app.utils.url_download import (
    DownloadError,
    download_filename,
    download_public_url,
    extension_from_content_type,
    extension_from_url,
)
from shared.py.wide_events import log


@tool
@with_rate_limiting("download")
@with_doc(DOWNLOAD_TOOL)
async def download(
    config: RunnableConfig,
    url: Annotated[str, "Direct, public http(s) URL of the file to download"],
) -> str:
    """Download a file from a URL into the session workspace; return its path."""
    log.set(tool={"name": "download", "action": "download"})

    try:
        user_id = get_user_id(config)
    except ValueError as e:
        return f"Error: {e}"
    session_id = get_session_id(config)
    if not session_id:
        return "Error: download requires a conversation-scoped run"

    if not urlparse(url).scheme:
        url = f"https://{url}"

    # Always refetch. The on-disk name is knowable from the URL alone, so an
    # existing file could be returned without hitting the network — but nothing
    # invalidates it, so "download it again, it changed" would hand the agent the
    # stale bytes with no way to ask for the current ones.
    try:
        result = await download_public_url(url)
    except DownloadError as e:
        return f"Error: {e}"

    if result.content_type in HTML_CONTENT_TYPES:
        return DOWNLOAD_HTML_REJECTED.format(content_type=result.content_type)

    ext = extension_from_url(url) or extension_from_content_type(result.content_type)
    rel = session_download_relpath(download_filename(url, ext))
    _, sandbox_path = await write_session_file(
        user_id=user_id,
        conversation_id=session_id,
        relative_path=rel,
        content=result.data,
    )
    log.set(download={"bytes": len(result.data), "content_type": result.content_type})
    log.info(f"{LogTag.TOOL} Downloaded a file into the workspace")
    return sandbox_path


tools = [download]
