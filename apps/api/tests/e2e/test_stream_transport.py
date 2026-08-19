"""The SSE transport itself: ownership, replay, turn dedup, client disconnect.

Everything here rides the real endpoint functions over a real ``StreamManager``
backed by ``fakeredis`` — Redis Streams semantics (``XADD``/``XREAD``, cursors,
entry ids) are the thing under test, so mocking them away would leave nothing.
Only the turn itself (``run_chat_stream_background``) is doubled, because what
the agent produces is covered elsewhere; what is covered here is what the
transport does with it.

Four seams, none of which had a test before:

* ``GET /api/v1/stream/{id}`` — 400/404/403 and the already-complete
  short-circuit. The 403 is the only thing stopping one user from reading
  another user's stream.
* ``Last-Event-ID`` — a reconnect must resume *after* the cursor. Replay goes
  through the same ``subscribe_stream`` as the live attach and differs only in
  its start cursor, so "attach, drop, re-attach, diff the bytes" is an exact
  assertion. If the header stopped reaching ``subscribe_stream``, every
  reconnect would replay from ``0-0`` and duplicate the whole turn.
* The ``turn_id`` SETNX claim — the only guard against a retried POST
  persisting the same user+bot message pair twice.
* Client disconnect — the headline claim in ``apps/api/CLAUDE.md``: the turn is
  decoupled from the HTTP request and still runs to completion and persists.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
import json
from typing import Any
from uuid import uuid4

import fakeredis.aioredis
from fastapi import FastAPI
from httpx import AsyncClient
import pytest
from starlette.requests import Request

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.endpoints import chat as chat_endpoint
from app.constants.cache import STREAM_EVENTS_PREFIX, STREAM_TURN_DEDUP_PREFIX
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.utils.agent_utils import format_sse_data
from tests.conftest import FAKE_USER, FAKE_USER_2
from tests.e2e._harness.transcript import DONE, Transcript

pytestmark = pytest.mark.e2e

OWNER_ID: str = FAKE_USER["user_id"]
INTRUDER_ID: str = FAKE_USER_2["user_id"]

#: A turn's worth of frames, distinct enough that a duplicated replay is visible.
TURN_FRAMES = [
    format_sse_data({"response": word}) for word in ("Hello", " there", ", ", "friend", "!")
]

_ASGI_SPEC_VERSION = "2.3"  # what uvicorn advertises (uvicorn/protocols/http/h11_impl.py)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def fake_redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    """Point the module singleton at an in-process Redis with real Streams."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    original = redis_cache.redis
    redis_cache.redis = client
    yield client
    redis_cache.redis = original
    await client.flushall()
    await client.connection_pool.disconnect()


@pytest.fixture
def as_user(test_app: FastAPI) -> Iterator[Callable[[dict[str, Any]], None]]:
    """Swap the authenticated principal for one test, restoring the app after."""
    original = test_app.dependency_overrides.get(get_current_user)

    def _set(user: dict[str, Any]) -> None:
        test_app.dependency_overrides[get_current_user] = lambda: user

    yield _set

    if original is None:
        test_app.dependency_overrides.pop(get_current_user, None)
    else:
        test_app.dependency_overrides[get_current_user] = original


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def seed_cancelled_turn(user_id: str, frames: list[str]) -> str:
    """A subscribable stream whose event log is already terminated.

    Cancellation is the terminator used here on purpose: it leaves progress
    present and ``is_complete`` false, so ``GET /stream/{id}`` still goes
    through ``_stream_from_redis`` instead of taking the already-complete
    short-circuit (which is exercised separately). On the wire a cancelled
    turn ends with a bare ``data: [DONE]`` carrying no ``id:`` line.
    """
    stream_id = str(uuid4())
    await stream_manager.start_stream(
        stream_id=stream_id,
        conversation_id=str(uuid4()),
        user_id=user_id,
    )
    for frame in frames:
        await stream_manager.publish_chunk(stream_id, frame)
    await stream_manager.cancel_stream(stream_id)
    return stream_id


def chat_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "message": "hi",
        "messages": [{"role": "user", "content": "hi"}],
    }
    payload.update(overrides)
    return payload


