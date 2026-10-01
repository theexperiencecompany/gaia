"""The live view: it streams the page the agent is on, follows it, and lets go cleanly.

A real run_live_view drives a FakeMux and a fake viewer socket; the host is
reduced to the one thing the view asks of it, which page to stream.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast
from unittest.mock import MagicMock

from fastapi import WebSocketDisconnect
import pytest
from starlette.websockets import WebSocketState

from app.browser_host import screencast
from app.browser_host.cdp_mux import CdpCommandError
from app.browser_host.chromium import HostSession
from app.config.browser_host_settings import browser_host_settings
from app.constants.browser import BROWSER_VIEWPORT_HEIGHT, BROWSER_VIEWPORT_WIDTH, BrowserEngine
from tests.unit.browser_host.conftest import FakeMux, make_session

pytestmark = pytest.mark.unit

_FAVICON = "https://example.com/icon.png"


class _Viewer:
    """The viewer's socket: what it sends in, and every frame the view sent out."""

    def __init__(self) -> None:
        self.inbound: asyncio.Queue[str | None] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.got_frame = asyncio.Event()
        self.client_state = WebSocketState.CONNECTED
        self.application_state = WebSocketState.CONNECTED
        # Starlette's way of reporting a read after the socket closed, instead of a disconnect.
        self.closed_under_read = False

    async def receive_text(self) -> str:
        raw = await self.inbound.get()
        if raw is None:
            if self.closed_under_read:
                self.client_state = WebSocketState.DISCONNECTED
                raise RuntimeError('WebSocket is not connected. Need to call "accept" first.')
            raise WebSocketDisconnect
        return raw

    async def send_text(self, raw: str) -> None:
        self.sent.append(json.loads(raw))
        self.got_frame.set()

    def say(self, **message: Any) -> None:
        self.inbound.put_nowait(json.dumps(message))

    def leave(self) -> None:
        self.inbound.put_nowait(None)


class _Host:
    """Answers which page to stream: whatever the test says is open, the focus first."""

    def __init__(self, session: HostSession, pages: list[str]) -> None:
        self.session = session
        self.pages = pages

    async def focused_target_id(self, session: HostSession) -> str | None:
        if session.focused_target_id in self.pages:
            return session.focused_target_id
        return self.pages[-1] if self.pages else None

    def move_focus(self, target_id: str) -> None:
        self.session.focused_target_id = target_id
        moved, self.session.focus_moved = self.session.focus_moved, asyncio.Event()
        moved.set()


def _mux() -> FakeMux:
    return FakeMux(
        {
            "Target.getTargetInfo": {"targetInfo": {"url": "https://example.com/", "title": "Ex"}},
            "Runtime.evaluate": {"result": {"value": _FAVICON}},
            "Page.captureScreenshot": {"data": "<pulled>"},
        }
    )


class _Run:
    def __init__(self, pages: list[str] | None = None) -> None:
        self.mux = _mux()
        self.session = make_session(mux=self.mux, target_id="t1")
        self.host = _Host(self.session, pages if pages is not None else ["t1"])
        self.viewer = _Viewer()
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.task = asyncio.create_task(
            screencast.run_live_view(cast(Any, self.host), self.session, cast(Any, self.viewer))
        )
        await self.attached(1)

    async def attached(self, count: int) -> None:
        for _ in range(200):
            if len(self.mux.attached) >= count and "Page.startScreencast" in self.mux.methods:
                return
            await asyncio.sleep(0)
        raise AssertionError(f"never attached {count} times: {self.mux.methods}")

    @property
    def page_session(self) -> str:
        return self.mux.attached[-1]

    def frame(self, data: str, session: str | None = None) -> None:
        self.mux.emit(
            {
                "method": "Page.screencastFrame",
                "sessionId": session or self.page_session,
                "params": {
                    "data": data,
                    "sessionId": 7,
                    "metadata": {"deviceWidth": 800, "deviceHeight": 600},
                },
            }
        )

    async def finish(self) -> None:
        assert self.task is not None
        await asyncio.wait_for(self.task, 1.0)


async def _settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


