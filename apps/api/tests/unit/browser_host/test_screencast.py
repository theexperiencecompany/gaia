"""Live-view screencast setup must never strand a viewer slot.

Regression: add_viewer sat outside the try/finally, so a failure during
live-view setup (e.g. the CDP client cannot connect) left viewer_count > 0
forever. The idle reaper skips sessions with viewers, so that session was never
reclaimed, a permanent capacity leak that only a host restart cleared.
"""

import asyncio
import contextlib
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.browser_host import screencast
from app.constants.browser import BROWSER_VIEWPORT_HEIGHT, BROWSER_VIEWPORT_WIDTH
from tests.unit.browser_host.conftest import FakeMux, make_session

_SESSION_ID = "sess-1"
_PAGE_SESSION = "page-sess"

_DEFAULT_REPLIES: dict[str, dict[str, Any]] = {
    "Target.attachToTarget": {"sessionId": _PAGE_SESSION},
    "Target.getTargetInfo": {"targetInfo": {"url": "https://example.com", "title": "Example"}},
    "Runtime.evaluate": {"result": {"value": None}},
}


def make_mux(overrides: dict[str, dict[str, Any]] | None = None) -> FakeMux:
    """Build the shared fake answering the CDP calls a live view makes during setup."""
    return FakeMux({**_DEFAULT_REPLIES, **(overrides or {})})


@pytest.mark.unit
async def test_run_live_view_removes_viewer_when_setup_fails() -> None:
    host = MagicMock()
    host.focused_target_id = AsyncMock(return_value="target-1")

    mux = make_mux()
    mux.send_error = RuntimeError("cannot reach chromium")
    session = make_session(_SESSION_ID, mux=mux)

    with pytest.raises(RuntimeError):
        await screencast.run_live_view(host, session, MagicMock())

    # The viewer registration must be balanced even though setup blew up, or the
    # session can never be reaped.
    host.add_viewer.assert_called_once_with(_SESSION_ID)
    host.remove_viewer.assert_called_once_with(_SESSION_ID)


# _register_frame_handler: per-frame CSS size. Regression: viewers mapped click
# coords in frame-bitmap space into a larger CSS viewport, so takeover clicks
# landed short; every queued frame must carry the page's CSS size.


def _make_handler_and_queue(
    mux: FakeMux,
) -> tuple[asyncio.Queue[Any], set[asyncio.Task[Any]], Any]:
    frames: asyncio.Queue[Any] = asyncio.Queue(maxsize=2)
    background: set[asyncio.Task[Any]] = set()
    on_frame = screencast._make_frame_handler(
        mux, "page-session", frames, background, screencast._StreamState()
    )
    return frames, background, on_frame


@pytest.mark.unit
async def test_frame_handler_queues_frame_with_css_size_from_metadata() -> None:
    mux = make_mux()
    with patch.object(screencast, "cdp_call", AsyncMock()):
        frames, _background, on_frame = _make_handler_and_queue(mux)
        on_frame(
            {
                "data": "base64data",
                "sessionId": "frame-session",
                "metadata": {"deviceWidth": 1440, "deviceHeight": 900},
            }
        )
        await asyncio.sleep(0)  # let the scheduled ack task settle

    frame = frames.get_nowait()
    assert frame.data == "base64data"
    assert frame.css_width == 1440
    assert frame.css_height == 900


@pytest.mark.unit
async def test_frame_handler_queues_none_css_size_when_metadata_missing() -> None:
    mux = make_mux()
    with patch.object(screencast, "cdp_call", AsyncMock()):
        frames, _background, on_frame = _make_handler_and_queue(mux)
        on_frame({"data": "no-meta", "sessionId": "frame-session"})
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
        "favicon": None,
        "cssWidth": 1024,
        "cssHeight": 768,
    }


# --- _mouse_params: modifiers ----------------------------------------------


@pytest.mark.unit
def test_mouse_params_passes_modifiers_through() -> None:
    params = screencast._mouse_params({"event": "mousePressed", "x": 1, "y": 2, "modifiers": 8})
    assert params["modifiers"] == 8


# --- run_live_view over the shared mux -------------------------------------
# Regression: the viewer used to own its own engine connection. It now borrows
# the session's one connection, so closing it or leaking its sink breaks the session.


