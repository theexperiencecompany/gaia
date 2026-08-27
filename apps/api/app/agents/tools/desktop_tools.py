"""Tools executed on the user's computer through the desktop bridge.

Each tool relays its action over :mod:`app.services.desktop.bridge` to the
GAIA Electron app and awaits the result. They only surface (and only run) for
conversations originating from the desktop client.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.agents.tools.coding._context import get_session_id, get_user_id
from app.agents.workspace.paths import session_screenshot_relpath
from app.constants.log_tags import LogTag
from app.decorators import with_doc
from app.models.agent_models import agent_configurable
from app.models.chat_models import ConversationSource
from app.services.desktop.bridge import DesktopToolOutcome, request_desktop_action
from app.services.storage import write_session_file
from app.templates.docstrings.desktop_tool_docs import (
    LIST_WINDOWS,
    OPEN_APP,
    OPEN_URL,
    READ_CLIPBOARD,
    TAKE_SCREENSHOT,
    WRITE_CLIPBOARD,
)
from app.utils.image_codec import ImageCodec, InlineImage, InvalidImageError
from app.utils.multimodal import text_content_block
from shared.py.wide_events import log

_NOT_DESKTOP_ERROR = (
    "Desktop tools are only available when chatting from the GAIA desktop app. "
    "This conversation did not originate there, so this action cannot run."
)
_MISSING_CONTEXT_ERROR = "Desktop tool failed: no active stream context."


async def _run_desktop_action(
    config: RunnableConfig,
    tool_name: str,
    params: dict[str, Any] | None = None,
) -> DesktopToolOutcome | str:
    """Validate the run context and execute one action on the desktop.

    Returns an error string (for the LLM) when the conversation is not a
    desktop session or the stream context is missing.
    """
    configurable = agent_configurable(config)
    source = ConversationSource.coerce(configurable.get("conversation_source"))
    if source is not ConversationSource.DESKTOP:
        log.warning(
            f"{LogTag.TOOL} Desktop tool refused for source", tool_name=tool_name, source=source
        )
        return _NOT_DESKTOP_ERROR

    stream_id = configurable.get("stream_id")
    user_id = configurable.get("user_id")
    if not stream_id or not user_id:
        log.warning(
            f"{LogTag.TOOL} Desktop tool missing stream_id/user_id in config", tool_name=tool_name
        )
        return _MISSING_CONTEXT_ERROR

    return await request_desktop_action(
        stream_id=stream_id,
        user_id=user_id,
        tool=tool_name,
        params=params,
    )


def _emit_tool_data(tool_name: str, data: dict[str, Any]) -> None:
    """Stream a unified tool_data entry so the chat UI renders a card."""
    writer = get_stream_writer()
    writer(
        {
            "tool_data": {
                "tool_name": tool_name,
                "data": data,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        }
    )


async def _save_screenshot(config: RunnableConfig, image: InlineImage) -> str:
    """Persist a capture to the session workspace; return its `/workspace` path.

    A screenshot is inline media like any other, so it is evicted from context
    once newer images push past MAX_INLINE_MEDIA_BLOCKS. Writing it to the
    workspace is what makes that eviction recoverable — the agent `read`s the
    path back. The bytes stored are the ones the model was shown (post-ImageCodec),
    so a re-read round-trips instead of re-transcoding.
    """
    session_id = get_session_id(config)
    if not session_id:
        raise ValueError("take_screenshot requires a conversation-scoped run")
    filename = f"screenshot-{datetime.now(UTC):%Y%m%dT%H%M%S%f}{image.extension}"
    _, sandbox_path = await write_session_file(
        user_id=get_user_id(config),
        conversation_id=session_id,
        relative_path=session_screenshot_relpath(filename),
        content=image.data,
    )
    return sandbox_path


@tool
@with_doc(TAKE_SCREENSHOT)
async def take_screenshot(
    config: RunnableConfig,
    query: Annotated[str, "What to look for or describe on the screen"],
) -> str | list[dict[str, Any]]:
    writer = get_stream_writer()
    writer({"progress": "Looking at your screen..."})

    outcome = await _run_desktop_action(config, "screenshot")
    if isinstance(outcome, str):
        return outcome
    if not outcome.ok or not outcome.data:
        return f"Could not capture the screen: {outcome.error or 'unknown error'}"

    image_b64 = outcome.data.get("image_b64")
    if not image_b64:
        return "Could not capture the screen: the desktop app returned no image."

    thumbnail_b64 = outcome.data.get("thumbnail_b64")
    if thumbnail_b64:
        _emit_tool_data(
            "screenshot_data",
            {
                "thumbnail": f"data:image/jpeg;base64,{thumbnail_b64}",
                "width": outcome.data.get("width"),
                "height": outcome.data.get("height"),
            },
        )

    try:
        image = await ImageCodec.from_base64(image_b64)
    except InvalidImageError as e:
        return f"Could not read the captured screen: {e}"

    # Persisting the capture is best-effort: the pixels are already captured and
    # shown to the user, so a workspace write failure (no session, or storage I/O)
    # must not discard an otherwise-valid screenshot — it only costs the ability to
    # `read` the path back later.
    try:
        path = await _save_screenshot(config, image)
        location_note = f"saved to {path}, read that path to look at it again later"
    except Exception:
        log.exception(f"{LogTag.TOOL} Failed to persist screenshot to the workspace")
        location_note = (
            "not saved to the workspace, so it cannot be re-read later, answer from it now"
        )

    # The pixels go to the model as-is. A lane that cannot see them gets a text
    # description attached at execution time (MediaDescriptionMiddleware), which
    # reads the query below as its context — same treatment as every other tool
    # that returns media.
    return [
        text_content_block(
            f"Screenshot of the user's screen, {location_note}. Looking for: {query}\n\n"
            "The screenshot is already shown to the user; answer their request from "
            "it rather than describing it back to them verbatim."
        ),
        image.to_block(),
    ]


@tool
@with_doc(READ_CLIPBOARD)
async def read_clipboard(config: RunnableConfig) -> str:
    outcome = await _run_desktop_action(config, "read_clipboard")
    if isinstance(outcome, str):
        return outcome
    if not outcome.ok:
        return f"Could not read the clipboard: {outcome.error or 'unknown error'}"

    text = (outcome.data or {}).get("text", "")
    if not text:
        return "The clipboard is empty (or contains non-text content)."
    return f"Clipboard contents:\n{text}"


@tool
@with_doc(WRITE_CLIPBOARD)
async def write_clipboard(
    config: RunnableConfig,
    text: Annotated[str, "The exact text to place on the clipboard"],
) -> str:
    outcome = await _run_desktop_action(config, "write_clipboard", {"text": text})
    if isinstance(outcome, str):
        return outcome
    if not outcome.ok:
        return f"Could not write to the clipboard: {outcome.error or 'unknown error'}"
    return "Copied to the user's clipboard."


@tool
@with_doc(OPEN_APP)
async def open_app(
    config: RunnableConfig,
    app_name: Annotated[str, "The application's name, e.g. 'Safari' or 'Notes'"],
) -> str:
    outcome = await _run_desktop_action(config, "open_app", {"app_name": app_name})
    if isinstance(outcome, str):
        return outcome
    if not outcome.ok:
        return f"Could not open '{app_name}': {outcome.error or 'unknown error'}"
    return f"Opened {app_name} on the user's computer."


@tool
@with_doc(OPEN_URL)
async def open_url(
    config: RunnableConfig,
    url: Annotated[str, "The full http(s) URL to open in the default browser"],
) -> str:
    outcome = await _run_desktop_action(config, "open_url", {"url": url})
    if isinstance(outcome, str):
        return outcome
    if not outcome.ok:
        return f"Could not open the URL: {outcome.error or 'unknown error'}"
    return f"Opened {url} in the user's default browser."


@tool
@with_doc(LIST_WINDOWS)
async def list_windows(config: RunnableConfig) -> str:
    outcome = await _run_desktop_action(config, "list_windows")
    if isinstance(outcome, str):
        return outcome
    if not outcome.ok:
        return f"Could not list windows: {outcome.error or 'unknown error'}"

    windows = (outcome.data or {}).get("windows", [])
    if not windows:
        return "No open windows were reported."
    lines = [
        f"- {window.get('app', 'Unknown app')}: {window.get('title') or '(untitled)'}"
        for window in windows
    ]
    return "Open windows on the user's computer:\n" + "\n".join(lines)


tools = [
    take_screenshot,
    read_clipboard,
    write_clipboard,
    open_app,
    open_url,
    list_windows,
]