async def test_its_own_pages_frames_reach_the_viewer_with_the_tab_and_its_css_size() -> None:
    run = _Run()
    await run.start()

    run.frame("<jpeg>")
    await asyncio.wait_for(run.viewer.got_frame.wait(), 1.0)
    run.viewer.leave()
    await run.finish()

    assert run.viewer.sent == [
        {
            "type": "frame",
            "data": "<jpeg>",
            "format": "jpeg",
            "url": "https://example.com/",
            "title": "Ex",
            "favicon": _FAVICON,
            "cssWidth": 800,
            "cssHeight": 600,
        }
    ]
    assert run.mux.params_for("Page.startScreencast")[0] == {
        "format": "jpeg",
        "quality": 72,
        "maxWidth": BROWSER_VIEWPORT_WIDTH,
        "maxHeight": BROWSER_VIEWPORT_HEIGHT,
    }


async def test_every_frame_is_acked_even_when_the_viewer_is_behind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _Run()
    stuck = asyncio.Event()

    async def _behind(_raw: str) -> None:
        await stuck.wait()

    monkeypatch.setattr(run.viewer, "send_text", _behind)
    await run.start()

    for index in range(5):
        run.frame(f"f{index}")
    await _settle()

    acks = [c for c in run.mux.calls if c[0] == "Page.screencastFrameAck"]
    assert len(acks) == 5
    assert all(
        session == run.page_session and params == {"sessionId": 7} for _, params, session in acks
    )
    run.viewer.leave()
    await run.finish()


async def test_a_main_frame_navigation_refreshes_the_tab_and_a_subframe_does_not() -> None:
    run = _Run()
    await run.start()
    reads = run.mux.methods.count("Target.getTargetInfo")

    run.mux.emit(
        {
            "method": "Page.frameNavigated",
            "sessionId": run.page_session,
            "params": {"frame": {"parentId": "p"}},
        }
    )
    await _settle()
    assert run.mux.methods.count("Target.getTargetInfo") == reads
    run.mux.emit(
        {"method": "Page.frameNavigated", "sessionId": run.page_session, "params": {"frame": {}}}
    )
    await _settle()

    assert run.mux.methods.count("Target.getTargetInfo") == reads + 1
    run.viewer.leave()
    await run.finish()


async def test_the_viewers_input_drives_the_page_it_sees() -> None:
    run = _Run()
    await run.start()

    run.viewer.say(
        type="mouse", event="mousePressed", x=10, y=20, button="left", clickCount=1, junk=1
    )
    run.viewer.say(type="key", event="keyDown", key="a", text="a", modifiers=0)
    run.viewer.say(type="resize", width=640, height=480)
    run.viewer.say(type="unknown")
    run.viewer.leave()
    await run.finish()

    session = run.page_session
    assert (
        "Input.dispatchMouseEvent",
        {"type": "mousePressed", "x": 10, "y": 20, "button": "left", "clickCount": 1},
        session,
    ) in run.mux.calls
    assert (
        "Input.dispatchKeyEvent",
        {"type": "keyDown", "key": "a", "text": "a", "modifiers": 0},
        session,
    ) in run.mux.calls
    assert run.mux.params_for("Page.startScreencast")[-1] == {
        "format": "jpeg",
        "quality": 72,
        "maxWidth": 640,
        "maxHeight": 480,
    }


async def test_the_view_follows_the_agent_to_another_tab() -> None:
    run = _Run(pages=["t1", "t2"])
    await run.start()
    first = run.page_session

    run.host.move_focus("t2")
    await run.attached(2)
    run.frame("<second>")
    await asyncio.wait_for(run.viewer.got_frame.wait(), 1.0)
    run.viewer.leave()
    await run.finish()

    assert first in run.mux.detached
    assert ("Page.stopScreencast", None, first) in run.mux.calls
    assert run.mux.params_for("Target.attachToTarget")[-1] == {"targetId": "t2", "flatten": True}
    assert run.viewer.sent[0]["data"] == "<second>"


async def test_when_its_page_closes_the_view_moves_to_what_is_left_then_ends() -> None:
    run = _Run(pages=["t1", "t2"])
    await run.start()
    first = run.page_session

    run.host.pages.remove("t1")
    run.mux.emit({"method": "Target.detachedFromTarget", "params": {"sessionId": first}})
    await run.attached(2)
    run.host.pages.clear()
    run.mux.emit({"method": "Target.detachedFromTarget", "params": {"sessionId": run.page_session}})
    await run.finish()

    assert run.mux.params_for("Target.attachToTarget")[-1] == {"targetId": "t2", "flatten": True}
    assert ("Page.stopScreencast", None, first) not in run.mux.calls
    assert run.mux.closed is False


