"""Coverage for screencast.py."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.browser_host import screencast
from app.browser_host.screencast import (
    _FRAME_QUEUE_SIZE,
    _apply_input,
    _Frame,
    _key_params,
    _make_event_sink,
    _make_frame_handler,
    _make_nav_handler,
    _mouse_params,
    _PageMeta,
    _pull_frames,
    _refresh_meta,
    _send_frames,
    _start_screencast,
    _StreamState,
)
from app.constants.browser import BROWSER_VIEWPORT_HEIGHT, BROWSER_VIEWPORT_WIDTH
from app.constants.log_tags import LogTag
from tests.unit.browser_host.conftest import FakeMux, make_session
from tests.unit.browser_host.test_screencast import make_mux

if TYPE_CHECKING:
    from app.browser_host.chromium import HostSession


def _make_host_and_session(mux: FakeMux | None = None) -> tuple[MagicMock, HostSession]:
    host = MagicMock()
    host.focused_target_id = AsyncMock(return_value="target-1")
    return host, make_session("sess-1", mux=mux if mux is not None else make_mux())


@pytest.mark.unit
def test_page_meta_defaults() -> None:
    m = _PageMeta()
    assert m.url is None
    assert m.title is None


# ---------------------------------------------------------------------------
# _mouse_params / _key_params
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_mouse_params_filters_to_allowed_fields() -> None:
    msg = {"event": "mouseMoved", "x": 10, "y": 20, "button": "left", "extra": "drop"}
    params = _mouse_params(msg)
    assert params["type"] == "mouseMoved"
    assert params["x"] == 10
    assert params["y"] == 20
    assert params["button"] == "left"
    assert "extra" not in params


@pytest.mark.unit
def test_mouse_params_empty_for_unknown_fields() -> None:
    params = _mouse_params({"event": "mousePressed", "unknown": 123})
    assert params == {"type": "mousePressed"}


@pytest.mark.unit
def test_mouse_params_all_fields() -> None:
    msg = {
        "event": "mouseWheel",
        "x": 1,
        "y": 2,
        "button": "none",
        "buttons": 0,
        "clickCount": 1,
        "deltaX": 10,
        "deltaY": 20,
    }
    params = _mouse_params(msg)
    for k in ["x", "y", "button", "buttons", "clickCount", "deltaX", "deltaY"]:
        assert params[k] == msg[k]


@pytest.mark.unit
def test_key_params_filters() -> None:
    msg = {"event": "keyDown", "key": "a", "code": "KeyA", "text": "a", "extra": 1}
    params = _key_params(msg)
    assert params["type"] == "keyDown"
    assert params["key"] == "a"
    assert params["code"] == "KeyA"
    assert params["text"] == "a"
    assert "extra" not in params


@pytest.mark.unit
def test_key_params_all_fields() -> None:
    msg = {
        "event": "keyDown",
        "key": "Enter",
        "code": "Enter",
        "text": "\r",
        "unmodifiedText": "\r",
        "windowsVirtualKeyCode": 13,
        "nativeVirtualKeyCode": 13,
        "autoRepeat": False,
        "isKeypad": False,
        "location": 0,
        "modifiers": 0,
    }
    params = _key_params(msg)
    for k in [
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
    ]:
        assert params[k] == msg[k]


@pytest.mark.unit
def test_key_params_empty_extra() -> None:
    assert _key_params({"event": "keyUp", "bogus": 1}) == {"type": "keyUp"}


# ---------------------------------------------------------------------------
# _refresh_meta
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_refresh_meta_sets_url_and_title() -> None:
    fake_cdp = MagicMock()
    meta = _PageMeta()
    with patch.object(
        screencast,
        "cdp_call",
        new=AsyncMock(
            return_value={"targetInfo": {"url": "https://example.com", "title": "Example"}}
        ),
    ) as mock_call:
        await _refresh_meta(fake_cdp, "target-1", meta)
        mock_call.assert_awaited_once_with(
            fake_cdp, "Target.getTargetInfo", {"targetId": "target-1"}
        )
    assert meta.url == "https://example.com"
    assert meta.title == "Example"


@pytest.mark.unit
async def test_refresh_meta_missing_fields_sets_none() -> None:
    fake_cdp = MagicMock()
    meta = _PageMeta()
    meta.url = "old"
    meta.title = "old"
    with patch.object(screencast, "cdp_call", new=AsyncMock(return_value={"targetInfo": {}})):
        await _refresh_meta(fake_cdp, "t", meta)
    assert meta.url is None
    assert meta.title is None


@pytest.mark.unit
async def test_refresh_meta_no_target_info() -> None:
    fake_cdp = MagicMock()
    meta = _PageMeta()
    with patch.object(screencast, "cdp_call", new=AsyncMock(return_value={})):
        await _refresh_meta(fake_cdp, "t", meta)
    assert meta.url is None


# ---------------------------------------------------------------------------
# _start_screencast
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_start_screencast_sends_jpeg_with_quality() -> None:
    fake_cdp = MagicMock()
    with patch.object(screencast, "cdp_call", new=AsyncMock()) as mock_call:
        await _start_screencast(fake_cdp, "sess-1", 1280, 800)
        mock_call.assert_awaited_once()
        args = mock_call.call_args
        assert args[0][1] == "Page.startScreencast"
        params = args[0][2]
        assert params["format"] == "jpeg"
        assert params["maxWidth"] == 1280
        assert params["maxHeight"] == 800
        assert params["quality"] == 72
        assert args[1]["session_id"] == "sess-1"


@pytest.mark.unit
async def test_start_screencast_quality_only_for_jpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cdp = MagicMock()
    monkeypatch.setattr(screencast, "_SCREENCAST_FORMAT", "png")
    with patch.object(screencast, "cdp_call", new=AsyncMock()) as mock_call:
        await _start_screencast(fake_cdp, "sess-1", 640, 480)
        params = mock_call.call_args[0][2]
        assert params["format"] == "png"
        assert "quality" not in params


# ---------------------------------------------------------------------------
# _send_frames
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_send_frames_sends_json_with_meta() -> None:
    meta = _PageMeta()
    meta.url = "https://example.com"
    meta.title = "Title"
    frames: asyncio.Queue[_Frame] = asyncio.Queue()
    await frames.put(_Frame("base64data==", 1280, 800))
    client_ws = MagicMock()
    client_ws.send_text = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        # _send_frames loops forever; first iteration sends then second blocks on get
        # we make send_text cancel to exit
        await _send_frames(client_ws, frames, meta)

    client_ws.send_text.assert_awaited_once()
    sent = json.loads(client_ws.send_text.call_args[0][0])
    assert sent["type"] == "frame"
    assert sent["data"] == "base64data=="
    # The page's CSS size rides every frame — it is what viewers map clicks through.
    assert sent["cssWidth"] == 1280
    assert sent["cssHeight"] == 800
    assert sent["url"] == "https://example.com"
    assert sent["title"] == "Title"
    assert sent["format"] == "jpeg"


@pytest.mark.unit
async def test_send_frames_with_none_meta() -> None:
    meta = _PageMeta()
    frames: asyncio.Queue[_Frame] = asyncio.Queue()
    await frames.put(_Frame("data", None, None))
    client_ws = MagicMock()
    client_ws.send_text = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await _send_frames(client_ws, frames, meta)
    sent = json.loads(client_ws.send_text.call_args[0][0])
    assert sent["url"] is None
    assert sent["title"] is None


# ---------------------------------------------------------------------------
# _apply_input
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_apply_input_mouse_dispatch() -> None:
    host = MagicMock()
    session = MagicMock(session_id="s1")
    fake_cdp = MagicMock()
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps({"type": "mouse", "event": "mouseMoved", "x": 10, "y": 20}),
            asyncio.CancelledError,
        ]
    )
    with patch.object(screencast, "cdp_call", new=AsyncMock()) as mock_call:
        with pytest.raises(asyncio.CancelledError):
            await _apply_input(host, session, fake_cdp, client_ws, "page-sess")
        mock_call.assert_awaited_once()
        assert mock_call.call_args[0][1] == "Input.dispatchMouseEvent"
        assert mock_call.call_args[0][2]["x"] == 10
        host.touch.assert_called_once_with("s1")


@pytest.mark.unit
async def test_apply_input_key_dispatch() -> None:
    host = MagicMock()
    session = MagicMock(session_id="s1")
    fake_cdp = MagicMock()
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps({"type": "key", "event": "keyDown", "key": "a"}),
            asyncio.CancelledError,
        ]
    )
    with patch.object(screencast, "cdp_call", new=AsyncMock()) as mock_call:
        with pytest.raises(asyncio.CancelledError):
            await _apply_input(host, session, fake_cdp, client_ws, "page-sess")
        assert mock_call.call_args[0][1] == "Input.dispatchKeyEvent"
        assert mock_call.call_args[0][2]["key"] == "a"


@pytest.mark.unit
async def test_apply_input_resize_restarts_screencast() -> None:
    host = MagicMock()
    session = MagicMock(session_id="s1")
    fake_cdp = MagicMock()
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps({"type": "resize", "width": 640, "height": 480}),
            asyncio.CancelledError,
        ]
    )
    with patch.object(screencast, "_start_screencast", new=AsyncMock()) as mock_screencast:
        with pytest.raises(asyncio.CancelledError):
            await _apply_input(host, session, fake_cdp, client_ws, "page-sess")
        mock_screencast.assert_awaited_once_with(fake_cdp, "page-sess", 640, 480)


@pytest.mark.unit
async def test_apply_input_resize_defaults_when_missing() -> None:
    host = MagicMock()
    session = MagicMock(session_id="s1")
    fake_cdp = MagicMock()
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps({"type": "resize"}),
            asyncio.CancelledError,
        ]
    )
    with patch.object(screencast, "_start_screencast", new=AsyncMock()) as mock_screencast:
        with pytest.raises(asyncio.CancelledError):
            await _apply_input(host, session, fake_cdp, client_ws, "page-sess")
        mock_screencast.assert_awaited_once_with(
            fake_cdp, "page-sess", BROWSER_VIEWPORT_WIDTH, BROWSER_VIEWPORT_HEIGHT
        )


@pytest.mark.unit
async def test_apply_input_unknown_type_ignored() -> None:
    host = MagicMock()
    session = MagicMock(session_id="s1")
    fake_cdp = MagicMock()
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps({"type": "unknown", "event": "x"}),
            asyncio.CancelledError,
        ]
    )
    with patch.object(screencast, "cdp_call", new=AsyncMock()) as mock_call:
        with pytest.raises(asyncio.CancelledError):
            await _apply_input(host, session, fake_cdp, client_ws, "page-sess")
        mock_call.assert_not_called()
        host.touch.assert_called_once_with("s1")


# ---------------------------------------------------------------------------
# _make_frame_handler
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_frame_handler_ack_and_enqueue() -> None:
    fake_cdp = MagicMock()
    frames: asyncio.Queue[str] = asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE)
    background: set[asyncio.Task] = set()

    with patch.object(screencast, "cdp_call", new=AsyncMock(return_value=None)):
        handler = _make_frame_handler(fake_cdp, "page-sess", frames, background, _StreamState())
        # call handler — needs running loop for ensure_future
        handler({"data": "abc", "sessionId": "frame-sess"})
        await asyncio.sleep(0)
        assert frames.qsize() == 1
        assert not frames.empty()
        # background task was added
        assert len(background) == 1
        # ack task should be cancellable
        for t in list(background):
            t.cancel()
        await asyncio.gather(*list(background), return_exceptions=True)


@pytest.mark.unit
async def test_frame_handler_drops_when_queue_full() -> None:
    fake_cdp = MagicMock()
    frames: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
    frames.put_nowait(_Frame("existing", None, None))
    background: set[asyncio.Task] = set()

    with patch.object(screencast, "cdp_call", new=AsyncMock(return_value=None)):
        handler = _make_frame_handler(fake_cdp, "page-sess", frames, background, _StreamState())
        # this put should be dropped (QueueFull suppressed) but ack still scheduled
        handler({"data": "new", "sessionId": "s"})
        await asyncio.sleep(0)
        assert frames.qsize() == 1
        assert frames.get_nowait().data == "existing"
        assert len(background) == 1
        for t in list(background):
            t.cancel()
        await asyncio.gather(*list(background), return_exceptions=True)


@pytest.mark.unit
def test_event_sink_routes_screencast_frames_to_the_frame_handler() -> None:
    seen: list[dict[str, Any]] = []
    sink = _make_event_sink(lambda params: seen.append(params), MagicMock())
    sink({"method": "Page.screencastFrame", "sessionId": "page-sess", "params": {"data": "a"}})
    assert seen == [{"data": "a"}]


# ---------------------------------------------------------------------------
# _make_nav_handler
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_nav_handler_top_level_triggers_refresh() -> None:
    fake_cdp = MagicMock()
    meta = _PageMeta()
    background: set[asyncio.Task] = set()
    with patch.object(screencast, "_refresh_meta", new=AsyncMock()):
        handler = _make_nav_handler(fake_cdp, "target-1", meta, background, "page-session")
        handler({"frame": {"parentId": None}})
        await asyncio.sleep(0)
        # scheduled as background task
        assert len(background) == 1
        for t in list(background):
            t.cancel()
        await asyncio.gather(*list(background), return_exceptions=True)


@pytest.mark.unit
def test_nav_handler_child_frame_not_refreshed() -> None:
    fake_cdp = MagicMock()
    meta = _PageMeta()
    background: set[asyncio.Task] = set()
    with patch.object(screencast, "_refresh_meta", new=AsyncMock()) as mock_refresh:
        handler = _make_nav_handler(fake_cdp, "target-1", meta, background, "page-session")
        handler({"frame": {"parentId": "parent-123"}})
        assert len(background) == 0
        mock_refresh.assert_not_called()


@pytest.mark.unit
async def test_nav_handler_missing_frame_triggers_refresh() -> None:
    fake_cdp = MagicMock()
    background: set[asyncio.Task] = set()
    with patch.object(screencast, "_refresh_meta", new=AsyncMock()):
        handler = _make_nav_handler(fake_cdp, "target-1", _PageMeta(), background, "page-session")
        # no frame key => frame defaults to {}, parentId None => triggers refresh
        handler({})
        await asyncio.sleep(0)
        assert len(background) == 1
        for t in list(background):
            t.cancel()
        await asyncio.gather(*list(background), return_exceptions=True)


@pytest.mark.unit
def test_event_sink_routes_navigation_to_the_nav_handler_and_ignores_other_methods() -> None:
    on_frame = MagicMock()
    on_nav = MagicMock()
    sink = _make_event_sink(on_frame, on_nav)
    sink({"method": "Page.frameNavigated", "sessionId": "page-sess", "params": {"frame": {}}})
    sink({"method": "Page.loadEventFired", "sessionId": "page-sess", "params": {}})
    # a forwarded proxy reply carries no method at all
    sink({"id": 7, "result": {}, "sessionId": "page-sess"})

    on_nav.assert_called_once_with({"frame": {}})
    on_frame.assert_not_called()


@pytest.mark.unit
async def test_event_sink_hands_a_paramless_event_an_empty_params_mapping() -> None:
    """A CDP event can carry no params at all; a handler given None would raise instead."""
    background: set[asyncio.Task[Any]] = set()
    with patch.object(screencast, "_refresh_meta", new=AsyncMock()) as mock_refresh:
        sink = _make_event_sink(
            MagicMock(),
            _make_nav_handler(MagicMock(), "target-1", _PageMeta(), background, "page-sess"),
        )
        sink({"method": "Page.frameNavigated", "sessionId": "page-sess"})
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    mock_refresh.assert_awaited_once()


@pytest.mark.unit
def test_event_sink_handles_every_frame_the_mux_routes_to_it() -> None:
    """The mux already withholds other pages, so a sink that re-filtered would drop its own frames."""
    on_frame = MagicMock()
    on_nav = MagicMock()
    sink = _make_event_sink(on_frame, on_nav)
    sink({"method": "Page.screencastFrame", "sessionId": "other-sess", "params": {"data": "x"}})
    sink({"method": "Page.frameNavigated", "sessionId": None, "params": {"frame": {}}})

    on_frame.assert_called_once_with({"data": "x"})
    on_nav.assert_called_once_with({"frame": {}})


# ---------------------------------------------------------------------------
# run_live_view - viewer and teardown paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_run_live_view_cleans_up_background_and_removes_viewer_on_success() -> None:
    mux = make_mux()
    host, session = _make_host_and_session(mux)

    with patch.object(screencast, "pump_until_first_close", new=AsyncMock()):
        await screencast.run_live_view(host, session, MagicMock())

    host.add_viewer.assert_called_once_with("sess-1")
    host.remove_viewer.assert_called_once_with("sess-1")
    # the connection outlives the viewer: the host and the proxy still use it
    assert mux.closed is False


@pytest.mark.unit
async def test_run_live_view_cancels_background_tasks() -> None:
    mux = make_mux()
    host, session = _make_host_and_session(mux)
    bg_task = asyncio.create_task(asyncio.sleep(10))

    def fake_make_frame(*_args: Any, **_kwargs: Any) -> Any:
        _args[3].add(bg_task)
        return MagicMock()

    def fake_make_nav(*_args: Any, **_kwargs: Any) -> Any:
        _args[3].add(bg_task)
        return MagicMock()

    with (
        patch.object(screencast, "pump_until_first_close", new=AsyncMock(return_value=None)),
        patch.object(screencast, "_make_frame_handler", side_effect=fake_make_frame),
        patch.object(screencast, "_make_nav_handler", side_effect=fake_make_nav),
    ):
        await screencast.run_live_view(host, session, MagicMock())

    await asyncio.sleep(0)
    assert bg_task.cancelled()


@pytest.mark.unit
async def test_run_live_view_cdp_call_sequence_and_exact_args() -> None:
    """Every CDP call run_live_view makes, in order, with exact method/params/session_id."""
    mux = make_mux()
    host, session = _make_host_and_session(mux)
    calls: list[tuple[Any, str, dict[str, Any] | None, str | None]] = []

    async def fake_cdp_call(
        cdp: Any,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        calls.append((cdp, method, params, session_id))
        if method == "Target.attachToTarget":
            return {"sessionId": "page-sess"}
        if method == "Target.getTargetInfo":
            return {"targetInfo": {"url": "https://example.com", "title": "Example"}}
        return {}

    with (
        patch.object(screencast, "cdp_call", new=AsyncMock(side_effect=fake_cdp_call)),
        patch.object(screencast, "pump_until_first_close", new=AsyncMock()),
    ):
        await screencast.run_live_view(host, session, MagicMock())

    host.focused_target_id.assert_awaited_once_with("sess-1")
    # every cdp_call rides the session's own mux, never a second connection
    assert calls == [
        (mux, "Target.attachToTarget", {"targetId": "target-1", "flatten": True}, None),
        (mux, "Page.enable", {}, "page-sess"),
        (mux, "Target.getTargetInfo", {"targetId": "target-1"}, None),
        # The page's declared favicon, read once per navigation so the tab shows
        # the same icon the user's own browser would.
        (
            mux,
            "Runtime.evaluate",
            {"expression": screencast._FAVICON_JS, "returnByValue": True},
            "page-sess",
        ),
        (
            mux,
            "Page.startScreencast",
            {"format": "jpeg", "maxWidth": 1280, "maxHeight": 800, "quality": 72},
            "page-sess",
        ),
    ]


@pytest.mark.unit
async def test_run_live_view_builds_handlers_with_expected_args() -> None:
    mux = make_mux()
    host, session = _make_host_and_session(mux)
    with (
        patch.object(screencast, "_make_frame_handler") as mock_frame,
        patch.object(screencast, "_make_nav_handler") as mock_nav,
        patch.object(screencast, "_start_screencast", new=AsyncMock()) as mock_start,
        patch.object(screencast, "pump_until_first_close", new=AsyncMock()),
    ):
        await screencast.run_live_view(host, session, MagicMock())

    frame_args = mock_frame.call_args[0]
    assert frame_args[0] is mux
    assert frame_args[1] == "page-sess"
    assert isinstance(frame_args[2], asyncio.Queue)
    assert frame_args[2].maxsize == _FRAME_QUEUE_SIZE
    assert frame_args[3] == set()

    nav_args = mock_nav.call_args[0]
    assert nav_args[0] is mux
    assert nav_args[1] == "target-1"
    assert isinstance(nav_args[2], _PageMeta)
    assert nav_args[3] is frame_args[3]  # same background set shared by both handlers
    # Without the page session the post-navigation refresh cannot read the favicon
    # (_refresh_meta skips it when page_session is falsy), so the tab icon would
    # freeze on whatever the first page declared.
    assert nav_args[4] == "page-sess"

    mock_start.assert_awaited_once_with(
        mux, "page-sess", BROWSER_VIEWPORT_WIDTH, BROWSER_VIEWPORT_HEIGHT
    )


@pytest.mark.unit
async def test_run_live_view_subscribes_one_sink_and_removes_it_on_exit() -> None:
    mux = make_mux()
    host, session = _make_host_and_session(mux)

    with patch.object(screencast, "pump_until_first_close", new=AsyncMock()):
        await screencast.run_live_view(host, session, MagicMock())

    assert len(mux.unsubscribed) == 1
    assert mux.sinks == []


@pytest.mark.unit
async def test_run_live_view_pump_uses_send_frames_and_apply_input_with_correct_args() -> None:
    mux = make_mux()
    host, session = _make_host_and_session(mux)
    client_ws = MagicMock()

    with (
        patch.object(screencast, "_send_frames", new=AsyncMock()) as mock_send,
        patch.object(screencast, "_apply_input", new=AsyncMock()) as mock_apply,
    ):
        await screencast.run_live_view(host, session, client_ws)

    mock_send.assert_awaited_once()
    send_args = mock_send.call_args[0]
    assert send_args[0] is client_ws
    assert isinstance(send_args[1], asyncio.Queue)
    assert isinstance(send_args[2], _PageMeta)

    mock_apply.assert_awaited_once()
    apply_args = mock_apply.call_args[0]
    assert apply_args[0] is host
    assert apply_args[1] is session
    assert apply_args[2] is mux
    assert apply_args[3] is client_ws
    assert apply_args[4] == "page-sess"


@pytest.mark.unit
async def test_run_live_view_add_viewer_before_body_and_removed_when_setup_fails() -> None:
    """add_viewer runs before the try; a failure inside still hits the finally teardown."""
    mux = make_mux()
    mux.send_error = RuntimeError("boom")
    host, session = _make_host_and_session(mux)

    with pytest.raises(RuntimeError, match="boom"):
        await screencast.run_live_view(host, session, MagicMock())

    host.add_viewer.assert_called_once_with("sess-1")
    host.remove_viewer.assert_called_once_with("sess-1")
    # a failed viewer must not take the session's connection down with it
    assert mux.closed is False


@pytest.mark.unit
async def test_run_live_view_logs_closed_event_with_session_id() -> None:
    host, session = _make_host_and_session()

    with (
        patch.object(screencast, "pump_until_first_close", new=AsyncMock()),
        patch.object(screencast, "log") as mock_log,
    ):
        await screencast.run_live_view(host, session, MagicMock())

    mock_log.set.assert_called_once_with(
        browser={"session_id": "sess-1", "operation": "live_view_closed"}
    )
    mock_log.info.assert_called_once()
    assert "browser live view closed" in mock_log.info.call_args[0][0]


# ---------------------------------------------------------------------------
# _make_frame_handler — exact ack args and background auto-discard
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_frame_handler_ack_uses_exact_cdp_call_args() -> None:
    fake_cdp = MagicMock()
    frames: asyncio.Queue[str] = asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE)
    background: set[asyncio.Task] = set()

    with patch.object(screencast, "cdp_call", new=AsyncMock(return_value=None)) as mock_call:
        handler = _make_frame_handler(fake_cdp, "page-sess", frames, background, _StreamState())
        handler({"data": "abc", "sessionId": "frame-sess"})
        # one tick runs the ack coroutine to completion; a second lets its
        # add_done_callback (scheduled via call_soon) actually fire
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        mock_call.assert_awaited_once_with(
            fake_cdp,
            "Page.screencastFrameAck",
            {"sessionId": "frame-sess"},
            session_id="page-sess",
        )
        # the done callback discards the finished ack task from `background`
        assert background == set()
        # the queued frame is params["data"], not some other field
        assert frames.get_nowait().data == "abc"


@pytest.mark.unit
async def test_nav_handler_refresh_uses_exact_args() -> None:
    fake_cdp = MagicMock()
    meta = _PageMeta()
    background: set[asyncio.Task] = set()

    with patch.object(screencast, "_refresh_meta", new=AsyncMock()) as mock_refresh:
        handler = _make_nav_handler(fake_cdp, "target-1", meta, background, "page-session")
        handler({"frame": {"parentId": None}})
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        mock_refresh.assert_awaited_once_with(fake_cdp, "target-1", meta, "page-session")
        # the done callback discards the finished refresh task from `background`
        assert background == set()


# ---------------------------------------------------------------------------
# _start_screencast — exact params dict, no stray keys
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_start_screencast_params_dict_has_exactly_expected_keys() -> None:
    fake_cdp = MagicMock()
    with patch.object(screencast, "cdp_call", new=AsyncMock()) as mock_call:
        await _start_screencast(fake_cdp, "sess-1", 1280, 800)
        params = mock_call.call_args[0][2]
        assert params == {"format": "jpeg", "maxWidth": 1280, "maxHeight": 800, "quality": 72}


# ---------------------------------------------------------------------------
# _apply_input — exact session_id kwarg and int() coercion on resize
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_apply_input_mouse_uses_exact_session_id_kwarg() -> None:
    host = MagicMock()
    session = MagicMock(session_id="s1")
    fake_cdp = MagicMock()
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps({"type": "mouse", "event": "mouseMoved", "x": 10, "y": 20}),
            asyncio.CancelledError,
        ]
    )
    with patch.object(screencast, "cdp_call", new=AsyncMock()) as mock_call:
        with pytest.raises(asyncio.CancelledError):
            await _apply_input(host, session, fake_cdp, client_ws, "page-sess")
        assert mock_call.call_args.kwargs["session_id"] == "page-sess"
        assert mock_call.call_args[0][0] is fake_cdp


@pytest.mark.unit
async def test_apply_input_key_uses_exact_session_id_kwarg() -> None:
    host = MagicMock()
    session = MagicMock(session_id="s1")
    fake_cdp = MagicMock()
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps({"type": "key", "event": "keyDown", "key": "a"}),
            asyncio.CancelledError,
        ]
    )
    with patch.object(screencast, "cdp_call", new=AsyncMock()) as mock_call:
        with pytest.raises(asyncio.CancelledError):
            await _apply_input(host, session, fake_cdp, client_ws, "page-sess")
        assert mock_call.call_args.kwargs["session_id"] == "page-sess"
        assert mock_call.call_args[0][0] is fake_cdp


@pytest.mark.unit
async def test_apply_input_resize_coerces_string_dimensions_to_int() -> None:
    """width/height arrive as JSON numbers but the handler must int()-coerce them."""
    host = MagicMock()
    session = MagicMock(session_id="s1")
    fake_cdp = MagicMock()
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps({"type": "resize", "width": "999", "height": "555"}),
            asyncio.CancelledError,
        ]
    )
    with patch.object(screencast, "_start_screencast", new=AsyncMock()) as mock_screencast:
        with pytest.raises(asyncio.CancelledError):
            await _apply_input(host, session, fake_cdp, client_ws, "page-sess")
        args = mock_screencast.call_args[0]
        assert args[2] == 999
        assert isinstance(args[2], int)
        assert args[3] == 555
        assert isinstance(args[3], int)


# ---------------------------------------------------------------------------
# _read_favicon
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_read_favicon_returns_the_evaluated_href() -> None:
    """The icon shown in the live-view tab is whatever the page's own JS resolved, read out of the CDP Runtime.evaluate result envelope."""
    with patch.object(
        screencast,
        "cdp_call",
        new=AsyncMock(return_value={"result": {"value": "https://example.com/icon.png"}}),
    ):
        assert (
            await screencast._read_favicon(MagicMock(), "page-sess")
            == "https://example.com/icon.png"
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "envelope",
    [
        {},
        {"result": {}},
        {"result": {"value": None}},
        {"result": {"value": 123}},
    ],
    ids=["no-result", "no-value", "null-value", "non-string-value"],
)
async def test_read_favicon_returns_none_for_a_missing_or_non_string_value(
    envelope: dict[str, Any],
) -> None:
    with patch.object(screencast, "cdp_call", new=AsyncMock(return_value=envelope)):
        assert await screencast._read_favicon(MagicMock(), "page-sess") is None