async def _run_with_pump(
    mux: FakeMux, during_pump: Any
) -> tuple[asyncio.Queue[Any], screencast._PageMeta]:
    host = MagicMock()
    host.focused_target_id = AsyncMock(return_value="target-1")
    captured: dict[str, Any] = {}

    async def fake_send_frames(
        _client_ws: Any, frames: asyncio.Queue[Any], meta: screencast._PageMeta
    ) -> None:
        captured["frames"] = frames
        captured["meta"] = meta
        await during_pump()

    with patch.object(screencast, "_send_frames", new=fake_send_frames):
        with patch.object(screencast, "_apply_input", new=AsyncMock()):
            await screencast.run_live_view(host, make_session(_SESSION_ID, mux=mux), MagicMock())
    return captured["frames"], captured["meta"]


async def _run_to_client(mux: FakeMux, during_pump: Any) -> list[dict[str, Any]]:
    """Run a live view with the real frame sender and return what reached the client."""
    host = MagicMock()
    host.focused_target_id = AsyncMock(return_value="target-1")
    sent: list[dict[str, Any]] = []
    client_ws = MagicMock()
    client_ws.send_text = AsyncMock(side_effect=lambda text: sent.append(json.loads(text)))

    async def fake_apply_input(*_args: Any, **_kwargs: Any) -> None:
        await during_pump()

    with patch.object(screencast, "_apply_input", new=fake_apply_input):
        await screencast.run_live_view(host, make_session(_SESSION_ID, mux=mux), client_ws)
    return sent


def _screencast_frame(session_id: str, data: str) -> dict[str, Any]:
    return {
        "method": "Page.screencastFrame",
        "sessionId": session_id,
        "params": {
            "data": data,
            "sessionId": "cast-1",
            "metadata": {"deviceWidth": 800, "deviceHeight": 600},
        },
    }


@pytest.mark.unit
async def test_run_live_view_does_not_close_the_shared_mux() -> None:
    """The mux is the session's, shared with the host and the proxy: closing it kills them."""
    mux = make_mux()
    host = MagicMock()
    host.focused_target_id = AsyncMock(return_value="target-1")

    with patch.object(screencast, "pump_until_first_close", new=AsyncMock()):
        await screencast.run_live_view(host, make_session(_SESSION_ID, mux=mux), MagicMock())

    assert mux.closed is False


@pytest.mark.unit
async def test_run_live_view_returns_when_the_engine_drops_the_connection() -> None:
    """An idle viewer has nothing to fail on, so the mux closing is what ends the view."""
    mux = make_mux()
    host = MagicMock()
    host.focused_target_id = AsyncMock(return_value="target-1")
    client_ws = MagicMock()
    client_ws.send_text = AsyncMock()

    async def never_speaks() -> str:
        await asyncio.Event().wait()
        raise AssertionError("an idle viewer never sends")

    client_ws.receive_text = never_speaks

    viewing = asyncio.create_task(
        screencast.run_live_view(host, make_session(_SESSION_ID, mux=mux), client_ws)
    )
    mux.close_signal.set()  # the engine hung up

    await asyncio.wait_for(viewing, timeout=1.0)
    host.remove_viewer.assert_called_once_with(_SESSION_ID)


@pytest.mark.unit
async def test_run_live_view_unsubscribes_its_sink_on_exit() -> None:
    mux = make_mux()
    host = MagicMock()
    host.focused_target_id = AsyncMock(return_value="target-1")

    with patch.object(screencast, "pump_until_first_close", new=AsyncMock()):
        await screencast.run_live_view(host, make_session(_SESSION_ID, mux=mux), MagicMock())

    assert mux.sinks == []
    assert len(mux.unsubscribed) == 1


@pytest.mark.unit
async def test_run_live_view_claims_the_page_session_it_attached() -> None:
    """Claiming its own page session is what keeps this viewer's frames off every other consumer."""
    mux = make_mux()
    claimed: list[list[str | None]] = []

    async def record_claim() -> None:
        claimed.append(list(mux.owned_sessions))

    await _run_with_pump(mux, record_claim)

    assert claimed == [[_PAGE_SESSION]]


@pytest.mark.unit
async def test_run_live_view_sends_a_frame_for_its_claimed_session_to_the_client() -> None:
    mux = make_mux()

    async def emit_owned_frame() -> None:
        mux.emit(_screencast_frame(_PAGE_SESSION, "mine"))
        for _ in range(5):
            await asyncio.sleep(0)

    sent = await _run_to_client(mux, emit_owned_frame)

    assert [payload["data"] for payload in sent] == ["mine"]
    assert sent[0]["cssWidth"] == 800
    assert sent[0]["cssHeight"] == 600


