"""Unit tests for the logging middleware and log_function_call decorator.

BEHAVIOR SPEC
=============

UNIT: app/api/v1/middleware/logging.py :: log_function_call
EXPECTED: A decorator that wraps a sync or async callable, transparently
          returning its result, and recording wide-event side-effects:
          a "slow function" WARNING when wall-time > 1.0s, and a
          "function failed" ERROR (then re-raise) when the wrapped call throws.
MECHANISM: asyncio.iscoroutinefunction(func) picks the async vs sync wrapper.
          Each measures time.time() before/after; on the happy path it only
          warns if execution_time > 1.0; on Exception it calls wide_log.error
          with function/duration_ms/error/error_type and re-raises.
MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - the wrapped result is returned verbatim, args/kwargs forwarded (async+sync)
  - the warning fires strictly ABOVE 1.0s, NOT at/below it (> not >=, boundary)
  - the warning carries function=<qualname> and duration_ms (the real value)
  - the error path records errors[] with the real error string + type, re-raises
  - async coroutine -> async_wrapper; plain def -> sync_wrapper

UNIT: app/api/v1/middleware/logging.py :: LoggingMiddleware (dispatch)
EXPECTED: Emit exactly one structured wide event per HTTP request, except for
          the skip-paths set which are passed straight through with no event.
MECHANISM: skip -> call_next only. Otherwise reset wide event, honour incoming
          x-trace-id, parse content-length, run the route, derive final level
          from max(wide-event level, HTTP status), bind the full context onto
          request_logger and emit, then mirror trace_id into the response header.
          On an unhandled route exception it logs an ERROR event (status 500)
          and re-raises.
MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - /health, /metrics, /favicon.ico produce NO log event
  - a normal 2xx request emits one event with method/path/status_code/level=INFO
  - status >= 500 forces level ERROR; 400-499 forces at least WARNING
  - a 400 request whose handler already logged an ERROR keeps ERROR (not downgraded)
  - the status_phrase is the HTTPStatus phrase, "Unknown" for a non-standard code
  - incoming x-trace-id is echoed on the response; absent -> a generated id is echoed
  - content-length parses to int; non-numeric -> 0
  - response_size_bytes comes from the response content-length header
  - client_ip falls back to x-forwarded-for when there is no client peer
  - an unhandled exception still emits an ERROR event (status 500) and re-raises

EQUIVALENT MUTANTS (allowed survivors, justified): documented inline at the
bottom of this module if any survive the loop.
"""

import asyncio
from http import HTTPStatus
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
import pytest
from starlette.testclient import TestClient

from app.api.v1.middleware.logging import LoggingMiddleware, log_function_call
from shared.py.wide_events import log as wide_log

LOGGER_PATH = "app.api.v1.middleware.logging.request_logger"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_test_app() -> FastAPI:
    """Minimal FastAPI app exercising every middleware branch via real routes."""
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/metrics")
    async def metrics() -> dict:
        return {"m": 1}

    @app.get("/favicon.ico")
    async def favicon() -> JSONResponse:
        return JSONResponse(content={}, status_code=204)

    @app.get("/api/v1/test")
    async def ok_route() -> dict:
        return {"result": "ok"}

    @app.get("/api/v1/teapot")
    async def teapot_route() -> JSONResponse:
        # 418 is a real HTTPStatus -> phrase "I'm a Teapot".
        return JSONResponse(content={}, status_code=418)

    @app.get("/api/v1/weird")
    async def weird_route() -> JSONResponse:
        # 499 is NOT in http.HTTPStatus -> phrase must fall back to "Unknown".
        return JSONResponse(content={}, status_code=499)

    @app.get("/api/v1/server-error")
    async def server_error() -> JSONResponse:
        return JSONResponse(content={"detail": "err"}, status_code=500)

    app.add_middleware(LoggingMiddleware)
    return app


def _make_request(
    *,
    path: str = "/api/v1/test",
    method: str = "GET",
    client: tuple[str, int] | None = ("127.0.0.1", 5000),
    headers: dict[str, str] | None = None,
) -> Request:
    """Build a bare Starlette Request so dispatch() runs in THIS contextvar context.

    Starlette's BaseHTTPMiddleware runs call_next in a child task whose
    ContextVar writes do not propagate back to the middleware. Driving dispatch
    directly keeps the wide-event ContextVar shared, which is required to test
    level escalation that depends on warnings/errors logged before emission.
    """
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": raw_headers,
        "query_string": b"",
        "client": client,
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


