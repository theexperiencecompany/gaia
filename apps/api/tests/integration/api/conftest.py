"""API integration test fixtures.

Provides an httpx AsyncClient wired to the FastAPI app via ASGITransport,
with authentication mocked out, rate limiter disabled, and lifespan skipped.
"""

from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import ClassVar
from unittest.mock import patch

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import pytest
from workos import AsyncWorkOSClient

from app.api.v1.middleware.auth import WorkOSAuthMiddleware
from app.config.settings import settings
from app.models.user_models import AuthenticatedUser
from tests.conftest import FAKE_USER
from tests.factories import make_authenticated_user
from tests.helpers import (
    WORKOS_TEST_CLIENT_ID,
    WORKOS_TEST_KID,
    MockAuthMiddleware,
    NoAuthMiddleware,
    rsa_public_jwk,
)


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    """No-op lifespan that skips real service initialization."""
    yield


def _test_configure_middleware(app: FastAPI) -> None:
    """Minimal middleware stack for testing: CORS only, no Redis/WorkOS."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _create_test_app() -> FastAPI:
    """Create a FastAPI app with mocked lifespan and minimal middleware."""
    with (
        patch("app.core.app_factory.lifespan", _noop_lifespan),
        patch("app.core.app_factory.configure_middleware", _test_configure_middleware),
    ):
        from app.core.app_factory import create_app

        app = create_app()
    return app


@pytest.fixture
def real_auth_app() -> Callable[[AsyncWorkOSClient | None], FastAPI]:
    """Build the app behind the real WorkOSAuthMiddleware, given the WorkOS client it should use."""

    def build(workos_client: AsyncWorkOSClient | None) -> FastAPI:
        app = _create_test_app()
        app.add_middleware(WorkOSAuthMiddleware, workos_client=workos_client)
        return app

    return build


class _WorkOSStub(BaseHTTPRequestHandler):
    """Serve the JWKS the WorkOS SDK fetches, and refuse every refresh as WorkOS does for a bad session."""

    jwks: ClassVar[dict[str, object]] = {}

    def do_GET(self) -> None:
        found = self.path == f"/sso/jwks/{WORKOS_TEST_CLIENT_ID}"
        self._reply(200 if found else 404, self.jwks)

    def do_POST(self) -> None:
        self._reply(401, {"error": "invalid_grant", "error_description": "Session has ended."})

    def _reply(self, status: int, body: dict[str, object]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture(scope="session")
def workos_signing_key() -> rsa.RSAPrivateKey:
    """Generate the key the stub WorkOS signs access tokens with."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def workos_stub_url(workos_signing_key: rsa.RSAPrivateKey) -> Iterator[str]:
    """Run a local stand-in for api.workos.com that publishes workos_signing_key."""
    _WorkOSStub.jwks = {"keys": [rsa_public_jwk(workos_signing_key, kid=WORKOS_TEST_KID)]}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _WorkOSStub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()


@pytest.fixture
def workos_cookie_password(monkeypatch: pytest.MonkeyPatch) -> str:
    """Put the instance in WorkOS auth mode with a fresh cookie-sealing password."""
    password = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "WORKOS_COOKIE_PASSWORD", password)
    monkeypatch.setattr(settings, "AUTH_MODE", "workos")
    return password


@pytest.fixture
def workos_client(workos_stub_url: str, workos_cookie_password: str) -> AsyncWorkOSClient:
    """Build a real WorkOS SDK client pointed at the stub."""
    return AsyncWorkOSClient(
        api_key="sk_test_workos", client_id=WORKOS_TEST_CLIENT_ID, base_url=workos_stub_url
    )


@pytest.fixture
def test_user() -> AuthenticatedUser:
    return make_authenticated_user(user_id=FAKE_USER.user_id, email="test@test.com")


@pytest.fixture
async def test_client(test_user):
    """Provide an httpx AsyncClient against the FastAPI app with auth mocked."""
    app = _create_test_app()
    app.add_middleware(MockAuthMiddleware, user=test_user)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",  # NOSONAR
    ) as client:
        yield client


@pytest.fixture
async def gated_test_client(test_user):
    """Build test_client with the real EntitlementMiddleware for routes whose 402 is the middleware's."""
    from app.api.v1.middleware.entitlement import EntitlementMiddleware

    app = _create_test_app()
    app.add_middleware(EntitlementMiddleware)
    # Added last so it runs first: the gate reads the user this one writes.
    app.add_middleware(MockAuthMiddleware, user=test_user)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",  # NOSONAR
    ) as client:
        yield client


@pytest.fixture
async def unauthenticated_client():
    """Provide an httpx AsyncClient without auth for testing 401 responses."""
    app = _create_test_app()
    app.add_middleware(NoAuthMiddleware)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",  # NOSONAR
    ) as client:
        yield client
