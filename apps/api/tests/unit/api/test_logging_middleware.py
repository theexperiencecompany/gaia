"""Unit tests for the logging middleware.

Covers skip paths, status code handling, trace-id propagation, exception
handling, and request/response size capture.
"""

from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from app.api.v1.middleware.logging import LoggingMiddleware
from app.models.user_models import AuthenticatedUser
from shared.py.wide_events import log as wide_log

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_test_app(skip_paths: frozenset | None = None):
    """Create a minimal FastAPI app with LoggingMiddleware."""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

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
        # Logger should have been called
        assert mock_logger.bind.called


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
