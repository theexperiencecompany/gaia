"""Shared test utilities for GAIA API tests."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import math
import os
import re
import socket
from typing import Any, ClassVar

from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, BaseMessage
from pydantic import Field
import pytest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp
import uvicorn

from app.config.rate_limits import RateLimitConfig
from app.constants.db import LANGGRAPH_SETUP_LOCK_ID
from app.models.user_models import AuthenticatedUser
from shared.py.wide_events import log, log_context


def effective_limit(config: RateLimitConfig, period: str) -> float:
    """Compute a comparable allowance for a period under RateLimitConfig's 0-semantics.

    0 is overloaded: a tier with BOTH periods 0 has no access at all
    (returns 0.0); otherwise a period of 0 means that period is uncapped
    (returns math.inf). Lets free and pro allowances be ordered directly
    despite 0 meaning either "no access" or "unlimited" by context.
    """
    if config.day <= 0 and config.month <= 0:
        return 0.0
    value = getattr(config, period)
    return math.inf if value <= 0 else float(value)


def pick_free_port() -> int:
    """Bind to port 0, read the OS-assigned port, then release it.

    For tests that need a real bound TCP port (a live uvicorn server an
    external process can actually dial into), not an in-process ASGI transport.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# Resolved DB is never 0 (the app's live DB, flushed by this helper's teardown).
# GAIA_REDIS_DB_BASE (default 8) moves the high-DB block; CI lanes get 8 + r*32
# (scripts/ci/test-services.sh runs Redis with --databases 448).
try:
    _TEST_REDIS_DB_BLOCK_START = int(os.environ.get("GAIA_REDIS_DB_BASE", "8"))
except ValueError:
    _TEST_REDIS_DB_BLOCK_START = 8
# Each lane owns a 32-DB stripe, giving 24 flushable DBs (8-31 for base 8,
# 40-63 for base 40, ...) with DB 0 of the server untouched.
_TEST_REDIS_STRIPE = 32
_TEST_REDIS_STRIPE_BASE = _TEST_REDIS_DB_BLOCK_START - (
    _TEST_REDIS_DB_BLOCK_START % _TEST_REDIS_STRIPE
)
_TEST_REDIS_DB_BLOCK_SIZE = _TEST_REDIS_STRIPE - (_TEST_REDIS_DB_BLOCK_START % _TEST_REDIS_STRIPE)


