"""The root-mounted live view, recap and step frames, opened only by the authority each was handed out with.

Runs the real live codes, takeover tokens and session registry against a
per-test Redis; only the viewer's socket and the host's stream are stand-ins.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast

import fakeredis.aioredis
from fastapi import FastAPI, Request, Response, WebSocket, status
from httpx import ASGITransport, AsyncClient
import pytest
from starlette.websockets import WebSocketDisconnect, WebSocketState
from tests.helpers import captured_wide_event

from app.api.v1.endpoints import browser_live_view as blv
from app.config.settings import settings
from app.services.browser import takeover_token
from app.services.browser.live_code import mint_live_code, revoke_handoff_live_code
from app.services.browser.registry import register_session
from app.services.browser.replay import create_replay_link
from app.services.browser.shot_store import store_step_screenshot
from app.services.browser.takeover_token import create_takeover_token

pytestmark = pytest.mark.unit

_BASE = "https://browser.test"
_HOST_STREAM = "ws://host/live/sess-1"


@pytest.fixture(autouse=True)
def _live_view_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_TAKEOVER_TOKEN_SECRET", "s" * 40, raising=False)
    monkeypatch.setattr("app.services.browser.links.settings.BROWSER_LIVE_VIEW_BASE_URL", _BASE)


@pytest.fixture
def events() -> list[dict[str, Any]]:
    """Each request's wide event, in order."""
    return []


