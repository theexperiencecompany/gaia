"""Unit tests for the logging middleware and log_function_call decorator.

Tests cover LoggingMiddleware (skip paths, status code handling, trace-id
propagation, exception handling, request/response size capture) and the
log_function_call decorator (async/sync, slow function warnings, error
logging).
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app.api.v1.middleware.logging import LoggingMiddleware, log_function_call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_test_app(skip_paths: frozenset | None = None):
    """Create a minimal FastAPI app with LoggingMiddleware."""
    from fastapi import FastAPI
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

    app.add_middleware(LoggingMiddleware)
    return app


# ===========================================================================
# LoggingMiddleware
# ===========================================================================


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


# ===========================================================================
# log_function_call decorator
# ===========================================================================


@pytest.mark.unit
class TestLogFunctionCallAsync:
    """Async function decoration."""

    async def test_async_function_returns_result(self) -> None:
        @log_function_call
        async def add(a: int, b: int) -> int:
            return a + b

        result = await add(1, 2)
        assert result == 3

    async def test_async_slow_function_warns(self) -> None:
        @log_function_call
        async def slow():
            await asyncio.sleep(0)
            return "done"

        with patch("app.api.v1.middleware.logging.time.time") as mock_time:
            # Simulate >1s execution
            mock_time.side_effect = [0.0, 2.0]
            with patch("app.api.v1.middleware.logging.wide_log.warning") as mock_warn:
                result = await slow()
            mock_warn.assert_called_once()
            assert "slow function" in mock_warn.call_args[0][0]
        assert result == "done"

    async def test_async_function_error_logs_error(self) -> None:
        @log_function_call
        async def fail():
            raise ValueError("oops")

        with patch("app.api.v1.middleware.logging.wide_log.error") as mock_err:
            with pytest.raises(ValueError, match="oops"):
                await fail()
            mock_err.assert_called_once()
            assert "function failed" in mock_err.call_args[0][0]


@pytest.mark.unit
class TestLogFunctionCallSync:
    """Sync function decoration."""

    def test_sync_function_returns_result(self) -> None:
        @log_function_call
        def multiply(a: int, b: int) -> int:
            return a * b

        assert multiply(3, 4) == 12

    def test_sync_slow_function_warns(self) -> None:
        @log_function_call
        def slow():
            return "done"

        with patch("app.api.v1.middleware.logging.time.time") as mock_time:
            mock_time.side_effect = [0.0, 1.5]
            with patch("app.api.v1.middleware.logging.wide_log.warning") as mock_warn:
                result = slow()
            mock_warn.assert_called_once()
        assert result == "done"

    def test_sync_function_error_logs_error(self) -> None:
        @log_function_call
        def fail():
            raise RuntimeError("sync fail")

        with patch("app.api.v1.middleware.logging.wide_log.error") as mock_err:
            with pytest.raises(RuntimeError, match="sync fail"):
                fail()
            mock_err.assert_called_once()

    def test_sync_fast_function_no_warning(self) -> None:
        @log_function_call
        def fast():
            return 42

        with patch("app.api.v1.middleware.logging.time.time") as mock_time:
            mock_time.side_effect = [0.0, 0.1]
            with patch("app.api.v1.middleware.logging.wide_log.warning") as mock_warn:
                result = fast()
            mock_warn.assert_not_called()
        assert result == 42
