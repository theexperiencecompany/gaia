"""Authenticated screencast and input for a session's focused page.

WS /live/{session_id} is the backend of the live view the user watches (and,
during a handoff, drives). It attaches to the context's focused page, streams
JPEG frames out as {"type":"frame", data, url, title}, and turns inbound
{"type":"mouse"|"key"|"resize"} messages into CDP input. Obscura screencasts
only the session that caused the repaint, so a paced capture fills the gaps
when the stream goes quiet; both feed one queue and one sender.

The session's one engine connection is the host's CdpMux, shared with the
control path and the proxy: this viewer borrows it, claims the page session it
attaches so its frames reach nobody else, and must never close it. Acks and
input dispatch are scheduled as tasks, not awaited inline: an event arrives in
the mux's one read loop, so awaiting a round trip there deadlocks it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
from dataclasses import dataclass
import json
from typing import TYPE_CHECKING, Any

from app.browser_host.cdp_mux import CdpFrame, CdpMux
from app.browser_host.chromium import cdp_call
from app.browser_host.pumps import pump_until_first_close
from app.constants.browser import BROWSER_VIEWPORT_HEIGHT, BROWSER_VIEWPORT_WIDTH
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

if TYPE_CHECKING:
    from fastapi import WebSocket

    from app.browser_host.chromium import ChromiumHost, HostSession

# JPEG, not PNG: a live view is judged on smoothness, and a PNG frame is ~8-10x
# larger than JPEG (and slower to encode in Chromium + decode in the browser),
# which is what makes the stream lag. ``_SCREENCAST_QUALITY`` applies only to "jpeg".
_SCREENCAST_FORMAT = "jpeg"
_SCREENCAST_QUALITY = 72
# Bounded so a slow viewer applies backpressure by dropping stale frames, not by
# stalling Chromium (we ack every frame regardless).
_FRAME_QUEUE_SIZE = 2
# Fallback cadence when the engine screencasts only the session that drove the
# repaint. 2/s at ~33 KB a capture is ~66 KB/s, an eighth of the ~0.5 MB/s a live
# screencast costs, and still reads as live where 1 s apart reads as a stalled tab.
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

_EventHandler = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class _PageMeta:
    """Latest url/title/favicon of the streamed page, refreshed on navigation."""

    url: str | None = None
    title: str | None = None
    favicon: str | None = None


class _StreamState:
    """The latest frame the screencast delivered, written only by the frame handler.

    The pull keeps its own mark of the frame it last saw rather than clearing a
    shared flag, so a quiet stream is simply "the latest frame has not changed".
    """

    __slots__ = ("latest",)

    def __init__(self) -> None:
        self.latest: _Frame | None = None


class _Frame:
    """One screencast frame plus the page-CSS size it was captured at."""

    __slots__ = ("css_height", "css_width", "data")

    def __init__(self, data: str, css_width: int | None, css_height: int | None) -> None:
        self.data = data
        self.css_width = css_width
        self.css_height = css_height


async def run_live_view(host: ChromiumHost, session: HostSession, client_ws: WebSocket) -> None:
    """Stream the session's focused page to a live-view client and apply its input."""
    # add_viewer sits immediately before the try so entering the block guarantees
    # the finally: an un-removed viewer shields the session from the idle reaper
    # forever. Every CDP call below is bounded for the same reason.
    background: set[asyncio.Task[Any]] = set()
    mux = session.mux
    unsubscribe: Callable[[], None] | None = None
    host.add_viewer(session.session_id)
    try:
        target_id = await host.focused_target_id(session.session_id)
        attached = await cdp_call(
            mux, "Target.attachToTarget", {"targetId": target_id, "flatten": True}
        )
        page_session: str = attached["sessionId"]
        await cdp_call(mux, "Page.enable", session_id=page_session)

        meta = _PageMeta()
        await _refresh_meta(mux, target_id, meta, page_session)
        frames: asyncio.Queue[_Frame] = asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE)
        stream = _StreamState()

        unsubscribe = mux.subscribe(
            _make_event_sink(
                _make_frame_handler(mux, page_session, frames, background, stream),
                _make_nav_handler(mux, target_id, meta, background, page_session),
            ),
            owns_session=page_session,
        )

        # Capped at the agent viewport, so frames are 1:1 with the page and takeover
        # input maps exactly; 1280-wide q72 frames (~7 KB, ~0.5 MB/s) stay smooth.
        await _start_screencast(mux, page_session, BROWSER_VIEWPORT_WIDTH, BROWSER_VIEWPORT_HEIGHT)

        await pump_until_first_close(
            _send_frames(client_ws, frames, meta),
            _apply_input(host, session, mux, client_ws, page_session),
            _pull_frames(mux, page_session, target_id, meta, frames, stream),
            mux.wait_closed(),
        )
    finally:
        # The mux belongs to the session, not to this viewer: closing it here would
        # kill the browser task and every other consumer of the same connection.
        if unsubscribe is not None:
            unsubscribe()
        for task in background:
            task.cancel()
        host.remove_viewer(session.session_id)
    log.set(browser={"session_id": session.session_id, "operation": "live_view_closed"})
    log.info(f"{LogTag.BROWSER} browser live view closed")


def _make_event_sink(on_frame: _EventHandler, on_nav: _EventHandler) -> Callable[[CdpFrame], None]:
    """Route this viewer's page events to its handlers, ignoring the rest of the stream."""
    handlers: dict[str, _EventHandler] = {
        _SCREENCAST_FRAME_EVENT: on_frame,
        _FRAME_NAVIGATED_EVENT: on_nav,
    }

    def sink(frame: CdpFrame) -> None:
        handler = handlers.get(frame.get("method"))
        if handler is not None:
            handler(frame.get("params", {}))

    return sink


