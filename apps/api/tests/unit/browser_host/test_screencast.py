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
