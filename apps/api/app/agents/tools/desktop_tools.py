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

from app.agents.llm.client import ainvoke_llm, get_default_llm
from app.constants.log_tags import LogTag
from app.decorators import with_doc
from app.models.chat_models import ConversationSource
from app.services.desktop.bridge import DesktopToolOutcome, request_desktop_action
from app.templates.docstrings.desktop_tool_docs import (
    LIST_WINDOWS,
    OPEN_APP,
    OPEN_URL,
    READ_CLIPBOARD,
    TAKE_SCREENSHOT,
    WRITE_CLIPBOARD,
)
from shared.py.wide_events import log

_NOT_DESKTOP_ERROR = (
    "Desktop tools are only available when chatting from the GAIA desktop app. "
    "This conversation did not originate there, so this action cannot run."
)
_MISSING_CONTEXT_ERROR = "Desktop tool failed: no active stream context."

_SCREENSHOT_VISION_PROMPT = (
    "This is a screenshot of the user's computer screen. Describe what is visible "
    "in detail: the focused application, window titles, and any text, errors, or "
    "UI elements relevant to the request. Transcribe important text exactly.\n\n"
    "Focus on: {query}"
)


async def _run_desktop_action(
    config: RunnableConfig,
    tool_name: str,
    params: dict[str, Any] | None = None,
) -> DesktopToolOutcome | str:
    """Validate the run context and execute one action on the desktop.

    Returns an error string (for the LLM) when the conversation is not a
    desktop session or the stream context is missing.
    """
    configurable = config.get("configurable", {})
    source = ConversationSource.coerce(configurable.get("conversation_source"))
    if source is not ConversationSource.DESKTOP:
        log.warning(f"{LogTag.TOOL} Desktop tool '{tool_name}' refused for source '{source}'")
        return _NOT_DESKTOP_ERROR

    stream_id = configurable.get("stream_id")
    user_id = configurable.get("user_id")
    if not stream_id or not user_id:
        log.warning(f"{LogTag.TOOL} Desktop tool '{tool_name}' missing stream_id/user_id in config")
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


async def _describe_screenshot(image_b64: str, query: str) -> str | None:
    """Run a one-off vision call so any provider can 'see' the screen.

    Image blocks inside tool results are not portable across providers
    (OpenAI rejects them), so the screenshot is described here in a regular
    user-role message and the description is returned to the agent.

    The default model (Gemini) is multimodal, so the screenshot is described on
    it via ``ainvoke_llm``. Should the model reject the image (transient provider
    error), return ``None`` so the caller degrades gracefully instead of failing
    the whole tool.
    """
    try:
        response = await ainvoke_llm(
            get_default_llm(),
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _SCREENSHOT_VISION_PROMPT.format(query=query)},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                }
            ],
            label="desktop_vision",
        )
    except Exception as exc:  # noqa: BLE001 - any provider failure degrades gracefully
        log.warning(f"{LogTag.TOOL} Screenshot vision call failed: {exc}")
        return None
    content = getattr(response, "content", response)
    return content if isinstance(content, str) else str(content)


@tool
@with_doc(TAKE_SCREENSHOT)
async def take_screenshot(
    config: RunnableConfig,
    query: Annotated[str, "What to look for or describe on the screen"],
) -> str:
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

    description = await _describe_screenshot(image_b64, query)
    if description is None:
        return (
            "Captured the user's screen (already shown to them), but it could not "
            "be analyzed because no vision-capable model was available. Ask the "
            "user to describe what they see, or try again."
        )
    return (
        f"Screenshot of the user's screen (described for: {query}):\n\n{description}\n\n"
        "The screenshot itself is already shown to the user — do not describe it "
        "back verbatim; answer their request using this context."
    )


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
