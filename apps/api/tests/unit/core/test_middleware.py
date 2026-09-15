"""Middleware registration order — the invariant PostHog identity rests on.

Starlette runs app.user_middleware outermost-first, so a middleware's index
IS its execution order. Two orderings here are load-bearing and neither was
asserted anywhere; the module had no unit test at all.
"""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI, WebSocket
from limits import parse
import pytest
from slowapi.errors import RateLimitExceeded
from slowapi.wrappers import Limit
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient

from app.api.v1.middleware.auth import PostHogRequestContextMiddleware
from app.api.v1.middleware.websocket_wide_event import WebSocketWideEventMiddleware
from app.core.middleware import configure_middleware, rate_limit_handler
from shared.py.wide_events import log


def _boundary_fields() -> dict[str, object]:
    event = log.get()
    return {key: event.get(key) for key in ("task", "trace_id", "path")}


@pytest.fixture
def ws_client() -> TestClient:
    app = FastAPI()

    @app.websocket("/api/v1/ws/device/")
    async def device(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json(_boundary_fields())
        await websocket.close()

    @app.websocket("/api/v1/ws/chat")
    async def chat(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json(_boundary_fields())
        await websocket.close()

    @app.get("/plain")
    async def plain() -> dict[str, object]:
        return _boundary_fields()

    app.add_middleware(WebSocketWideEventMiddleware)
    return TestClient(app)


class TestWebSocketWideEventBoundary:
    def test_the_device_socket_gets_its_own_task_and_the_callers_trace_id(
        self, ws_client: TestClient
    ) -> None:
        with ws_client.websocket_connect(
            "/api/v1/ws/device/", headers={"x-trace-id": "trace-1"}
        ) as ws:
            fields = ws.receive_json()

        assert fields == {
            "task": "device_ws_connection",
            "trace_id": "trace-1",
            "path": "/api/v1/ws/device/",
        }

    def test_any_other_socket_is_a_generic_connection_with_a_minted_trace(
        self, ws_client: TestClient
    ) -> None:
        with ws_client.websocket_connect("/api/v1/ws/chat") as ws:
            fields = ws.receive_json()

        assert (fields["task"], fields["path"]) == ("ws_connection", "/api/v1/ws/chat")
        assert isinstance(fields["trace_id"], str)
        assert fields["trace_id"]

    def test_http_requests_pass_through_without_a_boundary(self, ws_client: TestClient) -> None:
        assert ws_client.get("/plain", headers={"x-trace-id": "trace-1"}).json()["task"] is None


@pytest.fixture
def middleware_names() -> list[str]:
    app = FastAPI()
    configure_middleware(app)
    return [m.cls.__name__ for m in app.user_middleware]


def test_posthog_context_is_registered(middleware_names: list[str]) -> None:
    """Without it no authenticated request is identified and every capture lands on an anonymous profile."""
    assert "PostHogRequestContextMiddleware" in middleware_names


def test_posthog_context_runs_inside_workos_auth(middleware_names: list[str]) -> None:
    """Registered the other way round it would run first, see no user, and silently identify nobody."""
    assert middleware_names.index("WorkOSAuthMiddleware") < middleware_names.index(
        "PostHogRequestContextMiddleware"
    )


def test_bot_auth_runs_inside_posthog_context(middleware_names: list[str]) -> None:
    """BotAuthMiddleware runs inside the PostHog context, which has already decided nobody to identify — hence capture_event(user_id, ...) on bot routes."""
    assert middleware_names.index("PostHogRequestContextMiddleware") < (
        middleware_names.index("BotAuthMiddleware")
    )


class TestPostHogContextDoesNotSwallowExceptions:
    """The context must not become the thing that reports the error.

    new_context autocaptures escaping exceptions by default, through the
    MODULE-level posthog client — which this codebase never configures, since
    it builds a Posthog() instance via the lazy provider. That autocapture
    raises ValueError("API key is required") on the way out and REPLACES the
    real exception, so every authenticated 500 reaches the error handler, the
    wide event and Sentry as the same bogus ValueError.

    Order assertions above cannot catch this; only driving a request can.
    """

    @staticmethod
    def _app_that_raises() -> FastAPI:
        app = FastAPI()

        class _AuthenticateEveryone(BaseHTTPMiddleware):
            async def dispatch(
                self, request: Request, call_next: RequestResponseEndpoint
            ) -> Response:
                request.state.user = {"user_id": "user-123"}
                return await call_next(request)

        app.add_middleware(PostHogRequestContextMiddleware)
        app.add_middleware(_AuthenticateEveryone)

        @app.get("/boom")
        async def boom() -> None:
            raise RuntimeError("the real bug in the handler")

        return app

    def test_the_handlers_own_exception_is_what_propagates(self) -> None:
        with patch("app.api.v1.middleware.auth.providers") as providers:
            providers.is_available.return_value = True
            providers.get.return_value = MagicMock()
            client = TestClient(self._app_that_raises())

            with pytest.raises(RuntimeError, match="the real bug in the handler"):
                client.get("/boom")


class TestRateLimitHandler:
    """slowapi's 429 answers before any route runs, so it must be the envelope too."""

    def test_configure_middleware_registers_it_for_slowapi(self) -> None:
        app = FastAPI()
        configure_middleware(app)
        assert app.exception_handlers[RateLimitExceeded] is rate_limit_handler

    @staticmethod
    def _app_that_is_rate_limited(retry_after: int | None) -> FastAPI:
        app = FastAPI()
        app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
        limit = Limit(
            parse("5/minute"),
            key_func=lambda: "client",
            scope=None,
            per_method=False,
            methods=None,
            error_message="Too many requests, slow down",
            exempt_when=None,
            cost=1,
            override_defaults=False,
        )

        @app.get("/limited")
        async def limited() -> None:
            exc = RateLimitExceeded(limit)
            if retry_after is not None:
                exc.retry_after = retry_after
            raise exc

        return app

    def test_the_429_body_is_the_envelope_with_the_retry_hint(self) -> None:
        resp = TestClient(self._app_that_is_rate_limited(30)).get("/limited")
        assert resp.status_code == 429
        assert resp.json() == {
            "message": "Too many requests, slow down",
            "code": "rate_limit_exceeded",
            "retry_after": 30,
        }

    def test_no_retry_hint_is_an_explicit_null(self) -> None:
        resp = TestClient(self._app_that_is_rate_limited(None)).get("/limited")
        assert resp.status_code == 429
        assert resp.json() == {
            "message": "Too many requests, slow down",
            "code": "rate_limit_exceeded",
            "retry_after": None,
        }