async def _dispatch_with_response(
    request: Request, response: JSONResponse, mock_logger: MagicMock
) -> None:
    """Run dispatch() returning `response` from call_next under a mocked logger."""
    mw = LoggingMiddleware(app=MagicMock())

    async def call_next(_req: Request) -> JSONResponse:
        return response

    with patch(LOGGER_PATH, mock_logger):
        await mw.dispatch(request, call_next)


def _bound_context(mock_logger: MagicMock) -> dict:
    """Return the kwargs dict passed to request_logger.bind(**context)."""
    return mock_logger.bind.call_args.kwargs


def _emitted_level(mock_logger: MagicMock) -> str:
    """Return the level positional arg passed to .log(level, 'http_request')."""
    return mock_logger.bind.return_value.log.call_args.args[0]


# ===========================================================================
# LoggingMiddleware — skip paths
# ===========================================================================


@pytest.mark.unit
class TestSkipPaths:
    """The three infra paths must pass through with NO wide event emitted."""

    @pytest.mark.parametrize(
        ("path", "expected_status"),
        [("/health", 200), ("/metrics", 200), ("/favicon.ico", 204)],
    )
    def test_skip_paths_emit_no_event(self, path: str, expected_status: int) -> None:
        app = _build_test_app()
        with patch(LOGGER_PATH) as mock_logger:
            with TestClient(app) as client:
                resp = client.get(path)
        assert resp.status_code == expected_status
        mock_logger.bind.assert_not_called()

    def test_non_skip_path_emits_event(self) -> None:
        # Guards the membership check: a path NOT in the skip set must be logged.
        app = _build_test_app()
        with patch(LOGGER_PATH) as mock_logger:
            with TestClient(app) as client:
                resp = client.get("/api/v1/test")
        assert resp.status_code == 200
        mock_logger.bind.assert_called_once()


# ===========================================================================
# LoggingMiddleware — successful requests + context contract
# ===========================================================================


@pytest.mark.unit
class TestSuccessfulRequestContext:
    """A normal request emits one event carrying the full HTTP context."""

    def test_context_fields_and_info_level(self) -> None:
        app = _build_test_app()
        with patch(LOGGER_PATH) as mock_logger:
            with TestClient(app) as client:
                resp = client.get("/api/v1/test")
        assert resp.status_code == 200

        mock_logger.bind.assert_called_once()
        ctx = _bound_context(mock_logger)
        assert ctx["method"] == "GET"
        assert ctx["path"] == "/api/v1/test"
        assert ctx["status_code"] == 200
        assert ctx["status_phrase"] == "OK"
        assert isinstance(ctx["duration_ms"], float)
        assert ctx["duration_ms"] >= 0.0
        # Environment characteristics injected on every event.
        assert ctx["service"] == "gaia-api"
        assert "env" in ctx
        assert "commit" in ctx
        # 2xx with no warnings/errors -> level INFO.
        assert _emitted_level(mock_logger) == "INFO"
        mock_logger.bind.return_value.log.assert_called_once()
        # The event name is the second positional arg of .log(level, name).
        assert mock_logger.bind.return_value.log.call_args.args[1] == "http_request"

    def test_status_phrase_resolved_for_known_code(self) -> None:
        # 418 is a real HTTPStatus -> phrase must be its canonical text, proving
        # status_phrase is derived from the status code, not hardcoded.
        app = _build_test_app()
        with patch(LOGGER_PATH) as mock_logger:
            with TestClient(app) as client:
                resp = client.get("/api/v1/teapot")
        assert resp.status_code == 418
        ctx = _bound_context(mock_logger)
        assert ctx["status_code"] == 418
        assert ctx["status_phrase"] == HTTPStatus(418).phrase

    def test_unknown_status_code_phrase_falls_back(self) -> None:
        # 499 is not a standard HTTPStatus -> ValueError caught -> "Unknown".
        app = _build_test_app()
        with patch(LOGGER_PATH) as mock_logger:
            with TestClient(app) as client:
                resp = client.get("/api/v1/weird")
        assert resp.status_code == 499
        ctx = _bound_context(mock_logger)
        assert ctx["status_code"] == 499
        assert ctx["status_phrase"] == "Unknown"

    async def test_duration_request_id_and_user_agent_on_success_path(self) -> None:
        # Driven through dispatch directly with pinned time so duration_ms is
        # deterministic to 2dp: 1000.123456 - 1000.0 = 0.123456s = 123.456ms ->
        # 123.46. Pins the * 1000 conversion and round(..., 2) on the happy path,
        # and proves request_id / user_agent are read from request headers
        # (not constants).
        mw = LoggingMiddleware(app=MagicMock())
        request = _make_request(headers={"user-agent": "agent/1.2", "x-request-id": "rid-9"})

        async def call_next(_req: Request) -> JSONResponse:
            return JSONResponse(content={"ok": True}, status_code=200)

        mock_logger = MagicMock()
        with patch(LOGGER_PATH, mock_logger):
            with patch(
                "app.api.v1.middleware.logging.time.time",
                side_effect=[1000.0, 1000.123456],
            ):
                await mw.dispatch(request, call_next)
        ctx = mock_logger.bind.call_args.kwargs
        assert ctx["duration_ms"] == 123.46
        assert ctx["user_agent"] == "agent/1.2"
        assert ctx["request_id"] == "rid-9"


