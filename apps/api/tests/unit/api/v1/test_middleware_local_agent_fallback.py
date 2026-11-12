"""Unit tests for the agent-JWT fallback inside AUTH_MODE local dispatch.

The WorkOS branch accepts an AGENT_SECRET-signed JWT on agent-only paths (how
LiveKit voice authenticates its conversation calls); the local-session branch must
behave identically or self-hosted voice breaks with 401s. verify_agent_token
is faked at the same seam the WorkOS-mode suite uses.
"""

from datetime import UTC, datetime, timedelta
import time
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
import pytest
from starlette.testclient import TestClient

from app.api.v1.middleware import agent_auth
from app.api.v1.middleware.agent_auth import AgentTokenInfo
from app.config.settings import settings
from app.constants.auth import JWT_ALGORITHM
from app.models.user_models import UserDocument
from tests.helpers import (
    JOSE_AGENT_DEVICE_SECRET,
    JOSE_MINTED_AGENT_TOKEN,
    forge_jwt,
    hostile_jwts,
)

TEST_SECRET = "test-instance-secret-" + "x" * 16
ADMIN_ID = "507f1f77bcf86cd799439011"


def _warm_instance_secret(monkeypatch) -> None:
    """Warm local_auth_utils' secret cache exactly as production finds it."""
    from app.utils import local_auth_utils

    monkeypatch.setattr(local_auth_utils, "_resolved_secret", TEST_SECRET)


def _session_token(user_id: str) -> str:
    """Return a valid gaia_session JWT, encoded as issue_session_token does."""
    now = int(datetime.now(UTC).timestamp())
    return forge_jwt(
        {"sub": user_id, "exp": now + int(timedelta(days=1).total_seconds()), "iat": now},
        TEST_SECRET,
        alg=JWT_ALGORITHM,
    )


def _build_local_app() -> FastAPI:
    """Build a minimal app behind WorkOSAuthMiddleware in local mode.

    One agent-eligible route (a voice send) and one ordinary protected
    route, both reporting what request.state carries after dispatch.
    """
    from app.api.v1.middleware.auth import WorkOSAuthMiddleware

    def probe(request: Request) -> dict:
        user = getattr(request.state, "user", None)
        authed = getattr(request.state, "authenticated", False)
        if not authed or not user:
            return {"authenticated": False, "user": None}
        return {
            "authenticated": True,
            # request.state.user is the frozen AuthenticatedUser model.
            "email": user.email,
            "auth_provider": user.auth_provider,
            "impersonated": user.impersonated,
        }

    app = FastAPI()
    app.post("/api/v1/conversations/conv-1/messages")(probe)
    app.get("/api/v1/protected")(probe)
    app.add_middleware(WorkOSAuthMiddleware, workos_client=MagicMock())
    return app


class TestLocalModeAgentTokenFallback:
    def test_valid_local_session_wins_over_agent_token(self, monkeypatch) -> None:
        """Give session credentials precedence over a presented agent JWT; flip surfaces as wrong identity."""
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
                return_value=AgentTokenInfo(user_id=other_id, impersonated=True),
            ) as fake_verify,
            patch(
                "app.api.v1.middleware.auth.user_repository.get",
                return_value=user_doc,
            ) as fake_repo_get,
        ):
            client = TestClient(_build_local_app())
            client.cookies.set("gaia_session", _session_token(ADMIN_ID))
            resp = client.post(
                "/api/v1/conversations/conv-1/messages",
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

    def test_agent_jwt_authenticates_a_voice_send_in_local_mode(self, monkeypatch) -> None:
        """Fall back to verify_agent_token on an agent-only path with no cookie, like the WorkOS branch."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS_EMAIL", None)
        _warm_instance_secret(monkeypatch)

        user_doc = UserDocument.model_validate(
            {"id": ADMIN_ID, "email": "voice@gaia.dev", "name": "Voice User"}
        )
        with (
            patch(
                "app.api.v1.middleware.auth.verify_agent_token",
                return_value=AgentTokenInfo(user_id=ADMIN_ID, impersonated=True),
            ),
            patch(
                "app.api.v1.middleware.auth.user_repository.get",
                return_value=user_doc,
            ) as fake_repo_get,
        ):
            client = TestClient(_build_local_app())
            resp = client.post(
                "/api/v1/conversations/conv-1/messages",
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
        """Scope the fallback to agent-only paths; elsewhere a bare agent JWT authenticates nobody."""
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS_EMAIL", None)
        _warm_instance_secret(monkeypatch)

        with patch(
            "app.api.v1.middleware.auth.verify_agent_token",
            return_value=AgentTokenInfo(user_id=ADMIN_ID, impersonated=True),
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


class TestLocalModeRealAgentTokens:
    """The real verify_agent_token behind the middleware, against real and hostile tokens."""

    def _post(self, monkeypatch, token: str) -> tuple[dict, MagicMock]:
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        monkeypatch.setattr(settings, "DEV_AUTH_BYPASS_EMAIL", None)
        monkeypatch.setattr(agent_auth, "AGENT_SECRET", JOSE_AGENT_DEVICE_SECRET)
        _warm_instance_secret(monkeypatch)
        user_doc = UserDocument.model_validate(
            {"id": ADMIN_ID, "email": "voice@gaia.dev", "name": "Voice User"}
        )
        with patch(
            "app.api.v1.middleware.auth.user_repository.get", return_value=user_doc
        ) as fake_repo_get:
            resp = TestClient(_build_local_app()).post(
                "/api/v1/conversations/conv-1/messages",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        return resp.json(), fake_repo_get

    def test_an_agent_token_minted_by_python_jose_authenticates(self, monkeypatch) -> None:
        body, fake_repo_get = self._post(monkeypatch, JOSE_MINTED_AGENT_TOKEN)
        assert body["authenticated"] is True, body
        assert body["impersonated"] is True
        fake_repo_get.assert_called_once_with("u-jose")

    @pytest.mark.parametrize("kind", sorted(hostile_jwts({}, "s")))
    def test_a_hostile_agent_token_stays_anonymous(self, monkeypatch, kind: str) -> None:
        claims = {"sub": ADMIN_ID, "role": "agent", "exp": int(time.time()) + 600}
        body, fake_repo_get = self._post(
            monkeypatch, hostile_jwts(claims, JOSE_AGENT_DEVICE_SECRET)[kind]
        )
        assert body["authenticated"] is False
        fake_repo_get.assert_not_called()
