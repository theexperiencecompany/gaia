"""Live-view screencast setup must never strand a viewer slot.

Regression: ``add_viewer`` sat outside the try/finally, so a failure during
live-view setup (e.g. the CDP client cannot connect) left ``viewer_count`` > 0
forever. The idle reaper skips sessions with viewers, so that session was never
reclaimed — a permanent capacity leak that only a host restart cleared.
"""

import asyncio
import contextlib
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.browser_host import screencast


@pytest.mark.unit
async def test_run_live_view_removes_viewer_when_setup_fails() -> None:
    host = MagicMock()
    host.root_ws_url = "ws://fake-host"
    session = MagicMock()
    session.session_id = "sess-1"

    failing_cdp = MagicMock()
    failing_cdp.start = AsyncMock(side_effect=RuntimeError("cannot reach chromium"))
    failing_cdp.stop = AsyncMock()

    with patch.object(screencast, "CDPClient", return_value=failing_cdp):
        with pytest.raises(RuntimeError):
            await screencast.run_live_view(host, session, MagicMock())

    # The viewer registration must be balanced even though setup blew up, or the
    # session can never be reaped.
    host.add_viewer.assert_called_once_with("sess-1")
    host.remove_viewer.assert_called_once_with("sess-1")


# --- _register_frame_handler: per-frame CSS size --------------------------
#
# Regression: viewers mapped click coordinates in frame-bitmap space into a
# larger CSS viewport, so takeover clicks landed short. Every queued frame must
# now carry the page's CSS size straight from the screencast metadata.


def _register_and_capture(
    cdp: MagicMock,
) -> tuple[asyncio.Queue[Any], set[asyncio.Task[Any]], Any]:
    frames: asyncio.Queue[Any] = asyncio.Queue(maxsize=2)
    background: set[asyncio.Task[Any]] = set()
    registered: dict[str, Any] = {}
    cdp._event_registry = MagicMock()
    cdp._event_registry.register = MagicMock(
        side_effect=lambda event, cb: registered.__setitem__(event, cb)
    )
    screencast._register_frame_handler(cdp, "page-session", frames, background)
    return frames, background, registered["Page.screencastFrame"]


@pytest.mark.unit
async def test_register_frame_handler_queues_frame_with_css_size_from_metadata() -> None:
    cdp = MagicMock()
    with patch.object(screencast, "cdp_call", AsyncMock()):
        frames, _background, on_frame = _register_and_capture(cdp)
        on_frame(
            {
                "data": "base64data",
                "sessionId": "frame-session",
                "metadata": {"deviceWidth": 1440, "deviceHeight": 900},
            },
            None,
        )
        await asyncio.sleep(0)  # let the scheduled ack task settle

    frame = frames.get_nowait()
    assert frame.data == "base64data"
    assert frame.css_width == 1440
    assert frame.css_height == 900


@pytest.mark.unit
async def test_register_frame_handler_queues_none_css_size_when_metadata_missing() -> None:
    cdp = MagicMock()
    with patch.object(screencast, "cdp_call", AsyncMock()):
        frames, _background, on_frame = _register_and_capture(cdp)
        on_frame({"data": "no-meta", "sessionId": "frame-session"}, None)
        await asyncio.sleep(0)

    frame = frames.get_nowait()
    assert frame.data == "no-meta"
    assert frame.css_width is None
    assert frame.css_height is None


# --- _send_frames: cssWidth/cssHeight on the wire --------------------------


@pytest.mark.unit
async def test_send_frames_serializes_css_width_and_height() -> None:
    frames: asyncio.Queue[Any] = asyncio.Queue()
    await frames.put(screencast._Frame("b64data", 1024, 768))
    meta = screencast._PageMeta()
    meta.url = "https://example.com"
    meta.title = "Example"
    sent: list[str] = []
    client_ws = MagicMock()
    client_ws.send_text = AsyncMock(side_effect=lambda text: sent.append(text))

    task = asyncio.ensure_future(screencast._send_frames(client_ws, frames, meta))
    await asyncio.sleep(0)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    (payload,) = sent
    assert json.loads(payload) == {
        "type": "frame",
        "data": "b64data",
        "format": screencast._SCREENCAST_FORMAT,
        "url": "https://example.com",
        "title": "Example",
        "cssWidth": 1024,
        "cssHeight": 768,
    }


# --- _mouse_params: modifiers ----------------------------------------------


@pytest.mark.unit
def test_mouse_params_passes_modifiers_through() -> None:
    params = screencast._mouse_params({"event": "mousePressed", "x": 1, "y": 2, "modifiers": 8})
    assert params["modifiers"] == 8