# ===========================================================================
# LoggingMiddleware — final-level derivation
# ===========================================================================


@pytest.mark.unit
class TestFinalLevel:
    """Final level = worst of (HTTP status, explicit warning/error calls)."""

    def test_500_status_forces_error(self) -> None:
        app = _build_test_app()
        with patch(LOGGER_PATH) as mock_logger:
            with TestClient(app) as client:
                resp = client.get("/api/v1/server-error")
        assert resp.status_code == 500
        assert _emitted_level(mock_logger) == "ERROR"
        assert _bound_context(mock_logger)["final_level"] == "ERROR"

    def test_400_status_forces_warning(self) -> None:
        app = _build_test_app()
        with patch(LOGGER_PATH) as mock_logger:
            with TestClient(app) as client:
                resp = client.get("/api/v1/teapot")  # 418 -> 4xx
        assert resp.status_code == 418
        assert _emitted_level(mock_logger) == "WARNING"

    async def test_warning_logged_on_200_keeps_warning(self) -> None:
        # 2xx never escalates the HTTP level, but a warning logged mid-flight must
        # still drive the emitted level via get_max_level(). The warning is logged
        # INSIDE call_next (after dispatch's own reset()) and reaches the
        # middleware because direct dispatch shares the wide-event ContextVar.
        mock_logger = await self._dispatch_logging_during_route(
            level_call=lambda: wide_log.warning("mid-flight warning"),
            status_code=200,
        )
        assert _emitted_level(mock_logger) == "WARNING"

    async def test_error_logged_on_400_is_not_downgraded(self) -> None:
        # 4xx escalates to WARNING only when the current level is BELOW WARNING.
        # With an ERROR already logged the guard
        # (_LEVEL_ORDER[level] < _LEVEL_ORDER["WARNING"]) is False, so ERROR wins.
        mock_logger = await self._dispatch_logging_during_route(
            level_call=lambda: wide_log.error("mid-flight error"),
            status_code=400,
        )
        assert _emitted_level(mock_logger) == "ERROR"

    async def test_400_with_no_prior_level_escalates_to_warning(self) -> None:
        # Mirror of the above but with a clean INFO baseline: the guard is True,
        # so a 4xx escalates to WARNING. Together the two pin the < comparison.
        mock_logger = await self._dispatch_logging_during_route(
            level_call=lambda: None, status_code=400
        )
        assert _emitted_level(mock_logger) == "WARNING"

    @staticmethod
    async def _dispatch_logging_during_route(level_call, status_code: int) -> MagicMock:
        """Run dispatch where the route logs via level_call before responding."""
        mw = LoggingMiddleware(app=MagicMock())
        request = _make_request()

        async def call_next(_req: Request) -> JSONResponse:
            level_call()
            return JSONResponse(content={"x": 1}, status_code=status_code)

        mock_logger = MagicMock()
        with patch(LOGGER_PATH, mock_logger):
            await mw.dispatch(request, call_next)
        return mock_logger


# ===========================================================================
# LoggingMiddleware — trace id propagation
# ===========================================================================


