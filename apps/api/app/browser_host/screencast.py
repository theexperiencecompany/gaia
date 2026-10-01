"""Authenticated screencast and input for a session's focused page.

WS /live/{session_id} is the backend of the live view the user watches (and,
during a handoff, drives). It attaches to the page the agent last brought to the
front, streams JPEG frames out as {"type":"frame", data, url, title}, and turns
inbound {"type":"mouse"|"key"|"resize"} messages into CDP input. When the agent
moves to another tab, or the streamed one closes, it follows; when no page is
left it ends. Obscura screencasts only the session that caused the repaint, so
on Obscura a paced capture fills the gaps while the stream is quiet.

The session's one engine connection is the host's CdpMux, shared with the
control path and the proxy: this viewer borrows it, owns the page session it
attaches so its frames reach nobody else, and must never close it. Acks and
input dispatch are scheduled as tasks, not awaited inline: an event arrives in
the mux's one read loop, so awaiting a round trip there deadlocks it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
import contextlib
from dataclasses import dataclass, field
import json
from typing import TYPE_CHECKING, Any

from app.browser_host.cdp_mux import (
    CdpCommandError,
    CdpConnectionClosed,
    CdpFrame,
    CdpMux,
    CDPTimeoutError,
    cdp_attach,
    cdp_call,
    cdp_detach,
)
from app.browser_host.pumps import pump_until_first_close
from app.config.browser_host_settings import browser_host_settings
from app.constants.browser import (
    BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS,
    BROWSER_VIEWPORT_HEIGHT,
    BROWSER_VIEWPORT_WIDTH,
    BrowserEngine,
)
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

if TYPE_CHECKING:
    from fastapi import WebSocket

    from app.browser_host.chromium import ChromiumHost, HostSession

# JPEG, not PNG: a live view is judged on smoothness, and a PNG frame is ~8-10x
# larger (and slower to encode and decode), which is what makes the stream lag.
_SCREENCAST_FORMAT = "jpeg"
_SCREENCAST_QUALITY = 72
# Bounded so a slow viewer drops stale frames instead of stalling the engine (every frame is acked).
_FRAME_QUEUE_SIZE = 2
# Obscura screencasts only the session that drove the repaint. 2/s at ~33 KB a
# capture is an eighth of a live screencast's ~0.5 MB/s and still reads as live.
_PULL_INTERVAL_SECONDS = 0.5

_MOUSE_FIELDS = ("x", "y", "button", "buttons", "clickCount", "deltaX", "deltaY", "modifiers")
_KEY_FIELDS = (
    "key",
    "code",
    "text",
    "unmodifiedText",
    "windowsVirtualKeyCode",
    "nativeVirtualKeyCode",
    "autoRepeat",
    "isKeypad",
    "location",
    "modifiers",
)

_SCREENCAST_FRAME_EVENT = "Page.screencastFrame"
_FRAME_NAVIGATED_EVENT = "Page.frameNavigated"
_DETACHED_EVENT = "Target.detachedFromTarget"

_EventHandler = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class _PageMeta:
    """Latest url/title/favicon of the streamed page, refreshed on navigation."""

    url: str | None = None
    title: str | None = None
    favicon: str | None = None


class _Frame:
    """One screencast frame plus the page-CSS size it was captured at."""

    __slots__ = ("css_height", "css_width", "data")

    def __init__(self, data: str, css_width: int | None, css_height: int | None) -> None:
        self.data = data
        self.css_width = css_width
        self.css_height = css_height


@dataclass(slots=True)
class _Stream:
    """One attach of the live view to one page: its session, meta and latest frame."""

    target_id: str
    page_session: str
    meta: _PageMeta = field(default_factory=_PageMeta)
    latest: _Frame | None = None
    # Set when the engine lets go of the page (it closed), so the view moves on.
    detached: asyncio.Event = field(default_factory=asyncio.Event)
    # Set when this stream ended to follow another page rather than for the viewer leaving.
    retargeted: bool = False


async def run_live_view(host: ChromiumHost, session: HostSession, client_ws: WebSocket) -> None:
    """Stream the session's focused page to a live-view client and apply its input."""
    mux = session.mux
    frames: asyncio.Queue[_Frame] = asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE)
    background: set[asyncio.Task[Any]] = set()
    try:
        while not mux.closed:
            # Taken before the page is chosen, so a move while attaching still retargets.
            focus_moved = session.focus_moved
            target_id = await host.focused_target_id(session)
            if target_id is None:
                break
            stream = await _open_stream(mux, target_id, frames, background)
            try:
                await _serve_stream(mux, client_ws, stream, frames, focus_moved)
            finally:
                await _close_stream(mux, stream)
            if not stream.retargeted:
                break
    finally:
        for task in background:
            task.cancel()
    log.set(browser={"session_id": session.session_id, "operation": "live_view_closed"})
    log.info(f"{LogTag.BROWSER} browser live view closed")


