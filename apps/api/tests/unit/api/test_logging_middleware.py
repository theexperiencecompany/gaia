"""Unit tests for the logging middleware.

Covers skip paths, status code handling, trace-id propagation, exception
handling, and request/response size capture.
"""

from array import array
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from prometheus_client import REGISTRY
import pytest
from starlette.testclient import TestClient

from app.api.v1.middleware.internal_caller_metrics import (
    INTERNAL_CALLER_REFUSED_TOTAL,
    create_internal_caller_series,
)
from app.api.v1.middleware.logging import LoggingMiddleware
from app.config.settings import settings
from app.constants.http import INTERNAL_CALLER_HEADER
from app.models.user_models import AuthenticatedUser
from app.services.turn_timings import close_ingress
from shared.py.wide_events import log as wide_log
from tests.helpers import series_labels

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


#: What the streamed route writes: three SSE lines of different sizes.
_STREAMED = (b"data: one\n\n", b"data: three\n\n", b": keepalive\n\n")


def _build_test_app(skip_paths: frozenset | None = None):
    """Create a minimal FastAPI app with LoggingMiddleware."""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, StreamingResponse

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/metrics")
    async def metrics():
        return {"m": 1}

    @app.get("/favicon.ico")
    async def favicon():
        return JSONResponse(content={}, status_code=204)

    @app.get("/api/v1/test")
    async def test_route():
        return {"result": "ok"}

    @app.get("/api/v1/bad-request")
    async def bad_request():
        return JSONResponse(content={"detail": "bad"}, status_code=400)

    @app.get("/api/v1/server-error")
    async def server_error():
        return JSONResponse(content={"detail": "err"}, status_code=500)

    @app.get("/api/v1/raise")
    async def raise_route():
        raise RuntimeError("boom")

    @app.get("/api/v1/authed")
    async def authed_route(request: Request):
        request.state.user = AuthenticatedUser(user_id="user_42")
        return {"result": "ok"}

    @app.get("/api/v1/authed-explicit-id")
    async def authed_explicit_id_route(request: Request):
        request.state.user = AuthenticatedUser(user_id="user_42")
        wide_log.set(user={"id": "handler_chosen_id"})
        return {"result": "ok"}

    @app.post("/api/v1/accept")
    async def accept_route():
        ingress = close_ingress()
        return {"ingress": None if ingress is None else sorted(ingress)}

    @app.get("/api/v1/refused")
    async def refused_route():
        return JSONResponse(content={"detail": "no"}, status_code=401)

    @app.get("/api/v1/stream")
    async def stream_route():
        async def lines():
            for written, chunk in enumerate(_STREAMED, start=1):
                yield chunk
                wide_log.set(result_count=written)

        return StreamingResponse(lines(), media_type="text/event-stream")

    @app.get("/api/v1/views")
    async def views_route():
        # Two-byte items, so a view's length is half its bytes.
        return StreamingResponse(iter([memoryview(array("H", [1, 2])), memoryview(b"abc")]))

    app.add_middleware(LoggingMiddleware)
    return app


# ===========================================================================
# LoggingMiddleware
# ===========================================================================


class TestLoggingMiddlewareSkipPaths:
    """Requests to skip paths should not be logged."""

    def test_health_skipped(self) -> None:
        app = _build_test_app()
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            client = TestClient(app)
            resp = client.get("/health")
        assert resp.status_code == 200
        # The logger should not have been called for /health
        mock_logger.bind.assert_not_called()

    def test_metrics_skipped(self) -> None:
        app = _build_test_app()
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            client = TestClient(app)
            resp = client.get("/metrics")
        assert resp.status_code == 200
        mock_logger.bind.assert_not_called()

    def test_favicon_skipped(self) -> None:
        app = _build_test_app()
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            client = TestClient(app)
            client.get("/favicon.ico")
        mock_logger.bind.assert_not_called()


class TestLoggingMiddlewareNormalRequests:
    """Normal requests should produce a structured log event."""

    def test_successful_request_logged(self) -> None:
        app = _build_test_app()
        mock_bound = MagicMock()
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            mock_logger.bind.return_value = mock_bound
            client = TestClient(app)
            resp = client.get("/api/v1/test")
        assert resp.status_code == 200
        mock_logger.bind.assert_called_once()
        context = mock_logger.bind.call_args[1]
        assert context["method"] == "GET"
        assert context["path"] == "/api/v1/test"
        assert context["status_code"] == 200
        assert "duration_ms" in context
        mock_bound.log.assert_called_once()
        # A clean 2xx with no warning/error calls stays at INFO, and every HTTP
        # event is emitted under the one name the dashboards query.
        assert mock_bound.log.call_args[0] == ("INFO", "http_request")

    def test_400_response_logged_as_warning(self) -> None:
        app = _build_test_app()
        mock_bound = MagicMock()
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            mock_logger.bind.return_value = mock_bound
            client = TestClient(app)
            resp = client.get("/api/v1/bad-request")
        assert resp.status_code == 400
        mock_bound.log.assert_called_once()
        level = mock_bound.log.call_args[0][0]
        assert level == "WARNING"

    def test_500_response_logged_as_error(self) -> None:
        app = _build_test_app()
        mock_bound = MagicMock()
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            mock_logger.bind.return_value = mock_bound
            client = TestClient(app)
            resp = client.get("/api/v1/server-error")
        assert resp.status_code == 500
        mock_bound.log.assert_called_once()
        level = mock_bound.log.call_args[0][0]
        assert level == "ERROR"