@pytest.mark.unit
class TestTraceId:
    """trace_id is honoured from the request and mirrored to the response."""

    def test_incoming_trace_id_echoed(self) -> None:
        app = _build_test_app()
        with patch(LOGGER_PATH) as mock_logger:
            with TestClient(app) as client:
                resp = client.get("/api/v1/test", headers={"x-trace-id": "trace-abc-123"})
        assert resp.status_code == 200
        assert resp.headers.get("x-trace-id") == "trace-abc-123"
        # The honoured id is also merged into the emitted event context.
        assert _bound_context(mock_logger)["trace_id"] == "trace-abc-123"

    def test_generated_trace_id_echoed_when_absent(self) -> None:
        # reset() always seeds a 16-hex trace_id; with no incoming header the
        # response still carries that generated id (the `if trace_id:` guard is
        # truthy because reset() populated it).
        app = _build_test_app()
        with patch(LOGGER_PATH):
            with TestClient(app) as client:
                resp = client.get("/api/v1/test")
        assert resp.status_code == 200
        echoed = resp.headers.get("x-trace-id")
        assert echoed is not None
        assert len(echoed) == 16


# ===========================================================================
# LoggingMiddleware — request / response size capture
# ===========================================================================


@pytest.mark.unit
class TestSizeCapture:
    """request_size_bytes from request CL; response_size_bytes from response CL."""

    def test_request_size_from_content_length(self) -> None:
        app = _build_test_app()
        with patch(LOGGER_PATH) as mock_logger:
            with TestClient(app) as client:
                resp = client.get("/api/v1/test", headers={"Content-Length": "42"})
        assert resp.status_code == 200
        assert _bound_context(mock_logger)["request_size_bytes"] == 42

    def test_invalid_content_length_defaults_zero(self) -> None:
        app = _build_test_app()
        with patch(LOGGER_PATH) as mock_logger:
            with TestClient(app) as client:
                resp = client.get("/api/v1/test", headers={"Content-Length": "not_a_number"})
        assert resp.status_code == 200
        assert _bound_context(mock_logger)["request_size_bytes"] == 0

    async def test_missing_content_length_defaults_zero(self) -> None:
        # No Content-Length header at all -> the `0` default of headers.get is
        # used, so request_size_bytes is 0 (pins the default, not a `1`).
        mw = LoggingMiddleware(app=MagicMock())
        request = _make_request()  # no headers

        async def call_next(_req: Request) -> JSONResponse:
            return JSONResponse(content={"ok": True}, status_code=200)

        mock_logger = MagicMock()
        with patch(LOGGER_PATH, mock_logger):
            await mw.dispatch(request, call_next)
        assert mock_logger.bind.call_args.kwargs["request_size_bytes"] == 0

    async def test_response_without_content_length_defaults_zero(self) -> None:
        # A response carrying NO Content-Length header -> response_size_bytes
        # falls back to 0 (pins both the headers.get default and the `or 0`).
        mw = LoggingMiddleware(app=MagicMock())
        request = _make_request()

        async def call_next(_req: Request) -> Response:
            resp = Response(status_code=200)
            del resp.headers["content-length"]
            return resp

        mock_logger = MagicMock()
        with patch(LOGGER_PATH, mock_logger):
            await mw.dispatch(request, call_next)
        assert mock_logger.bind.call_args.kwargs["response_size_bytes"] == 0

    def test_response_size_from_response_content_length(self) -> None:
        # The JSON body {"result":"ok"} has a non-zero, deterministic length;
        # response_size_bytes must reflect the response Content-Length header.
        app = _build_test_app()
        with patch(LOGGER_PATH) as mock_logger:
            with TestClient(app) as client:
                resp = client.get("/api/v1/test")
        assert resp.status_code == 200
        ctx = _bound_context(mock_logger)
        expected = int(resp.headers["content-length"])
        assert ctx["response_size_bytes"] == expected
        assert expected > 0


# ===========================================================================
# LoggingMiddleware — client ip resolution (direct dispatch, no TestClient peer)
# ===========================================================================


@pytest.mark.unit
class TestClientIpFallback:
    """client_ip uses request.client.host, else x-forwarded-for, else 'unknown'."""

    async def _dispatch(self, request: Request) -> dict:
        mock_logger = MagicMock()
        await _dispatch_with_response(
            request, JSONResponse(content={"ok": True}, status_code=200), mock_logger
        )
        return mock_logger.bind.call_args.kwargs

    async def test_client_host_used_when_peer_present(self) -> None:
        req = _make_request(client=("203.0.113.7", 5000))
        ctx = await self._dispatch(req)
        assert ctx["client_ip"] == "203.0.113.7"

    async def test_forwarded_for_used_when_no_peer(self) -> None:
        req = _make_request(client=None, headers={"x-forwarded-for": "198.51.100.9"})
        ctx = await self._dispatch(req)
        assert ctx["client_ip"] == "198.51.100.9"

    async def test_unknown_when_no_peer_and_no_header(self) -> None:
        req = _make_request(client=None)
        ctx = await self._dispatch(req)
        assert ctx["client_ip"] == "unknown"


