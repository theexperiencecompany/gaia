"""Unit tests for the agent-JWT fallback inside AUTH_MODE="local" dispatch.

The WorkOS dispatch branch has always accepted an ``AGENT_SECRET``-signed JWT
on agent-only paths (how LiveKit voice authenticates its chat-stream turns);
the local-session branch must behave identically or self-hosted voice breaks
with 401s. These tests pin the contract through the real middleware dispatch
against a minimal app, with ``verify_agent_token`` faked at the same seam the
WorkOS-mode suite (``tests/unit/api/test_auth_middleware.py``) uses.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from jose import jwt
from starlette.testclient import TestClient

from app.config.settings import settings
from app.constants.auth import JWT_ALGORITHM
from app.models.user_models import UserDocument

TEST_SECRET = "test-instance-secret-" + "x" * 16
ADMIN_ID = "507f1f77bcf86cd799439011"


def _warm_instance_secret(monkeypatch) -> None:
    """Warm local_auth_utils' secret cache exactly as production finds it."""
    from app.utils import local_auth_utils

    monkeypatch.setattr(local_auth_utils, "_resolved_secret", TEST_SECRET)


def _session_token(user_id: str) -> str:
    """A valid gaia_session JWT, encoded the way issue_session_token does."""
    return jwt.encode(
        {
            "sub": user_id,
            "exp": datetime.now(UTC) + timedelta(days=1),
            "iat": datetime.now(UTC),
        },
        TEST_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def _build_local_app() -> FastAPI:
    """Minimal app behind WorkOSAuthMiddleware in local mode, with one
    agent-eligible route (/api/v1/chat-stream) and one ordinary protected
    route. Both report what request.state carries after dispatch."""
    from app.api.v1.middleware.auth import WorkOSAuthMiddleware

    def probe(request: Request) -> dict:
        user = getattr(request.state, "user", None)
        authed = getattr(request.state, "authenticated", False)
        if not authed or not user:
            return {"authenticated": False, "user": None}
        return {
            "authenticated": True,
            "email": user.get("email"),
            "auth_provider": user.get("auth_provider"),
            "impersonated": user.get("impersonated", False),
        }

    app = FastAPI()
    app.post("/api/v1/chat-stream")(probe)
    app.get("/api/v1/protected")(probe)
    app.add_middleware(WorkOSAuthMiddleware, workos_client=MagicMock())
    return app


class TestLocalModeAgentTokenFallback:
    def test_valid_local_session_wins_over_agent_token(self, monkeypatch) -> None:
        """A valid gaia_session cookie authenticates the request even when an
        agent JWT is also presented — session credentials take precedence and
        the agent-token path is never consulted. The agent token names a
        different user, so an ordering flip would surface as the wrong
        identity, not just a different code path."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS_EMAIL", None)
        _warm_instance_secret(monkeypatch)

        other_id = "607f1f77bcf86cd7994390aa"
        user_doc = UserDocument.model_validate(
            {"id": ADMIN_ID, "email": "session@gaia.dev", "name": "Session User"}
        )
        with (
            patch(
                "app.api.v1.middleware.auth.verify_agent_token",
                return_value={"user_id": other_id, "impersonated": True},
            ) as fake_verify,
            patch(
                "app.api.v1.middleware.auth.user_repository.get",
                return_value=user_doc,
            ) as fake_repo_get,
        ):
            client = TestClient(_build_local_app())
            client.cookies.set("gaia_session", _session_token(ADMIN_ID))
            resp = client.post(
                "/api/v1/chat-stream",
                headers={"Authorization": "Bearer agent_jwt_token"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True, resp.text
        assert data["email"] == "session@gaia.dev"
        assert data["auth_provider"] == "email"
        assert data["impersonated"] is False
        fake_verify.assert_not_called()
        # Only the session's user was ever loaded.
        fake_repo_get.assert_called_once_with(ADMIN_ID)

    def test_agent_jwt_authenticates_chat_stream_in_local_mode(self, monkeypatch) -> None:
        """No cookie, only an agent JWT on an agent-only path: the local branch
        must fall back to verify_agent_token and load that user exactly like
        the WorkOS branch — full doc spread, impersonated=True. This is how
        LiveKit voice turns authenticate on a self-hosted instance."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS_EMAIL", None)
        _warm_instance_secret(monkeypatch)

        user_doc = UserDocument.model_validate(
            {"id": ADMIN_ID, "email": "voice@gaia.dev", "name": "Voice User"}
        )
        with (
            patch(
                "app.api.v1.middleware.auth.verify_agent_token",
                return_value={"user_id": ADMIN_ID, "impersonated": True},
            ),
            patch(
                "app.api.v1.middleware.auth.user_repository.get",
                return_value=user_doc,
            ) as fake_repo_get,
        ):
            client = TestClient(_build_local_app())
            resp = client.post(
                "/api/v1/chat-stream",
                headers={"Authorization": "Bearer agent_jwt_token"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True, resp.text
        assert data["email"] == "voice@gaia.dev"
        assert data["impersonated"] is True
        fake_repo_get.assert_called_once_with(ADMIN_ID)


class TestLocalModeAgentTokenScope:
    def test_agent_jwt_on_non_agent_path_stays_anonymous(self, monkeypatch) -> None:
        """The fallback is scoped to agent-only paths: elsewhere a bare agent
        JWT must not authenticate anyone, mirroring the WorkOS branch."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS_EMAIL", None)
        _warm_instance_secret(monkeypatch)

        with patch(
            "app.api.v1.middleware.auth.verify_agent_token",
            return_value={"user_id": ADMIN_ID, "impersonated": True},
        ) as fake_verify:
            client = TestClient(_build_local_app())
            resp = client.get(
                "/api/v1/protected",
                headers={"Authorization": "Bearer agent_jwt_token"},
            )

        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False
        # Never even consulted off the agent paths.
        fake_verify.assert_not_called()