def worker_redis_url(base_url: str) -> str:
    """Return a Redis URL with a per-xdist-worker DB number that is safe to flush.

    The resolved DB is never 0 (the app's live DB); an unpinned or DB-0 URL is
    relocated into a high-DB block of 24 DBs starting at GAIA_REDIS_DB_BASE
    (default 8). Setting that to 8 + lane*32 gives each CI lane its own
    32-DB stripe on one shared Redis (see scripts/ci/test-services.sh).
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    try:
        worker_num = int(worker.removeprefix("gw"))
    except ValueError:
        worker_num = 0
    match = re.search(r"/(\d+)$", base_url)
    configured_db = int(match.group(1)) if match else 0
    # The per-lane block is 24 DBs wide, room for 24 workers with no wrapping;
    # wrapping only happens past 24 workers, a deliberate documented degradation.
    if configured_db:
        # Deliberate non-zero DB: offset per worker within this lane's stripe,
        # but never land on the stripe's DB 0.
        offset = (configured_db + worker_num) % _TEST_REDIS_STRIPE
        db = _TEST_REDIS_STRIPE_BASE + offset if offset else _TEST_REDIS_DB_BLOCK_START
    else:
        db = _TEST_REDIS_DB_BLOCK_START + (worker_num % _TEST_REDIS_DB_BLOCK_SIZE)
    if match:
        return re.sub(r"/\d+$", f"/{db}", base_url)
    return base_url.rstrip("/") + f"/{db}"


def worker_mongo_db_name(base_name: str | None = None) -> str:
    """Return a per-xdist-worker MongoDB database name.

    Same reason as worker_redis_url: fixtures wipe collections with
    delete_many({}) on setup/teardown, so a shared database lets one worker
    clear another's in-flight documents. Base defaults to GAIA_MONGO_DB_BASE
    (default gaia_test) so CI lanes can share one mongod without colliding.
    """
    base = base_name if base_name is not None else os.environ.get("GAIA_MONGO_DB_BASE", "gaia_test")
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    return f"{base}_{worker}"


class BindableToolsFakeModel(FakeMessagesListChatModel):
    """Fake chat model whose pre-programmed responses survive bind_tools().

    langchain-core >= 1.4 implements bind_tools on FakeMessagesListChatModel
    itself (delegating through bind), so no override is needed here anymore.
    Production code (create_agent.py) binds tools before every invocation;
    the returned RunnableBinding still routes ainvoke back into this fake,
    which answers from the messages it is shown.

    Every real chat LLM carries a context-window profile (init_*_llm pin it);
    fractional-token middleware raises without one, so the default here keeps
    graph-building tests on the same contract.
    """

    # bind_tools() override stays on purpose: the inherited implementation
    # returns a NEW RunnableBinding, but callers rely on the fake staying the same object.
    profile: dict[str, int] = Field(default={"max_input_tokens": 100_000})

    def bind_tools(self, tools: Any, **kwargs: Any) -> "BindableToolsFakeModel":
        return self


def create_fake_llm(responses: list[str]) -> BindableToolsFakeModel:
    return BindableToolsFakeModel(responses=[AIMessage(content=r) for r in responses])


def create_fake_llm_with_tool_calls(
    tool_calls_then_response: list[dict[str, Any] | str],
) -> BindableToolsFakeModel:
    messages: list[BaseMessage] = []
    for item in tool_calls_then_response:
        if isinstance(item, dict):
            messages.append(AIMessage(content="", tool_calls=[item]))
        else:
            messages.append(AIMessage(content=item))
    return BindableToolsFakeModel(responses=messages)


class PassthroughFakeLLM:
    """Base for hand-rolled fake LLMs that create_agent drives directly.

    create_agent reshapes the model before every call (with_config,
    bind_tools, bind, with_retry); each returns a new runnable in production,
    so these hand themselves back once here — subclasses write only ainvoke.
    Duck-typed rather than a BaseChatModel subclass so these answer from the
    messages they are shown, unlike FakeMessagesListChatModel's fixed list.
    Carries _llm_type and profile, the two attributes production middleware
    reads without invoking.
    """

    _llm_type = "passthrough-fake"
    profile: ClassVar[dict[str, Any]] = {"max_input_tokens": 100_000}

    def with_config(self, **_kwargs: Any) -> "PassthroughFakeLLM":
        return self

    def bind_tools(self, _tools: Any, **_kwargs: Any) -> "PassthroughFakeLLM":
        return self

    def bind(self, **_kwargs: Any) -> "PassthroughFakeLLM":
        return self

    def with_retry(self, **_kwargs: Any) -> "PassthroughFakeLLM":
        return self


def assert_tool_called(messages: list[BaseMessage], tool_name: str) -> None:
    tool_calls = extract_tool_calls(messages)
    names = [tc["name"] for tc in tool_calls]
    assert tool_name in names, f"Tool '{tool_name}' not found in tool calls. Found: {names}"


def extract_tool_calls(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            tool_calls.extend(msg.tool_calls)  # type: ignore[arg-type]  # langchain tool_calls typed loosely upstream
    return tool_calls


class MockAuthMiddleware(BaseHTTPMiddleware):
    """Injects a test user into request.state, standing in for WorkOSAuthMiddleware.

    WorkOS SSO can't be driven headlessly in a test, so every API-level test in
    this repo that needs "a signed-in user" swaps this in for the real auth
    middleware instead (see tests/integration/api/conftest.py and
    tests/integration/real/conftest.py). It does not touch any of the business logic
    under test — only the login step no automated test can perform for real.
    """

    def __init__(self, app, user: AuthenticatedUser):
        super().__init__(app)
        self._user = user

    async def dispatch(self, request: Request, call_next):
        request.state.authenticated = True
        request.state.user = self._user
        return await call_next(request)


class NoAuthMiddleware(BaseHTTPMiddleware):
    """Sets request.state to unauthenticated, for testing 401 responses."""

    async def dispatch(self, request: Request, call_next):
        request.state.authenticated = False
        request.state.user = None
        return await call_next(request)


class HeaderDrivenAuthMiddleware(BaseHTTPMiddleware):
    """Test-only stand-in for WorkOSAuthMiddleware that trusts an X-Test-User-Id header.

    Unlike MockAuthMiddleware (one fixed user baked in at app-construction
    time), this lets a single live server be hit as several different
    signed-in users by varying a request header per call.
    """

    async def dispatch(self, request: Request, call_next):
        user_id = request.headers.get("x-test-user-id")
        if user_id:
            request.state.authenticated = True
            request.state.user = AuthenticatedUser(
                user_id=user_id, auth_provider="workos", email=f"{user_id}@test.local"
            )
        else:
            request.state.authenticated = False
            request.state.user = None
        return await call_next(request)


def real_services_available() -> bool:
    """Return True when the run is allowed to dial real service containers.

    CI (the Dagger service container) sets USE_REAL_SERVICES=1 explicitly; a
    bare local run must stay offline.
    """
    return os.environ.get("USE_REAL_SERVICES", "0") == "1"


def skip_items_without_real_services(
    items: list[pytest.Item],
    reason: str = "requires USE_REAL_SERVICES=1 (Docker + real Postgres/Redis/MongoDB/ChromaDB)",
) -> None:
    """Skip collected items in place unless real services are available.

    Collection-time skip: fast (no connections, no imports of the real-infra
    stack) so a bare run reports an instant, visible skip instead of hanging
    on dead ports or failing with connection errors minutes later.
    """
    if real_services_available():
        return
    marker = pytest.mark.skip(reason=reason)
    for item in items:
        item.add_marker(marker)


class AssertNumDbCalls:
    """Assert exactly N SQL statements executed inside the block (Django's assertNumQueries pattern).

    Listens for SQLAlchemy before_cursor_execute on the given engine (sync or
    async) and dumps every captured statement on mismatch. warmup excludes
    the first statements that only establish the pool.
    """

    def __init__(self, expected: int, engine: Any, *, warmup: int = 0) -> None:
        self.expected = expected
        self.engine = engine
        self.warmup = warmup
        self.statements: list[str] = []

    def _record(
        self,
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: Any,
    ) -> None:
        self.statements.append(statement)

    def __enter__(self) -> "AssertNumDbCalls":
        from sqlalchemy import event

        event.listen(self.engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *_exc: Any) -> bool:
        from sqlalchemy import event

        event.remove(self.engine, "before_cursor_execute", self._record)
        actual = max(0, len(self.statements) - self.warmup)
        assert actual == self.expected, (
            f"expected {self.expected} DB query(ies), got {actual}:\n"
            + "\n".join(f"  {statement}" for statement in self.statements)
        )
        return False


def assert_num_db_calls(expected: int, engine: Any, *, warmup: int = 0) -> AssertNumDbCalls:
    """Context manager: fail if the block runs anything but expected SQL statements against engine.

    Attach to a real engine at the repository layer — N+1 and
    accidental-query regressions die here.
    """
    return AssertNumDbCalls(expected, engine, warmup=warmup)


class WideEventRecorder:
    """Captures every wide event a boundary flushes through the loguru sink.

    log.get() only ever sees the INNERMOST open boundary, so it cannot read
    fields a nested wide_task owns — and a fire-and-forget task that opens
    its own boundary (memory ingestion, ARQ jobs) is exactly that case. This
    stands in for the sink instead, so the assertion reads the event the code
    actually emitted:

        recorder = WideEventRecorder()
        with patch("shared.py.wide_events._loguru", recorder):
            await work()
        assert recorder.event("memory_retain")["memory_ingest"] == {...}
    """

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._ctx: dict[str, Any] = {}

    def bind(self, **kwargs: Any) -> "WideEventRecorder":
        self._ctx = kwargs
        return self

    def log(self, level: str, message: str) -> None:
        self.events.append({**self._ctx, "_message": message})

    def opt(self, **kwargs: Any) -> "WideEventRecorder":
        return self

    def __getattr__(self, name: str) -> Any:
        return lambda *a, **k: None

    def event(self, task: str) -> dict[str, Any]:
        """Return the single event emitted by the wide_task/log_context named task.

        Raises if that boundary emitted nothing or emitted twice.
        """
        matches = [event for event in self.events if event.get("task") == task]
        if len(matches) != 1:
            raise AssertionError(
                f"expected exactly one {task!r} event, got {len(matches)}; "
                f"emitted: {[event.get('task') for event in self.events]}"
            )
        return matches[0]


@asynccontextmanager
async def captured_wide_event(operation: str = "test") -> AsyncIterator[dict[str, Any]]:
    """Run a block inside a real wide-event boundary, exposing its live fields.

    log.warning/log.error append to the event's warnings/errors only inside
    a boundary — outside one every write is discarded — so this is what a
    test needs to prove a swallowed failure is actually observable.
    """
    async with log_context(operation):
        yield log.get()


@asynccontextmanager
async def pg_advisory_lock(
    conninfo: str, lock_id: int = LANGGRAPH_SETUP_LOCK_ID
) -> AsyncIterator[None]:
    """Hold Postgres advisory lock lock_id for the block, across processes."""
    import psycopg

    async with await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as conn:
        await conn.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
        try:
            yield
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))


#: How long a test's in-process ASGI server gets to start listening.
_ASGI_STARTUP_TIMEOUT_SECONDS = 5


@asynccontextmanager
async def serve_asgi(app: ASGIApp) -> AsyncIterator[str]:
    """Serve an ASGI app on a port the OS picks; yield its base URL.

    Binding port 0 leaves no window for another process to take a pre-picked
    port, and a server that never starts fails the test instead of yielding.
    """
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    )
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(_ASGI_STARTUP_TIMEOUT_SECONDS):
            while not server.started:
                if task.done():
                    task.result()
                    raise RuntimeError("test ASGI server exited before it started")
                await asyncio.sleep(0)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task