def stub_turn(monkeypatch: pytest.MonkeyPatch, runs: list[dict[str, Any]]) -> None:
    """Replace the turn with one that emits a frame and completes."""

    async def _fake_turn(
        *,
        stream_id: str,
        body: Any,
        user: dict[str, Any],
        conversation_id: str,
        source: str | None = None,
    ) -> None:
        runs.append({"stream_id": stream_id, "conversation_id": conversation_id})
        await stream_manager.publish_chunk(stream_id, TURN_FRAMES[0])
        await stream_manager.complete_stream(stream_id)

    monkeypatch.setattr(chat_endpoint, "run_chat_stream_background", _fake_turn)


# ---------------------------------------------------------------------------
# GET /api/v1/stream/{id} — the guard rails
# ---------------------------------------------------------------------------


class TestSubscribeAuthorization:
    async def test_owner_receives_the_whole_turn(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        """Positive control: without this, the 403/404 tests prove nothing."""
        as_user(FAKE_USER)
        stream_id = await seed_cancelled_turn(OWNER_ID, TURN_FRAMES)

        response = await client.get(f"/api/v1/stream/{stream_id}")

        assert response.status_code == 200
        transcript = Transcript.from_sse(response.text)
        assert transcript.final_text() == "Hello there, friend!"

    async def test_another_users_stream_is_refused_and_leaks_nothing(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        as_user(FAKE_USER_2)
        stream_id = await seed_cancelled_turn(OWNER_ID, TURN_FRAMES)

        response = await client.get(f"/api/v1/stream/{stream_id}")

        assert response.status_code == 403
        assert "Hello" not in response.text

    async def test_unknown_stream_is_404(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        as_user(FAKE_USER)

        response = await client.get(f"/api/v1/stream/{uuid4()}")

        assert response.status_code == 404

    async def test_principal_without_user_id_is_400(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        as_user({**FAKE_USER, "user_id": None})
        stream_id = await seed_cancelled_turn(OWNER_ID, TURN_FRAMES)

        response = await client.get(f"/api/v1/stream/{stream_id}")

        assert response.status_code == 400


async def seed_completed_turn(user_id: str, frames: list[str]) -> str:
    """A stream terminated the way a real turn terminates, log intact.

    The producer publishes ``data: [DONE]`` into the log as an ordinary chunk
    and only then calls ``complete_stream`` (``services/chat/stream.py``,
    ``background/executor_runner.py``). The control entry that
    ``complete_stream`` writes is consumed by ``subscribe_stream`` and never
    reaches the wire, so seeding without the chunk would build a log no
    producer can actually create — and a replay of it would look like a client
    that never closes.
    """
    stream_id = str(uuid4())
    await stream_manager.start_stream(
        stream_id=stream_id,
        conversation_id=str(uuid4()),
        user_id=user_id,
    )
    for frame in [*frames, "data: [DONE]\n\n"]:
        await stream_manager.publish_chunk(stream_id, frame)
    await stream_manager.complete_stream(stream_id)
    return stream_id


class TestAlreadyCompleteShortCircuit:
    """``is_complete`` alone is not a reason to hang up.

    A HIL resume publishes its frames and closes inside ~100ms — quicker than
    the client's websocket-to-fetch round trip — so a short-circuit keyed on
    ``is_complete`` threw away nearly every resumed run: the next approval card
    never arrived and the turn sat on "Waiting for your approval" forever. The
    log outliving the turn is what makes the late attach recoverable, so the
    short-circuit is keyed on the log being *gone*, not on the turn being over.

    The unit tier (``unit/api/test_chat_stream_endpoint.py``) pins the same two
    branches with ``has_events`` and ``subscribe_stream`` mocked — which is
    precisely the code the fix leans on. This is the tier that runs them for
    real, over a real event log.
    """

    async def test_a_completed_turn_replays_its_whole_log_then_closes_once(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        as_user(FAKE_USER)
        stream_id = await seed_completed_turn(OWNER_ID, TURN_FRAMES)

        response = await client.get(f"/api/v1/stream/{stream_id}")

        assert response.status_code == 200
        transcript = Transcript.from_sse(response.text)
        assert transcript.final_text() == "Hello there, friend!"
        assert transcript.kinds().count(DONE) == 1, "the client would never close"
        assert transcript.kinds()[-1] == DONE

    async def test_an_expired_log_still_short_circuits_to_a_bare_done(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        """With nothing left to replay there is nothing to wait for either —
        without this branch the attach idles on keepalives until it times out."""
        as_user(FAKE_USER)
        stream_id = await seed_completed_turn(OWNER_ID, TURN_FRAMES)
        await redis_cache.redis.delete(f"{STREAM_EVENTS_PREFIX}{stream_id}")

        response = await client.get(f"/api/v1/stream/{stream_id}")

        assert response.status_code == 200
        assert response.text == "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Last-Event-ID replay
# ---------------------------------------------------------------------------


class TestLastEventIdReplay:
    async def test_reconnect_resumes_after_the_cursor_byte_for_byte(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        """The reconnect body is the exact tail of the first attach's body.

        Live and replay share ``subscribe_stream`` and differ only in the start
        cursor, so equality of the raw bytes is the honest assertion — not just
        "the right number of frames came back".
        """
        as_user(FAKE_USER)
        stream_id = await seed_cancelled_turn(OWNER_ID, TURN_FRAMES)

        first = await client.get(f"/api/v1/stream/{stream_id}")
        assert first.status_code == 200
        whole = Transcript.from_sse(first.text)
        event_ids = [frame.event_id for frame in whole.frames() if frame.event_id]
        assert len(event_ids) == len(TURN_FRAMES)

        resumed = await client.get(
            f"/api/v1/stream/{stream_id}",
            headers={"Last-Event-ID": event_ids[1]},
        )

        assert resumed.status_code == 200
        assert resumed.text == "".join(whole.raw()[2:])
        tail = Transcript.from_sse(resumed.text)
        assert [f.event_id for f in tail.frames() if f.event_id] == event_ids[2:]
        assert tail.final_text() == ", friend!"

    async def test_reconnect_without_the_header_replays_the_whole_turn(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        """The control for the test above: absent cursor means replay from 0-0."""
        as_user(FAKE_USER)
        stream_id = await seed_cancelled_turn(OWNER_ID, TURN_FRAMES)

        first = await client.get(f"/api/v1/stream/{stream_id}")
        again = await client.get(f"/api/v1/stream/{stream_id}")

        assert again.text == first.text
        assert Transcript.from_sse(again.text).final_text() == "Hello there, friend!"

    async def test_resuming_from_the_last_frame_yields_no_duplicates(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        as_user(FAKE_USER)
        stream_id = await seed_cancelled_turn(OWNER_ID, TURN_FRAMES)

        first = await client.get(f"/api/v1/stream/{stream_id}")
        event_ids = [f.event_id for f in Transcript.from_sse(first.text).frames() if f.event_id]

        resumed = await client.get(
            f"/api/v1/stream/{stream_id}",
            headers={"Last-Event-ID": event_ids[-1]},
        )

        assert Transcript.from_sse(resumed.text).kinds() == [DONE]
        assert resumed.text == "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# turn_id idempotency
# ---------------------------------------------------------------------------


class TestTurnDedup:
    async def test_retried_send_is_rejected_and_runs_the_turn_once(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
        fake_redis: fakeredis.aioredis.FakeRedis,
    ) -> None:
        as_user(FAKE_USER)
        runs: list[dict[str, Any]] = []
        stub_turn(monkeypatch, runs)
        payload = chat_payload(turn_id="turn-abc")

        first = await client.post("/api/v1/chat-stream", json=payload)
        second = await client.post("/api/v1/chat-stream", json=payload)

        assert first.status_code == 200
        assert second.status_code == 409
        assert second.json()["detail"] == "duplicate turn_id: this send was already accepted"
        assert len(runs) == 1
        # The claim holds the winning stream id, so a client can find its turn.
        claimed = await fake_redis.get(f"{STREAM_TURN_DEDUP_PREFIX}{OWNER_ID}:turn-abc")
        assert claimed == first.headers["X-Stream-Id"] == runs[0]["stream_id"]

    async def test_a_different_turn_id_is_accepted(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        as_user(FAKE_USER)
        runs: list[dict[str, Any]] = []
        stub_turn(monkeypatch, runs)

        first = await client.post("/api/v1/chat-stream", json=chat_payload(turn_id="turn-one"))
        second = await client.post("/api/v1/chat-stream", json=chat_payload(turn_id="turn-two"))

        assert (first.status_code, second.status_code) == (200, 200)
        assert len(runs) == 2

    async def test_the_claim_is_namespaced_per_user(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Two users can collide on a turn_id — it is client-generated."""
        runs: list[dict[str, Any]] = []
        stub_turn(monkeypatch, runs)
        payload = chat_payload(turn_id="turn-collide")

        as_user(FAKE_USER)
        owner = await client.post("/api/v1/chat-stream", json=payload)
        as_user(FAKE_USER_2)
        other = await client.post("/api/v1/chat-stream", json=payload)

        assert (owner.status_code, other.status_code) == (200, 200)
        assert len(runs) == 2

    async def test_sends_without_a_turn_id_are_never_deduped(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        as_user(FAKE_USER)
        runs: list[dict[str, Any]] = []
        stub_turn(monkeypatch, runs)

        first = await client.post("/api/v1/chat-stream", json=chat_payload())
        second = await client.post("/api/v1/chat-stream", json=chat_payload())

        assert (first.status_code, second.status_code) == (200, 200)
        assert len(runs) == 2


# ---------------------------------------------------------------------------
# Client disconnect
# ---------------------------------------------------------------------------


def request_that_disconnects(disconnected: asyncio.Event) -> Request:
    """A real Starlette Request whose receive channel drops when told to."""

    async def receive() -> dict[str, Any]:
        await disconnected.wait()
        return {"type": "http.disconnect"}

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
        },
        receive,
    )


class TestClientDisconnect:
    async def test_forwarding_stops_at_the_disconnect_but_the_turn_runs_on(self) -> None:
        """``_stream_from_redis`` stops forwarding; the turn keeps publishing.

        Asserted on the generator directly because the disconnect check lives
        there — the frames published after the client is gone must reach Redis
        (and therefore a later re-attach) but must not reach this client.
        """
        stream_id = str(uuid4())
        await stream_manager.start_stream(
            stream_id=stream_id, conversation_id=str(uuid4()), user_id=OWNER_ID
        )
        disconnected = asyncio.Event()
        first_delivered = asyncio.Event()
        persisted: list[str] = []

        async def turn() -> None:
            await stream_manager.publish_chunk(stream_id, TURN_FRAMES[0])
            await first_delivered.wait()
            for frame in TURN_FRAMES[1:]:
                await stream_manager.publish_chunk(stream_id, frame)
            persisted.append(stream_id)
            await stream_manager.complete_stream(stream_id)

        task = asyncio.create_task(turn())
        delivered: list[str] = []
        request = request_that_disconnects(disconnected)

        async for chunk in chat_endpoint._stream_from_redis(stream_id, request):
            delivered.append(chunk)
            disconnected.set()
            first_delivered.set()

        await asyncio.wait_for(task, timeout=5)

        assert Transcript.from_sse("".join(delivered)).final_text() == "Hello"
        assert persisted == [stream_id]
        # Everything the client missed is still in the log for a re-attach.
        replayed = [chunk async for chunk in stream_manager.subscribe_stream(stream_id)]
        assert Transcript.from_sse("".join(replayed)).final_text() == "Hello there, friend!"

    async def test_the_generator_stops_reading_redis_at_the_disconnect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The disconnect must END the generator, not merely mute it.

        Its sibling above proves no further frame reaches the client, which a
        ``continue`` in place of the ``break`` satisfies just as well: the
        generator goes on consuming Redis for a client that is gone, holding the
        response open until the turn's own DONE — up to ``EXECUTOR_WAIT_TIMEOUT``
        later. One leaked generator per abandoned connection.

        Asserted on how much it *reads*, not on how long it takes. A drained
        generator does still stop once the log ends, so waiting on
        ``StopAsyncIteration`` passes either way (it just takes ten times as
        long); and a timing bound would be flaky by construction. Counting the
        reads is the difference itself.
        """
        stream_id = str(uuid4())
        await stream_manager.start_stream(
            stream_id=stream_id, conversation_id=str(uuid4()), user_id=OWNER_ID
        )
        reads = 0
        real_subscribe = stream_manager.subscribe_stream

        async def counting_subscribe(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
            nonlocal reads
            async for chunk in real_subscribe(*args, **kwargs):
                reads += 1
                yield chunk

        monkeypatch.setattr(stream_manager, "subscribe_stream", counting_subscribe)

        disconnected = asyncio.Event()
        await stream_manager.publish_chunk(stream_id, TURN_FRAMES[0])
        generator = chat_endpoint._stream_from_redis(
            stream_id, request_that_disconnects(disconnected)
        )
        first = await generator.__anext__()
        # The frame arrives behind its replay ``id:`` line (see the reconnect
        # tests), so this is the body, not a loose containment check.
        assert first.endswith(TURN_FRAMES[0])

        disconnected.set()
        for frame in TURN_FRAMES[1:]:
            await stream_manager.publish_chunk(stream_id, frame)
        await stream_manager.complete_stream(stream_id)

        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()

        # The delivered frame, plus the one whose arrival surfaced the
        # disconnect. Everything after it belongs to nobody.
        assert reads == 2, f"kept draining the log for a departed client: {reads} reads"

    async def test_turn_completes_and_persists_after_the_client_is_gone(
        self,
        test_app: FastAPI,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The turn outlives the connection — the claim in ``apps/api/CLAUDE.md``.

        What it defends is the *detachment*: replacing the
        ``asyncio.create_task(run_chat_stream_background(...))`` with a bare
        ``await`` deadlocks this test and nothing else. It does not defend
        GAIA's own ``is_disconnected()`` handling, which can be deleted outright
        with this test still green — Starlette's ``StreamingResponse`` installs
        its own disconnect listener and tears the response down on
        ``http.disconnect`` regardless. That handling is pinned by
        ``TestClientDisconnect`` above instead.

        Driven over raw ASGI rather than ``ASGITransport`` because httpx never
        emits ``http.disconnect`` — without a real disconnect message there is
        no disconnect to test. The scope advertises spec version 2.3, the same
        as uvicorn, so Starlette installs its disconnect listener exactly as it
        does in production.
        """
        as_user(FAKE_USER)
        client_gone = asyncio.Event()
        finished = asyncio.Event()
        saved: list[str] = []

        async def _fake_turn(
            *,
            stream_id: str,
            body: Any,
            user: dict[str, Any],
            conversation_id: str,
            source: str | None = None,
        ) -> None:
            await stream_manager.publish_chunk(stream_id, TURN_FRAMES[0])
            await client_gone.wait()
            for frame in TURN_FRAMES[1:]:
                await stream_manager.publish_chunk(stream_id, frame)
            saved.append(stream_id)
            await stream_manager.complete_stream(stream_id)
            finished.set()

        monkeypatch.setattr(chat_endpoint, "run_chat_stream_background", _fake_turn)

        body = json.dumps(chat_payload()).encode()
        disconnect = asyncio.Event()
        request_delivered = False
        received: list[str] = []
        headers: dict[str, str] = {}

        async def receive() -> dict[str, Any]:
            nonlocal request_delivered
            if not request_delivered:
                request_delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers.update({k.decode().lower(): v.decode() for k, v in message["headers"]})
            elif message["type"] == "http.response.body" and message.get("body"):
                received.append(message["body"].decode())
                disconnect.set()  # the client walks away after the first frame

        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": _ASGI_SPEC_VERSION},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/chat-stream",
            "raw_path": b"/api/v1/chat-stream",
            "root_path": "",
            "query_string": b"",
            "headers": [
                (b"host", b"test"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
            "client": ("127.0.0.1", 5000),
            "server": ("test", 80),
        }

        await asyncio.wait_for(test_app(scope, receive, send), timeout=10)

        # The HTTP response is over and the client saw exactly one frame.
        assert Transcript.from_sse("".join(received)).final_text() == "Hello"
        stream_id = headers["x-stream-id"]

        client_gone.set()
        await asyncio.wait_for(finished.wait(), timeout=10)

        assert saved == [stream_id], "the turn did not run to completion once the client left"
        progress = await stream_manager.get_progress(stream_id)
        assert progress is not None and progress["is_complete"] is True
        replayed = [chunk async for chunk in stream_manager.subscribe_stream(stream_id)]
        assert Transcript.from_sse("".join(replayed)).final_text() == "Hello there, friend!"