@pytest.fixture
async def client(
    fake_redis: fakeredis.aioredis.FakeRedis, events: list[dict[str, Any]]
) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.include_router(blv.router)

    @app.middleware("http")
    async def _wide_event(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        async with captured_wide_event() as event:
            events.append(event)
            return await call_next(request)

    async with AsyncClient(transport=ASGITransport(app=app), base_url=_BASE) as http:
        yield http


class _Observed:
    """A fake socket end a test can wait on: every change it records wakes the waiters."""

    def __init__(self) -> None:
        self._changed = asyncio.Condition()

    async def _record(self) -> None:
        async with self._changed:
            self._changed.notify_all()

    async def until(self, holds: Callable[[], bool]) -> None:
        """Return once holds() is true, as of the last change this end recorded."""
        async with asyncio.timeout(2), self._changed:
            await self._changed.wait_for(holds)


class _Viewer(_Observed):
    """The viewer's end of a live-view socket: what it was sent, and how it was closed."""

    def __init__(self, says: list[str] | None = None, *, gone: bool = False) -> None:
        super().__init__()
        #: The viewer has left: a send fails the way Starlette fails one on a closed socket.
        self._gone = gone
        self.application_state = WebSocketState.CONNECTED
        self.client_state = WebSocketState.CONNECTED
        self.accepted = False
        self.close_code: int | None = None
        self.received: list[bytes | str] = []
        self._says = list(says or [])

    async def accept(self) -> None:
        self.accepted = True
        await self._record()

    async def close(self, code: int = status.WS_1000_NORMAL_CLOSURE) -> None:
        self.close_code = code
        self.application_state = WebSocketState.DISCONNECTED
        await self._record()

    async def send_bytes(self, data: bytes) -> None:
        if self._gone:
            self.client_state = WebSocketState.DISCONNECTED
            raise RuntimeError('Cannot call "send" once a close message has been sent.')
        self.received.append(data)
        await self._record()

    async def send_text(self, data: str) -> None:
        self.received.append(data)
        await self._record()

    async def receive_text(self) -> str:
        if self._says:
            return self._says.pop(0)
        await asyncio.Event().wait()
        raise WebSocketDisconnect


class _HostStream(_Observed):
    """The host's live stream: sends its frames, records input, and stays open until closed."""

    def __init__(self, frames: list[bytes | str] | None = None) -> None:
        super().__init__()
        self.opened = False
        self._frames = list(frames or [])
        self._closed = asyncio.Event()
        self.input: list[str] = []
        self.dialed: list[tuple[str, int | None]] = []

    def connect(self, url: str, max_size: int | None = 2**20) -> _HostStream:
        self.dialed.append((url, max_size))
        return self

    async def __aenter__(self) -> _HostStream:
        self.opened = True
        await self._record()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self._closed.set()

    def __aiter__(self) -> _HostStream:
        return self

    async def __anext__(self) -> bytes | str:
        if self._frames:
            return self._frames.pop(0)
        await self._closed.wait()
        raise StopAsyncIteration

    async def send(self, message: str) -> None:
        self.input.append(message)
        await self._record()


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> _HostStream:
    stream = _HostStream()
    monkeypatch.setattr("app.api.v1.endpoints.browser_live_view.websockets.connect", stream.connect)
    return stream


def _watch(viewer: _Viewer, code: str, token: str | None = None) -> asyncio.Task[None]:
    return asyncio.create_task(blv.live_view_ws(cast(WebSocket, viewer), code, t=token))


# --- step frames and the recap --------------------------------------------------


async def test_a_frame_the_worker_stored_is_served_by_the_url_it_returned(
    client: AsyncClient, events: list[dict[str, Any]]
) -> None:
    url = await store_step_screenshot(b"\xff\xd8jpeg-payload", "sess-1", 2)
    assert url is not None

    resp = await client.get(url.removeprefix(_BASE))

    assert (resp.status_code, resp.content) == (200, b"\xff\xd8jpeg-payload")
    assert resp.headers["content-type"] == "image/jpeg"
    for missing in (url.removeprefix(_BASE).replace("/2.jpg", "/3.jpg"), "/shots/never/2.jpg"):
        resp = await client.get(missing)
        assert (resp.status_code, resp.json()["detail"]) == (404, "Screenshot not found or expired")
    assert [event["browser"]["operation"] for event in events] == ["step_screenshot"] * 3


@pytest.mark.parametrize("index", ["..", "%2e%2e", "-", "1.jpg", "step_1"])
async def test_a_non_integer_frame_index_is_refused_by_the_route_itself(
    client: AsyncClient, index: str
) -> None:
    url = await store_step_screenshot(b"jpeg", "sess-1", 1)
    assert url is not None
    code = url.split("/shots/")[1].split("/")[0]

    assert (await client.get(f"/shots/{code}/{index}.jpg")).status_code == 422


async def test_a_recap_link_opens_its_slideshow_and_an_unknown_one_does_not(
    client: AsyncClient, events: list[dict[str, Any]]
) -> None:
    link = await create_replay_link("sess-1", ["https://cdn/1.jpg"])
    assert link is not None

    page = await client.get(link.removeprefix(_BASE))
    missing = await client.get("/replays/never-minted")

    assert page.status_code == 200
    assert "https://cdn/1.jpg" in page.text
    assert (missing.status_code, missing.json()["detail"]) == (404, "Recap not found or expired")
    assert [event["browser"] for event in events] == [
        {"operation": "replay_page", "session_id": "sess-1"},
        {"operation": "replay_page"},
    ]


# --- who may open the live view page --------------------------------------------


async def test_a_bot_link_opens_its_session_while_its_handoff_waits(
    client: AsyncClient, events: list[dict[str, Any]]
) -> None:
    await register_session("sess-1", "u1", live_ws=_HOST_STREAM)
    code = await mint_live_code("sess-1", "u1", "h1")

    page = await client.get(f"/live/{code}")

    assert page.status_code == 200
    assert "sess-1" in page.text
    assert events[-1]["browser"] == {"operation": "live_view_page", "session_id": "sess-1"}
    await revoke_handoff_live_code("h1")
    settled = await client.get(f"/live/{code}")
    assert (settled.status_code, settled.json()["detail"]) == (
        404,
        "Live view not found or expired",
    )
    assert events[-1]["browser"] == {"operation": "live_view_page"}


async def test_the_web_cards_token_opens_its_own_session(client: AsyncClient) -> None:
    await register_session("sess-1", "u1", live_ws=_HOST_STREAM)

    page = await client.get("/live/sess-1", params={"t": create_takeover_token("sess-1", "u1")})

    assert page.status_code == 200
    assert "sess-1" in page.text


@pytest.mark.parametrize(
    ("path", "token", "refused", "why"),
    [
        # A raw session id without a token is no authority at all: there is no cookie path.
        ("/live/sess-1", None, 404, "Live view not found or expired"),
        ("/live/sess-1", "not-a-token", 401, "Invalid or expired link"),
        ("/live/sess-2", ("sess-1", "u1"), 403, "Link does not match this session"),
        ("/live/sess-1", ("sess-1", "intruder"), 403, "Not authorized for this session"),
    ],
)
async def test_anything_else_is_turned_away_saying_why(
    client: AsyncClient,
    path: str,
    token: tuple[str, str] | str | None,
    refused: int,
    why: str,
) -> None:
    await register_session("sess-1", "u1", live_ws=_HOST_STREAM)
    await register_session("sess-2", "u2", live_ws=_HOST_STREAM)
    sent = create_takeover_token(*token) if isinstance(token, tuple) else token

    page = await client.get(path, params={"t": sent} if sent is not None else None)

    assert (page.status_code, page.json()["detail"]) == (refused, why)


async def test_a_bot_link_for_a_session_its_owner_no_longer_holds_is_refused(
    client: AsyncClient,
) -> None:
    await register_session("sess-1", "someone-else", live_ws=_HOST_STREAM)
    code = await mint_live_code("sess-1", "u1", "h1")

    assert (await client.get(f"/live/{code}")).status_code == status.HTTP_403_FORBIDDEN


# --- the live socket ------------------------------------------------------------


async def test_a_socket_relays_frames_out_and_input_in(
    fake_redis: fakeredis.aioredis.FakeRedis, host: _HostStream
) -> None:
    await register_session("sess-1", "u1", live_ws=_HOST_STREAM)
    host._frames = [b"\xff\xd8frame", '{"type":"meta"}']
    viewer = _Viewer(says=['{"type":"click"}'])

    async with captured_wide_event() as event:
        watching = _watch(viewer, "sess-1", create_takeover_token("sess-1", "u1"))
        await viewer.until(lambda: len(viewer.received) == 2)
        await host.until(lambda: bool(host.input))

    assert viewer.accepted
    assert event["browser"] == {"operation": "live_view_ws", "session_id": "sess-1"}
    # Unbounded: a full-page frame is larger than websockets' 1 MiB default.
    assert host.dialed == [(_HOST_STREAM, None)]
    assert viewer.received == [b"\xff\xd8frame", '{"type":"meta"}']
    assert host.input == ['{"type":"click"}']
    watching.cancel()
    await asyncio.gather(watching, return_exceptions=True)


async def test_a_refused_socket_is_closed_as_a_policy_violation_unopened(
    fake_redis: fakeredis.aioredis.FakeRedis, host: _HostStream
) -> None:
    await register_session("sess-1", "u1", live_ws=_HOST_STREAM)
    viewer = _Viewer()

    async with captured_wide_event() as event:
        await _watch(viewer, "sess-1", create_takeover_token("sess-1", "intruder"))

    assert (viewer.accepted, viewer.close_code) == (False, status.WS_1008_POLICY_VIOLATION)
    assert host.dialed == []
    assert event["warnings"][-1]["reason"] == "Not authorized for this session"


async def test_a_session_with_no_host_stream_closes_as_gone(
    fake_redis: fakeredis.aioredis.FakeRedis, host: _HostStream
) -> None:
    await register_session("sess-1", "u1", live_ws=None)
    viewer = _Viewer()

    async with captured_wide_event() as event:
        await _watch(viewer, "sess-1", create_takeover_token("sess-1", "u1"))

    assert (viewer.accepted, viewer.close_code) == (False, 4404)
    assert event["browser"] == {"operation": "live_view_ws", "session_id": "sess-1"}
    assert "host stream" in event["warnings"][-1]["msg"]


async def test_a_bot_link_socket_closes_the_moment_its_handoff_settles(
    fake_redis: fakeredis.aioredis.FakeRedis, host: _HostStream
) -> None:
    """Settled, nobody is to watch or drive that browser any more, an open socket included."""
    await register_session("sess-1", "u1", live_ws=_HOST_STREAM)
    code = await mint_live_code("sess-1", "u1", "h1")
    viewer = _Viewer()
    watching = _watch(viewer, code)
    await host.until(lambda: host.opened)
    # Open for as long as the handoff waits.
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(watching), 0.05)

    await revoke_handoff_live_code("h1")

    await asyncio.wait_for(watching, timeout=2)
    assert viewer.close_code is not None


