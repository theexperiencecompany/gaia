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
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import fakeredis.aioredis
from fastapi import FastAPI, HTTPException
from httpx import AsyncClient
import pytest
from starlette.requests import Request

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.endpoints import chat as chat_endpoint
from app.api.v1.middleware.tiered_rate_limiter import CostBudgetExceededException
from app.constants.cache import STREAM_TURN_DEDUP_PREFIX, STREAM_TURN_DEDUP_TTL
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.models.message_models import MessageRequestWithHistory
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
        runs.append(
            {
                "stream_id": stream_id,
                "conversation_id": conversation_id,
                "source": source,
                "user": user,
                "body": body,
            }
        )
        await stream_manager.publish_chunk(stream_id, TURN_FRAMES[0])
        await stream_manager.complete_stream(stream_id)

    monkeypatch.setattr(chat_endpoint, "run_chat_stream_background", _fake_turn)


# ---------------------------------------------------------------------------
# _resolve_source / _build_chat_context — the seams
# ---------------------------------------------------------------------------


def _request_with_headers(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": headers,
            "query_string": b"",
        }
    )


class TestResolveSource:
    """The X-Client-Type header → conversation source map, at the seam.

    Only the desktop app is trusted to claim a non-web source; anything
    else — absent, unknown, or a hostile casing — lands on web. A change
    that widened trust (or broke desktop detection) would silently route
    desktop-executed tools to the wrong tier, so every branch is exact.
    """

    def test_absent_header_resolves_to_web(self) -> None:
        assert chat_endpoint._resolve_source(_request_with_headers([])) == "web"

    def test_desktop_header_resolves_to_desktop(self) -> None:
        request = _request_with_headers([(b"x-client-type", b"desktop")])
        assert chat_endpoint._resolve_source(request) == "desktop"

    def test_header_is_trimmed_and_case_insensitive(self) -> None:
        request = _request_with_headers([(b"x-client-type", b"  DESKTOP  ")])
        assert chat_endpoint._resolve_source(request) == "desktop"

    def test_unknown_client_type_resolves_to_web(self) -> None:
        request = _request_with_headers([(b"x-client-type", b"mobile")])
        assert chat_endpoint._resolve_source(request) == "web"