def _make_frame_handler(
    mux: CdpMux,
    page_session: str,
    frames: asyncio.Queue[_Frame],
    background: set[asyncio.Task[Any]],
    stream: _StreamState,
) -> _EventHandler:
    """Build the screencastFrame handler: ack out of band, enqueue, never block the read loop."""

    def on_frame(params: dict[str, Any]) -> None:
        ack = asyncio.ensure_future(
            cdp_call(
                mux,
                "Page.screencastFrameAck",
                {"sessionId": params["sessionId"]},
                session_id=page_session,
            )
        )
        background.add(ack)
        ack.add_done_callback(background.discard)
        # deviceWidth/Height are the page's CSS pixel size — the coordinate space
        # Input.dispatchMouseEvent expects — which differs from the (possibly
        # downscaled) frame bitmap. Viewers scale their pointer math with these.
        frame_meta: dict[str, Any] = params.get("metadata") or {}
        frame = _Frame(
            params["data"],
            frame_meta.get("deviceWidth"),
            frame_meta.get("deviceHeight"),
        )
        stream.latest = frame
        # Drop the frame when the viewer is behind — we still ack Chromium above,
        # so the stream keeps flowing and the viewer catches the next frame.
        with contextlib.suppress(asyncio.QueueFull):
            frames.put_nowait(frame)

    return on_frame


def _make_nav_handler(
    mux: CdpMux,
    target_id: str,
    meta: _PageMeta,
    background: set[asyncio.Task[Any]],
    page_session: str,
) -> _EventHandler:
    """Build the frameNavigated handler: refresh the page meta off the read loop."""

    def on_nav(params: dict[str, Any]) -> None:
        frame = params.get("frame", {})
        if frame.get("parentId") is None:
            refresh = asyncio.ensure_future(_refresh_meta(mux, target_id, meta, page_session))
            background.add(refresh)
            refresh.add_done_callback(background.discard)

    return on_nav


# The icon the PAGE declares, resolved absolute, preferring the largest declared
# size — this is what the user's own browser shows in its tab. Falls back to
# /favicon.ico, which is what a browser does when nothing is declared.
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

    Best-effort: a favicon is decoration, so a page that blocks evaluation (or
    is mid-navigation) must not break the metadata the tab actually needs.
    """
    try:
        result = await cdp_call(
            mux,
            "Runtime.evaluate",
            {"expression": _FAVICON_JS, "returnByValue": True},
            session_id=page_session,
        )
    except Exception as exc:
        # A favicon is decoration — a page that blocks evaluation or is mid-navigation
        # must not break the tab's real metadata. Logged so a persistent failure shows up.
        log.warning(
            f"{LogTag.BROWSER} Could not read page favicon",
            error_type=type(exc).__name__,
        )
        return None
    value = result.get("result", {}).get("value")
    return value if isinstance(value, str) else None


async def _refresh_meta(
    mux: CdpMux, target_id: str, meta: _PageMeta, page_session: str | None = None
) -> bool:
    """Reload the tab metadata from the target; returns whether the url changed."""
    info = await cdp_call(mux, "Target.getTargetInfo", {"targetId": target_id})
    target_info = info.get("targetInfo", {})
    previous_url = meta.url
    meta.url = target_info.get("url")
    meta.title = target_info.get("title")
    if page_session:
        meta.favicon = await _read_favicon(mux, page_session)
    return meta.url != previous_url


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


async def _pull_frames(
    mux: CdpMux,
    page_session: str,
    target_id: str,
    meta: _PageMeta,
    frames: asyncio.Queue[_Frame],
    stream: _StreamState,
) -> None:
    """Capture the page on a timer for as long as the screencast stays quiet."""
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
            result = await _capture_page(mux, page_session, target_id, meta)
        except Exception as exc:
            # Same posture as _read_favicon: a pull is the fallback, so a page
            # mid-navigation or one refused call must not end the viewer. One line
            # per streak keeps a persistent failure visible without flooding at 2/s.
            failures += 1
            if failures == 1:
                log.warning(
                    f"{LogTag.BROWSER} Could not pull a live-view frame",
                    error_type=type(exc).__name__,
                )
            continue
        failures = 0
        # A capture is the same page at the same viewport, so it carries the CSS
        # size the screencast last reported; none yet leaves the viewer on the bitmap.
        css_width = latest.css_width if latest is not None else None
        css_height = latest.css_height if latest is not None else None
        # Same drop-when-behind rule as a screencast frame: a stale capture is
        # worth less to the viewer than the next one.
        with contextlib.suppress(asyncio.QueueFull):
            frames.put_nowait(_Frame(result["data"], css_width, css_height))


async def _capture_page(
    mux: CdpMux, page_session: str, target_id: str, meta: _PageMeta
) -> dict[str, Any]:
    """Refresh the tab metadata off the target, then capture the page itself."""
    if await _refresh_meta(mux, target_id, meta):
        # frameNavigated reaches only the session that navigated, so on an engine
        # that isolates them a changed url is the viewer's one sign that the icon
        # it is showing belongs to a page that is gone.
        meta.favicon = await _read_favicon(mux, page_session)
    return await cdp_call(mux, "Page.captureScreenshot", _image_params(), session_id=page_session)


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


async def _apply_input(
    host: ChromiumHost,
    session: HostSession,
    mux: CdpMux,
    client_ws: WebSocket,
    page_session: str,
) -> None:
    while True:
        message: dict[str, Any] = json.loads(await client_ws.receive_text())
        host.touch(session.session_id)
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
    for field in _MOUSE_FIELDS:
        if field in message:
            params[field] = message[field]
    return params


def _key_params(message: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"type": message["event"]}
    for field in _KEY_FIELDS:
        if field in message:
            params[field] = message[field]
    return params