@pytest.mark.unit
async def test_read_favicon_swallows_evaluation_failure_and_names_the_exception() -> None:
    """A page that blocks evaluation must not break the tab's real metadata, but a persistent failure has to be diagnosable -- the warning carries the real exception type, which is all an operator gets."""
    with (
        patch.object(screencast, "cdp_call", new=AsyncMock(side_effect=TimeoutError("boom"))),
        patch.object(screencast.log, "warning") as mock_warning,
    ):
        assert await screencast._read_favicon(MagicMock(), "page-sess") is None

    mock_warning.assert_called_once_with(
        f"{LogTag.BROWSER} Could not read page favicon",
        error_type="TimeoutError",
    )


# ---------------------------------------------------------------------------
# _pull_frames — the paced capture that fills a quiet screencast
# ---------------------------------------------------------------------------


async def _tick_pull(
    mux: FakeMux,
    meta: _PageMeta,
    frames: asyncio.Queue[_Frame],
    stream: _StreamState,
    ticks: int = 2,
) -> None:
    """Run the pull for a fixed number of ticks, with the interval already patched to 0."""
    task = asyncio.ensure_future(_pull_frames(mux, "page-sess", "target-1", meta, frames, stream))
    # One extra pass: the first only starts the task, which then sleeps its interval.
    for _ in range(ticks + 1):
        await asyncio.sleep(0)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest.mark.unit
