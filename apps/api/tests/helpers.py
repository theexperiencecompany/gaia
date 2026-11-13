"""Shared test utilities for GAIA API tests."""

import asyncio
import base64
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterator,
    Mapping,
    Sequence,
)
from contextlib import ExitStack, asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import socket
import sys
import time
from types import ModuleType, SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch
import zoneinfo

from arq.connections import ArqRedis
from arq.jobs import JobDef
from bson import ObjectId
from bson.errors import InvalidId
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from langchain.agents.middleware.types import ToolCallRequest
from langchain.tools import ToolRuntime
from langchain_core.language_models import ModelProfile
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolCall
from motor.motor_asyncio import AsyncIOMotorCollection
from pydantic import Field
import pytest
import respx
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp
import time_machine
import uvicorn
from workos.session import SessionModule

from app.config.rate_limits import RateLimitConfig
from app.constants.analytics import AT_MOST_ONCE_TASK_NAME
from app.constants.chat import ConversationSource
from app.constants.db import LANGGRAPH_SETUP_LOCK_ID
from app.constants.hil import HIL_JEV_URL
from app.constants.trigger_gates import GateKind
from app.db.repositories.conversation_log import conversation_log_repository
from app.db.repositories.conversations import conversation_repository
from app.models.conversation_log_models import (
    LoggedEntry,
    Reply,
    ReplyOutcome,
    ReplySettled,
    UserMessage,
)
from app.models.email_verdict_models import EmailVerdictDocument
from app.models.quiet_hours_models import DEFAULT_QUIET_HOURS
from app.models.user_models import AuthenticatedUser, UserDocument
from app.services.conversation.mongo_log import MongoConversationLog
from app.services.providers.provider_credentials_service import ProviderConfig
from app.services.runtime.secrets_store import fernet_key_from
from app.utils.timezone import Timezone
from shared.py.wide_events import log, log_context

#: A well-formed user id with no users row behind it.
UNKNOWN_USER_ID = "6a387b78347776fca38bbd99"


async def users_get(user_id: str) -> UserDocument | None:
    """Stand in for user_repository.get: bson refuses a non-ObjectId, UNKNOWN_USER_ID has no row."""
    if not ObjectId.is_valid(user_id):
        raise InvalidId(f"{user_id!r} is not a valid ObjectId")
    if user_id == UNKNOWN_USER_ID:
        return None
    return UserDocument.model_validate({"id": user_id, "onboarding": {"completed": True}})


def session_set_cookie(name: str, value: str, max_age: int, *, secure: bool) -> str:
    """Spell the whole Set-Cookie header every session cookie (WorkOS or local) must carry."""
    header = f"{name}={value}; HttpOnly; Max-Age={max_age}; Path=/; SameSite=lax"
    return f"{header}; Secure" if secure else header


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


# The mutation lane runs a copy of apps/api outside the repo and says where the repo is.
LLM_STUB_DIR = (
    Path(os.environ.get("GAIA_REPO_ROOT") or Path(__file__).resolve().parents[3])
    / "tools"
    / "llm-stub"
)


