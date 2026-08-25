"""End-to-end contracts of the wide-event pipeline — one test per shipped bug class.

Every test here is a regression lock on a bug that was proven in production
code while the unit suite stayed green: each asserts a *cross-component
contract* (facade × Starlette × sink × middleware order) using the real
components, mocking only the final emit boundary. If one of these goes red,
telemetry is silently broken in a way no per-function test can see.
"""

import asyncio
from contextlib import asynccontextmanager
import datetime
import json
from typing import Any
from unittest.mock import patch

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import pytest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.testclient import TestClient

from app.api.v1.middleware.logging import LoggingMiddleware
from app.api.v1.middleware.timeout import RequestTimeoutMiddleware
from app.core.app_factory import create_app
from app.core.middleware import configure_middleware
from shared.py.logging import MAX_JSON_LINE_BYTES, _json_stdout_sink, env_context
from shared.py.wide_events import (
    _event_state,
    get_trace_id,
    log,
    log_context,
    spawn_logged_task,
    wide_task,
)
from tests.helpers import WideEventRecorder


class _EmitRecorder:
    """Stands in for request_logger — captures the bound wide-event context."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._pending: dict[str, Any] = {}

    def bind(self, **context: Any) -> "_EmitRecorder":
        self._pending = dict(context)
        return self

    def log(self, level: str, message: str) -> None:
        self.events.append({**self._pending, "_level": level, "_message": message})


@pytest.fixture
def emitted():
    recorder = _EmitRecorder()
    with patch("app.api.v1.middleware.logging.request_logger", recorder):
        yield recorder.events


def _app_with_logging() -> FastAPI:
    app = FastAPI()
    app.add_middleware(LoggingMiddleware)
    return app


def test_app_code_cannot_clobber_the_service_identity(capsys):
    """`env`/`service`/`commit` must equal this process's infra identity, always.

    The shipped bug: env fields were merged BEFORE handler fields, so 16
    service-layer callers doing log.set(service="notes_service") overwrote the
    infra identity — `{service="gaia-backend"} | json | service="gaia-backend"`
    stopped agreeing with itself and dashboards under-counted silently.

    The guarantee now lives in the sink rather than in the middleware's dict
    ordering: `_build_json_entry` stamps the identity on EVERY line (matching
    what buildRecord does for the TypeScript bots) and re-emits a colliding app
    field as ctx_<key>. So this asserts the sink, which also covers the
    real-time lines the middleware never touched.
    """
    hijack = {"service": "HIJACKED", "env": "HIJACKED", "commit": "HIJACKED"}
    _json_stdout_sink(type("M", (), {"record": _record(hijack)})())
    line = json.loads(capsys.readouterr().out.strip())

    identity = env_context()
    assert line["service"] == identity["service"]
    assert line["env"] == identity["env"]
    assert line["commit"] == identity["commit"]
    # The attempt is preserved, just relocated — never silently dropped.
    assert line["ctx_service"] == line["ctx_env"] == line["ctx_commit"] == "HIJACKED"


def test_handler_fields_reach_the_emitted_event(emitted):
    """Handler/service log.set, set_ns and errors[] must survive call_next.

    The shipped bug: BaseHTTPMiddleware runs handlers in a copied context, and
    the rebind-based accumulator dropped every handler field from the emitted
    http_request line.
    """
    app = _app_with_logging()

    @app.get("/t")
    async def handler():
        log.set(todo={"operation": "create"})
        log.set_ns("todo", id="t_1")
        log.error("mid-flight failure", error_type="Boom")
        return {"ok": True}

    TestClient(app).get("/t")
    (event,) = emitted
    assert event["todo"] == {"operation": "create", "id": "t_1"}
    assert event["errors"][0]["error_type"] == "Boom"
    assert event["final_level"] == "ERROR"
    assert event["status_code"] == 200


@pytest.mark.regression
def test_a_second_set_of_a_namespace_merges_instead_of_replacing(emitted):
    """`log.set(ns={...})` must accumulate, exactly like `set_ns`.

    The shipped bug: `set` did a flat `fields.update()`, so a later whole-dict
    write REPLACED the namespace instead of merging into it. In production
    complete_execution's `log.set(workflow={...})` — the last write on a run, and
    the one that carries no trigger_type — erased that field from 34,247 of
    34,413 workflow fires, leaving no way to tell a scheduled fire from a webhook
    one. Every layer of a request writes the same namespace; whichever wrote last
    silently won.
    """
    app = _app_with_logging()

    @app.get("/t")
    async def handler():
        log.set(workflow={"id": "wf_1", "trigger_type": "schedule", "steps_count": 3})
        log.set(workflow={"id": "wf_1", "status": "success", "duration_ms": 12})
        return {"ok": True}

    TestClient(app).get("/t")
    (event,) = emitted
    assert event["workflow"] == {
        "id": "wf_1",
        "trigger_type": "schedule",
        "steps_count": 3,
        "status": "success",
        "duration_ms": 12,
    }


def test_set_and_set_ns_are_interchangeable(emitted):
    """Both setters merge into the namespace, in either order and either mix."""
    app = _app_with_logging()

    @app.get("/t")
    async def handler():
        log.set(todo={"operation": "create"})
        log.set_ns("todo", id="t_1")
        log.set(todo={"result_count": 2})
        return {"ok": True}

    TestClient(app).get("/t")
    (event,) = emitted
    assert event["todo"] == {"operation": "create", "id": "t_1", "result_count": 2}


def test_a_non_dict_value_still_replaces(emitted):
    """Only dict-into-dict merges. A scalar (or a scalar over a dict) overwrites —
    merging is about accumulating a namespace, not about never overwriting."""
    app = _app_with_logging()

    @app.get("/t")
    async def handler():
        log.set(outcome="pending", todo={"operation": "create"})
        log.set(outcome="done", todo="replaced-by-scalar")
        return {"ok": True}

    TestClient(app).get("/t")
    (event,) = emitted
    assert event["outcome"] == "done"
    assert event["todo"] == "replaced-by-scalar"


def test_user_identity_attached_from_request_state(emitted):
    """user.id auto-attaches from auth state (email stays out of the logs); handler-set fields win."""

    class FakeAuth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user = {"user_id": "u_state", "email": "s@x.com"}
            return await call_next(request)

    # Auth INSIDE the boundary, as in production.
    inner_app = FastAPI()

    @inner_app.get("/t")
    async def handler():
        log.set(user={"plan": "pro"})
        return {}

    inner_app.add_middleware(FakeAuth)
    inner_app.add_middleware(LoggingMiddleware)
    TestClient(inner_app).get("/t")
    (event,) = emitted
    assert event["user"] == {"id": "u_state", "plan": "pro"}


def test_timed_out_request_emits_event_with_partial_context(emitted):
    """A 504 must produce an http_request event carrying the handler's fields.

    The shipped bug: the timeout middleware sat OUTSIDE the logging boundary;
    anyio's cancellation killed the emit and the slowest requests were the
    only ones with zero telemetry.
    """
    app = FastAPI()
    app.add_middleware(RequestTimeoutMiddleware, timeout=0.2)
    app.add_middleware(LoggingMiddleware)  # outermost, as in production

    @app.get("/slow")
    async def slow():
        log.set(todo={"operation": "hang"})
        await asyncio.sleep(5)
        return {}

    response = TestClient(app).get("/slow")
    assert response.status_code == 504
    (event,) = emitted
    assert event["status_code"] == 504
    assert event["todo"] == {"operation": "hang"}


def test_rejections_by_inner_middleware_are_logged(emitted):
    """An auth-style early-return 401 must still emit an event (boundary is outermost)."""
    app = FastAPI()

    class Reject(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            log.set(auth_failure="invalid_session")
            return JSONResponse(status_code=401, content={"detail": "nope"})

    app.add_middleware(Reject)
    app.add_middleware(LoggingMiddleware)
    assert TestClient(app).get("/anything").status_code == 401
    (event,) = emitted
    assert event["status_code"] == 401
    assert event["auth_failure"] == "invalid_session"


def test_raised_http_exception_lands_in_errors_with_its_cause(emitted):
    """`raise HTTPException(500, ...) from e` must reach errors[] with the real cause.

    The shipped bug: Starlette's ExceptionMiddleware turns an HTTPException
    into a response INSIDE call_next, so the boundary's except path never sees
    it. Every one of the ~428 `raise HTTPException` sites emitted an event with
    final_level=ERROR but no `errors` key at all — the real failure (the
    exception the handler caught) was nowhere in the telemetry.
    """

    @asynccontextmanager
    async def _noop_lifespan(app: FastAPI):
        yield

    with (
        patch("app.core.app_factory.lifespan", _noop_lifespan),
        patch(
            "app.core.app_factory.configure_middleware",
            lambda app: app.add_middleware(LoggingMiddleware),
        ),
    ):
        app = create_app()

    @app.get("/boom")
    async def boom():
        raise HTTPException(status_code=500, detail="Failed to create todo") from RuntimeError(
            "db down"
        )

    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500
    (event,) = emitted
    assert event["final_level"] == "ERROR"
    (error,) = event["errors"]
    assert error["status_code"] == 500
    assert error["detail"] == "Failed to create todo"
    assert error["path"] == "/boom"
    # error_type + error (a string) is the cross-runtime vocabulary for a
    # thrown value — see scripts/ci/wide-event-conformance/contract.json.
    assert error["error_type"] == "RuntimeError"
    assert error["error"] == "db down"


def test_production_middleware_order_keeps_logging_outermost():
    """The wide-event boundaries must stay the outermost app middleware, timeout inside them.

    Two boundaries, one per scope: ``WebSocketWideEventMiddleware`` (pure ASGI,
    wraps websocket scope) must be outermost because ``LoggingMiddleware`` is a
    ``BaseHTTPMiddleware`` that drops websocket scope; ``LoggingMiddleware``
    (HTTP) sits just inside it. Both must stay outside the request timeout so a
    timed-out request still gets a canonical event.
    """
    app = FastAPI()
    configure_middleware(app)
    names = [m.cls.__name__ for m in app.user_middleware]
    # Starlette applies user_middleware[0] as the OUTERMOST layer.
    assert names[0] == "WebSocketWideEventMiddleware"
    assert names[1] == "LoggingMiddleware"
    assert names.index("LoggingMiddleware") < names.index("RequestTimeoutMiddleware")


def test_braces_in_message_with_kwargs_do_not_raise():
    """The loguru format trap: dynamic message content must never be formatted.

    The shipped bug: kwargs made loguru str.format the message at the call
    site, so braces in exception text raised INSIDE log.error, masking the
    real error and dropping the errors[] entry.
    """
    log.reset()
    log.error("payload {bad json", error_type="X")
    log.error('failed: {"detail": "boom"}', user_id="u1")
    log.error("failed: {} things", k="v")
    entries = log.get()["errors"]
    assert [e["msg"] for e in entries] == [
        "payload {bad json",
        'failed: {"detail": "boom"}',
        "failed: {} things",
    ]


class _FakeRecord(dict):
    pass


def _record(extra: dict[str, Any]) -> dict[str, Any]:
    class _Level:
        name = "ERROR"

    return {
        "time": datetime.datetime.now(datetime.UTC),
        "level": _Level(),
        "message": "boom",
        "module": "m",
        "line": 1,
        "extra": extra,
        "exception": None,
    }


@pytest.mark.parametrize(
    "hostile_extra",
    [
        {"bad": {1: "non-str-key"}},
        {"level": "CLOBBER", "message": "CLOBBER"},
        {"blob": "x" * (MAX_JSON_LINE_BYTES + 1)},
    ],
    ids=["non-str-dict-key", "core-key-collision", "oversized-line"],
)
def test_json_sink_is_total(hostile_extra, capsys):
    """Hostile values must degrade, never drop or corrupt the line.

    The shipped bugs: a non-str dict key dropped the entire http_request
    line; log.set(level=...) clobbered the line's real level; a huge value
    produced a line Loki rejects.
    """
    circular: dict[str, Any] = {}
    circular["self"] = circular
    _json_stdout_sink(type("M", (), {"record": _record({**hostile_extra, "circular": circular})})())
    line = capsys.readouterr().out.strip()
    parsed = json.loads(line)
    assert parsed["level"] == "ERROR"
    assert parsed["message"] == "boom"
    assert len(line.encode()) <= MAX_JSON_LINE_BYTES
    if "level" in hostile_extra:
        assert parsed["ctx_level"] == "CLOBBER"


def test_writes_outside_a_boundary_are_discarded_not_shared():
    """No boundary → throwaway state: no accumulation, no shared ambient dict.

    The shipped bug: a lazily bound ambient state was inherited by every task
    spawned from the main context (WebSockets, ARQ jobs) — one process-global
    dict that mixed users and grew forever.
    """
    _event_state.set(None)
    log.set(user={"id": "leak?"})
    log.error("orphan", error_type="X")
    assert log.get() == {}
    assert _event_state.get() is None


async def test_spawn_logged_task_emits_correlated_event():
    """Fire-and-forget work must emit its own event with the spawner's trace_id.

    The shipped bug: bare create_task work inherited an already-emitted
    request state; its fields (LLM cost accounting included) vanished.
    """
    emitted: list[dict[str, Any]] = []

    class _Recorder:
        def bind(self, **kwargs: Any) -> "_Recorder":
            self._ctx = kwargs
            return self

        def log(self, level: str, message: str) -> None:
            emitted.append({**self._ctx, "_message": message})

        def opt(self, **kwargs: Any) -> "_Recorder":
            return self

        def __getattr__(self, name: str) -> Any:
            return lambda *a, **k: None

    async def work() -> str:
        log.set(model={"tokens_used": 42})
        return "done"

    with patch("shared.py.wide_events._loguru", _Recorder()):
        async with wide_task("parent"):
            parent_trace = log.get_trace_id()
            task = spawn_logged_task("child_work", work())
            assert await task == "done"

    child = next(e for e in emitted if e.get("task") == "child_work")
    assert child["trace_id"] == parent_trace
    assert child["model"] == {"tokens_used": 42}
    assert child["_message"] == "background_task"


async def test_interleaved_wide_tasks_stay_isolated():
    """Concurrent worker tasks must not bleed fields into each other's events."""
    emitted: list[dict[str, Any]] = []

    class _Recorder:
        def bind(self, **kwargs: Any) -> "_Recorder":
            self._ctx = kwargs
            return self

        def log(self, level: str, message: str) -> None:
            emitted.append(dict(self._ctx))

        def opt(self, **kwargs: Any) -> "_Recorder":
            return self

        def __getattr__(self, name: str) -> Any:
            return lambda *a, **k: None

    async def job(name: str) -> None:
        async with wide_task(name):
            log.set(job_name=name)
            await asyncio.sleep(0.01)
            log.set_ns("todo", op=name)

    with patch("shared.py.wide_events._loguru", _Recorder()):
        async with anyio.create_task_group() as tg:
            tg.start_soon(job, "job_a")
            tg.start_soon(job, "job_b")

    by_name = {e["job_name"]: e for e in emitted if "job_name" in e}
    assert by_name["job_a"]["todo"] == {"op": "job_a"}
    assert by_name["job_b"]["todo"] == {"op": "job_b"}
    assert by_name["job_a"]["trace_id"] != by_name["job_b"]["trace_id"]