def test_stream_state_starts_undelivered_and_sizeless() -> None:
    stream = _StreamState()
    assert (stream.delivered, stream.css_width, stream.css_height) == (False, None, None)


@pytest.mark.unit
async def test_frame_handler_records_delivery_and_css_size_on_the_stream_state() -> None:
    """The pull reads this to tell a live engine from one that stopped screencasting."""
    frames: asyncio.Queue[_Frame] = asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE)
    stream = _StreamState()
    with patch.object(screencast, "cdp_call", new=AsyncMock(return_value=None)):
        handler = _make_frame_handler(MagicMock(), "page-sess", frames, set(), stream)
        handler(
            {
                "data": "abc",
                "sessionId": "cast-1",
                "metadata": {"deviceWidth": 1024, "deviceHeight": 768},
            }
        )
        await asyncio.sleep(0)

    assert stream.delivered is True
    assert (stream.css_width, stream.css_height) == (1024, 768)


@pytest.mark.unit
async def test_pull_captures_on_the_page_session_with_the_screencast_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux({"Page.captureScreenshot": {"data": "pulled"}})
    frames: asyncio.Queue[_Frame] = asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE)
    stream = _StreamState()
    stream.css_width, stream.css_height = 1280, 800

    await _tick_pull(mux, _PageMeta(), frames, stream, ticks=1)

    assert ("Page.captureScreenshot", {"format": "jpeg", "quality": 72}, "page-sess") in mux.calls
    # The metadata the frame is sent with comes off the streamed target, not off
    # whatever target the shared connection last touched.
    assert ("Target.getTargetInfo", {"targetId": "target-1"}, None) in mux.calls
    frame = frames.get_nowait()
    assert (frame.data, frame.css_width, frame.css_height) == ("pulled", 1280, 800)