def load_llm_stub_module(name: str) -> ModuleType:
    """Load one of tools/llm-stub's stdlib-only modules under its own name, as its siblings import it."""
    spec = importlib.util.spec_from_file_location(name, LLM_STUB_DIR / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"tools/llm-stub/{name}.py is missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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


@contextmanager
def trigger_gate_seams(tz: Timezone, *, now: datetime | None = None) -> Iterator[SimpleNamespace]:
    """Serve JEV at its Decisions URL and pin what decide_gate reads beside it: key, flag, PostHog, clock.

    Every gate kind is enforced, so a verdict is what the gate decided; a shadow test narrows it.
    Without now, the caller moves the clock.
    """
    gate = "app.services.triggers.trigger_gate"
    with (
        ExitStack() as clock,
        respx.mock(assert_all_called=False) as router,
        patch(
            "app.services.hil.jev_client.resolve",
            AsyncMock(return_value=ProviderConfig(api_key="or-key")),  # pragma: allowlist secret
        ),
        patch(f"{gate}.is_trigger_gates_enforced", AsyncMock(return_value=True)) as enforced,
        patch("app.models.trigger_gate_models.ENFORCED_GATE_KINDS", frozenset(GateKind)),
        patch(f"{gate}.capture", MagicMock()) as capture,
        patch(f"{gate}.get_profile_timezone", AsyncMock(return_value=tz)) as profile_tz,
        patch(
            f"{gate}.get_quiet_hours", AsyncMock(return_value=DEFAULT_QUIET_HOURS)
        ) as quiet_hours,
        patch(f"{gate}.user_wrote_in_thread", AsyncMock(return_value=True)) as wrote,
        patch(f"{gate}.workflow_repository.remember_gate_skip", AsyncMock()) as workflow_skips,
        patch(
            f"{gate}.todo_repository.remember_subscription_gate_skip", AsyncMock()
        ) as watch_skips,
        # What memory knows about the user, which the email verdict reads; none unless set.
        patch(
            "app.services.mail.email_verdict.memory_engine.get_core_context",
            AsyncMock(return_value=""),
        ) as core,
        patch(
            "app.services.mail.email_verdict.email_verdict_repository", FakeEmailVerdicts()
        ) as verdicts,
    ):
        if now is not None:
            clock.enter_context(time_machine.travel(now, tick=False))
        yield SimpleNamespace(
            jev=router.post(HIL_JEV_URL),
            enforced=enforced,
            capture=capture,
            tz=profile_tz,
            quiet_hours=quiet_hours,
            wrote=wrote,
            workflow_skips=workflow_skips,
            watch_skips=watch_skips,
            core=core,
            verdicts=verdicts,
        )


class FakeEmailVerdicts:
    """email_verdict_repository in memory, keyed as its unique index is: (user_id, message_id)."""

    def __init__(self) -> None:
        self.kept: dict[tuple[str, str], EmailVerdictDocument] = {}

    async def get(self, message_id: str, *, user_id: str) -> EmailVerdictDocument | None:
        return self.kept.get((user_id, message_id))

    async def keep(self, verdict: EmailVerdictDocument) -> None:
        self.kept[verdict.user_id, verdict.message_id] = verdict


# JEV answers, as P(true) per judgment, that the decision table reads as each bucket.
_BUCKET_ANSWERS: Mapping[str, Mapping[str, float]] = {
    "reply": {
        "is_person": 0.95,
        "asks_user": 0.9,
        "reports_issue": 0.1,
        "official": 0.05,
        "relevant": 0.8,
        "bulk": 0.05,
    },
    "act": {
        "is_person": 0.05,
        "asks_user": 0.6,
        "reports_issue": 0.95,
        "official": 0.05,
        "relevant": 0.6,
        "bulk": 0.1,
    },
    "fyi": {
        "is_person": 0.05,
        "asks_user": 0.05,
        "reports_issue": 0.05,
        "official": 0.05,
        "relevant": 0.9,
        "bulk": 0.05,
    },
    "junk": {
        "is_person": 0.05,
        "asks_user": 0.05,
        "reports_issue": 0.05,
        "official": 0.05,
        "relevant": 0.05,
        "bulk": 0.05,
    },
    "unsure": {
        "is_person": 0.05,
        "asks_user": 0.5,
        "reports_issue": 0.05,
        "official": 0.05,
        "relevant": 0.5,
        "bulk": 0.5,
    },
}


def email_verdict_answers(
    bucket: str,
    overrides: Mapping[str, float] | None = None,
    *,
    can_wait: float = 1.0,
    leaning: str = "meeting",
) -> dict[str, object]:
    """Return a Decisions body the email verdict reads as bucket, and its urgent answer; overrides win."""
    answers: dict[str, object] = {
        judgment: {"type": "noul", "noul": p}
        for judgment, p in {**_BUCKET_ANSWERS[bucket], **(overrides or {})}.items()
    }
    answers["urgent"] = {
        "type": "choice",
        "choice": "can_wait" if can_wait >= 0.5 else leaning,
        "probabilities": {"can_wait": can_wait, leaning: 1 - can_wait},
    }
    return {"answers": answers}


def reaction_answers(
    *, upset: float = 0.0, task: float = 1.0, sign_off: float = 0.0, emoji: str = "🔎"
) -> dict[str, object]:
    """Return a Decisions body for the instant reaction's three questions; needs_words takes the rest."""
    kinds: dict[str, float] = {
        "task": task,
        "sign_off": sign_off,
        "needs_words": round(1.0 - task - sign_off, 6),
    }
    top_kind = max(kinds, key=kinds.__getitem__)
    return {
        "answers": {
            "upset": {"type": "noul", "noul": upset},
            "kind": {
                "type": "choice",
                "choice": top_kind,
                "probabilities": kinds,
            },
            "emoji": {"type": "choice", "choice": emoji, "probabilities": {emoji: 1.0}},
        }
    }


@contextmanager
def local_timezone(tz_name: str) -> Iterator[None]:
    """Run the body with the process local timezone set, restoring it afterwards.

    datetime.now reads the local zone and datetime.now(UTC) does not, so a test
    that has to tell the two apart has to run where they differ. Asia/Kolkata
    is UTC+5:30, so anything near midnight separates them.
    """
    zoneinfo.ZoneInfo(tz_name)  # fail loudly on a zone this box does not have
    original = os.environ.get("TZ")
    try:
        os.environ["TZ"] = tz_name
        if hasattr(time, "tzset"):
            time.tzset()
        yield
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        if hasattr(time, "tzset"):
            time.tzset()


async def stored_conversation(
    conversations: AsyncIOMotorCollection, conversation_id: str
) -> dict[str, Any] | None:
    """Read a stored conversation's head with its messages, as the repository assembles them from entries."""
    head = await conversations.find_one({"conversation_id": conversation_id})
    if head is None:
        return None
    doc = await conversation_repository.get(conversation_id, user_id=head["user_id"])
    messages = [] if doc is None else [m.model_dump(exclude_none=True) for m in doc.messages]
    return {**head, "messages": messages}


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
    profile: ModelProfile | None = Field(default=ModelProfile(max_input_tokens=100_000))

    def bind_tools(self, tools: Any, **kwargs: Any) -> "BindableToolsFakeModel":
        return self


#: One (namespace, mode, payload) triple of a graph's astream(subgraphs=True).
GraphStreamEvent = tuple[tuple[str, ...], str, Any]


class ScriptedGraph:
    """A graph whose astream replays exactly the events handed to it.

    Drives the real stream translator (frames_for_stream_event) over shapes a
    real model wire never produces: an id-less message, a tool call announced
    before its text, arguments that never parse, a retraction mid-node.
    """

    def __init__(self, events: Sequence[tuple[Any, ...]]) -> None:
        self._events = events

    def astream(self, *_args: Any, **_kwargs: Any) -> AsyncGenerator[tuple[Any, ...], None]:
        events = self._events

        async def stream() -> AsyncGenerator[tuple[Any, ...], None]:
            for event in events:
                yield event

        return stream()


def message_chunk_event(
    *, message_id: str | None, content: str = "", **kwargs: Any
) -> GraphStreamEvent:
    """Build a messages-mode event carrying one assistant chunk."""
    return ((), "messages", (AIMessageChunk(id=message_id, content=content, **kwargs), {}))


def agent_update_event(message: AIMessage) -> GraphStreamEvent:
    """Build an updates-mode event closing the agent node with message as its reply."""
    return ((), "updates", {"agent": {"messages": [message]}})


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

    def with_config(self, _config: Any = None, **_kwargs: Any) -> "PassthroughFakeLLM":
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

    CI (the test-python service containers) sets USE_REAL_SERVICES=1 explicitly; a
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

    def __exit__(self, *_exc: Any) -> None:
        from sqlalchemy import event

        event.remove(self.engine, "before_cursor_execute", self._record)
        actual = max(0, len(self.statements) - self.warmup)
        assert actual == self.expected, (
            f"expected {self.expected} DB query(ies), got {actual}:\n"
            + "\n".join(f"  {statement}" for statement in self.statements)
        )


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


#: The CDP URL of the fake Browser-Use sessions the patch tests drive.
OBSCURA_TEST_CDP_URL = "ws://obscura.test:9300/devtools/browser/run-1"


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
    except BaseException:
        # A server stuck in startup never sees should_exit; cancel it rather than wait forever.
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    try:
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


async def drain_at_most_once_sends() -> None:
    """Wait for the gated sends capture spawned, so their outcome is observable."""
    await asyncio.gather(
        *(task for task in asyncio.all_tasks() if task.get_name() == AT_MOST_ONCE_TASK_NAME)
    )


CREDENTIAL_STORE_SECRET = "unit-test-instance-secret"


class InMemoryCredentialStore:
    """The credential store's Mongo rows, held encrypted in memory exactly as the service reads them."""

    def __init__(self) -> None:
        self.configs: dict[str, ProviderConfig] = {}

    def save(
        self,
        provider: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        account_id: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self.configs[provider] = ProviderConfig(
            api_key=api_key,
            base_url=base_url,
            model=None,
            preset=None,
            account_id=account_id,
            api_secret=api_secret,
        )

    async def find_by_provider(self, provider: str) -> SimpleNamespace | None:
        config = self.configs.get(provider)
        if config is None:
            return None
        ciphertext = Fernet(fernet_key_from(CREDENTIAL_STORE_SECRET)).encrypt(
            json.dumps(config.model_dump()).encode()
        )
        return SimpleNamespace(provider=provider, data_encrypted=ciphertext.decode())

    async def upsert_encrypted(self, provider: str, data_encrypted: str) -> None:
        plaintext = Fernet(fernet_key_from(CREDENTIAL_STORE_SECRET)).decrypt(data_encrypted)
        self.configs[provider] = ProviderConfig.model_validate_json(plaintext)

    async def delete(self, provider: str) -> bool:
        return self.configs.pop(provider, None) is not None


async def live_through(
    queue: ArqRedis,
    arrivals: Sequence[datetime],
    arrive: Callable[[datetime], Awaitable[object]],
    fire: Callable[[JobDef], Awaitable[object]],
) -> None:
    """Play arrivals and the queue on one clock: each arrival at its moment, each job when due.

    An arrival due with a job goes first. Raises when the queue never empties.
    """
    pending = sorted(arrivals)
    with time_machine.travel(pending[0], tick=False) as clock:
        for _ in range(4 * len(pending) + 8):
            jobs = sorted(await queue.queued_jobs(), key=lambda job: job.score)
            due = datetime.fromtimestamp(jobs[0].score / 1000, UTC) if jobs else None
            if pending and (due is None or pending[0] <= due):
                clock.move_to(pending[0])
                await arrive(pending.pop(0))
            elif due is not None:
                clock.move_to(due)
                await fire(jobs[0])
            else:
                return
    raise AssertionError(f"the queue never emptied: {await queue.queued_jobs()}")


def tool_call_request(
    tool_call: ToolCall,
    *,
    configurable: dict[str, object] | None = None,
    state: dict[str, object] | None = None,
) -> ToolCallRequest:
    """Build the request middleware sees for one tool call, run under configurable."""
    return ToolCallRequest(
        tool_call=tool_call,
        tool=None,
        state=state,
        runtime=ToolRuntime(
            state=state or {},
            context=None,
            config={"configurable": configurable or {}},
            stream_writer=None,
            tool_call_id=tool_call["id"],
            store=None,
        ),
    )


# ---------------------------------------------------------------------------
# JWT forging: stdlib HMAC, so a token test never trusts the library it tests
# ---------------------------------------------------------------------------

_HMAC_HASHES = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}

# Tokens minted by python-jose 3.5.0, the JWT library before PyJWT, exp 2100-01-01:
# a token issued before that swap stays live after the deploy and must still verify.
JOSE_AGENT_DEVICE_SECRET = "jose-fixture-agent-secret-" + "x" * 16  # pragma: allowlist secret
JOSE_MINTED_AGENT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1LWpvc2UiLCJyb2xlIjoiYWdlbnQiLCJleHAiOjQxMDI0NDQ4MDAsImlhdCI6MTc5MzcwMDAwMH0.Mv_SlZ6pQl8tr-LTEZjIKq9PUHg_8qLpdwjLhiSUhCs"  # gitleaks:allow — signed with a test secret
JOSE_MINTED_DEVICE_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1LWpvc2UiLCJkZXZpY2VfaWQiOiJkZXYtam9zZSIsImF1ZCI6ImRldmljZS1icmlkZ2UiLCJyb2xlIjoiZGV2aWNlIiwiaWF0IjoxNzkzNzAwMDAwLCJleHAiOjQxMDI0NDQ4MDB9.k1GPpR5z1WmoSx8sk357ksLYY-7fyPIPSuahtijDRfE"  # gitleaks:allow — signed with a test secret
#: Signed with the local-auth tests' TEST_SECRET; sub u-jose, ver 3.
JOSE_MINTED_SESSION_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1LWpvc2UiLCJleHAiOjQxMDI0NDQ4MDAsImlhdCI6MTc5MzcwMDAwMCwidmVyIjozfQ.EOIx7VzYc3TIr8In4C5e-2gac43qUvlVigEFlkve5DQ"  # gitleaks:allow — signed with a test secret
#: Signed with "a" * 64, the bot tests' BOT_SESSION_TOKEN_SECRET; platform telegram, tg-jose.
JOSE_MINTED_BOT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1LWpvc2UiLCJwbGF0Zm9ybSI6InRlbGVncmFtIiwicGxhdGZvcm1fdXNlcl9pZCI6InRnLWpvc2UiLCJyb2xlIjoiYm90IiwiZXhwIjo0MTAyNDQ0ODAwLCJpYXQiOjE3OTM3MDAwMDB9.9xTk_jz9LJ7g3opCxKLlhdSIPuQuVIpSkLcJIa0K8QA"  # gitleaks:allow — signed with a test secret
#: Signed with "x" * 40, the takeover tests' secret; session sess-jose.
JOSE_MINTED_TAKEOVER_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1LWpvc2UiLCJzZXNzaW9uX2lkIjoic2Vzcy1qb3NlIiwicm9sZSI6ImJyb3dzZXJfdGFrZW92ZXIiLCJleHAiOjQxMDI0NDQ4MDAsImlhdCI6MTc5MzcwMDAwMH0.p3fvSTs2zoH-aCJ5lNoAF5VcGjxrFSkQjSXC_jdUfWM"  # gitleaks:allow — signed with a test secret


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64url_json(value: Mapping[str, object]) -> str:
    return _b64url(json.dumps(value, separators=(",", ":")).encode())


def bot_jwt_claims(user_id: str, platform: str, platform_user_id: str) -> dict[str, object]:
    """Build the claims of a valid bot session JWT that expires in 15 minutes."""
    return {
        "sub": user_id,
        "platform": platform,
        "platform_user_id": platform_user_id,
        "role": "bot",
        "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
    }


def read_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a compact JWT's header and claims, unverified, without any JWT library."""
    header, claims, _ = token.split(".")
    return _b64url_json_decode(header), _b64url_json_decode(claims)


def _b64url_json_decode(segment: str) -> dict[str, Any]:
    decoded: dict[str, Any] = json.loads(
        base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    )
    return decoded


def forge_jwt(
    claims: Mapping[str, object],
    secret: str,
    *,
    alg: str = "HS256",
    header_alg: str | None = None,
    kid: str | None = None,
) -> str:
    """Sign claims as a compact HMAC JWT without any JWT library; header_alg forges the declared alg."""
    header = {"alg": header_alg or alg, "typ": "JWT", **({"kid": kid} if kid else {})}
    signing_input = f"{_b64url_json(header)}.{_b64url_json(claims)}"
    signature = hmac.new(secret.encode(), signing_input.encode(), _HMAC_HASHES[alg]).digest()
    return f"{signing_input}.{_b64url(signature)}"


def forge_rs256_jwt(claims: Mapping[str, object], key: rsa.RSAPrivateKey, *, kid: str) -> str:
    """Sign claims as a compact RS256 JWT with cryptography alone, the shape WorkOS access tokens take."""
    header = {"alg": "RS256", "typ": "JWT", "kid": kid}
    signing_input = f"{_b64url_json(header)}.{_b64url_json(claims)}"
    signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64url(signature)}"