@pytest.mark.unit
async def test_run_live_view_never_sends_another_pages_frame_to_the_client() -> None:
    """An unowned frame goes to sinks that claimed nothing, so a claiming viewer never sees it."""
    mux = make_mux()

    async def emit_both_frames() -> None:
        mux.emit(_screencast_frame("other-page-sess", "not-mine"))
        mux.emit(_screencast_frame(_PAGE_SESSION, "mine"))
        for _ in range(5):
            await asyncio.sleep(0)

    sent = await _run_to_client(mux, emit_both_frames)

    assert [payload["data"] for payload in sent] == ["mine"]


@pytest.mark.unit
async def test_run_live_view_renders_frames_for_its_own_page_session() -> None:
    mux = make_mux()

    async def emit_frame() -> None:
        mux.emit(_screencast_frame(_PAGE_SESSION, "mine"))

    frames, _meta = await _run_with_pump(mux, emit_frame)

    frame = frames.get_nowait()
    assert frame.data == "mine"
    assert (frame.css_width, frame.css_height) == (800, 600)


@pytest.mark.unit
async def test_run_live_view_ignores_frames_from_another_page_session() -> None:
    """One socket carries every page now, so an unfiltered sink would show the wrong page."""
    mux = make_mux()

    async def emit_other_page_frame() -> None:
        mux.emit(_screencast_frame("other-page-sess", "not-mine"))

    frames, _meta = await _run_with_pump(mux, emit_other_page_frame)

    assert frames.empty()


@pytest.mark.unit
async def test_run_live_view_refreshes_meta_on_frame_navigated() -> None:
    mux = make_mux(
        {"Target.getTargetInfo": {"targetInfo": {"url": "https://first", "title": "First"}}}
    )

    async def navigate() -> None:
        mux.responses["Target.getTargetInfo"] = {
            "targetInfo": {"url": "https://second", "title": "Second"}
        }
        mux.emit(
            {
                "method": "Page.frameNavigated",
                "sessionId": _PAGE_SESSION,
                "params": {"frame": {"parentId": None}},
            }
        )
        for _ in range(5):
            await asyncio.sleep(0)

    _frames, meta = await _run_with_pump(mux, navigate)

    assert meta.url == "https://second"
    assert meta.title == "Second"


@pytest.mark.unit
async def test_run_live_view_ignores_navigation_on_another_page_session() -> None:
    mux = make_mux()

    async def navigate_elsewhere() -> None:
        mux.responses["Target.getTargetInfo"] = {
            "targetInfo": {"url": "https://other", "title": "Other"}
        }
        mux.emit(
            {
                "method": "Page.frameNavigated",
                "sessionId": "other-page-sess",
                "params": {"frame": {"parentId": None}},
            }
        )
        for _ in range(5):
            await asyncio.sleep(0)

    _frames, meta = await _run_with_pump(mux, navigate_elsewhere)

    assert meta.url == "https://example.com"


# --- the paced pull that keeps the view live when the screencast goes quiet ---
# Obscura emits Page.screencastFrame only to the session whose own commands
# repainted, so an agent-driven page freezes the viewer on its first frame.