# ===========================================================================
# LoggingMiddleware — unhandled exception path
# ===========================================================================


@pytest.mark.unit
class TestExceptionPath:
    """An unhandled route error still emits an ERROR event, then re-raises."""

    async def test_exception_emits_error_event_and_reraises(self) -> None:
        mw = LoggingMiddleware(app=MagicMock())
        request = _make_request(
            path="/api/v1/raise",
            method="POST",
            client=("192.0.2.5", 1234),
            headers={
                "x-request-id": "req-77",
                "content-length": "10",
                "user-agent": "pytest-agent/9",
            },
        )

        async def call_next(_req: Request) -> JSONResponse:
            raise RuntimeError("kaboom")

        # Pin time: 1000.123456 - 1000.0 = 0.123456s -> 123.46ms (3dp pins round).
        with patch(LOGGER_PATH) as mock_logger:
            with patch(
                "app.api.v1.middleware.logging.time.time",
                side_effect=[1000.0, 1000.123456],
            ):
                with pytest.raises(RuntimeError, match="kaboom"):
                    await mw.dispatch(request, call_next)

        mock_logger.bind.assert_called_once()
        ctx = mock_logger.bind.call_args.kwargs
        # Status is forced to the 500 fallback (response is None).
        assert ctx["status_code"] == 500
        assert ctx["status_phrase"] == "Internal Server Error"
        assert ctx["method"] == "POST"
        assert ctx["path"] == "/api/v1/raise"
        assert ctx["request_id"] == "req-77"
        assert ctx["request_size_bytes"] == 10
        assert ctx["user_agent"] == "pytest-agent/9"
        assert ctx["client_ip"] == "192.0.2.5"
        assert ctx["duration_ms"] == 123.46
        assert ctx["final_level"] == "ERROR"
        assert ctx["outcome"] == "failed"
        # The unhandled_exception error was recorded with the real msg/type/message.
        errors = ctx["errors"]
        assert errors[-1]["msg"] == "unhandled_exception"
        assert errors[-1]["error_type"] == "RuntimeError"
        assert errors[-1]["error_message"] == "kaboom"
        # Emitted at ERROR severity with the canonical event name.
        log_call = mock_logger.bind.return_value.log.call_args
        assert log_call.args[0] == "ERROR"
        assert log_call.args[1] == "http_request"

    async def test_exception_path_uses_forwarded_for_without_peer(self) -> None:
        mw = LoggingMiddleware(app=MagicMock())
        request = _make_request(
            path="/api/v1/raise",
            client=None,
            headers={"x-forwarded-for": "203.0.113.99"},
        )

        async def call_next(_req: Request) -> JSONResponse:
            raise ValueError("nope")

        with patch(LOGGER_PATH) as mock_logger:
            with pytest.raises(ValueError, match="nope"):
                await mw.dispatch(request, call_next)
        assert mock_logger.bind.call_args.kwargs["client_ip"] == "203.0.113.99"

    async def test_exception_path_client_ip_unknown_without_peer_or_header(
        self,
    ) -> None:
        # No peer and no x-forwarded-for -> the "unknown" default is used (pins
        # the default string in request.headers.get("x-forwarded-for", "unknown")).
        mw = LoggingMiddleware(app=MagicMock())
        request = _make_request(path="/api/v1/raise", client=None)

        async def call_next(_req: Request) -> JSONResponse:
            raise ValueError("nope")

        with patch(LOGGER_PATH) as mock_logger:
            with pytest.raises(ValueError, match="nope"):
                await mw.dispatch(request, call_next)
        assert mock_logger.bind.call_args.kwargs["client_ip"] == "unknown"


# ===========================================================================
# log_function_call — async wrapper
# ===========================================================================


