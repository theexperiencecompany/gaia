"""The hosted login: a WorkOS sealed-session cookie through the real middleware and the real WorkOS SDK.

The SDK verifies the cookie's RS256 access token with PyJWT against a JWKS it
fetches over HTTP, so a local stub stands in for api.workos.com; the cookie
unsealing, the JWKS fetch, the signature check and the refresh attempt on a
failed check all run for real.
"""

from collections.abc import Callable
import json
import time
from unittest.mock import AsyncMock

from bson import ObjectId
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
import httpx
import pytest
from workos import AsyncWorkOSClient

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.auth import WOS_SESSION_COOKIE
from app.db.repositories.users import user_repository
from app.models.user_models import AuthenticatedUser, UserDocument
from tests.helpers import (
    WORKOS_TEST_KID,
    forge_jwt,
    forge_rs256_jwt,
    rsa_public_jwk,
    seal_workos_session,
    workos_access_token_claims,
)

USER_EMAIL = "hosted@gaia.test"
USER_ID = str(ObjectId())


@pytest.fixture
def hosted_app(
    workos_client: AsyncWorkOSClient,
    real_auth_app: Callable[[AsyncWorkOSClient | None], FastAPI],
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    user = UserDocument(id=USER_ID, email=USER_EMAIL, name="Hosted")
    monkeypatch.setattr(
        user_repository,
        "get_by_email",
        AsyncMock(side_effect=lambda email: user if email == USER_EMAIL else None),
    )
    monkeypatch.setattr(user_repository, "touch_last_active", AsyncMock())
    app = real_auth_app(workos_client)

    @app.get("/probe")
    async def probe(user: AuthenticatedUser = Depends(get_current_user)) -> dict[str, str | None]:
        return {"user_id": user.user_id, "auth_provider": user.auth_provider}

    return app


async def _probe(app: FastAPI, sealed_session: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(WOS_SESSION_COOKIE, sealed_session)
        return await client.get("/probe")


async def test_a_signed_workos_session_authenticates_its_user(
    hosted_app: FastAPI, workos_signing_key: rsa.RSAPrivateKey, workos_cookie_password: str
) -> None:
    token = forge_rs256_jwt(workos_access_token_claims(), workos_signing_key, kid=WORKOS_TEST_KID)

    response = await _probe(
        hosted_app, seal_workos_session(token, workos_cookie_password, email=USER_EMAIL)
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"user_id": USER_ID, "auth_provider": "workos"}


@pytest.mark.parametrize(
    "kind",
    [
        "expired",
        "foreign_key",
        "tampered_payload",
        "alg_none",
        "hmac_with_public_key",
        "not_sealed_with_our_password",
        "unknown_user",
    ],
)
async def test_a_bad_workos_session_is_401(
    hosted_app: FastAPI,
    workos_signing_key: rsa.RSAPrivateKey,
    workos_cookie_password: str,
    kind: str,
) -> None:
    claims = workos_access_token_claims()
    genuine = forge_rs256_jwt(claims, workos_signing_key, kid=WORKOS_TEST_KID)
    header, _, signature = genuine.split(".")
    intruder = forge_rs256_jwt(
        {**claims, "sub": "intruder"}, workos_signing_key, kid=WORKOS_TEST_KID
    )
    foreign_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.dumps(rsa_public_jwk(workos_signing_key, kid=WORKOS_TEST_KID))
    access_tokens = {
        "expired": forge_rs256_jwt(
            {**claims, "exp": int(time.time()) - 60}, workos_signing_key, kid=WORKOS_TEST_KID
        ),
        "foreign_key": forge_rs256_jwt(claims, foreign_key, kid=WORKOS_TEST_KID),
        "tampered_payload": f"{header}.{intruder.split('.')[1]}.{signature}",
        "alg_none": forge_jwt(claims, "", header_alg="none", kid=WORKOS_TEST_KID).rsplit(".", 1)[0]
        + ".",
        "hmac_with_public_key": forge_jwt(claims, public_jwk, kid=WORKOS_TEST_KID),
    }
    sealed = {
        **{
            name: seal_workos_session(token, workos_cookie_password, email=USER_EMAIL)
            for name, token in access_tokens.items()
        },
        "not_sealed_with_our_password": seal_workos_session(
            genuine, Fernet.generate_key().decode(), email=USER_EMAIL
        ),
        "unknown_user": seal_workos_session(
            genuine, workos_cookie_password, email="stranger@gaia.test"
        ),
    }

    response = await _probe(hosted_app, sealed[kind])

    assert response.status_code == 401, response.text