async def test_a_viewer_leaving_stops_the_screencast_and_lets_go_of_the_page() -> None:
    run = _Run()
    await run.start()
    page = run.page_session

    run.viewer.leave()
    await run.finish()

    assert ("Page.stopScreencast", None, page) in run.mux.calls
    assert run.mux.detached == [page]
    assert run.mux.sinks == []
    assert run.mux.closed is False


async def test_the_connection_closing_ends_the_view_without_another_word_to_the_engine() -> None:
    run = _Run()
    await run.start()
    sent = len(run.mux.calls)

    await run.mux.close()
    await run.finish()

    assert len(run.mux.calls) == sent


async def test_a_page_that_will_not_let_go_is_left_to_the_sessions_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _Run()
    await run.start()
    warning = MagicMock()
    monkeypatch.setattr(screencast.log, "warning", warning)
    run.mux.send_error = CdpCommandError({"message": "Target closed"})

    run.viewer.leave()
    await run.finish()

    assert warning.call_args.kwargs == {"error_type": "CdpCommandError"}


async def test_a_session_with_no_page_open_shows_nothing() -> None:
    run = _Run(pages=[])

    await screencast.run_live_view(cast(Any, run.host), run.session, cast(Any, run.viewer))

    assert run.mux.attached == []
    assert run.viewer.sent == []


async def test_a_page_that_refuses_evaluation_streams_without_a_favicon() -> None:
    run = _Run()
    run.mux.responses["Runtime.evaluate"] = {"result": {"value": 5}}
    await run.start()

    run.frame("<jpeg>")
    await asyncio.wait_for(run.viewer.got_frame.wait(), 1.0)
    run.viewer.leave()
    await run.finish()

    assert run.viewer.sent[0]["favicon"] is None


async def test_a_favicon_read_that_fails_is_warned_about_and_left_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mux = _mux()
    warning = MagicMock()
    monkeypatch.setattr(screencast.log, "warning", warning)

    async def _refuse(method: str, params: Any = None, session_id: Any = None) -> dict[str, Any]:
        raise CdpCommandError({"message": "no context"})

    monkeypatch.setattr(mux, "send_raw", _refuse)

    assert await screencast._read_favicon(cast(Any, mux), "S") is None
    assert warning.call_args.kwargs == {"error_type": "CdpCommandError"}
    assert "Could not read page favicon" in warning.call_args.args[0]


@pytest.mark.parametrize(
    ("engine", "pulls"), [(BrowserEngine.OBSCURA, True), (BrowserEngine.CHROMIUM, False)]
)
async def test_only_obscura_pulls_a_capture_while_the_screencast_is_quiet(
    monkeypatch: pytest.MonkeyPatch, engine: BrowserEngine, pulls: bool
) -> None:
    """Obscura screencasts only the session that repainted; Chromium screencasts every one."""
    monkeypatch.setattr(browser_host_settings, "BROWSER_ENGINE", engine)
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0.0)
    run = _Run()
    await run.start()

    await _settle()
    run.viewer.leave()
    await run.finish()

    assert ("Page.captureScreenshot" in run.mux.methods) is pulls
    if pulls:
        assert run.viewer.sent[0]["data"] == "<pulled>"
        assert run.viewer.sent[0]["cssWidth"] is None


async def test_a_pull_waits_while_frames_keep_arriving_and_carries_their_css_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _Run()
    stream = screencast._Stream(target_id="t1", page_session="S")
    frames: asyncio.Queue[screencast._Frame] = asyncio.Queue(maxsize=2)
    ticks = 0

    async def _tick(_seconds: float) -> None:
        nonlocal ticks
        ticks += 1
        if ticks == 1:
            stream.latest = screencast._Frame("<fresh>", 800, 600)
        if ticks == 4:
            raise asyncio.CancelledError

    monkeypatch.setattr(screencast.asyncio, "sleep", _tick)
    with pytest.raises(asyncio.CancelledError):
        await screencast._pull_frames(cast(Any, run.mux), stream, frames)

    assert run.mux.methods.count("Page.captureScreenshot") == 2
    pulled = frames.get_nowait()
    assert (pulled.data, pulled.css_width, pulled.css_height) == ("<pulled>", 800, 600)