class TestLoggingMiddlewareUserContext:
    """The authenticated user's id is merged into the emitted event."""

    def test_authenticated_user_id_is_stamped_on_the_event(self) -> None:
        app = _build_test_app()
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            client = TestClient(app)
            resp = client.get("/api/v1/authed")
        assert resp.status_code == 200
        assert mock_logger.bind.call_args[1]["user"] == {"id": "user_42"}

    def test_handler_set_user_id_wins_over_the_request_user(self) -> None:
        app = _build_test_app()
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            client = TestClient(app)
            resp = client.get("/api/v1/authed-explicit-id")
        assert resp.status_code == 200
        assert mock_logger.bind.call_args[1]["user"] == {"id": "handler_chosen_id"}

    def test_unauthenticated_request_carries_no_user(self) -> None:
        app = _build_test_app()
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            client = TestClient(app)
            client.get("/api/v1/test")
        assert "user" not in mock_logger.bind.call_args[1]


class TestLoggingMiddlewareTraceId:
    """x-trace-id header propagation."""

    def test_incoming_trace_id_set_on_event(self) -> None:
        app = _build_test_app()
        mock_bound = MagicMock()
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            mock_logger.bind.return_value = mock_bound
            client = TestClient(app)
            resp = client.get(
                "/api/v1/test",
                headers={"x-trace-id": "trace-abc-123"},
            )
        assert resp.status_code == 200
        # trace_id should appear in response headers
        assert resp.headers.get("x-trace-id") == "trace-abc-123"


class TestLoggingMiddlewareExceptionHandling:
    """Unhandled exceptions should still produce a log event."""

    def test_unhandled_exception_logged_and_reraised(self) -> None:
        app = _build_test_app()
        mock_bound = MagicMock()
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            mock_logger.bind.return_value = mock_bound
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/v1/raise")
        # FastAPI converts unhandled exceptions to 500
        assert resp.status_code == 500
        context = mock_logger.bind.call_args.kwargs
        assert context["path"] == "/api/v1/raise"
        assert context["status_code"] == 500
        mock_bound.log.assert_called_once_with("ERROR", "http_request")


class TestLoggingMiddlewareRequestSize:
    """Request size is captured from Content-Length header."""

    def test_request_size_captured(self) -> None:
        app = _build_test_app()
        mock_bound = MagicMock()
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            mock_logger.bind.return_value = mock_bound
            client = TestClient(app)
            resp = client.get(
                "/api/v1/test",
                headers={"Content-Length": "42"},
            )
        assert resp.status_code == 200
        context = mock_logger.bind.call_args[1]
        assert context["request_size_bytes"] == 42

    def test_invalid_content_length_defaults_to_zero(self) -> None:
        app = _build_test_app()
        mock_bound = MagicMock()
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            mock_logger.bind.return_value = mock_bound
            client = TestClient(app)
            resp = client.get(
                "/api/v1/test",
                headers={"Content-Length": "not_a_number"},
            )
        assert resp.status_code == 200
        context = mock_logger.bind.call_args[1]
        assert context["request_size_bytes"] == 0