async def _open_stream(
    mux: CdpMux,
    target_id: str,
    frames: asyncio.Queue[_Frame],
    background: set[asyncio.Task[Any]],
) -> _Stream:
    """Attach to one page, owning its session, and start its screencast."""
    holder: list[_Stream] = []

    def sink(frame: CdpFrame) -> None:
        # Events can arrive before the attach returns; none of them are frames yet.
        if holder:
            _route_event(mux, holder[0], frames, background, frame)

    page_session = await cdp_attach(
        mux, target_id, sink, timeout=BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS
    )
    stream = _Stream(target_id=target_id, page_session=page_session)
    holder.append(stream)
    await cdp_call(mux, "Page.enable", session_id=page_session)
    await _refresh_meta(mux, stream)
    # Capped at the agent viewport, so frames are 1:1 with the page and takeover input maps exactly.
    await _start_screencast(mux, page_session, BROWSER_VIEWPORT_WIDTH, BROWSER_VIEWPORT_HEIGHT)
    return stream


async def _serve_stream(
    mux: CdpMux,
    client_ws: WebSocket,
    stream: _Stream,
    frames: asyncio.Queue[_Frame],
    focus_moved: asyncio.Event,
) -> None:
    directions = [
        _send_frames(client_ws, frames, stream.meta),
        _apply_input(mux, client_ws, stream.page_session),
        mux.wait_closed(),
        _follow_focus(stream, focus_moved),
    ]
    if browser_host_settings.BROWSER_ENGINE is BrowserEngine.OBSCURA:
        directions.append(_pull_frames(mux, stream, frames))
    await pump_until_first_close(*directions, sockets=(client_ws,))


async def _follow_focus(stream: _Stream, focus_moved: asyncio.Event) -> None:
    """Return, marking the stream retargeted, once the agent moves tabs or the page closes."""
    waits = [
        asyncio.ensure_future(focus_moved.wait()),
        asyncio.ensure_future(stream.detached.wait()),
    ]
    try:
        await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for wait in waits:
            wait.cancel()
    stream.retargeted = True


async def _close_stream(mux: CdpMux, stream: _Stream) -> None:
    """Stop the page's screencast and let go of it, unless the page or the connection is already gone."""
    if mux.closed or stream.detached.is_set():
        return
    try:
        await cdp_call(
            mux,
            "Page.stopScreencast",
            session_id=stream.page_session,
            timeout=BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS,
        )
        await cdp_detach(mux, stream.page_session, timeout=BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS)
    except (CDPTimeoutError, CdpCommandError, CdpConnectionClosed) as exc:
        # The page is closing under us or the engine is wedged; the session's own teardown frees it.
        log.warning(
            f"{LogTag.BROWSER} browser live view left its page attached",
            error_type=type(exc).__name__,
        )


def _route_event(
    mux: CdpMux,
    stream: _Stream,
    frames: asyncio.Queue[_Frame],
    background: set[asyncio.Task[Any]],
    frame: CdpFrame,
) -> None:
    """Handle one event on the viewer's own page session, never blocking the read loop."""
    method = frame.get("method")
    params: dict[str, Any] = frame.get("params") or {}
    if method == _SCREENCAST_FRAME_EVENT:
        _on_screencast_frame(mux, stream, frames, background, params)
    elif method == _FRAME_NAVIGATED_EVENT and params.get("frame", {}).get("parentId") is None:
        _spawn(background, _refresh_meta(mux, stream))
    elif method == _DETACHED_EVENT:
        stream.detached.set()


def _on_screencast_frame(
    mux: CdpMux,
    stream: _Stream,
    frames: asyncio.Queue[_Frame],
    background: set[asyncio.Task[Any]],
    params: dict[str, Any],
) -> None:
    _spawn(
        background,
        cdp_call(
            mux,
            "Page.screencastFrameAck",
            {"sessionId": params["sessionId"]},
            session_id=stream.page_session,
        ),
    )
    # deviceWidth/Height are the page's CSS size, the space Input.dispatchMouseEvent
    # expects; the bitmap may be downscaled, so viewers scale their pointer math by them.
    frame_meta: dict[str, Any] = params.get("metadata") or {}
    frame = _Frame(params["data"], frame_meta.get("deviceWidth"), frame_meta.get("deviceHeight"))
    stream.latest = frame
    # A viewer that is behind drops this frame and catches the next; the engine was acked.
    with contextlib.suppress(asyncio.QueueFull):
        frames.put_nowait(frame)


def _spawn(background: set[asyncio.Task[Any]], coro: Coroutine[object, object, object]) -> None:
    task = asyncio.ensure_future(coro)
    background.add(task)
    task.add_done_callback(background.discard)


# The icon the PAGE declares, resolved absolute, preferring the largest declared
# size; falls back to /favicon.ico, as a browser does when nothing is declared.
_FAVICON_JS = """(() => {
  const links = [...document.querySelectorAll('link[rel~="icon" i]')];
  const score = (l) => {
    const s = (l.getAttribute('sizes') || '').match(/\\d+/);
    return s ? parseInt(s[0], 10) : 0;
  };
  const best = links.sort((a, b) => score(b) - score(a))[0];
  const href = best && best.getAttribute('href');
  try {
    return new URL(href || '/favicon.ico', document.baseURI).href;
  } catch (e) {
    return null;
  }
})()"""