async def test_a_web_socket_ends_when_its_token_lapses(
    fake_redis: fakeredis.aioredis.FakeRedis, host: _HostStream, monkeypatch: pytest.MonkeyPatch
) -> None:
    await register_session("sess-1", "u1", live_ws=_HOST_STREAM)
    token = create_takeover_token("sess-1", "u1")
    expiry = takeover_token.verify_takeover_token(token).exp
    # The token is read as a few milliseconds from lapsing.
    monkeypatch.setattr(takeover_token, "time", SimpleNamespace(time=lambda: expiry - 0.01))
    viewer = _Viewer()

    # Inside the token's last moments, not some floor of its own.
    await asyncio.wait_for(_watch(viewer, "sess-1", token), timeout=0.5)

    assert viewer.accepted and viewer.close_code is not None


async def test_an_unreachable_host_closes_the_viewer(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _refused(url: str, max_size: int | None = None) -> object:
        raise OSError("connection refused")

    monkeypatch.setattr("app.api.v1.endpoints.browser_live_view.websockets.connect", _refused)
    await register_session("sess-1", "u1", live_ws=_HOST_STREAM)
    viewer = _Viewer()

    async with captured_wide_event() as event:
        await asyncio.wait_for(
            _watch(viewer, "sess-1", create_takeover_token("sess-1", "u1")), timeout=2
        )

    assert viewer.accepted and viewer.close_code is not None
    assert event["warnings"][-1]["error_type"] == "OSError"


async def test_a_viewer_gone_mid_frame_ends_the_proxy_without_an_error(
    fake_redis: fakeredis.aioredis.FakeRedis, host: _HostStream
) -> None:
    """Starlette answers a send on a closed socket with a bare RuntimeError: a disconnect, not a fault."""
    await register_session("sess-1", "u1", live_ws=_HOST_STREAM)
    host._frames = [b"frame"]
    viewer = _Viewer(gone=True)

    await asyncio.wait_for(_watch(viewer, "sess-1", create_takeover_token("sess-1", "u1")), 2)

    assert viewer.close_code is not None
