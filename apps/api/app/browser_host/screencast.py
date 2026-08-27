"""Authenticated screencast + input for a session's focused page.

``WS /live/{session_id}`` is the backend of the live view the user watches (and,
during a handoff, drives). It attaches to the context's focused page, streams
JPEG frames out as ``{"type":"frame", data, url, title}``, and turns inbound
``{"type":"mouse"|"key"|"resize"}`` messages into CDP input.

CDP frame acks and input dispatch are scheduled as tasks rather than awaited
inline: the frame arrives inside ``cdp_use``'s single read loop, so awaiting a
CDP round-trip from within the frame handler would block the very loop that
resolves it — a deadlock. The handler enqueues and returns; a sender task drains
the queue to the client.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Any

from cdp_use.client import CDPClient

from app.browser_host.chromium import cdp_call
from app.browser_host.pumps import pump_until_first_close
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
# The stream cap equals the agent viewport (constants/browser.py), so frames are
# 1:1 with the page — pixel-crisp with no downscale blur, and takeover input maps
# exactly. A repainting page (scroll, video, animation) emits 70+ fps and the
# browser decodes every frame on its main thread; 1280-wide q72 frames (~7 KB,
# ~0.5 MB/s) stay smooth. Every frame also carries the page's CSS size (from the
# screencast metadata) so viewers translate pointer events into page coordinates
# instead of assuming frame pixels == CSS pixels.
_DEFAULT_MAX_WIDTH = 1280
_DEFAULT_MAX_HEIGHT = 800
# Bounded so a slow viewer applies backpressure by dropping stale frames, not by
# stalling Chromium (we ack every frame regardless).
_FRAME_QUEUE_SIZE = 2

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


class _PageMeta:
    """Latest url/title of the streamed page, refreshed on navigation."""

    def __init__(self) -> None:
        self.url: str | None = None
        self.title: str | None = None


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
    # the finally: the viewer protects the session from the idle reaper (which
    # skips viewer_count > 0), so an un-removed viewer would strand the session
    # forever — a permanent capacity leak that only a host restart clears. Every
    # CDP call below is bounded for the same reason: an unbounded await never
    # reaches the finally at all.
    background: set[asyncio.Task[Any]] = set()
    cdp = CDPClient(host.root_ws_url)
    host.add_viewer(session.session_id)
    try:
        await cdp.start()
        target_id = await host.focused_target_id(session.session_id)
        attached = await cdp_call(
            cdp, "Target.attachToTarget", {"targetId": target_id, "flatten": True}
        )
        page_session: str = attached["sessionId"]
        await cdp_call(cdp, "Page.enable", {}, session_id=page_session)

        meta = _PageMeta()
        await _refresh_meta(cdp, target_id, meta)
        frames: asyncio.Queue[_Frame] = asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE)

        _register_frame_handler(cdp, page_session, frames, background)
        _register_nav_handler(cdp, target_id, meta, background)

        await _start_screencast(cdp, page_session, _DEFAULT_MAX_WIDTH, _DEFAULT_MAX_HEIGHT)

        await pump_until_first_close(
            _send_frames(client_ws, frames, meta),
            _apply_input(host, session, cdp, client_ws, page_session),
        )
    finally:
        for task in background:
            task.cancel()
        host.remove_viewer(session.session_id)
        try:
            await cdp.stop()
        except Exception as exc:  # a dead socket on teardown is not actionable
            log.warning(
                f"{LogTag.BROWSER} browser live view teardown failed",
                error_type=type(exc).__name__,
            )
    log.set(browser={"session_id": session.session_id, "operation": "live_view_closed"})
    log.info(f"{LogTag.BROWSER} browser live view closed")


def _register_frame_handler(
    cdp: CDPClient,
    page_session: str,
    frames: asyncio.Queue[_Frame],
    background: set[asyncio.Task[Any]],
) -> None:
    def on_frame(params: dict[str, Any], _session_id: str | None) -> None:
        ack = asyncio.ensure_future(
            cdp_call(
                cdp,
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
        # Drop the frame when the viewer is behind — we still ack Chromium above,
        # so the stream keeps flowing and the viewer catches the next frame.
        with contextlib.suppress(asyncio.QueueFull):
            frames.put_nowait(frame)

    cdp._event_registry.register("Page.screencastFrame", on_frame)


def _register_nav_handler(
    cdp: CDPClient,
    target_id: str,
    meta: _PageMeta,
    background: set[asyncio.Task[Any]],
) -> None:
    def on_nav(params: dict[str, Any], _session_id: str | None) -> None:
        frame = params.get("frame", {})
        if frame.get("parentId") is None:
            refresh = asyncio.ensure_future(_refresh_meta(cdp, target_id, meta))
            background.add(refresh)
            refresh.add_done_callback(background.discard)

    cdp._event_registry.register("Page.frameNavigated", on_nav)


async def _refresh_meta(cdp: CDPClient, target_id: str, meta: _PageMeta) -> None:
    info = await cdp_call(cdp, "Target.getTargetInfo", {"targetId": target_id})
    target_info = info.get("targetInfo", {})
    meta.url = target_info.get("url")
    meta.title = target_info.get("title")


async def _start_screencast(
    cdp: CDPClient, page_session: str, max_width: int, max_height: int
) -> None:
    params: dict[str, Any] = {
        "format": _SCREENCAST_FORMAT,
        "maxWidth": max_width,
        "maxHeight": max_height,
    }
    if _SCREENCAST_FORMAT == "jpeg":
        params["quality"] = _SCREENCAST_QUALITY
    await cdp_call(cdp, "Page.startScreencast", params, session_id=page_session)


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
                    "cssWidth": frame.css_width,
                    "cssHeight": frame.css_height,
                }
            )
        )


async def _apply_input(
    host: ChromiumHost,
    session: HostSession,
    cdp: CDPClient,
    client_ws: WebSocket,
    page_session: str,
) -> None:
    while True:
        message: dict[str, Any] = json.loads(await client_ws.receive_text())
        host.touch(session.session_id)
        kind = message.get("type")
        if kind == "mouse":
            await cdp_call(
                cdp,
                "Input.dispatchMouseEvent",
                _mouse_params(message),
                session_id=page_session,
            )
        elif kind == "key":
            await cdp_call(
                cdp,
                "Input.dispatchKeyEvent",
                _key_params(message),
                session_id=page_session,
            )
        elif kind == "resize":
            await _start_screencast(
                cdp,
                page_session,
                int(message.get("width", _DEFAULT_MAX_WIDTH)),
                int(message.get("height", _DEFAULT_MAX_HEIGHT)),
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