@pytest.mark.unit
async def test_pull_skips_the_tick_after_a_screencast_frame_arrived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux({"Page.captureScreenshot": {"data": "pulled"}})
    stream = _StreamState()
    stream.delivered = True

    await _tick_pull(mux, _PageMeta(), asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE), stream, ticks=1)

    assert "Page.captureScreenshot" not in mux.methods
    assert stream.delivered is False


@pytest.mark.unit
async def test_pull_rereads_the_favicon_only_when_the_url_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux(
        {
            "Page.captureScreenshot": {"data": "pulled"},
            "Runtime.evaluate": {"result": {"value": "https://example.com/icon.png"}},
        }
    )
    meta = _PageMeta()
    meta.url = "https://example.com"

    await _tick_pull(mux, meta, asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE), _StreamState(), ticks=2)

    # The url never moved, so the tab icon is still the one this page declared.
    assert "Runtime.evaluate" not in mux.methods
    mux.responses["Target.getTargetInfo"] = {"targetInfo": {"url": "https://next", "title": "Next"}}

    await _tick_pull(mux, meta, asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE), _StreamState(), ticks=1)

    assert mux.methods.count("Runtime.evaluate") == 1
    # The re-read must ride the page session this viewer attached: on the shared
    # connection an unaddressed Runtime.evaluate is a different page's DOM.
    assert (
        "Runtime.evaluate",
        {"expression": screencast._FAVICON_JS, "returnByValue": True},
        "page-sess",
    ) in mux.calls
    assert meta.favicon == "https://example.com/icon.png"