def _fail_capture(monkeypatch: pytest.MonkeyPatch, mux: FakeMux, exc: Exception) -> None:
    """Make every Page.captureScreenshot on this mux raise, leaving other calls alone."""
    send_raw = mux.send_raw

    async def send(
        method: str, params: dict[str, Any] | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        result = await send_raw(method, params, session_id)
        if method == "Page.captureScreenshot":
            raise exc
        return result

    monkeypatch.setattr(mux, "send_raw", send)


@pytest.mark.unit
async def test_live_view_pulls_a_capture_when_the_screencast_goes_quiet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux({"Page.captureScreenshot": {"data": "pulled"}})

    async def go_quiet_after_one_frame() -> None:
        mux.emit(_screencast_frame(_PAGE_SESSION, "first"))
        for _ in range(8):
            await asyncio.sleep(0)

    sent = await _run_to_client(mux, go_quiet_after_one_frame)

    pulled = [payload for payload in sent if payload["data"] == "pulled"]
    assert pulled, [payload["data"] for payload in sent]
    # A pulled frame is the same page at the same viewport, so it carries the CSS
    # size the screencast last reported — what the viewer maps its clicks through.
    assert (pulled[0]["cssWidth"], pulled[0]["cssHeight"]) == (800, 600)


@pytest.mark.unit
async def test_live_view_pull_refreshes_url_and_title_so_the_tab_is_not_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux({"Page.captureScreenshot": {"data": "pulled"}})

    async def navigate_on_another_session() -> None:
        mux.responses["Target.getTargetInfo"] = {
            "targetInfo": {"url": "https://driven", "title": "Driven"}
        }
        for _ in range(8):
            await asyncio.sleep(0)

    sent = await _run_to_client(mux, navigate_on_another_session)

    assert sent, "the pull never produced a frame"
    assert (sent[-1]["url"], sent[-1]["title"]) == ("https://driven", "Driven")


@pytest.mark.unit
async def test_live_view_does_not_pull_while_screencast_frames_keep_arriving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux({"Page.captureScreenshot": {"data": "pulled"}})

    captures_while_streaming: list[int] = []

    async def keep_streaming() -> None:
        for index in range(8):
            mux.emit(_screencast_frame(_PAGE_SESSION, f"live-{index}"))
            await asyncio.sleep(0)
            captures_while_streaming.append(mux.methods.count("Page.captureScreenshot"))

    sent = await _run_to_client(mux, keep_streaming)

    assert captures_while_streaming == [0] * 8
    # The pull only wakes once the stream really has stopped, so every frame the
    # client saw while it was flowing is a screencast frame.
    streamed = [payload["data"] for payload in sent[:8]]
    assert streamed == [f"live-{i}" for i in range(8)]


@pytest.mark.unit
async def test_live_view_survives_a_failing_capture_and_logs_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux()
    _fail_capture(monkeypatch, mux, RuntimeError("capture refused"))

    async def wait_out_several_ticks() -> None:
        for _ in range(8):
            await asyncio.sleep(0)

    with patch.object(screencast.log, "warning") as mock_warning:
        sent = await _run_to_client(mux, wait_out_several_ticks)

    assert sent == []
    # The viewer keeps ticking rather than dying with the first refused capture,
    # and one line per failure streak makes a persistent failure visible at 2/s.
    assert mux.methods.count("Page.captureScreenshot") > 1
    mock_warning.assert_called_once()
    assert mock_warning.call_args.kwargs["error_type"] == "RuntimeError"


@pytest.mark.unit
async def test_live_view_pull_addresses_the_attached_target_and_page_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pull rides the same shared connection: misaddressed, it captures another page."""
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux({"Page.captureScreenshot": {"data": "pulled"}})

    async def go_quiet() -> None:
        for _ in range(8):
            await asyncio.sleep(0)

    await _run_to_client(mux, go_quiet)

    captures = [
        (params, sid) for method, params, sid in mux.calls if method == "Page.captureScreenshot"
    ]
    assert captures
    assert all(sid == _PAGE_SESSION for _, sid in captures)

    infos = [params for method, params, _ in mux.calls if method == "Target.getTargetInfo"]
    # one from setup plus one per pull, every one naming the focused target
    assert len(infos) > 1
    assert all(params == {"targetId": "target-1"} for params in infos)


# --- the CDP conversation a live view holds with the engine -----------------
# A misnamed method, a missing param or a call on the wrong session is a view
# that never paints (or paints another page): pin what goes over the connection.


def _wire(mux: FakeMux, method: str) -> list[tuple[dict[str, Any], str | None]]:
    """Return what reached the engine for one method, framed as the real mux does (no params is {})."""
    return [(params or {}, sid) for sent, params, sid in mux.calls if sent == method]


async def _view_with_client_input(
    mux: FakeMux, messages: list[dict[str, Any]]
) -> tuple[MagicMock, list[dict[str, Any]]]:
    """Run a live view whose client sends messages, and close it once every one was applied."""
    host = MagicMock()
    # Only this session's focused page is target-1; any other lookup is a bug.
    host.focused_target_id = AsyncMock(side_effect=lambda sid: {_SESSION_ID: "target-1"}[sid])
    inbox: asyncio.Queue[str] = asyncio.Queue()
    for message in messages:
        inbox.put_nowait(json.dumps(message))
    drained = asyncio.Event()
    sent: list[dict[str, Any]] = []
    client_ws = MagicMock()
    client_ws.send_text = AsyncMock(side_effect=lambda text: sent.append(json.loads(text)))

    async def receive_text() -> str:
        # Asked for the next message only after the previous one was dispatched.
        if inbox.empty():
            drained.set()
        return await inbox.get()

    client_ws.receive_text = receive_text
    viewing = asyncio.create_task(
        screencast.run_live_view(host, make_session(_SESSION_ID, mux=mux), client_ws)
    )
    await asyncio.wait_for(drained.wait(), timeout=1.0)
    mux.close_signal.set()
    await asyncio.wait_for(viewing, timeout=1.0)
    return host, sent


async def _settle() -> None:
    for _ in range(8):
        await asyncio.sleep(0)


@pytest.mark.unit
async def test_live_view_attaches_the_focused_page_as_a_flat_session_and_enables_its_events() -> (
    None
):
    mux = make_mux()

    await _view_with_client_input(mux, [])

    # flatten is what gives back a sessionId usable on this same connection.
    assert _wire(mux, "Target.attachToTarget") == [
        ({"targetId": "target-1", "flatten": True}, None)
    ]
    # Without Page.enable on the attached session no navigation event ever arrives.
    assert _wire(mux, "Page.enable") == [({}, _PAGE_SESSION)]


@pytest.mark.unit
async def test_live_view_starts_a_jpeg_screencast_capped_at_the_agent_viewport() -> None:
    mux = make_mux()

    await _view_with_client_input(mux, [])

    assert _wire(mux, "Page.startScreencast") == [
        (
            {
                "format": "jpeg",
                "quality": screencast._SCREENCAST_QUALITY,
                "maxWidth": BROWSER_VIEWPORT_WIDTH,
                "maxHeight": BROWSER_VIEWPORT_HEIGHT,
            },
            _PAGE_SESSION,
        )
    ]


@pytest.mark.unit
async def test_live_view_frames_carry_the_favicon_the_page_declares() -> None:
    mux = make_mux({"Runtime.evaluate": {"result": {"value": "https://example.com/icon.png"}}})

    async def emit_frame() -> None:
        mux.emit(_screencast_frame(_PAGE_SESSION, "mine"))
        await _settle()

    sent = await _run_to_client(mux, emit_frame)

    assert [payload["favicon"] for payload in sent] == ["https://example.com/icon.png"]
    # Read in the page itself, by value, so the icon is the one this tab declares.
    assert _wire(mux, "Runtime.evaluate") == [
        ({"expression": screencast._FAVICON_JS, "returnByValue": True}, _PAGE_SESSION)
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "evaluation",
    [{"result": {"value": 42}}, {"result": {}}, {}],
    ids=["non-string", "no-value", "no-result"],
)
async def test_live_view_shows_no_favicon_when_the_page_yields_no_icon_url(
    evaluation: dict[str, Any],
) -> None:
    mux = make_mux({"Runtime.evaluate": evaluation})

    async def emit_frame() -> None:
        mux.emit(_screencast_frame(_PAGE_SESSION, "mine"))
        await _settle()

    sent = await _run_to_client(mux, emit_frame)

    assert [(payload["data"], payload["favicon"]) for payload in sent] == [("mine", None)]


@pytest.mark.unit
async def test_live_view_streams_without_a_favicon_when_the_page_refuses_evaluation() -> None:
    mux = FakeMux(
        dict(_DEFAULT_REPLIES),
        fail_on_first_call={"Runtime.evaluate": RuntimeError("evaluation blocked")},
    )

    async def emit_frame() -> None:
        mux.emit(_screencast_frame(_PAGE_SESSION, "mine"))
        await _settle()

    with patch.object(screencast.log, "warning") as mock_warning:
        sent = await _run_to_client(mux, emit_frame)

    assert [(payload["data"], payload["favicon"]) for payload in sent] == [("mine", None)]
    mock_warning.assert_called_once()
    assert "favicon" in mock_warning.call_args.args[0]
    assert mock_warning.call_args.kwargs == {"error_type": "RuntimeError"}


@pytest.mark.unit
async def test_live_view_close_is_recorded_on_the_wide_event_with_its_session() -> None:
    mux = make_mux()

    with patch.object(screencast, "log") as mock_log:
        await _view_with_client_input(mux, [])

    mock_log.set.assert_called_once_with(
        browser={"session_id": _SESSION_ID, "operation": "live_view_closed"}
    )


@pytest.mark.unit
async def test_every_frame_is_acked_on_the_page_session_even_when_the_viewer_is_behind() -> None:
    """Chromium stops casting until a frame is acked, so a dropped frame must still be acked."""
    mux = make_mux()
    frames, background, on_frame = _make_handler_and_queue(mux)

    for index in range(3):  # one more than the queue holds
        on_frame({"data": f"f{index}", "sessionId": index})
    await _settle()

    assert _wire(mux, "Page.screencastFrameAck") == [
        ({"sessionId": index}, "page-session") for index in range(3)
    ]
    # The stale-frame rule drops the newest when behind; the viewer is not stalled.
    assert [frames.get_nowait().data for _ in range(frames.qsize())] == ["f0", "f1"]
    # Finished acks leave the set run_live_view cancels on exit, so a long view does not grow it.
    assert background == set()


@pytest.mark.unit
async def test_live_view_ignores_a_subframe_navigation() -> None:
    """An iframe navigating is not the tab changing page, so the tab keeps its url and title."""
    mux = make_mux()

    async def navigate_iframe() -> None:
        mux.responses["Target.getTargetInfo"] = {
            "targetInfo": {"url": "https://ads.example", "title": "Ad"}
        }
        mux.emit(
            {
                "method": "Page.frameNavigated",
                "sessionId": _PAGE_SESSION,
                "params": {"frame": {"id": "child", "parentId": "main"}},
            }
        )
        await _settle()

    _frames, meta = await _run_with_pump(mux, navigate_iframe)

    assert (meta.url, meta.title) == ("https://example.com", "Example")
    assert len(_wire(mux, "Target.getTargetInfo")) == 1  # setup only


@pytest.mark.unit
@pytest.mark.parametrize(
    "event_params",
    [{"frame": {"id": "main"}}, {}, None],
    ids=["main-frame", "no-frame", "no-params"],
)
async def test_live_view_navigation_refreshes_the_tab_url_title_and_favicon(
    event_params: dict[str, Any] | None,
) -> None:
    """A top-level navigation (or one too sparse to tell) re-reads the whole tab from the target."""
    mux = make_mux({"Runtime.evaluate": {"result": {"value": "https://first/icon.png"}}})

    async def navigate() -> None:
        mux.responses["Target.getTargetInfo"] = {
            "targetInfo": {"url": "https://second", "title": "Second"}
        }
        mux.responses["Runtime.evaluate"] = {"result": {"value": "https://second/icon.png"}}
        event: dict[str, Any] = {"method": "Page.frameNavigated", "sessionId": _PAGE_SESSION}
        if event_params is not None:
            event["params"] = event_params
        mux.emit(event)
        await _settle()

    _frames, meta = await _run_with_pump(mux, navigate)

    assert (meta.url, meta.title, meta.favicon) == (
        "https://second",
        "Second",
        "https://second/icon.png",
    )
    assert {params["targetId"] for params, _ in _wire(mux, "Target.getTargetInfo")} == {"target-1"}
    assert {sid for _, sid in _wire(mux, "Runtime.evaluate")} == {_PAGE_SESSION}


@pytest.mark.unit
async def test_navigation_refresh_does_not_accumulate_finished_tasks() -> None:
    mux = make_mux()
    background: set[asyncio.Task[Any]] = set()
    on_nav = screencast._make_nav_handler(
        mux, "target-1", screencast._PageMeta(), background, _PAGE_SESSION
    )

    on_nav({"frame": {"id": "main"}})
    assert len(background) == 1  # held while in flight, so exit can cancel it
    await _settle()

    assert background == set()


@pytest.mark.unit
async def test_live_view_pull_captures_as_jpeg_and_keeps_the_favicon_while_the_url_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux(
        {
            "Page.captureScreenshot": {"data": "pulled"},
            "Runtime.evaluate": {"result": {"value": "https://example.com/icon.png"}},
        }
    )

    sent = await _run_to_client(mux, _settle)

    assert sent
    assert {payload["favicon"] for payload in sent} == {"https://example.com/icon.png"}
    # The icon is read once at setup; an unchanged url is no reason to evaluate again.
    assert len(_wire(mux, "Runtime.evaluate")) == 1
    assert {
        (json.dumps(params, sort_keys=True), sid)
        for params, sid in _wire(mux, "Page.captureScreenshot")
    } == {
        (
            json.dumps({"format": "jpeg", "quality": screencast._SCREENCAST_QUALITY}),
            _PAGE_SESSION,
        )
    }


@pytest.mark.unit
async def test_live_view_pull_rereads_the_favicon_when_the_url_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Engines that isolate sessions never tell the viewer about the agent's navigation."""
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux(
        {
            "Page.captureScreenshot": {"data": "pulled"},
            "Runtime.evaluate": {"result": {"value": "https://example.com/icon.png"}},
        }
    )

    async def navigate_on_another_session() -> None:
        mux.responses["Target.getTargetInfo"] = {
            "targetInfo": {"url": "https://driven", "title": "Driven"}
        }
        mux.responses["Runtime.evaluate"] = {"result": {"value": "https://driven/icon.png"}}
        await _settle()

    sent = await _run_to_client(mux, navigate_on_another_session)

    assert sent[-1]["favicon"] == "https://driven/icon.png"
    assert {sid for _, sid in _wire(mux, "Runtime.evaluate")} == {_PAGE_SESSION}


def _script_capture(monkeypatch: pytest.MonkeyPatch, mux: FakeMux, script: list[Any]) -> None:
    """Answer each Page.captureScreenshot from the script, then fail every later one.

    A script entry is a reply dict, an exception to raise, or a callable run
    first (to emit a screencast frame mid-pull) before raising.
    """
    send_raw = mux.send_raw
    steps = iter(script)

    async def send(
        method: str, params: dict[str, Any] | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        result = await send_raw(method, params, session_id)
        if method != "Page.captureScreenshot":
            return result
        step = next(steps, RuntimeError("capture refused"))
        if callable(step) and not isinstance(step, Exception):
            step()
            raise RuntimeError("capture refused")
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(mux, "send_raw", send)


@pytest.mark.unit
async def test_live_view_logs_a_new_failure_streak_after_the_screencast_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux()
    # The first failing pull races a real screencast frame: the stream recovered,
    # so the next failure is a new outage and must be visible on its own.
    _script_capture(monkeypatch, mux, [lambda: mux.emit(_screencast_frame(_PAGE_SESSION, "live"))])

    with patch.object(screencast.log, "warning") as mock_warning:
        await _run_to_client(mux, _settle)

    assert mock_warning.call_count == 2
    assert all("frame" in call.args[0] for call in mock_warning.call_args_list)


@pytest.mark.unit
async def test_live_view_logs_a_new_failure_streak_after_a_successful_pull(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux()
    _script_capture(monkeypatch, mux, [RuntimeError("first outage"), {"data": "pulled"}])

    with patch.object(screencast.log, "warning") as mock_warning:
        sent = await _run_to_client(mux, _settle)

    assert [payload["data"] for payload in sent] == ["pulled"]
    assert mock_warning.call_count == 2


# --- takeover input: what the user's pointer and keys become in the page -----


@pytest.mark.unit
async def test_live_view_dispatches_the_users_mouse_on_the_page_session() -> None:
    mux = make_mux()
    click = {
        "type": "mouse",
        "event": "mousePressed",
        "x": 10,
        "y": 20,
        "button": "left",
        "clickCount": 1,
        "unrelated": "dropped",
    }

    host, _sent = await _view_with_client_input(mux, [click])

    assert _wire(mux, "Input.dispatchMouseEvent") == [
        (
            {"type": "mousePressed", "x": 10, "y": 20, "button": "left", "clickCount": 1},
            _PAGE_SESSION,
        )
    ]
    # Input is activity: a user driving the page keeps the session from being reaped.
    host.touch.assert_called_once_with(_SESSION_ID)


@pytest.mark.unit
async def test_live_view_dispatches_the_users_keys_on_the_page_session() -> None:
    mux = make_mux()
    press = {"type": "key", "event": "keyDown", "key": "a", "code": "KeyA", "text": "a", "x": 5}

    await _view_with_client_input(mux, [press])

    assert _wire(mux, "Input.dispatchKeyEvent") == [
        ({"type": "keyDown", "key": "a", "code": "KeyA", "text": "a"}, _PAGE_SESSION)
    ]
    assert _wire(mux, "Input.dispatchMouseEvent") == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("resize", "expected"),
    [
        ({"type": "resize", "width": "800", "height": "600"}, (800, 600)),
        ({"type": "resize"}, (BROWSER_VIEWPORT_WIDTH, BROWSER_VIEWPORT_HEIGHT)),
    ],
    ids=["sized", "defaults-to-agent-viewport"],
)
async def test_live_view_resize_restarts_the_screencast_at_the_viewers_size(
    resize: dict[str, Any], expected: tuple[int, int]
) -> None:
    mux = make_mux()

    await _view_with_client_input(mux, [resize])

    restart_params, restart_session = _wire(mux, "Page.startScreencast")[-1]
    assert (restart_params["maxWidth"], restart_params["maxHeight"]) == expected
    assert restart_params["format"] == "jpeg"
    assert restart_session == _PAGE_SESSION
    assert len(_wire(mux, "Page.startScreencast")) == 2


@pytest.mark.unit
async def test_live_view_ignores_a_message_of_unknown_type_but_counts_it_as_activity() -> None:
    mux = make_mux()

    host, _sent = await _view_with_client_input(mux, [{"type": "wheel?", "event": "x"}, {}])

    driven = [m for m in mux.methods if m.startswith("Input.") or m == "Page.startScreencast"]
    assert driven == ["Page.startScreencast"]  # the setup one only
    assert host.touch.call_count == 2


@pytest.mark.unit
async def test_live_view_acks_each_streamed_frame_on_its_own_page_session() -> None:
    mux = make_mux()

    async def emit_frame() -> None:
        mux.emit(_screencast_frame(_PAGE_SESSION, "mine"))
        await _settle()

    await _run_to_client(mux, emit_frame)

    assert _wire(mux, "Page.screencastFrameAck") == [({"sessionId": "cast-1"}, _PAGE_SESSION)]


@pytest.mark.unit
async def test_live_view_streams_with_an_unknown_tab_when_the_engine_omits_target_info() -> None:
    """A partial CDP engine may answer getTargetInfo bare; the pixels still matter more."""
    mux = make_mux({"Target.getTargetInfo": {}})

    async def emit_frame() -> None:
        mux.emit(_screencast_frame(_PAGE_SESSION, "mine"))
        await _settle()

    sent = await _run_to_client(mux, emit_frame)

    assert [(p["data"], p["url"], p["title"]) for p in sent] == [("mine", None, None)]


@pytest.mark.unit
async def test_live_view_pull_before_any_screencast_frame_reports_no_css_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no screencast metadata yet the viewer must fall back to the bitmap, not a bogus size."""
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0)
    mux = make_mux({"Page.captureScreenshot": {"data": "pulled"}})

    sent = await _run_to_client(mux, _settle)

    assert sent
    assert {(p["cssWidth"], p["cssHeight"]) for p in sent} == {(None, None)}


class _StopPulling(Exception):
    """Ends a directly driven pull loop after the ticks a test asked for."""


def _tick(monkeypatch: pytest.MonkeyPatch, ticks: int) -> None:
    """Let the pull loop wake exactly that many times, then stop it at its next sleep."""
    real_sleep = asyncio.sleep
    remaining = [ticks]

    async def sleep(_delay: float) -> None:
        if remaining[0] == 0:
            raise _StopPulling
        remaining[0] -= 1
        await real_sleep(0)

    monkeypatch.setattr(screencast.asyncio, "sleep", sleep)


async def _pull(mux: FakeMux, frames: asyncio.Queue[Any], stream: Any) -> None:
    with pytest.raises(_StopPulling):
        await screencast._pull_frames(
            mux, _PAGE_SESSION, "target-1", screencast._PageMeta(), frames, stream
        )


@pytest.mark.unit
async def test_pull_captures_on_its_first_tick_when_the_page_never_repainted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A view opened on a still page must paint after one interval, not two."""
    mux = make_mux({"Page.captureScreenshot": {"data": "pulled"}})
    frames: asyncio.Queue[Any] = asyncio.Queue(maxsize=2)
    _tick(monkeypatch, 1)

    await _pull(mux, frames, screencast._StreamState())

    assert [frames.get_nowait().data for _ in range(frames.qsize())] == ["pulled"]


@pytest.mark.unit
async def test_pull_keeps_capturing_when_the_viewer_is_behind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mux = make_mux({"Page.captureScreenshot": {"data": "pulled"}})
    frames: asyncio.Queue[Any] = asyncio.Queue(maxsize=1)
    frames.put_nowait(screencast._Frame("unsent", None, None))
    _tick(monkeypatch, 2)

    await _pull(mux, frames, screencast._StreamState())

    # The capture that finds the queue full is dropped, and the loop lives on.
    assert mux.methods.count("Page.captureScreenshot") == 2
    assert frames.get_nowait().data == "unsent"
