"""The hosted voice chain: a WorkOS session mints /token, and the voice worker replays its agent token on chat-stream.

The worker reads agentToken out of the LiveKit participant metadata and sends
it as a Bearer token on POST /api/v1/chat-stream, the one agent-only path. The
real WorkOS middleware runs on both legs; only the chat-stream handler is a
probe, so no agent turn runs.
"""

from collections.abc import Callable
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
import httpx
import pytest
from workos import AsyncWorkOSClient

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.middleware.auth import WorkOSAuthMiddleware
from app.config.settings import settings
from app.constants.auth import WOS_SESSION_COOKIE
from app.db.repositories.users import user_repository
from app.models.payment_models import PlanType
from app.models.user_models import AuthenticatedUser, UserDocument
from app.services.device.device_auth import create_device_token
from tests.helpers import (
    WORKOS_TEST_KID,
    forge_jwt,
    forge_rs256_jwt,
    hostile_jwts,
    read_jwt,
    seal_workos_session,
    workos_access_token_claims,
)

USER_EMAIL = "voice@gaia.test"
USER_ID = str(ObjectId())


@pytest.fixture
def voice_user(monkeypatch: pytest.MonkeyPatch) -> None:
    user = UserDocument(id=USER_ID, email=USER_EMAIL, name="Voice")
    monkeypatch.setattr(
        user_repository,
        "get_by_email",
        AsyncMock(side_effect=lambda e: user if e == USER_EMAIL else None),
    )
    monkeypatch.setattr(
        user_repository, "get", AsyncMock(side_effect=lambda i: user if i == USER_ID else None)
    )
    monkeypatch.setattr(user_repository, "touch_last_active", AsyncMock())


@pytest.fixture
def chat_stream_app(workos_client: AsyncWorkOSClient, voice_user: None) -> FastAPI:
    """Put the real middleware in front of a chat-stream probe that reports who it authenticated."""
    app = FastAPI()

    @app.post("/api/v1/chat-stream")
    async def chat_stream(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, str | None]:
        return {"user_id": user.user_id, "email": user.email}

    app.add_middleware(WorkOSAuthMiddleware, workos_client=workos_client)
    return app


async def _mint_agent_token(
    workos_client: AsyncWorkOSClient,
    workos_signing_key: rsa.RSAPrivateKey,
    workos_cookie_password: str,
    real_auth_app: Callable[[AsyncWorkOSClient | None], FastAPI],
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    """Sign in through WorkOS, call the real voice /token, and read agentToken as the worker does."""
    monkeypatch.setattr(settings, "LIVEKIT_API_KEY", "lk_test_key")
    monkeypatch.setattr(settings, "LIVEKIT_API_SECRET", "lk_test_secret_" + "x" * 32)
    monkeypatch.setattr(settings, "LIVEKIT_URL", "wss://voice.test")
    access_token = forge_rs256_jwt(
        workos_access_token_claims(), workos_signing_key, kid=WORKOS_TEST_KID
    )
    cookie = seal_workos_session(access_token, workos_cookie_password, email=USER_EMAIL)
    with (
        patch(
            "app.services.payments.payment_service.payment_service.get_user_subscription_status",
            new_callable=AsyncMock,
            return_value=MagicMock(plan_type=PlanType.PRO),
        ),
        patch(
            "app.api.v1.endpoints.voice.get_user_voice", new_callable=AsyncMock, return_value=None
        ),
    ):
        transport = httpx.ASGITransport(
            app=real_auth_app(workos_client), raise_app_exceptions=False
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            client.cookies.set(WOS_SESSION_COOKIE, cookie)
            response = await client.get("/api/v1/token")
    assert response.status_code == 200, response.text
    metadata = json.loads(read_jwt(response.json()["participantToken"])[1]["metadata"])
    agent_token: str = metadata["agentToken"]
    return agent_token


async def _chat_stream(app: FastAPI, bearer: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(
            "/api/v1/chat-stream", headers={"Authorization": f"Bearer {bearer}"}
        )


async def test_the_voice_token_agent_credential_authenticates_chat_stream_as_its_user(
    chat_stream_app: FastAPI,
    workos_client: AsyncWorkOSClient,
    workos_signing_key: rsa.RSAPrivateKey,
    workos_cookie_password: str,
    real_auth_app: Callable[[AsyncWorkOSClient | None], FastAPI],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_token = await _mint_agent_token(
        workos_client, workos_signing_key, workos_cookie_password, real_auth_app, monkeypatch
    )

    response = await _chat_stream(chat_stream_app, agent_token)

    assert response.status_code == 200, response.text
    assert response.json() == {"user_id": USER_ID, "email": USER_EMAIL}


@pytest.mark.parametrize("kind", [*sorted(hostile_jwts({}, "s")), "device_token", "bot_role"])
async def test_a_bad_agent_token_is_401_on_chat_stream(chat_stream_app: FastAPI, kind: str) -> None:
    claims = {"sub": USER_ID, "role": "agent", "exp": int(time.time()) + 600}
    tokens = {
        **hostile_jwts(claims, settings.AGENT_SECRET),
        "device_token": create_device_token("device-1", USER_ID)[0],
        "bot_role": forge_jwt({**claims, "role": "bot"}, settings.AGENT_SECRET),
    }

    response = await _chat_stream(chat_stream_app, tokens[kind])

    assert response.status_code == 401, response.text