class TestLoggingMiddlewareResponseSize:
    """The event carries the body bytes handed to the server, whether or not the response named its size."""

    def test_a_streamed_response_logs_the_bytes_written_to_the_server(self) -> None:
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            resp = TestClient(_build_test_app()).get("/api/v1/stream")
        context = mock_logger.bind.call_args.kwargs
        assert "content-length" not in resp.headers
        assert context["response_size_bytes"] == len(resp.content) == len(b"".join(_STREAMED))

    def test_a_streamed_response_s_event_holds_what_its_stream_set(self) -> None:
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            TestClient(_build_test_app()).get("/api/v1/stream")
        mock_logger.bind.assert_called_once()
        context = mock_logger.bind.call_args.kwargs
        assert context["result_count"] == len(_STREAMED)
        assert context["response_duration_ms"] >= context["duration_ms"] >= 0

    def test_the_event_times_the_response_s_start_and_its_last_byte(self) -> None:
        arrived, started, last_byte = 100.0, 100.25, 101.23456789
        clock = iter((arrived, started, last_byte))
        ticking = SimpleNamespace(time=lambda: next(clock), perf_counter=time.perf_counter)
        with (
            patch("app.api.v1.middleware.logging.request_logger") as mock_logger,
            patch("app.api.v1.middleware.logging.time", ticking),
        ):
            resp = TestClient(_build_test_app()).get(
                "/api/v1/stream", headers={"x-request-id": "req-7", "user-agent": "probe/1"}
            )
        context = mock_logger.bind.call_args.kwargs
        assert (context["duration_ms"], context["response_duration_ms"]) == (250.0, 1234.57)
        assert (context["status_code"], context["status_phrase"]) == (200, "OK")
        assert (context["request_id"], context["user_agent"]) == ("req-7", "probe/1")
        assert context["client_ip"] == "testclient"
        assert resp.headers["x-trace-id"] == context["trace_id"]

    def test_a_sized_response_logs_the_bytes_written_to_the_server(self) -> None:
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            resp = TestClient(_build_test_app()).get("/api/v1/test")
        context = mock_logger.bind.call_args.kwargs
        assert context["response_size_bytes"] == len(resp.content) == len(b'{"result":"ok"}')

    def test_a_body_sent_as_memoryviews_is_counted_in_bytes(self) -> None:
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            resp = TestClient(_build_test_app()).get("/api/v1/views")
        context = mock_logger.bind.call_args.kwargs
        assert context["response_size_bytes"] == len(resp.content) == 7

    async def test_a_client_that_leaves_mid_stream_still_gets_its_event(self) -> None:
        written: list[bytes] = []

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, object]) -> None:
            body = message.get("body")
            if message["type"] != "http.response.body" or not isinstance(body, bytes):
                return
            if written:
                raise OSError("the client left")
            written.append(body)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/stream",
            "raw_path": b"/api/v1/stream",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("203.0.113.7", 4711),
            "server": ("test", 80),
        }
        mock_bound = MagicMock()
        with patch("app.api.v1.middleware.logging.request_logger") as mock_logger:
            mock_logger.bind.return_value = mock_bound
            with pytest.raises(OSError, match="the client left"):
                await _build_test_app()(scope, receive, send)
        mock_logger.bind.assert_called_once()
        context = mock_logger.bind.call_args.kwargs
        assert written == [_STREAMED[0]]
        assert (context["status_code"], context["response_size_bytes"]) == (200, len(_STREAMED[0]))
        mock_bound.log.assert_called_once_with("INFO", "http_request")


class TestLoggingMiddlewareTurnTimings:
    """A chat turn's ingress is measured from the request's arrival at the middleware."""

    def test_a_request_that_accepts_a_message_reports_its_ingress(self) -> None:
        with patch("app.api.v1.middleware.logging.request_logger"):
            resp = TestClient(_build_test_app()).post("/api/v1/accept")
        assert resp.json() == {"ingress": ["other"]}


def _refused(reason: str) -> float:
    return (
        REGISTRY.get_sample_value("gaia_internal_caller_refused_total", {"reason": reason}) or 0.0
    )


class TestLoggingMiddlewareInternalCaller:
    """A refusal of GAIA's own web server is counted; anyone else's 401 is not."""

    @pytest.fixture(autouse=True)
    def _internal_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", "token-for-tests")
        monkeypatch.setattr(settings, "INTERNAL_API_TOKEN_PREVIOUS", None)

    def test_a_401_for_the_web_server_is_counted(self) -> None:
        before = _refused("unauthorized")
        with patch("app.api.v1.middleware.logging.request_logger"):
            TestClient(_build_test_app()).get(
                "/api/v1/refused", headers={INTERNAL_CALLER_HEADER: "token-for-tests"}
            )
        assert _refused("unauthorized") == before + 1

    def test_a_401_for_anyone_else_is_not_counted(self) -> None:
        before = _refused("unauthorized")
        with patch("app.api.v1.middleware.logging.request_logger"):
            client = TestClient(_build_test_app())
            client.get("/api/v1/refused")
            client.get("/api/v1/refused", headers={INTERNAL_CALLER_HEADER: "wrong"})
        assert _refused("unauthorized") == before

    def test_a_served_request_from_the_web_server_is_not_counted(self) -> None:
        before = _refused("unauthorized")
        with patch("app.api.v1.middleware.logging.request_logger"):
            TestClient(_build_test_app()).get(
                "/api/v1/test", headers={INTERNAL_CALLER_HEADER: "token-for-tests"}
            )
        assert _refused("unauthorized") == before

    def test_every_refusal_series_exists_before_the_first_refusal(self) -> None:
        INTERNAL_CALLER_REFUSED_TOTAL.clear()

        create_internal_caller_series()

        assert series_labels("gaia_internal_caller_refused_total") == {
            ("unauthorized",),
            ("forbidden",),
        }