async def test_a_failing_pull_is_warned_once_per_streak(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _Run()
    stream = screencast._Stream(target_id="t1", page_session="S")
    warned_at: list[int] = []
    warning = MagicMock(side_effect=lambda *a, **k: warned_at.append(ticks))
    monkeypatch.setattr(screencast.log, "warning", warning)
    failing = CdpCommandError({"message": "navigating"})
    # tick: 1-3 fail, 4 a screencast frame arrives, 5-7 fail, 8 succeeds, 9-11 fail
    plan = {1: failing, 4: "frame", 5: failing, 8: None, 9: failing, 12: "stop"}
    ticks = 0

    async def _tick(_seconds: float) -> None:
        nonlocal ticks
        ticks += 1
        step = plan.get(ticks)
        if step == "stop":
            raise asyncio.CancelledError
        if step == "frame":
            stream.latest = screencast._Frame("<cast>", 1, 1)
        elif ticks in plan:
            run.mux.send_error = cast(Any, step)

    monkeypatch.setattr(screencast.asyncio, "sleep", _tick)
    with pytest.raises(asyncio.CancelledError):
        await screencast._pull_frames(cast(Any, run.mux), stream, asyncio.Queue(maxsize=2))

    assert warned_at == [1, 5, 9]
    assert "Could not pull a live-view frame" in warning.call_args.args[0]
    assert warning.call_args.kwargs == {"error_type": "CdpCommandError"}


_ON_ITS_PAGE = {
    "Page.enable",
    "Page.startScreencast",
    "Page.stopScreencast",
    "Page.screencastFrameAck",
    "Page.captureScreenshot",
    "Runtime.evaluate",
    "Input.dispatchMouseEvent",
    "Input.dispatchKeyEvent",
}


async def test_everything_the_view_does_to_its_page_rides_its_own_page_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_ENGINE", BrowserEngine.OBSCURA)
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0.0)
    run = _Run()
    await run.start()
    run.frame("<jpeg>")
    run.viewer.say(type="mouse", event="mouseMoved", x=1, y=2)
    run.viewer.say(type="key", event="keyUp", key="a")
    run.viewer.say(type="resize")
    await _settle()
    page = run.page_session
    run.viewer.leave()
    await run.finish()

    on_page = [c for c in run.mux.calls if c[0] in _ON_ITS_PAGE]
    assert {c[0] for c in on_page} == _ON_ITS_PAGE
    assert all(session == page for _, _, session in on_page)
    assert (
        "Runtime.evaluate",
        {"expression": screencast._FAVICON_JS, "returnByValue": True},
        page,
    ) in run.mux.calls
    assert all(
        params == {"targetId": "t1"}
        for m, params, _ in run.mux.calls
        if m == "Target.getTargetInfo"
    )
    assert run.mux.params_for("Page.captureScreenshot")[0] == {"format": "jpeg", "quality": 72}
    assert run.mux.params_for("Page.startScreencast")[-1] == {
        "format": "jpeg",
        "quality": 72,
        "maxWidth": BROWSER_VIEWPORT_WIDTH,
        "maxHeight": BROWSER_VIEWPORT_HEIGHT,
    }


async def test_a_view_that_closes_logs_which_session_it_watched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = MagicMock()
    monkeypatch.setattr(screencast.log, "set", recorded)
    for pages, ends in ((["t1"], "leave"), ([], "nothing to show")):
        recorded.reset_mock()
        run = _Run(pages=pages)
        if ends == "leave":
            await run.start()
            run.viewer.leave()
            await run.finish()
        else:
            await screencast.run_live_view(cast(Any, run.host), run.session, cast(Any, run.viewer))

        recorded.assert_called_with(
            browser={"session_id": run.session.session_id, "operation": "live_view_closed"}
        )


async def test_a_viewer_whose_socket_closed_under_a_read_ends_the_view_cleanly() -> None:
    run = _Run()
    run.viewer.closed_under_read = True
    await run.start()

    run.viewer.leave()

    await run.finish()