def rsa_public_jwk(key: rsa.RSAPrivateKey, *, kid: str) -> dict[str, str]:
    """Publish an RSA key's public half as the JWK a JWKS endpoint serves."""
    numbers = key.public_key().public_numbers()

    def b64_int(value: int) -> str:
        return _b64url(value.to_bytes((value.bit_length() + 7) // 8, "big"))

    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": b64_int(numbers.n),
        "e": b64_int(numbers.e),
    }


WORKOS_TEST_CLIENT_ID = "client_workos_session_test"
WORKOS_TEST_KID = "sso_oidc_key_pair_test"


def workos_access_token_claims(**overrides: object) -> dict[str, object]:
    """Build the claims of a WorkOS access token that expires in five minutes."""
    now = int(time.time())
    claims: dict[str, object] = {
        "sub": "user_01WORKOS",
        "sid": "session_01WORKOS",
        "iat": now,
        "exp": now + 300,
    }
    return {**claims, **overrides}


def seal_workos_session(access_token: str, cookie_password: str, *, email: str) -> str:
    """Seal an access token into the wos-session cookie value, as WorkOS AuthKit does."""
    user = {
        "object": "user",
        "id": "user_01WORKOS",
        "email": email,
        "email_verified": True,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    return SessionModule.seal_data(
        {"access_token": access_token, "refresh_token": "refresh_test", "user": user},
        cookie_password,
    )


def hostile_jwts(claims: Mapping[str, object], secret: str) -> dict[str, str]:
    """Every way a token for claims can be wrong while still looking like one, by name."""
    genuine = forge_jwt(claims, secret)
    header, _, signature = genuine.split(".")
    return {
        "expired": forge_jwt({**claims, "exp": int(time.time()) - 60}, secret),
        "wrong_key": forge_jwt(claims, "a-completely-different-secret-" + "z" * 16),
        "alg_none": f"{_b64url_json({'alg': 'none', 'typ': 'JWT'})}.{_b64url_json(claims)}.",
        "other_hmac_alg": forge_jwt(claims, secret, alg="HS512"),
        "asymmetric_alg_header": forge_jwt(claims, secret, header_alg="RS256"),
        "tampered_payload": f"{header}.{_b64url_json({**claims, 'sub': 'intruder'})}.{signature}",
        "garbage": "not-a-jwt",
    }


async def log_history(
    conversation_id: str, user_id: str, messages: Sequence[Mapping[str, str]]
) -> None:
    """Log a finished exchange: each user message, then each bot reply settled as answering them.

    messages are what a client reads back: type ("user" or "bot"), response, and message_id.
    """
    log = MongoConversationLog(conversation_log_repository, lambda: datetime.now(UTC))
    asked: list[LoggedEntry] = []
    for message in messages:
        message_id = message.get("message_id") or f"m-{ObjectId()}"
        if message["type"] == "user":
            said = UserMessage(
                id=message_id, text=message["response"], surface=ConversationSource.WEB
            )
            asked.append((await log.append(conversation_id, user_id, said)).logged)
            continue
        reply = Reply(
            id=f"reply:{message_id}",
            reply_id=message_id,
            attempt_id=f"attempt:{message_id}",
            text=message["response"],
        )
        opened = (await log.append(conversation_id, user_id, reply)).logged
        settle = ReplySettled(
            id=f"settle:{message_id}",
            reply_id=message_id,
            outcome=ReplyOutcome.ANSWERED,
            answers=tuple(logged.entry.id for logged in asked),
            through=asked[-1].seq if asked else opened.seq,
            quote_target=None,
        )
        await log.append(conversation_id, user_id, settle)
        asked = []
