"""Coverage for screencast.py."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.browser_host import screencast
from app.browser_host.screencast import (
    _DEFAULT_MAX_HEIGHT,
    _DEFAULT_MAX_WIDTH,
    _FRAME_QUEUE_SIZE,
    _apply_input,
    _Frame,
    _key_params,
    _mouse_params,
    _PageMeta,
    _refresh_meta,
    _register_frame_handler,
    _register_nav_handler,
    _send_frames,
    _start_screencast,
)


def _make_host_and_session() -> tuple[MagicMock, MagicMock]:
    host = MagicMock()
    host.root_ws_url = "ws://fake"
    session = MagicMock(session_id="sess-1")
    host.focused_target_id = AsyncMock(return_value="target-1")
    return host, session


def _make_cdp() -> MagicMock:
    mock_cdp = MagicMock()
    mock_cdp.start = AsyncMock()
    mock_cdp.stop = AsyncMock()
    mock_cdp._event_registry = MagicMock()
    return mock_cdp


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
            fake_cdp, "page-sess", _DEFAULT_MAX_WIDTH, _DEFAULT_MAX_HEIGHT
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
# _register_frame_handler
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_register_frame_handler_ack_and_enqueue() -> None:
    fake_cdp = MagicMock()
    registry = MagicMock()
    fake_cdp._event_registry = registry
    frames: asyncio.Queue[str] = asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE)
    background: set[asyncio.Task] = set()

    with patch.object(screencast, "cdp_call", new=AsyncMock(return_value=None)):
        _register_frame_handler(fake_cdp, "page-sess", frames, background)
        # capture handler
        handler = registry.register.call_args[0][1]
        # call handler — needs running loop for ensure_future
        handler({"data": "abc", "sessionId": "frame-sess"}, None)
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
async def test_register_frame_handler_drops_when_queue_full() -> None:
    fake_cdp = MagicMock()
    registry = MagicMock()
    fake_cdp._event_registry = registry
    frames: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
    frames.put_nowait(_Frame("existing", None, None))
    background: set[asyncio.Task] = set()

    with patch.object(screencast, "cdp_call", new=AsyncMock(return_value=None)):
        _register_frame_handler(fake_cdp, "page-sess", frames, background)
        handler = registry.register.call_args[0][1]
        # this put should be dropped (QueueFull suppressed) but ack still scheduled
        handler({"data": "new", "sessionId": "s"}, None)
        await asyncio.sleep(0)
        assert frames.qsize() == 1
        assert frames.get_nowait().data == "existing"
        assert len(background) == 1
        for t in list(background):
            t.cancel()
        await asyncio.gather(*list(background), return_exceptions=True)


@pytest.mark.unit
def test_register_frame_handler_registers_correct_event() -> None:
    fake_cdp = MagicMock()
    registry = MagicMock()
    fake_cdp._event_registry = registry
    with patch.object(screencast, "cdp_call", new=AsyncMock()):
        _register_frame_handler(fake_cdp, "page-sess", asyncio.Queue(), set())
        registry.register.assert_called_once()
        assert registry.register.call_args[0][0] == "Page.screencastFrame"


# ---------------------------------------------------------------------------
# _register_nav_handler
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_register_nav_handler_top_level_triggers_refresh() -> None:
    fake_cdp = MagicMock()
    registry = MagicMock()
    fake_cdp._event_registry = registry
    meta = _PageMeta()
    background: set[asyncio.Task] = set()
    with patch.object(screencast, "_refresh_meta", new=AsyncMock()):
        _register_nav_handler(fake_cdp, "target-1", meta, background)
        handler = registry.register.call_args[0][1]
        handler({"frame": {"parentId": None}}, None)
        await asyncio.sleep(0)
        # scheduled as background task
        assert len(background) == 1
        for t in list(background):
            t.cancel()
        await asyncio.gather(*list(background), return_exceptions=True)


@pytest.mark.unit
def test_register_nav_handler_child_frame_not_refreshed() -> None:
    fake_cdp = MagicMock()
    registry = MagicMock()
    fake_cdp._event_registry = registry
    meta = _PageMeta()
    background: set[asyncio.Task] = set()
    with patch.object(screencast, "_refresh_meta", new=AsyncMock()) as mock_refresh:
        _register_nav_handler(fake_cdp, "target-1", meta, background)
        handler = registry.register.call_args[0][1]
        handler({"frame": {"parentId": "parent-123"}}, None)
        assert len(background) == 0
        mock_refresh.assert_not_called()


@pytest.mark.unit
async def test_register_nav_handler_missing_frame_triggers_refresh() -> None:
    fake_cdp = MagicMock()
    registry = MagicMock()
    fake_cdp._event_registry = registry
    background: set[asyncio.Task] = set()
    with patch.object(screencast, "_refresh_meta", new=AsyncMock()):
        _register_nav_handler(fake_cdp, "target-1", _PageMeta(), background)
        handler = registry.register.call_args[0][1]
        # no frame key => frame defaults to {}, parentId None => triggers refresh
        handler({}, None)
        await asyncio.sleep(0)
        assert len(background) == 1
        for t in list(background):
            t.cancel()
        await asyncio.gather(*list(background), return_exceptions=True)


@pytest.mark.unit
def test_register_nav_handler_registers_correct_event() -> None:
    fake_cdp = MagicMock()
    registry = MagicMock()
    fake_cdp._event_registry = registry
    _register_nav_handler(fake_cdp, "t", _PageMeta(), set())
    assert registry.register.call_args[0][0] == "Page.frameNavigated"


# ---------------------------------------------------------------------------
# run_live_view - viewer and teardown paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_run_live_view_cleans_up_background_and_removes_viewer_on_success() -> None:
    host = MagicMock()
    host.root_ws_url = "ws://fake"
    session = MagicMock(session_id="sess-1")
    host.focused_target_id = AsyncMock(return_value="target-1")

    mock_cdp = MagicMock()
    mock_cdp.start = AsyncMock()
    mock_cdp.stop = AsyncMock()
    mock_cdp._event_registry = MagicMock()

    with (
        patch.object(screencast, "CDPClient", return_value=mock_cdp),
        patch.object(
            screencast,
            "cdp_call",
            new=AsyncMock(
                side_effect=[
                    {"sessionId": "page-sess"},
                    {},
                    {"targetInfo": {"url": "https://example.com", "title": "Example"}},
                    {},
                ]
            ),
        ),
        patch.object(screencast, "pump_until_first_close", new=AsyncMock()),
    ):
        await screencast.run_live_view(host, session, MagicMock())

    host.add_viewer.assert_called_once_with("sess-1")
    host.remove_viewer.assert_called_once_with("sess-1")
    mock_cdp.stop.assert_awaited_once()


@pytest.mark.unit
async def test_run_live_view_teardown_suppresses_cdp_stop_error() -> None:
    host = MagicMock()
    host.root_ws_url = "ws://fake"
    session = MagicMock(session_id="sess-1")
    host.focused_target_id = AsyncMock(return_value="target-1")
    mock_cdp = MagicMock()
    mock_cdp.start = AsyncMock()
    mock_cdp.stop = AsyncMock(side_effect=RuntimeError("socket dead"))
    mock_cdp._event_registry = MagicMock()

    with (
        patch.object(screencast, "CDPClient", return_value=mock_cdp),
        patch.object(
            screencast,
            "cdp_call",
            new=AsyncMock(
                side_effect=[
                    {"sessionId": "page-sess"},
                    {},
                    {"targetInfo": {"url": "https://example.com", "title": "Example"}},
                    {},
                ]
            ),
        ),
        patch.object(screencast, "pump_until_first_close", new=AsyncMock()),
    ):
        # should not raise even though stop fails
        await screencast.run_live_view(host, session, MagicMock())

    host.remove_viewer.assert_called_once_with("sess-1")


@pytest.mark.unit
async def test_run_live_view_cancels_background_tasks() -> None:
    host = MagicMock()
    host.root_ws_url = "ws://fake"
    session = MagicMock(session_id="sess-1")
    host.focused_target_id = AsyncMock(return_value="target-1")
    mock_cdp = MagicMock()
    mock_cdp.start = AsyncMock()
    mock_cdp.stop = AsyncMock()
    mock_cdp._event_registry = MagicMock()

    bg_task = asyncio.create_task(asyncio.sleep(10))

    async def fake_pump(*_args, **_kwargs):
        # simulate that background set already has a task
        # we need to inject via the closure — instead check that after run, bg_task is cancelled
        pass

    # We will manually test the finally path: if background contains a task, it gets cancelled
    # Patch _register_* to add bg_task to the background set
    def fake_register_frame(cdp, page_sess, frames, background):
        background.add(bg_task)

    def fake_register_nav(cdp, target_id, meta, background):
        background.add(bg_task)

    with (
        patch.object(screencast, "CDPClient", return_value=mock_cdp),
        patch.object(
            screencast,
            "cdp_call",
            new=AsyncMock(
                side_effect=[
                    {"sessionId": "page-sess"},
                    {},
                    {"targetInfo": {"url": "https://example.com", "title": "Example"}},
                    {},
                ]
            ),
        ),
        patch.object(screencast, "pump_until_first_close", new=AsyncMock(return_value=None)),
        patch.object(screencast, "_register_frame_handler", side_effect=fake_register_frame),
        patch.object(screencast, "_register_nav_handler", side_effect=fake_register_nav),
    ):
        await screencast.run_live_view(host, session, MagicMock())

    # The background task was cancelled in the finally; give the loop a tick
    await asyncio.sleep(0)
    assert bg_task.done()
    assert bg_task.cancelled()
    # cleanup
    if not bg_task.done():
        bg_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bg_task


@pytest.mark.unit
async def test_run_live_view_cdp_call_sequence_and_exact_args() -> None:
    """Every CDP call run_live_view makes, in order, with exact method/params/session_id."""
    host, session = _make_host_and_session()
    mock_cdp = _make_cdp()
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
        patch.object(screencast, "CDPClient", return_value=mock_cdp) as mock_ctor,
        patch.object(screencast, "cdp_call", new=AsyncMock(side_effect=fake_cdp_call)),
        patch.object(screencast, "pump_until_first_close", new=AsyncMock()),
    ):
        await screencast.run_live_view(host, session, MagicMock())

    mock_ctor.assert_called_once_with("ws://fake")
    host.focused_target_id.assert_awaited_once_with("sess-1")
    # every cdp_call carries the session's own CDPClient, not a dropped/None one
    assert calls == [
        (mock_cdp, "Target.attachToTarget", {"targetId": "target-1", "flatten": True}, None),
        (mock_cdp, "Page.enable", {}, "page-sess"),
        (mock_cdp, "Target.getTargetInfo", {"targetId": "target-1"}, None),
        (
            mock_cdp,
            "Page.startScreencast",
            {"format": "jpeg", "maxWidth": 1280, "maxHeight": 800, "quality": 72},
            "page-sess",
        ),
    ]


@pytest.mark.unit
async def test_run_live_view_registers_handlers_with_expected_args() -> None:
    host, session = _make_host_and_session()
    mock_cdp = _make_cdp()
    with (
        patch.object(screencast, "CDPClient", return_value=mock_cdp),
        patch.object(
            screencast,
            "cdp_call",
            new=AsyncMock(side_effect=[{"sessionId": "page-sess"}, {}, {"targetInfo": {}}, {}]),
        ),
        patch.object(screencast, "_register_frame_handler") as mock_frame,
        patch.object(screencast, "_register_nav_handler") as mock_nav,
        patch.object(screencast, "_start_screencast", new=AsyncMock()) as mock_start,
        patch.object(screencast, "pump_until_first_close", new=AsyncMock()),
    ):
        await screencast.run_live_view(host, session, MagicMock())

    mock_frame.assert_called_once()
    frame_args = mock_frame.call_args[0]
    assert frame_args[0] is mock_cdp
    assert frame_args[1] == "page-sess"
    assert isinstance(frame_args[2], asyncio.Queue)
    assert frame_args[2].maxsize == _FRAME_QUEUE_SIZE
    assert frame_args[3] == set()

    mock_nav.assert_called_once()
    nav_args = mock_nav.call_args[0]
    assert nav_args[0] is mock_cdp
    assert nav_args[1] == "target-1"
    assert isinstance(nav_args[2], _PageMeta)
    assert nav_args[3] is frame_args[3]  # same background set shared by both handlers

    mock_start.assert_awaited_once_with(
        mock_cdp, "page-sess", _DEFAULT_MAX_WIDTH, _DEFAULT_MAX_HEIGHT
    )


@pytest.mark.unit
async def test_run_live_view_pump_uses_send_frames_and_apply_input_with_correct_args() -> None:
    host, session = _make_host_and_session()
    mock_cdp = _make_cdp()
    client_ws = MagicMock()

    with (
        patch.object(screencast, "CDPClient", return_value=mock_cdp),
        patch.object(
            screencast,
            "cdp_call",
            new=AsyncMock(side_effect=[{"sessionId": "page-sess"}, {}, {"targetInfo": {}}, {}]),
        ),
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
    assert apply_args[2] is mock_cdp
    assert apply_args[3] is client_ws
    assert apply_args[4] == "page-sess"


@pytest.mark.unit
async def test_run_live_view_add_viewer_before_body_and_removed_when_start_fails() -> None:
    """add_viewer runs before the try; a failure inside still hits the finally teardown."""
    host, session = _make_host_and_session()
    mock_cdp = _make_cdp()
    mock_cdp.start = AsyncMock(side_effect=RuntimeError("boom"))

    with patch.object(screencast, "CDPClient", return_value=mock_cdp):
        with pytest.raises(RuntimeError, match="boom"):
            await screencast.run_live_view(host, session, MagicMock())

    host.add_viewer.assert_called_once_with("sess-1")
    host.remove_viewer.assert_called_once_with("sess-1")
    mock_cdp.stop.assert_awaited_once()


@pytest.mark.unit
async def test_run_live_view_logs_closed_event_with_session_id() -> None:
    host, session = _make_host_and_session()
    mock_cdp = _make_cdp()

    with (
        patch.object(screencast, "CDPClient", return_value=mock_cdp),
        patch.object(
            screencast,
            "cdp_call",
            new=AsyncMock(side_effect=[{"sessionId": "page-sess"}, {}, {"targetInfo": {}}, {}]),
        ),
        patch.object(screencast, "pump_until_first_close", new=AsyncMock()),
        patch.object(screencast, "log") as mock_log,
    ):
        await screencast.run_live_view(host, session, MagicMock())

    mock_log.set.assert_called_once_with(
        browser={"session_id": "sess-1", "operation": "live_view_closed"}
    )
    mock_log.info.assert_called_once()
    assert "browser live view closed" in mock_log.info.call_args[0][0]


@pytest.mark.unit
async def test_run_live_view_teardown_warning_has_exact_error_type() -> None:
    host, session = _make_host_and_session()
    mock_cdp = _make_cdp()
    mock_cdp.stop = AsyncMock(side_effect=RuntimeError("socket dead"))

    with (
        patch.object(screencast, "CDPClient", return_value=mock_cdp),
        patch.object(
            screencast,
            "cdp_call",
            new=AsyncMock(side_effect=[{"sessionId": "page-sess"}, {}, {"targetInfo": {}}, {}]),
        ),
        patch.object(screencast, "pump_until_first_close", new=AsyncMock()),
        patch.object(screencast, "log") as mock_log,
    ):
        await screencast.run_live_view(host, session, MagicMock())

    mock_log.warning.assert_called_once()
    assert "browser live view teardown failed" in mock_log.warning.call_args[0][0]
    assert mock_log.warning.call_args.kwargs == {"error_type": "RuntimeError"}


# ---------------------------------------------------------------------------
# _register_frame_handler — exact ack args and background auto-discard
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_register_frame_handler_ack_uses_exact_cdp_call_args() -> None:
    fake_cdp = MagicMock()
    registry = MagicMock()
    fake_cdp._event_registry = registry
    frames: asyncio.Queue[str] = asyncio.Queue(maxsize=_FRAME_QUEUE_SIZE)
    background: set[asyncio.Task] = set()

    with patch.object(screencast, "cdp_call", new=AsyncMock(return_value=None)) as mock_call:
        _register_frame_handler(fake_cdp, "page-sess", frames, background)
        handler = registry.register.call_args[0][1]
        handler({"data": "abc", "sessionId": "frame-sess"}, None)
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
async def test_register_nav_handler_refresh_uses_exact_args() -> None:
    fake_cdp = MagicMock()
    registry = MagicMock()
    fake_cdp._event_registry = registry
    meta = _PageMeta()
    background: set[asyncio.Task] = set()

    with patch.object(screencast, "_refresh_meta", new=AsyncMock()) as mock_refresh:
        _register_nav_handler(fake_cdp, "target-1", meta, background)
        handler = registry.register.call_args[0][1]
        handler({"frame": {"parentId": None}}, None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        mock_refresh.assert_awaited_once_with(fake_cdp, "target-1", meta)
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