async def _read_favicon(mux: CdpMux, page_session: str) -> str | None:
    """Return the page's own favicon URL, or None when it cannot be read.

    A favicon is decoration, so a page that blocks evaluation (or is
    mid-navigation) must not break the metadata the tab actually needs.
    """
    try:
        result = await cdp_call(
            mux,
            "Runtime.evaluate",
            {"expression": _FAVICON_JS, "returnByValue": True},
            session_id=page_session,
        )
    except (CDPTimeoutError, CdpCommandError) as exc:
        log.warning(f"{LogTag.BROWSER} Could not read page favicon", error_type=type(exc).__name__)
        return None
    value = result.get("result", {}).get("value")
    return value if isinstance(value, str) else None


async def _refresh_meta(mux: CdpMux, stream: _Stream) -> None:
    """Reload the tab metadata from the target."""
    info = await cdp_call(mux, "Target.getTargetInfo", {"targetId": stream.target_id})
    target_info = info.get("targetInfo", {})
    stream.meta.url = target_info.get("url")
    stream.meta.title = target_info.get("title")
    stream.meta.favicon = await _read_favicon(mux, stream.page_session)


def _image_params() -> dict[str, Any]:
    """Return the encoding the screencast and a pulled capture share."""
    params: dict[str, Any] = {"format": _SCREENCAST_FORMAT}
    if _SCREENCAST_FORMAT == "jpeg":
        params["quality"] = _SCREENCAST_QUALITY
    return params


async def _start_screencast(
    mux: CdpMux, page_session: str, max_width: int, max_height: int
) -> None:
    params = _image_params()
    params["maxWidth"] = max_width
    params["maxHeight"] = max_height
    await cdp_call(mux, "Page.startScreencast", params, session_id=page_session)


async def _pull_frames(mux: CdpMux, stream: _Stream, frames: asyncio.Queue[_Frame]) -> None:
    """Capture the page on a timer for as long as the screencast stays quiet (Obscura only)."""
    failures = 0
    seen: _Frame | None = None
    while True:
        await asyncio.sleep(_PULL_INTERVAL_SECONDS)
        latest = stream.latest
        if latest is not seen:
            seen = latest
            failures = 0
            continue
        try:
            # frameNavigated reaches only the session that navigated on Obscura, so a
            # changed url is the viewer's one sign its meta belongs to a page that is gone.
            await _refresh_meta(mux, stream)
            result = await cdp_call(
                mux, "Page.captureScreenshot", _image_params(), session_id=stream.page_session
            )
        except (CDPTimeoutError, CdpCommandError) as exc:
            # A page mid-navigation refuses one capture; one line per streak keeps a
            # persistent failure visible without flooding at 2/s.
            failures += 1
            if failures == 1:
                log.warning(
                    f"{LogTag.BROWSER} Could not pull a live-view frame",
                    error_type=type(exc).__name__,
                )
            continue
        failures = 0
        # Same page at the same viewport: it carries the CSS size the screencast last reported.
        css_width = latest.css_width if latest is not None else None
        css_height = latest.css_height if latest is not None else None
        with contextlib.suppress(asyncio.QueueFull):
            frames.put_nowait(_Frame(result["data"], css_width, css_height))


async def _send_frames(
    client_ws: WebSocket, frames: asyncio.Queue[_Frame], meta: _PageMeta
) -> None:
    while True:
        frame = await frames.get()
        await client_ws.send_text(
            json.dumps(
                {
                    "type": "frame",
                    "data": frame.data,
                    "format": _SCREENCAST_FORMAT,
                    "url": meta.url,
                    "title": meta.title,
                    "favicon": meta.favicon,
                    "cssWidth": frame.css_width,
                    "cssHeight": frame.css_height,
                }
            )
        )


async def _apply_input(mux: CdpMux, client_ws: WebSocket, page_session: str) -> None:
    while True:
        message: dict[str, Any] = json.loads(await client_ws.receive_text())
        kind = message.get("type")
        if kind == "mouse":
            await cdp_call(
                mux,
                "Input.dispatchMouseEvent",
                _mouse_params(message),
                session_id=page_session,
            )
        elif kind == "key":
            await cdp_call(
                mux,
                "Input.dispatchKeyEvent",
                _key_params(message),
                session_id=page_session,
            )
        elif kind == "resize":
            await _start_screencast(
                mux,
                page_session,
                int(message.get("width", BROWSER_VIEWPORT_WIDTH)),
                int(message.get("height", BROWSER_VIEWPORT_HEIGHT)),
            )


def _mouse_params(message: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"type": message["event"]}
    for field_name in _MOUSE_FIELDS:
        if field_name in message:
            params[field_name] = message[field_name]
    return params


def _key_params(message: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"type": message["event"]}
    for field_name in _KEY_FIELDS:
        if field_name in message:
            params[field_name] = message[field_name]
    return params
