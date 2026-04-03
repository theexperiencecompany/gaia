"""Unit tests for the WorkOS auth middleware.

Tests cover session extraction from cookies and Authorization headers,
excluded paths, agent-only paths, session refresh cookie setting,
and the _authenticate_session helper.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app.api.v1.middleware.auth import WorkOSAuthMiddleware, get_current_user


# ---------------------------------------------------------------------------
# get_current_user dependency
# ---------------------------------------------------------------------------


@pytest.mark.unit
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


@pytest.mark.unit
class TestWorkOSAuthMiddlewareExcludedPaths:
    """Requests to excluded paths should pass through without authentication."""

    def test_health_endpoint_skips_auth(self) -> None:
        app = _build_test_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_custom_exclude_paths(self) -> None:
        app = _build_test_app(
            middleware_kwargs={"exclude_paths": ["/health", "/api/v1/protected"]}
        )
        client = TestClient(app)
        resp = client.get("/api/v1/protected")
        assert resp.status_code == 200
        # No auth was performed, so user is None
        assert resp.json()["user"] is None


@pytest.mark.unit
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
            resp = client.get(
                "/api/v1/protected", cookies={"wos_session": "sealed_tok"}
            )
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
            resp = client.get("/api/v1/protected", cookies={"wos_session": "old_tok"})
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
            resp = client.get("/api/v1/protected", cookies={"wos_session": "bad_tok"})
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
            resp = client.get("/api/v1/protected", cookies={"wos_session": "tok"})
        # Request should still go through, just unauthenticated
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False


@pytest.mark.unit
class TestWorkOSAuthMiddlewareAgentAuth:
    """Agent-only paths use JWT agent tokens when no session is present."""

    def test_agent_token_authenticates_on_agent_path(self) -> None:
        app = _build_test_app()
        user_data = {
            "_id": "507f1f77bcf86cd799439011",
            "email": "agent@test.com",
            "name": "Agent User",
            "picture": None,
        }
        with (
            patch(
                "app.api.v1.middleware.auth.verify_agent_token",
                return_value={
                    "user_id": "507f1f77bcf86cd799439011",
                    "impersonated": True,
                },
            ),
            patch(
                "app.api.v1.middleware.auth.users_collection.find_one",
                new_callable=AsyncMock,
                return_value=user_data,
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
                "app.api.v1.middleware.auth.users_collection.find_one",
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


@pytest.mark.unit
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
                "app.api.v1.middleware.auth.users_collection.update_one",
                new_callable=AsyncMock,
            ) as mock_update,
        ):
            result_user, result_sess = await middleware._authenticate_session("tok")
        assert result_user == user_info
        assert result_sess == "new_sess"
        mock_update.assert_called_once()

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

    async def test_update_one_error_returns_none_user(self) -> None:
        """If updating last_active_at fails, user_info becomes None."""
        user_info = {"user_id": "u1", "email": "a@b.com", "name": "Test"}
        middleware = WorkOSAuthMiddleware(app=MagicMock(), workos_client=MagicMock())
        with (
            patch(
                "app.api.v1.middleware.auth.authenticate_workos_session",
                new_callable=AsyncMock,
                return_value=(user_info, None),
            ),
            patch(
                "app.api.v1.middleware.auth.users_collection.update_one",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db err"),
            ),
        ):
            result_user, result_sess = await middleware._authenticate_session("tok")
        # The middleware catches the exception and returns None for user
        assert result_user is None
