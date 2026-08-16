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

from app.browser_host.pumps import pump_until_first_close
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

if TYPE_CHECKING:
    from fastapi import WebSocket

    from app.browser_host.chromium import ChromiumHost, HostSession

# JPEG, not PNG: a live view is judged on smoothness, and a 1920-wide PNG frame is
# ~8-10x larger than JPEG (and slower to encode in Chromium + decode in the browser),
# which is what makes the stream lag. q82 keeps text crisp while cutting the per-frame
# bytes enough to stream fluidly. ``_SCREENCAST_QUALITY`` applies only to "jpeg".
_SCREENCAST_FORMAT = "jpeg"
_SCREENCAST_QUALITY = 82
# The frame is captured at the page's CSS viewport resolution (BROWSER_VIEWPORT_*,
# currently 1920x1200); these caps sit above it so the frame is never downscaled.
_DEFAULT_MAX_WIDTH = 2560
_DEFAULT_MAX_HEIGHT = 1600
# Bounded so a slow viewer applies backpressure by dropping stale frames, not by
# stalling Chromium (we ack every frame regardless).
_FRAME_QUEUE_SIZE = 2

_MOUSE_FIELDS = ("x", "y", "button", "buttons", "clickCount", "deltaX", "deltaY")
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


async def run_live_view(host: ChromiumHost, session: HostSession, client_ws: WebSocket) -> None:
    """Stream the session's focused page to a live-view client and apply its input."""
    host.add_viewer(session.session_id)
    cdp = CDPClient(host.root_ws_url)
    await cdp.start()
    background: set[asyncio.Task[Any]] = set()
    try:
        target_id = await host.focused_target_id(session.session_id)
        attached = await cdp.send_raw(
            "Target.attachToTarget", {"targetId": target_id, "flatten": True}
        )
        page_session: str = attached["sessionId"]
        await cdp.send_raw("Page.enable", {}, session_id=page_session)

        meta = _PageMeta()
        await _refresh_meta(cdp, target_id, meta)
        frames: asyncio.Queue[str] = asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE)

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
    frames: asyncio.Queue[str],
    background: set[asyncio.Task[Any]],
) -> None:
    def on_frame(params: dict[str, Any], _session_id: str | None) -> None:
        ack = asyncio.ensure_future(
            cdp.send_raw(
                "Page.screencastFrameAck",
                {"sessionId": params["sessionId"]},
                session_id=page_session,
            )
        )
        background.add(ack)
        ack.add_done_callback(background.discard)
        # Drop the frame when the viewer is behind — we still ack Chromium above,
        # so the stream keeps flowing and the viewer catches the next frame.
        with contextlib.suppress(asyncio.QueueFull):
            frames.put_nowait(params["data"])

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
    info = await cdp.send_raw("Target.getTargetInfo", {"targetId": target_id})
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
    await cdp.send_raw("Page.startScreencast", params, session_id=page_session)


async def _send_frames(client_ws: WebSocket, frames: asyncio.Queue[str], meta: _PageMeta) -> None:
    while True:
        data = await frames.get()
        await client_ws.send_text(
            json.dumps(
                {
                    "type": "frame",
                    "data": data,
                    "format": _SCREENCAST_FORMAT,
                    "url": meta.url,
                    "title": meta.title,
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
            await cdp.send_raw(
                "Input.dispatchMouseEvent",
                _mouse_params(message),
                session_id=page_session,
            )
        elif kind == "key":
            await cdp.send_raw(
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