@pytest.mark.unit
async def test_pull_drops_its_capture_when_the_viewer_is_behind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux({"Page.captureScreenshot": {"data": "pulled"}})
    frames: asyncio.Queue[_Frame] = asyncio.Queue(maxsize=1)
    frames.put_nowait(_Frame("queued", None, None))

    await _tick_pull(mux, _PageMeta(), frames, _StreamState(), ticks=2)

    assert frames.qsize() == 1
    assert frames.get_nowait().data == "queued"


@pytest.mark.unit
async def test_pull_logs_one_line_per_failure_streak_and_keeps_going(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pull failing twice a second must be visible once, not 120 times a minute."""
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux()
    mux.send_error = RuntimeError("engine wedged")
    frames: asyncio.Queue[_Frame] = asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE)

    with patch.object(screencast.log, "warning") as mock_warning:
        await _tick_pull(mux, _PageMeta(), frames, _StreamState(), ticks=4)

    assert frames.empty()
    assert len(mux.calls) > 1
    mock_warning.assert_called_once_with(
        f"{LogTag.BROWSER} Could not pull a live-view frame",
        error_type="RuntimeError",
    )


async def _pull_until(
    mux: FakeMux,
    stream: _StreamState,
    frames: asyncio.Queue[_Frame],
    ready: Callable[[], bool],
) -> None:
    """Run the pull, yielding to the loop until ready() (or the task dies), never on a clock."""
    task = asyncio.ensure_future(
        _pull_frames(mux, "page-sess", "target-1", _PageMeta(), frames, stream)
    )
    for _ in range(200):
        if ready() or task.done():
            break
        await asyncio.sleep(0)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest.mark.unit
async def test_pull_warns_again_once_a_screencast_frame_broke_the_failure_streak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one-line-per-streak counter belongs to the current run of failures, not the viewer."""
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux()
    stream = _StreamState()
    attempts = 0

    async def send(
        method: str, params: dict[str, Any] | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        nonlocal attempts
        if method == "Target.getTargetInfo":
            attempts += 1
            if attempts == 1:
                # the engine screencasts one frame before the next pull tick
                stream.delivered = True
            raise RuntimeError("engine wedged")
        return {}

    monkeypatch.setattr(mux, "send_raw", send)

    with patch.object(screencast.log, "warning") as mock_warning:
        await _pull_until(
            mux,
            stream,
            asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE),
            lambda: mock_warning.call_count == 2,
        )

    # Exactly two pulls were attempted: the first failed and spoke, the delivered
    # frame skipped the next tick, and the pull after it failed and spoke again.
    assert attempts == 2
    assert mock_warning.call_count == 2


@pytest.mark.unit
async def test_pull_warns_again_once_a_successful_capture_broke_the_failure_streak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capture that worked ends the streak, so the next failure is a new one worth a line."""
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux({"Page.captureScreenshot": {"data": "pulled"}})
    captures = 0
    send_raw = mux.send_raw

    async def send(
        method: str, params: dict[str, Any] | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        nonlocal captures
        result = await send_raw(method, params, session_id)
        if method == "Page.captureScreenshot":
            captures += 1
            if captures != 2:  # only the middle capture comes back
                raise RuntimeError("capture refused")
        return result

    monkeypatch.setattr(mux, "send_raw", send)
    frames: asyncio.Queue[_Frame] = asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE)

    with patch.object(screencast.log, "warning") as mock_warning:
        await _pull_until(mux, _StreamState(), frames, lambda: mock_warning.call_count == 2)

    assert captures == 3
    assert mock_warning.call_count == 2
    assert frames.get_nowait().data == "pulled"