class TestBuildChatContext:
    """The exact wide-event chat context, at the seam.

    Every field is derived behavior — a wrong count, a flipped boolean, or a
    missed attachment silently corrupts the per-turn wide event that chat
    product decisions read. Two payloads (bare and fully-loaded) pin every
    branch; the wire-level call is pinned by ``TestChatStreamEndpoint``.
    """

    def test_minimal_body(self) -> None:
        body = MessageRequestWithHistory(
            message="hi",
            messages=[{"role": "user", "content": "hi"}],
        )

        assert chat_endpoint._build_chat_context(body, "conv-1", "stream-1") == {
            "conversation_id": "conv-1",
            "stream_id": "stream-1",
            "is_new_conversation": True,
            "message_count": 1,
            "has_files": False,
            "file_count": 0,
            "tool_category": None,
            "has_reply": False,
            "has_calendar_event": False,
            "selected_workflow_id": None,
        }

    def test_fully_loaded_body(self) -> None:
        body = MessageRequestWithHistory(
            message="hi",
            conversation_id="conv-9",
            messages=[
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
            ],
            fileIds=["f1", "f2"],
            fileData=[
                {"fileId": "f3", "url": "http://files/f3", "filename": "f3.txt"}
            ],
            toolCategory="research",
            replyToMessage={"id": "m1", "content": "orig", "role": "user"},
            selectedCalendarEvent={
                "id": "evt-1",
                "summary": "Standup",
                "description": "",
                "start": {"dateTime": "2025-01-01T10:00:00Z"},
                "end": {"dateTime": "2025-01-01T10:30:00Z"},
            },
            selectedWorkflow={
                "id": "wf-9",
                "title": "Report",
                "description": "",
                "steps": [],
            },
        )

        assert chat_endpoint._build_chat_context(body, "conv-9", "stream-9") == {
            "conversation_id": "conv-9",
            "stream_id": "stream-9",
            "is_new_conversation": False,
            "message_count": 2,
            "has_files": True,
            "file_count": 3,
            "tool_category": "research",
            "has_reply": True,
            "has_calendar_event": True,
            "selected_workflow_id": "wf-9",
        }

    def test_files_without_file_data_still_count(self) -> None:
        """``has_files`` is the OR of the two attachment channels: a body
        carrying only ``fileIds`` (or only ``fileData``) still has files."""
        body = MessageRequestWithHistory(
            message="hi",
            messages=[{"role": "user", "content": "hi"}],
            fileIds=["f1"],
            fileData=[],
        )

        ctx = chat_endpoint._build_chat_context(body, "conv-1", "stream-1")

        assert ctx["has_files"] is True
        assert ctx["file_count"] == 1


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
        assert response.json()["detail"] == "Not authorized to subscribe to this stream"
        assert "Hello" not in response.text

    async def test_unknown_stream_is_404(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        as_user(FAKE_USER)

        response = await client.get(f"/api/v1/stream/{uuid4()}")

        assert response.status_code == 404
        assert response.json()["detail"] == "Stream not found"

    async def test_principal_without_user_id_is_400(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        as_user({**FAKE_USER, "user_id": None})
        stream_id = await seed_cancelled_turn(OWNER_ID, TURN_FRAMES)

        response = await client.get(f"/api/v1/stream/{stream_id}")

        assert response.status_code == 400
        assert response.json()["detail"] == "user_id is required"


class TestAlreadyCompleteShortCircuit:
    async def test_completed_stream_returns_exactly_one_done_frame(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        """A client that attaches after the turn ended must close, not replay.

        The event log outlives the turn by design (``cleanup`` keeps it), so
        dropping this branch would re-deliver every frame of a finished turn to
        a client that already rendered them.
        """
        as_user(FAKE_USER)
        stream_id = str(uuid4())
        await stream_manager.start_stream(
            stream_id=stream_id, conversation_id=str(uuid4()), user_id=OWNER_ID
        )
        for frame in TURN_FRAMES:
            await stream_manager.publish_chunk(stream_id, frame)
        await stream_manager.complete_stream(stream_id)

        response = await client.get(f"/api/v1/stream/{stream_id}")

        assert response.status_code == 200
        assert response.text == "data: [DONE]\n\n"
        assert Transcript.from_sse(response.text).kinds() == [DONE]


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
        # And it expires: a claim that never TTLs would grow unbounded in Redis.
        ttl = await fake_redis.ttl(f"{STREAM_TURN_DEDUP_PREFIX}{OWNER_ID}:turn-abc")
        assert 0 < ttl <= STREAM_TURN_DEDUP_TTL

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
# POST /api/v1/chat-stream — beyond dedup: context, cost wall, envelope
# ---------------------------------------------------------------------------


class TestChatStreamEndpoint:
    """The POST surface the dedup tests ride over: the 400 gate, the
    conversation/timezone/source plumbing into the turn, the cost wall, the
    exact wide event, and the response envelope.
    """

    async def test_principal_without_user_id_is_400(self) -> None:
        """The rate-limit wrapper's own 401 fires first over HTTP, so the
        endpoint's 400 is exercised at the unwrapped seam."""
        raw = chat_endpoint.chat_stream_endpoint.__wrapped__
        body = MessageRequestWithHistory(
            message="hi", messages=[{"role": "user", "content": "hi"}]
        )
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/chat-stream",
                "headers": [],
                "query_string": b"",
            }
        )

        with pytest.raises(HTTPException) as exc:
            await raw(request=request, body=body, user={"user_id": None}, home_timezone="UTC")

        assert exc.value.status_code == 400
        assert exc.value.detail == "user_id is required"

    async def test_new_conversation_gets_a_fresh_id_and_web_source(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        as_user(FAKE_USER)
        runs: list[dict[str, Any]] = []
        stub_turn(monkeypatch, runs)

        response = await client.post("/api/v1/chat-stream", json=chat_payload())

        assert response.status_code == 200
        assert len(runs) == 1
        # A fresh uuid must look like one — a "None" or "" stream id would
        # silently break every client that addresses the stream by id.
        assert UUID(runs[0]["conversation_id"])
        assert runs[0]["source"] == "web"
        # FAKE_USER stores "UTC" and no header is sent: the resolved zone is UTC.
        assert runs[0]["user"]["timezone"] == "UTC"

    async def test_existing_conversation_and_header_timezone_reach_the_turn(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        as_user(FAKE_USER)
        runs: list[dict[str, Any]] = []
        stub_turn(monkeypatch, runs)

        response = await client.post(
            "/api/v1/chat-stream",
            json=chat_payload(conversation_id="conv-123"),
            headers={"x-timezone": "America/New_York"},
        )

        assert response.status_code == 200
        assert runs[0]["conversation_id"] == "conv-123"
        # The stored "UTC" is healed from the header before the turn runs.
        assert runs[0]["user"]["timezone"] == "America/New_York"
        assert runs[0]["user"]["user_id"] == OWNER_ID
        # The parsed body (not a copy or None) reaches the turn, and the
        # progress record carries the owner + conversation for late viewers.
        assert runs[0]["body"].conversation_id == "conv-123"
        progress = await stream_manager.get_progress(runs[0]["stream_id"])
        assert progress is not None
        assert progress["conversation_id"] == "conv-123"
        assert progress["user_id"] == OWNER_ID

    async def test_client_type_header_selects_the_turn_source(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        as_user(FAKE_USER)
        runs: list[dict[str, Any]] = []
        stub_turn(monkeypatch, runs)

        desktop = await client.post(
            "/api/v1/chat-stream", json=chat_payload(), headers={"X-Client-Type": "desktop"}
        )
        other = await client.post(
            "/api/v1/chat-stream", json=chat_payload(), headers={"X-Client-Type": "mobile"}
        )

        assert (desktop.status_code, other.status_code) == (200, 200)
        assert runs[0]["source"] == "desktop"
        assert runs[1]["source"] == "web"

    async def test_cost_budget_wall_returns_429_and_runs_no_turn(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        blocked: list[tuple[str, str]] = []

        async def _blocked(user_id: str, feature_key: str) -> None:
            blocked.append((user_id, feature_key))
            raise CostBudgetExceededException(feature="chat_messages")

        monkeypatch.setattr(chat_endpoint, "enforce_daily_cost_budget", _blocked)
        as_user(FAKE_USER)
        runs: list[dict[str, Any]] = []
        stub_turn(monkeypatch, runs)

        response = await client.post("/api/v1/chat-stream", json=chat_payload())

        assert response.status_code == 429
        assert response.json()["detail"]["error"] == "rate_limit_exceeded"
        assert blocked == [(OWNER_ID, "chat_messages")]
        assert runs == []

    async def test_post_logs_the_exact_wide_event(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_log = MagicMock()
        monkeypatch.setattr(chat_endpoint, "log", mock_log)
        as_user(FAKE_USER)
        runs: list[dict[str, Any]] = []
        stub_turn(monkeypatch, runs)

        payload = chat_payload(
            message="hello there",
            messages=[
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "hello there"},
            ],
            conversation_id="conv-123",
            fileIds=["file-1", "file-2"],
            fileData=[
                {"fileId": "file-3", "url": "http://files/file-3", "filename": "f3.txt"}
            ],
            toolCategory="research",
            replyToMessage={"id": "m1", "content": "orig", "role": "user"},
            selectedCalendarEvent={
                "id": "evt-1",
                "summary": "Standup",
                "description": "",
                "start": {"dateTime": "2025-01-01T10:00:00Z"},
                "end": {"dateTime": "2025-01-01T10:30:00Z"},
            },
            selectedWorkflow={
                "id": "wf-9",
                "title": "Report",
                "description": "",
                "steps": [],
            },
            selectedTool="web_search",
        )
        response = await client.post("/api/v1/chat-stream", json=payload)

        assert response.status_code == 200
        mock_log.set.assert_called_once_with(
            user={"id": OWNER_ID},
            chat={
                "conversation_id": "conv-123",
                "stream_id": response.headers["x-stream-id"],
                "is_new_conversation": False,
                "message_count": 2,
                "has_files": True,
                "file_count": 3,
                "tool_category": "research",
                "has_reply": True,
                "has_calendar_event": True,
                "selected_workflow_id": "wf-9",
            },
            user_message_length=11,
            selected_tool="web_search",
        )

    async def test_post_response_envelope(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        as_user(FAKE_USER)
        runs: list[dict[str, Any]] = []
        stub_turn(monkeypatch, runs)

        response = await client.post("/api/v1/chat-stream", json=chat_payload())

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
        assert response.headers["x-stream-id"] == runs[0]["stream_id"]
        assert UUID(response.headers["x-stream-id"])
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["connection"] == "keep-alive"
        assert response.headers["x-accel-buffering"] == "no"
        # CORSMiddleware owns the CORS header; the endpoint must not pin one.
        assert "access-control-allow-origin" not in response.headers
        assert Transcript.from_sse(response.text).final_text() == "Hello"

    async def test_post_response_construction(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The exact ``StreamingResponse`` the POST builds, at the seam.

        Starlette lowercases response header names, so header-key casing is
        indistinguishable on the wire — but the endpoint's own dict is the
        contract, and a misspelled key would first show here. Same recording
        wrapper as the subscribe construction tests.
        """
        real = chat_endpoint.StreamingResponse
        constructed: list[dict[str, Any]] = []

        def recording(*args: Any, **kwargs: Any) -> Any:
            constructed.append(kwargs)
            return real(*args, **kwargs)

        monkeypatch.setattr(chat_endpoint, "StreamingResponse", recording)
        as_user(FAKE_USER)
        runs: list[dict[str, Any]] = []
        stub_turn(monkeypatch, runs)

        response = await client.post("/api/v1/chat-stream", json=chat_payload())

        assert response.status_code == 200
        assert constructed == [
            {
                "media_type": "text/event-stream",
                "headers": {
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "X-Stream-Id": runs[0]["stream_id"],
                },
            }
        ]

    async def test_empty_message_history_logs_zero_length(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An empty history must read as zero, not as one missing message.

        ``messages`` is required but may be ``[]``; the length expression's
        else-branch is the only thing standing between a client that sends an
        empty history and a wide event claiming one message existed.
        """
        mock_log = MagicMock()
        monkeypatch.setattr(chat_endpoint, "log", mock_log)
        as_user(FAKE_USER)
        runs: list[dict[str, Any]] = []
        stub_turn(monkeypatch, runs)

        response = await client.post(
            "/api/v1/chat-stream", json=chat_payload(messages=[])
        )

        assert response.status_code == 200
        chat = mock_log.set.call_args.kwargs["chat"]
        assert chat["message_count"] == 0
        assert mock_log.set.call_args.kwargs["user_message_length"] == 0

    async def test_turn_id_is_not_claimed_when_redis_is_down(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The dedup claim requires a live Redis; without one the send is
        accepted (and the client's turn_id means nothing). A mutant that
        dropped the ``and redis_cache.redis`` guard would crash on
        ``None.set`` and 500 instead of 200."""
        as_user(FAKE_USER)
        runs: list[dict[str, Any]] = []
        stub_turn(monkeypatch, runs)
        redis_cache.redis = None

        first = await client.post("/api/v1/chat-stream", json=chat_payload(turn_id="turn-abc"))
        second = await client.post(
            "/api/v1/chat-stream", json=chat_payload(turn_id="turn-abc")
        )

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


# ---------------------------------------------------------------------------
# _stream_from_redis — the failure branches
# ---------------------------------------------------------------------------


class TestStreamFromRedisErrorPaths:
    """The generator's failure branches: no Redis, a cancelled client, a
    broken subscription. Each must surface loudly — an error frame on the
    wire, a re-raised cancellation, or a logged error — never a silent hang.
    """

    async def test_redis_unavailable_yields_a_stream_error_frame(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_log = MagicMock()
        monkeypatch.setattr(chat_endpoint, "log", mock_log)
        redis_cache.redis = None
        stream_id = str(uuid4())

        body = [
            chunk
            async for chunk in chat_endpoint._stream_from_redis(
                stream_id, request_that_disconnects(asyncio.Event())
            )
        ]

        assert body == ["data: [STREAM_ERROR]\n\n"]
        mock_log.error.assert_called_once_with(
            f"{LogTag.CHAT} Redis unavailable for stream", stream_id=stream_id
        )

    async def test_stream_begins_the_log_context_boundary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The SSE delivery boundary is the wide-event seam for the stream.

        The operation name, the inherited trace id, and the stream id must
        all land on it — a boundary that drops them would silently discard
        every delivery outcome (disconnects, delivery errors).
        """
        monkeypatch.setattr(chat_endpoint, "get_trace_id", lambda: "trace-123")
        calls: list[tuple[Any, ...]] = []

        class _DummyBoundary:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *exc: Any) -> bool:
                return False

        def recording(
            operation: str, *, trace_id: str | None = None, **initial: Any
        ) -> Any:
            calls.append((operation, trace_id, initial))
            return _DummyBoundary()

        monkeypatch.setattr(chat_endpoint, "log_context", recording)
        redis_cache.redis = None
        stream_id = str(uuid4())

        body = [
            chunk
            async for chunk in chat_endpoint._stream_from_redis(
                stream_id, request_that_disconnects(asyncio.Event())
            )
        ]

        assert body == ["data: [STREAM_ERROR]\n\n"]
        assert calls == [("sse_delivery", "trace-123", {"stream_id": stream_id})]

    async def test_cancellation_is_reraised_and_logged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_log = MagicMock()
        monkeypatch.setattr(chat_endpoint, "log", mock_log)
        stream_id = str(uuid4())

        async def _cancelled(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
            raise asyncio.CancelledError()
            yield  # pragma: no cover - unreachable; makes this an async generator

        monkeypatch.setattr(stream_manager, "subscribe_stream", _cancelled)
        generator = chat_endpoint._stream_from_redis(
            stream_id, request_that_disconnects(asyncio.Event())
        )

        with pytest.raises(asyncio.CancelledError):
            await generator.__anext__()

        mock_log.set.assert_called_once_with(client_disconnected=True)
        mock_log.info.assert_called_once_with(
            f"{LogTag.CHAT} Client connection cancelled", stream_id=stream_id
        )

    async def test_subscription_error_is_logged_and_the_stream_ends(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_log = MagicMock()
        monkeypatch.setattr(chat_endpoint, "log", mock_log)
        stream_id = str(uuid4())

        async def _explode(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
            raise RuntimeError("redis exploded")
            yield  # pragma: no cover - unreachable; makes this an async generator

        monkeypatch.setattr(stream_manager, "subscribe_stream", _explode)
        generator = chat_endpoint._stream_from_redis(
            stream_id, request_that_disconnects(asyncio.Event())
        )

        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()

        mock_log.error.assert_called_once_with(
            f"{LogTag.CHAT} Error streaming to client",
            stream_id=stream_id,
            error_type="RuntimeError",
            error="redis exploded",
        )

    async def test_disconnect_logs_the_exact_wide_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_log = MagicMock()
        monkeypatch.setattr(chat_endpoint, "log", mock_log)
        stream_id = str(uuid4())
        await stream_manager.start_stream(
            stream_id=stream_id, conversation_id=str(uuid4()), user_id=OWNER_ID
        )
        await stream_manager.publish_chunk(stream_id, TURN_FRAMES[0])
        disconnected = asyncio.Event()
        generator = chat_endpoint._stream_from_redis(
            stream_id, request_that_disconnects(disconnected)
        )

        assert (await generator.__anext__()).endswith(TURN_FRAMES[0])

        disconnected.set()
        await stream_manager.publish_chunk(stream_id, TURN_FRAMES[1])
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()

        mock_log.set.assert_called_once_with(client_disconnected=True)
        mock_log.info.assert_called_once_with(
            f"{LogTag.CHAT} Client disconnected, stream continues in background",
            stream_id=stream_id,
        )


# ---------------------------------------------------------------------------
# POST /api/v1/cancel-stream/{id}
# ---------------------------------------------------------------------------


class TestCancelStream:
    """Cancellation: ownership check, not-found soft failure, and the cancel
    itself landing in Redis.
    """

    async def test_owner_cancels_their_stream(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_log = MagicMock()
        monkeypatch.setattr(chat_endpoint, "log", mock_log)
        as_user(FAKE_USER)
        stream_id = str(uuid4())
        await stream_manager.start_stream(
            stream_id=stream_id, conversation_id=str(uuid4()), user_id=OWNER_ID
        )

        response = await client.post(f"/api/v1/cancel-stream/{stream_id}")

        assert response.status_code == 200
        assert response.json() == {"success": True, "stream_id": stream_id, "error": None}
        assert await stream_manager.is_cancelled(stream_id) is True
        mock_log.set.assert_called_once_with(user={"id": OWNER_ID}, chat={"stream_id": stream_id})
        mock_log.info.assert_called_once_with(
            f"{LogTag.CHAT} Cancel stream request", stream_id=stream_id, success=True
        )

    async def test_unknown_stream_fails_softly(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        as_user(FAKE_USER)

        response = await client.post(f"/api/v1/cancel-stream/{uuid4()}")

        assert response.status_code == 200
        assert response.json()["success"] is False
        assert response.json()["error"] == "Stream not found"

    async def test_another_users_stream_is_403(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        as_user(FAKE_USER_2)
        stream_id = str(uuid4())
        await stream_manager.start_stream(
            stream_id=stream_id, conversation_id=str(uuid4()), user_id=OWNER_ID
        )

        response = await client.post(f"/api/v1/cancel-stream/{stream_id}")

        assert response.status_code == 403
        assert response.json()["detail"] == "Not authorized to cancel this stream"


# ---------------------------------------------------------------------------
# The response envelope: exact headers, media type, construction, and log calls
# ---------------------------------------------------------------------------

#: Every header the subscribe endpoint must set itself, on BOTH paths. The DONE
#: short-circuit and the live attach share one envelope (same media type, same
#: anti-caching headers, same CORS header) — asserted against the same dict.
_EXPECTED_SUBSCRIBE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "Access-Control-Allow-Origin": "*",
}

_SSE_CONTENT_TYPE = "text/event-stream; charset=utf-8"


async def _seed_completed_stream(user_id: str) -> str:
    """A stream whose event log is terminated with ``is_complete`` true.

    The one state that takes the already-complete short-circuit: progress
    present and ``is_complete`` true, so the endpoint returns ``[DONE]``
    instead of streaming the log again.
    """
    stream_id = str(uuid4())
    await stream_manager.start_stream(
        stream_id=stream_id, conversation_id=str(uuid4()), user_id=user_id
    )
    for frame in TURN_FRAMES:
        await stream_manager.publish_chunk(stream_id, frame)
    await stream_manager.complete_stream(stream_id)
    return stream_id


class TestSubscribeResponseSurface:
    """The exact envelope a subscriber receives, on both paths.

    The frame bodies are pinned byte-for-byte by the replay tests above; this
    pins the response itself — status, media type, and every header. Dropping
    any header (or changing its value) here would be a silent wire contract
    break, so each is asserted exactly.
    """

    async def test_already_complete_envelope(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        as_user(FAKE_USER)
        stream_id = await _seed_completed_stream(OWNER_ID)

        response = await client.get(f"/api/v1/stream/{stream_id}")

        assert response.status_code == 200
        assert response.headers["content-type"] == _SSE_CONTENT_TYPE
        for name, value in _EXPECTED_SUBSCRIBE_HEADERS.items():
            assert response.headers[name] == value

    async def test_live_envelope(
        self, client: AsyncClient, as_user: Callable[[dict[str, Any]], None]
    ) -> None:
        as_user(FAKE_USER)
        stream_id = await seed_cancelled_turn(OWNER_ID, TURN_FRAMES)

        response = await client.get(f"/api/v1/stream/{stream_id}")

        assert response.status_code == 200
        assert response.headers["content-type"] == _SSE_CONTENT_TYPE
        for name, value in _EXPECTED_SUBSCRIBE_HEADERS.items():
            assert response.headers[name] == value


class TestSubscribeResponseConstruction:
    """The exact ``StreamingResponse`` the endpoint builds, at the seam.

    The HTTP envelope above proves what the client receives; this proves what
    the endpoint *constructs*. Starlette lowercases response header names in
    ``Response.init_headers``, so two spellings of a header name are
    indistinguishable on the wire — but the endpoint's own dict is the real
    contract, and the construction call is where a misspelled key or a dropped
    kwarg would first show. A recording wrapper around the module's
    ``StreamingResponse`` keeps the response streaming for real while capturing
    the exact kwargs.
    """

    async def test_already_complete_construction(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        real = chat_endpoint.StreamingResponse
        constructed: list[dict[str, Any]] = []

        def recording(*args: Any, **kwargs: Any) -> Any:
            constructed.append(kwargs)
            return real(*args, **kwargs)

        monkeypatch.setattr(chat_endpoint, "StreamingResponse", recording)

        as_user(FAKE_USER)
        stream_id = await _seed_completed_stream(OWNER_ID)

        response = await client.get(f"/api/v1/stream/{stream_id}")

        assert response.status_code == 200
        assert constructed == [
            {
                "media_type": "text/event-stream",
                "headers": _EXPECTED_SUBSCRIBE_HEADERS,
            }
        ]

    async def test_live_construction(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        real = chat_endpoint.StreamingResponse
        constructed: list[dict[str, Any]] = []

        def recording(*args: Any, **kwargs: Any) -> Any:
            constructed.append(kwargs)
            return real(*args, **kwargs)

        monkeypatch.setattr(chat_endpoint, "StreamingResponse", recording)

        as_user(FAKE_USER)
        stream_id = await seed_cancelled_turn(OWNER_ID, TURN_FRAMES)

        response = await client.get(f"/api/v1/stream/{stream_id}")

        assert response.status_code == 200
        assert constructed == [
            {
                "media_type": "text/event-stream",
                "headers": _EXPECTED_SUBSCRIBE_HEADERS,
            }
        ]


class TestSubscribeLogging:
    """The wide-event fields the subscribe paths emit, asserted exactly.

    ``log.set`` seeds the request context with the owner and the stream; each
    path's ``log.info`` names the branch taken. A dropped kwarg or a
    misspelled key would silently corrupt the wide event, so the calls are
    pinned in full.
    """

    async def test_already_complete_logs_owner_and_done(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_log = MagicMock()
        monkeypatch.setattr(chat_endpoint, "log", mock_log)
        as_user(FAKE_USER)
        stream_id = await _seed_completed_stream(OWNER_ID)

        response = await client.get(f"/api/v1/stream/{stream_id}")

        assert response.status_code == 200
        mock_log.set.assert_called_once_with(
            user={"id": OWNER_ID}, chat={"stream_id": stream_id}
        )
        mock_log.info.assert_called_once_with(
            f"{LogTag.CHAT} Executor stream already complete, returning [DONE]",
            stream_id=stream_id,
        )

    async def test_live_subscribe_logs_owner_and_attach(
        self,
        client: AsyncClient,
        as_user: Callable[[dict[str, Any]], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_log = MagicMock()
        monkeypatch.setattr(chat_endpoint, "log", mock_log)
        as_user(FAKE_USER)
        stream_id = await seed_cancelled_turn(OWNER_ID, TURN_FRAMES)

        response = await client.get(f"/api/v1/stream/{stream_id}")

        assert response.status_code == 200
        mock_log.set.assert_called_once_with(
            user={"id": OWNER_ID}, chat={"stream_id": stream_id}
        )
        mock_log.info.assert_called_once_with(
            f"{LogTag.CHAT} Client subscribed to executor stream",
            stream_id=stream_id,
        )