async def test_a_nested_boundary_does_not_steal_the_outer_event():
    """An inner boundary must not consume the event the outer one owes.

    The shipped bug: `_wide_event_boundary` called `log.reset()` without
    restoring the caller's accumulator, and an `asynccontextmanager` body runs
    in the caller's context (no task copy). So an inner `log_context` left the
    ContextVar pointed at its own state — the outer boundary then emitted the
    INNER's fields a second time and silently lost every field of its own,
    including anything set after the inner block. This is what makes a
    per-iteration boundary inside a long-lived listener loop usable at all.
    """
    recorder = WideEventRecorder()

    with patch("shared.py.wide_events._loguru", recorder):
        async with log_context("outer", outer_before=True):
            outer_trace = log.get_trace_id()
            async with log_context("inner", inner_only=True):
                inner_trace = log.get_trace_id()
            # The outer accumulator and trace_id must be back.
            assert log.get_trace_id() == outer_trace
            log.set(outer_after=True)

    inner, outer = recorder.events
    assert inner["task"] == "inner" and outer["task"] == "outer"
    # Each event keeps only its own fields — no theft, no duplication.
    assert inner["inner_only"] is True
    assert "outer_before" not in inner
    assert outer["outer_before"] is True and outer["outer_after"] is True
    assert "inner_only" not in outer
    assert outer["trace_id"] == outer_trace != inner_trace


async def test_adopted_trace_id_reaches_spawned_child_work():
    """`log.set(trace_id=...)` must move the ContextVar, not just the field.

    The shipped bug: adopting an upstream `x-trace-id` wrote the FIELD only,
    while `get_trace_id()` (and therefore every `spawn_logged_task` child) kept
    returning the boundary's generated id — the parent event and its background
    work landed under two different traces and could not be joined.
    """
    upstream = "cafebabedeadbeef"
    recorder = WideEventRecorder()

    async def child() -> None:
        log.set(child_ran=True)

    with patch("shared.py.wide_events._loguru", recorder):
        async with wide_task("parent"):
            log.set(trace_id=upstream)  # what the middleware does per request
            assert get_trace_id() == upstream
            await spawn_logged_task("child_work", child())

    by_task = {e["task"]: e for e in recorder.events}
    assert by_task["child_work"]["child_ran"] is True
    assert by_task["parent"]["trace_id"] == by_task["child_work"]["trace_id"] == upstream