@pytest.mark.unit
class TestLogFunctionCallAsync:
    """Async decoration: result passthrough + slow-warning + error recording."""

    async def test_returns_result_and_forwards_args(self) -> None:
        @log_function_call
        async def add(a: int, b: int, *, c: int = 0) -> int:
            return a + b + c

        assert await add(1, 2, c=4) == 7

    async def test_no_warning_at_or_below_threshold(self) -> None:
        # Boundary: exactly 1.0s must NOT warn (guard is `> 1.0`, not `>= 1.0`).
        @log_function_call
        async def work() -> str:
            return "done"

        wide_log.reset()
        with patch("app.api.v1.middleware.logging.time.time", side_effect=[0.0, 1.0]):
            result = await work()
        assert result == "done"
        assert wide_log.get().get("warnings", []) == []

    async def test_slow_function_records_warning(self) -> None:
        @log_function_call
        async def slow() -> str:
            return "done"

        wide_log.reset()
        # 2.623456 - 1.0 = 1.623456s (> 1.0 -> warns) -> 1623.456ms = 1623.46 (2dp).
        # Non-zero start pins the subtraction; the 3dp value pins round(..., 2).
        with patch("app.api.v1.middleware.logging.time.time", side_effect=[1.0, 2.623456]):
            result = await slow()
        assert result == "done"
        warnings = wide_log.get()["warnings"]
        assert len(warnings) == 1
        assert warnings[0]["msg"] == "slow function"
        assert warnings[0]["function"].endswith("slow")
        assert warnings[0]["duration_ms"] == 1623.46

    async def test_error_records_error_and_reraises(self) -> None:
        @log_function_call
        async def boom() -> None:
            raise ValueError("oops")

        wide_log.reset()
        # 1.123456 - 1.0 = 0.123456s -> 123.456ms, rounded to 2dp = 123.46.
        # Non-zero start pins the subtraction; a 3dp value pins round(..., 2).
        with patch("app.api.v1.middleware.logging.time.time", side_effect=[1.0, 1.123456]):
            with pytest.raises(ValueError, match="oops"):
                await boom()
        errors = wide_log.get()["errors"]
        assert len(errors) == 1
        assert errors[0]["msg"] == "function failed"
        assert errors[0]["error"] == "oops"
        assert errors[0]["error_type"] == "ValueError"
        assert errors[0]["function"].endswith("boom")
        assert errors[0]["duration_ms"] == 123.46


# ===========================================================================
# log_function_call — sync wrapper
# ===========================================================================


@pytest.mark.unit
class TestLogFunctionCallSync:
    """Sync decoration mirrors the async wrapper's behaviour."""

    def test_returns_result_and_forwards_args(self) -> None:
        @log_function_call
        def multiply(a: int, b: int) -> int:
            return a * b

        assert multiply(3, 4) == 12

    def test_no_warning_at_or_below_threshold(self) -> None:
        @log_function_call
        def fast() -> int:
            return 42

        wide_log.reset()
        with patch("app.api.v1.middleware.logging.time.time", side_effect=[0.0, 1.0]):
            result = fast()
        assert result == 42
        assert wide_log.get().get("warnings", []) == []

    def test_slow_function_records_warning(self) -> None:
        @log_function_call
        def slow() -> str:
            return "done"

        wide_log.reset()
        # 2.623456 - 1.0 = 1.623456s (> 1.0 -> warns) -> 1623.46ms (2dp).
        # Non-zero start pins the subtraction; the 3dp value pins round(..., 2).
        with patch("app.api.v1.middleware.logging.time.time", side_effect=[1.0, 2.623456]):
            result = slow()
        assert result == "done"
        warnings = wide_log.get()["warnings"]
        assert len(warnings) == 1
        assert warnings[0]["msg"] == "slow function"
        assert warnings[0]["function"].endswith("slow")
        assert warnings[0]["duration_ms"] == 1623.46

    def test_error_records_error_and_reraises(self) -> None:
        @log_function_call
        def boom() -> None:
            raise RuntimeError("sync fail")

        wide_log.reset()
        # 1.123456 - 1.0 = 0.123456s -> 123.46ms (2dp). Non-zero start pins the
        # subtraction; the 3dp value pins round(..., 2).
        with patch("app.api.v1.middleware.logging.time.time", side_effect=[1.0, 1.123456]):
            with pytest.raises(RuntimeError, match="sync fail"):
                boom()
        errors = wide_log.get()["errors"]
        assert len(errors) == 1
        assert errors[0]["msg"] == "function failed"
        assert errors[0]["error"] == "sync fail"
        assert errors[0]["error_type"] == "RuntimeError"
        assert errors[0]["duration_ms"] == 123.46


@pytest.mark.unit
class TestWrapperSelection:
    """iscoroutinefunction(func) decides which wrapper is returned."""

    def test_async_func_yields_coroutine_wrapper(self) -> None:
        @log_function_call
        async def af() -> int:
            return 1

        assert asyncio.iscoroutinefunction(af)

    def test_sync_func_yields_plain_wrapper(self) -> None:
        @log_function_call
        def sf() -> int:
            return 1

        assert not asyncio.iscoroutinefunction(sf)
