"""Unit tests for the WorkOS auth middleware.

Tests cover session extraction from cookies and Authorization headers,
excluded paths, agent-only paths, session refresh cookie setting,
and the _authenticate_session helper.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from posthog.contexts import get_context_distinct_id
import pytest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.testclient import TestClient

from app.api.v1.middleware.auth import (
    PostHogRequestContextMiddleware,
    WorkOSAuthMiddleware,
    get_current_user,
)
from app.models.user_models import UserDocument


@pytest.fixture(autouse=True)
def _no_dev_bypass(monkeypatch):
    """This file tests the WorkOS session/agent paths. The developer's ambient
    .env legitimately sets DEV_AUTH_BYPASS_EMAIL, which would short-circuit the
    middleware before anything under test runs — pin it off. The bypass path
    itself is covered in tests/integration/api/test_dev_endpoints.py."""
    from app.config.settings import settings

    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS_EMAIL", None)


# ---------------------------------------------------------------------------
# get_current_user dependency
# ---------------------------------------------------------------------------


class TestGetCurrentUser:
    def test_returns_user_from_request_state(self) -> None:
        request = MagicMock()
        request.state.user = {"user_id": "u1", "email": "a@b.com"}
        result = get_current_user(request)
        assert result == {"user_id": "u1", "email": "a@b.com"}

    def test_returns_none_when_no_user(self) -> None:
        request = MagicMock()
        # Simulate a request.state that has no 'user' attribute
        request.state = MagicMock(spec=[])
        result = get_current_user(request)
        assert result is None


# ---------------------------------------------------------------------------
# WorkOSAuthMiddleware — unit tests with a minimal ASGI app
# ---------------------------------------------------------------------------


def _build_test_app(middleware_kwargs: dict | None = None):
    """Create a minimal FastAPI app with WorkOSAuthMiddleware for testing."""
    from fastapi import FastAPI, Request

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/api/v1/protected")
    async def protected(request: Request):
        user = getattr(request.state, "user", None)
        authed = getattr(request.state, "authenticated", False)
        return {"user": user, "authenticated": authed}

    @app.post("/api/v1/chat-stream")
    async def chat_stream(request: Request):
        user = getattr(request.state, "user", None)
        authed = getattr(request.state, "authenticated", False)
        return {"user": user, "authenticated": authed}

    kwargs = middleware_kwargs or {}
    # Always provide a mock WorkOS client so we don't need real credentials
    if "workos_client" not in kwargs:
        kwargs["workos_client"] = MagicMock()
    app.add_middleware(WorkOSAuthMiddleware, **kwargs)
    return app


class TestWorkOSAuthMiddlewareExcludedPaths:
    """Requests to excluded paths should pass through without authentication."""

    def test_health_endpoint_skips_auth(self) -> None:
        app = _build_test_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_custom_exclude_paths(self) -> None:
        app = _build_test_app(middleware_kwargs={"exclude_paths": ["/health", "/api/v1/protected"]})
        client = TestClient(app)
        resp = client.get("/api/v1/protected")
        assert resp.status_code == 200
        # No auth was performed, so user is None
        assert resp.json()["user"] is None


class TestWorkOSAuthMiddlewareSessionAuth:
    """Session-based authentication via cookies and Authorization header."""

    def test_no_session_sets_unauthenticated(self) -> None:
        app = _build_test_app()
        client = TestClient(app)
        resp = client.get("/api/v1/protected")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["user"] is None

    def test_cookie_session_authenticates(self) -> None:
        user_info = {"user_id": "u1", "email": "a@b.com", "name": "Test"}
        app = _build_test_app()
        with patch.object(
            WorkOSAuthMiddleware,
            "_authenticate_session",
            new_callable=AsyncMock,
            return_value=(user_info, None),
        ):
            client = TestClient(app)
            client.cookies.set("wos_session", "sealed_tok")
            resp = client.get("/api/v1/protected")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["user"]["email"] == "a@b.com"

    def test_bearer_header_fallback(self) -> None:
        user_info = {"user_id": "u2", "email": "b@c.com", "name": "User2"}
        app = _build_test_app()
        with patch.object(
            WorkOSAuthMiddleware,
            "_authenticate_session",
            new_callable=AsyncMock,
            return_value=(user_info, None),
        ):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/protected",
                headers={"Authorization": "Bearer some_token"},
            )
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True

    def test_session_refresh_sets_cookie(self) -> None:
        user_info = {"user_id": "u1", "email": "a@b.com", "name": "Test"}
        new_session = "refreshed_session_token"
        app = _build_test_app()
        with patch.object(
            WorkOSAuthMiddleware,
            "_authenticate_session",
            new_callable=AsyncMock,
            return_value=(user_info, new_session),
        ):
            client = TestClient(app)
            client.cookies.set("wos_session", "old_tok")
            resp = client.get("/api/v1/protected")
        assert resp.status_code == 200
        # The middleware should set a wos_session cookie
        assert "wos_session" in resp.cookies

    def test_failed_session_sets_auth_failure_state(self) -> None:
        app = _build_test_app()
        with patch.object(
            WorkOSAuthMiddleware,
            "_authenticate_session",
            new_callable=AsyncMock,
            return_value=(None, None),
        ):
            client = TestClient(app)
            client.cookies.set("wos_session", "bad_tok")
            resp = client.get("/api/v1/protected")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    def test_auth_exception_does_not_block_request(self) -> None:
        app = _build_test_app()
        with patch.object(
            WorkOSAuthMiddleware,
            "_authenticate_session",
            new_callable=AsyncMock,
            side_effect=RuntimeError("WorkOS error"),
        ):
            client = TestClient(app)
            client.cookies.set("wos_session", "tok")
            resp = client.get("/api/v1/protected")
        # Request should still go through, just unauthenticated
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False


class TestWorkOSAuthMiddlewareAgentAuth:
    """Agent-only paths use JWT agent tokens when no session is present."""

    def test_agent_token_authenticates_on_agent_path(self) -> None:
        app = _build_test_app()
        user_doc = UserDocument.model_validate(
            {
                "id": "507f1f77bcf86cd799439011",
                "email": "agent@test.com",
                "name": "Agent User",
            }
        )
        with (
            patch(
                "app.api.v1.middleware.auth.verify_agent_token",
                return_value={
                    "user_id": "507f1f77bcf86cd799439011",
                    "impersonated": True,
                },
            ),
            patch(
                "app.api.v1.middleware.auth.user_repository.get",
                new_callable=AsyncMock,
                return_value=user_doc,
            ),
        ):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/chat-stream",
                headers={"Authorization": "Bearer agent_jwt_token"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["user"]["impersonated"] is True

    def test_agent_token_invalid_returns_unauthenticated(self) -> None:
        app = _build_test_app()
        with patch(
            "app.api.v1.middleware.auth.verify_agent_token",
            return_value=None,
        ):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/chat-stream",
                headers={"Authorization": "Bearer bad_token"},
            )
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    def test_agent_token_user_not_in_db(self) -> None:
        app = _build_test_app()
        with (
            patch(
                "app.api.v1.middleware.auth.verify_agent_token",
                return_value={
                    "user_id": "507f1f77bcf86cd799439011",
                    "impersonated": True,
                },
            ),
            patch(
                "app.api.v1.middleware.auth.user_repository.get",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/chat-stream",
                headers={"Authorization": "Bearer agent_jwt_token"},
            )
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    def test_agent_token_invalid_user_id_format(self) -> None:
        app = _build_test_app()
        with patch(
            "app.api.v1.middleware.auth.verify_agent_token",
            return_value={"user_id": "not-an-objectid", "impersonated": True},
        ):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/chat-stream",
                headers={"Authorization": "Bearer agent_jwt"},
            )
        assert resp.status_code == 200
        # Invalid ObjectId format should not crash
        assert resp.json()["authenticated"] is False


class TestAuthenticateSession:
    """Unit tests for _authenticate_session helper."""

    async def test_successful_authentication_updates_last_activity(self) -> None:
        user_info = {"user_id": "u1", "email": "a@b.com", "name": "Test"}
        middleware = WorkOSAuthMiddleware(app=MagicMock(), workos_client=MagicMock())
        with (
            patch(
                "app.api.v1.middleware.auth.authenticate_workos_session",
                new_callable=AsyncMock,
                return_value=(user_info, "new_sess"),
            ),
            patch(
                "app.api.v1.middleware.auth.user_repository.touch_last_active",
                new_callable=AsyncMock,
            ) as mock_touch,
        ):
            result_user, result_sess = await middleware._authenticate_session("tok")
        assert result_user == user_info
        assert result_sess == "new_sess"
        mock_touch.assert_awaited_once_with("a@b.com")

    async def test_failed_authentication(self) -> None:
        middleware = WorkOSAuthMiddleware(app=MagicMock(), workos_client=MagicMock())
        with patch(
            "app.api.v1.middleware.auth.authenticate_workos_session",
            new_callable=AsyncMock,
            return_value=(None, None),
        ):
            result_user, result_sess = await middleware._authenticate_session("tok")
        assert result_user is None
        assert result_sess is None

    async def test_auth_outcome_is_independent_of_last_active_touch(self) -> None:
        """The last-active touch is fire-and-forget: a valid WorkOS session
        authenticates regardless of the touch (the previous swallow that turned a
        touch failure into a failed auth is gone; touch_last_active never raises)."""
        user_info = {"user_id": "u1", "email": "a@b.com", "name": "Test"}
        middleware = WorkOSAuthMiddleware(app=MagicMock(), workos_client=MagicMock())
        with (
            patch(
                "app.api.v1.middleware.auth.authenticate_workos_session",
                new_callable=AsyncMock,
                return_value=(user_info, None),
            ),
            patch(
                "app.api.v1.middleware.auth.user_repository.touch_last_active",
                new_callable=AsyncMock,
            ) as mock_touch,
        ):
            result_user, _ = await middleware._authenticate_session("tok")
        assert result_user == user_info
        mock_touch.assert_awaited_once_with("a@b.com")


# ---------------------------------------------------------------------------
# PostHogRequestContextMiddleware — the identity every authenticated capture
# inherits. If it binds nothing, or binds the wrong id, every event a route
# handler emits lands on an anonymous (or a second) profile and cross-surface
# funnels silently stop joining.
# ---------------------------------------------------------------------------

GAIA_USER_ID = "6812f0b3c9a14e2b7d5a91cc"
REQUEST_PATH = "/api/v1/notes"


async def _noop_asgi(scope, receive, send) -> None:  # pragma: no cover - never called
    """BaseHTTPMiddleware requires an inner app; ``dispatch`` is driven directly."""


def _authenticated_request(user: dict | None) -> Request:
    """A plain GET carrying ``state.user`` exactly as WorkOSAuthMiddleware leaves it."""
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "server": ("testserver", 80),
            "path": REQUEST_PATH,
            "raw_path": REQUEST_PATH.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
        }
    )
    if user is not None:
        request.state.user = user
    return request


async def _dispatch(request: Request) -> tuple[Response, dict]:
    """Run the middleware over ``request``, reporting what the route saw.

    ``downstream`` records the identity a capture inside the handler would be
    attributed to, plus the path the handler could still read — the middleware
    must hand the route its own request, not a substitute.
    """
    downstream: dict = {}

    async def call_next(forwarded: Request) -> Response:
        downstream["distinct_id"] = get_context_distinct_id()
        downstream["path"] = forwarded.url.path
        return PlainTextResponse("handler ran")

    middleware = PostHogRequestContextMiddleware(app=_noop_asgi)
    response = await middleware.dispatch(request, call_next)
    return response, downstream


class TestPostHogRequestContextIdentity:
    async def test_authenticated_request_is_identified_by_gaia_user_id(
        self, posthog_provider
    ) -> None:
        """The whole point of the middleware: a capture in the route handler is
        attributed to the stable Mongo user id, with no call site repeating it."""
        posthog_provider(available=True, client=object())

        response, downstream = await _dispatch(_authenticated_request({"user_id": GAIA_USER_ID}))

        assert downstream["distinct_id"] == GAIA_USER_ID
        assert downstream["path"] == REQUEST_PATH
        assert response.body == b"handler ran"

    async def test_identity_does_not_leak_past_the_request(self, posthog_provider) -> None:
        """The context is per-request; work after it must not inherit the user."""
        posthog_provider(available=True, client=object())

        await _dispatch(_authenticated_request({"user_id": GAIA_USER_ID}))

        assert get_context_distinct_id() is None

    async def test_unauthenticated_request_is_not_identified(self, posthog_provider) -> None:
        """Nobody to attribute to — the request must stay personless rather than
        binding the string "None" as a distinct_id and inventing a profile."""
        posthog_provider(available=True, client=object())

        response, downstream = await _dispatch(_authenticated_request(None))

        assert downstream["distinct_id"] is None
        assert downstream["path"] == REQUEST_PATH
        assert response.body == b"handler ran"

    async def test_user_without_a_user_id_is_not_identified(self, posthog_provider) -> None:
        """A user document missing the id is still nobody — never identify ""."""
        posthog_provider(available=True, client=object())

        _, downstream = await _dispatch(_authenticated_request({"email": "a@b.com"}))

        assert downstream["distinct_id"] is None

    async def test_request_is_served_when_posthog_is_unavailable(self, posthog_provider) -> None:
        """Analytics is never load-bearing: no token configured still serves the route."""
        posthog_provider(available=False, client=object())

        response, downstream = await _dispatch(_authenticated_request({"user_id": GAIA_USER_ID}))

        assert downstream["distinct_id"] is None
        assert downstream["path"] == REQUEST_PATH
        assert response.body == b"handler ran"

    async def test_request_is_served_when_the_posthog_client_is_none(
        self, posthog_provider
    ) -> None:
        """Available-but-unbuilt: the provider resolves to None, and identifying
        against no client would raise inside every authenticated request."""
        posthog_provider(available=True, client=None)

        response, downstream = await _dispatch(_authenticated_request({"user_id": GAIA_USER_ID}))

        assert downstream["distinct_id"] is None
        assert downstream["path"] == REQUEST_PATH
        assert response.body == b"handler ran"

    def test_identity_is_bound_through_the_real_asgi_stack(self, posthog_provider) -> None:
        """The unit tests above drive ``dispatch`` directly; this one proves the
        middleware still binds identity when Starlette runs it for real."""
        posthog_provider(available=True, client=object())
        seen: dict = {}

        app = FastAPI()

        class _AuthenticateEveryone(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state.user = {"user_id": GAIA_USER_ID}
                return await call_next(request)

        app.add_middleware(PostHogRequestContextMiddleware)
        app.add_middleware(_AuthenticateEveryone)

        @app.get("/notes")
        async def notes() -> dict:
            seen["distinct_id"] = get_context_distinct_id()
            return {"ok": True}

        assert TestClient(app).get("/notes").status_code == 200
        assert seen["distinct_id"] == GAIA_USER_ID