async def test_a_page_that_never_answers_its_attach_fails_the_view_inside_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(screencast, "BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS", 0.01)
    run = _Run()
    run.mux.hang_on = "Target.attachToTarget"

    with pytest.raises(screencast.CDPTimeoutError):
        await screencast.run_live_view(cast(Any, run.host), run.session, cast(Any, run.viewer))


@pytest.mark.parametrize("hangs", ["Page.stopScreencast", "Target.detachFromTarget"])
async def test_a_page_that_never_lets_go_is_left_inside_the_budget(
    monkeypatch: pytest.MonkeyPatch, hangs: str
) -> None:
    warning = MagicMock()
    monkeypatch.setattr(screencast.log, "warning", warning)
    run = _Run()
    await run.start()
    monkeypatch.setattr(screencast, "BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS", 0.01)
    run.mux.hang_on = hangs

    run.viewer.leave()
    await run.finish()

    assert "left its page attached" in warning.call_args.args[0]
    assert warning.call_args.kwargs == {"error_type": "CDPTimeoutError"}


async def test_a_navigation_without_a_frame_and_a_tab_without_info_are_still_read() -> None:
    run = _Run()
    run.mux.responses["Target.getTargetInfo"] = {}
    run.mux.responses["Runtime.evaluate"] = {}
    await run.start()
    reads = run.mux.methods.count("Target.getTargetInfo")

    run.mux.emit({"method": "Page.frameNavigated", "sessionId": run.page_session, "params": {}})
    await _settle()
    run.frame("<jpeg>")
    await asyncio.wait_for(run.viewer.got_frame.wait(), 1.0)
    run.viewer.leave()
    await run.finish()

    assert run.mux.methods.count("Target.getTargetInfo") == reads + 1
    assert (
        run.viewer.sent[0]["url"],
        run.viewer.sent[0]["title"],
        run.viewer.sent[0]["favicon"],
    ) == (
        None,
        None,
        None,
    )


async def test_a_pull_on_obscura_carries_the_css_size_the_screencast_last_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_ENGINE", BrowserEngine.OBSCURA)
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", 0.0)
    run = _Run()
    await run.start()

    run.frame("<cast>")
    for _ in range(200):
        if any(f["data"] == "<pulled>" and f["cssWidth"] == 800 for f in run.viewer.sent):
            break
        await asyncio.sleep(0)
    run.viewer.leave()
    await run.finish()

    assert any(f["data"] == "<pulled>" and f["cssWidth"] == 800 for f in run.viewer.sent)


async def test_the_first_pull_captures_a_page_that_never_repainted() -> None:
    run = _Run()
    stream = screencast._Stream(target_id="t1", page_session="S")
    frames: asyncio.Queue[screencast._Frame] = asyncio.Queue(maxsize=2)
    ticks = 0

    async def _tick(_seconds: float) -> None:
        nonlocal ticks
        ticks += 1
        if ticks == 2:
            raise asyncio.CancelledError

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(screencast.asyncio, "sleep", _tick)
        with pytest.raises(asyncio.CancelledError):
            await screencast._pull_frames(cast(Any, run.mux), stream, frames)

    assert frames.get_nowait().data == "<pulled>"


async def test_a_pull_into_a_full_queue_is_dropped_and_the_pull_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _Run()
    stream = screencast._Stream(target_id="t1", page_session="S")
    frames: asyncio.Queue[screencast._Frame] = asyncio.Queue(maxsize=1)
    ticks = 0

    async def _tick(_seconds: float) -> None:
        nonlocal ticks
        ticks += 1
        if ticks == 4:
            raise asyncio.CancelledError

    monkeypatch.setattr(screencast.asyncio, "sleep", _tick)
    with pytest.raises(asyncio.CancelledError):
        await screencast._pull_frames(cast(Any, run.mux), stream, frames)

    assert run.mux.methods.count("Page.captureScreenshot") == 3


async def test_a_finished_side_task_leaves_the_views_set() -> None:
    background: set[asyncio.Task[Any]] = set()

    async def _done() -> None:
        return None

    screencast._spawn(background, _done())
    assert len(background) == 1
    await _settle()

    assert background == set()
