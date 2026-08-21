"""Middleware registration order — the invariant PostHog identity rests on.

Starlette runs ``app.user_middleware`` outermost-first, so a middleware's index
IS its execution order. Two orderings here are load-bearing and neither was
asserted anywhere; the module had no unit test at all.
"""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
import pytest
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient

from app.api.v1.middleware.auth import PostHogRequestContextMiddleware
from app.core.middleware import configure_middleware


@pytest.fixture
def middleware_names() -> list[str]:
    app = FastAPI()
    configure_middleware(app)
    return [m.cls.__name__ for m in app.user_middleware]


def test_posthog_context_is_registered(middleware_names: list[str]) -> None:
    """Without it no authenticated request is identified and every capture in
    a route handler lands on an anonymous profile."""
    assert "PostHogRequestContextMiddleware" in middleware_names


def test_posthog_context_runs_inside_workos_auth(middleware_names: list[str]) -> None:
    """It reads ``request.state.user``, which WorkOSAuthMiddleware populates.

    Registered the other way round it would run first, see no user, and
    silently identify nobody — the events still send, just unattributed.
    """
    assert middleware_names.index("WorkOSAuthMiddleware") < middleware_names.index(
        "PostHogRequestContextMiddleware"
    )


def test_bot_auth_runs_inside_posthog_context(middleware_names: list[str]) -> None:
    """The documented reason bot routes must attribute explicitly.

    BotAuthMiddleware populates ``request.state.user`` for bot API-key traffic,
    but it runs INSIDE the PostHog context, which has already decided there is
    nobody to identify. Hence ``capture_event(user_id, ...)`` rather than
    ``capture_context_event`` on every bot route (see apps/api/CLAUDE.md).
    Should this order ever flip, that guidance becomes wrong.
    """
    assert middleware_names.index("PostHogRequestContextMiddleware") < (
        middleware_names.index("BotAuthMiddleware")
    )


class TestPostHogContextDoesNotSwallowExceptions:
    """The context must not become the thing that reports the error.

    ``new_context`` autocaptures escaping exceptions by default, through the
    MODULE-level posthog client — which this codebase never configures, since
    it builds a ``Posthog()`` instance via the lazy provider. That autocapture
    raises ``ValueError("API key is required")`` on the way out and REPLACES the
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
