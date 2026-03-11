"""API integration test fixtures.

Provides an httpx AsyncClient wired to the FastAPI app via ASGITransport,
with authentication mocked out, rate limiter disabled, and lifespan skipped.
"""

from contextlib import asynccontextmanager
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from tests.factories import make_user


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


class _MockAuthMiddleware(BaseHTTPMiddleware):
    """Injects a test user into request.state for auth bypass."""

    def __init__(self, app, user: dict):
        super().__init__(app)
        self._user = user

    async def dispatch(self, request: Request, call_next):
        request.state.authenticated = True
        request.state.user = self._user
        return await call_next(request)


class _NoAuthMiddleware(BaseHTTPMiddleware):
    """Sets request.state to unauthenticated."""

    async def dispatch(self, request: Request, call_next):
        request.state.authenticated = False
        request.state.user = None
        return await call_next(request)


@pytest.fixture
def test_user() -> dict:
    return make_user(user_id="integration-test-user-1", email="test@test.com")


@pytest.fixture
async def test_client(test_user):
    """Provide an httpx AsyncClient against the FastAPI app with auth mocked."""
    app = _create_test_app()
    app.add_middleware(_MockAuthMiddleware, user=test_user)

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
    app.add_middleware(_NoAuthMiddleware)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",  # NOSONAR
    ) as client:
        yield client
