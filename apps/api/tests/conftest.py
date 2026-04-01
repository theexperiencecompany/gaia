"""
Root test fixtures for the GAIA API test suite.

Provides:
- Environment setup that prevents connections to external services
- A FastAPI test app with mocked lifespan (no real DB/Redis connections)
- Authenticated test client with dependency overrides
- Reusable fake user and auth fixtures
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Environment setup — runs at import time, before any app module is loaded.
# ---------------------------------------------------------------------------

os.environ["ENV"] = "development"
os.environ.setdefault(
    "MONGO_DB",
    "mongodb://localhost:27017/gaia_test?serverSelectionTimeoutMS=100&connectTimeoutMS=100",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("WORKOS_API_KEY", "sk_test_fake")
os.environ.setdefault("WORKOS_CLIENT_ID", "client_fake")
os.environ.setdefault("WORKOS_COOKIE_PASSWORD", "a" * 32)
os.environ.setdefault(
    "MCP_ENCRYPTION_KEY",
    "dGVzdF9lbmNyeXB0aW9uX2tleV8zMl9ieXRlcw==",  # pragma: allowlist secret
)

# ---------------------------------------------------------------------------
# Infrastructure mock strategy
#
# USE_REAL_SERVICES=1 is set by the Dagger service container (see
# .dagger/src/gaia_ci/main.py _service_test_container). When set, real
# Postgres/Redis/MongoDB/ChromaDB are available and we skip the global
# _get_mongodb_instance mock so integration, e2e, and service tests reach
# the actual database.
#
# Unit tests that need isolated DB behaviour use the mock_mongodb fixture
# (tests/unit/conftest.py), which patches _get_collection at a higher level
# and is unaffected by this decision.
#
# Without USE_REAL_SERVICES (local pytest run without Docker), we keep the
# MagicMock to prevent hangs on connection attempts.
# ---------------------------------------------------------------------------

_USE_REAL_SERVICES = os.environ.get("USE_REAL_SERVICES", "1") == "1"

_mock_subscription = MagicMock()
_mock_subscription.plan_type = "free"

# Always mock: Infisical secrets and rate limiting. These are external SaaS
# services that must never be called in any test environment.
_always_patches = [
    patch("app.config.secrets.inject_infisical_secrets", return_value=None),
    patch("shared.py.secrets.inject_infisical_secrets", return_value=None),
    patch(
        "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
        new_callable=AsyncMock,
        return_value=_mock_subscription,
    ),
    patch(
        "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
        new_callable=AsyncMock,
        return_value={},
    ),
]

# Only mock MongoDB when real services are NOT available. When
# USE_REAL_SERVICES=1 the Dagger container has real MongoDB running and
# integration/e2e/service tests should reach it.
_infra_patches = (
    []
    if _USE_REAL_SERVICES
    else [
        patch(
            "app.db.mongodb.collections._get_mongodb_instance",
            return_value=MagicMock(),
        ),
    ]
)

_patches = [*_always_patches, *_infra_patches]
for p in _patches:
    p.start()

# ---------------------------------------------------------------------------
# Fake user data
# ---------------------------------------------------------------------------

FAKE_USER: dict = {
    "user_id": "507f1f77bcf86cd799439011",
    "email": "test@example.com",
    "name": "Test User",
    "picture": None,
    "auth_provider": "workos",
    "timezone": "UTC",
}

FAKE_USER_2: dict = {
    "user_id": "507f1f77bcf86cd799439022",
    "email": "other@example.com",
    "name": "Other User",
    "picture": None,
    "auth_provider": "workos",
    "timezone": "America/New_York",
}


# ---------------------------------------------------------------------------
# App factory for tests
# ---------------------------------------------------------------------------


def _create_test_app() -> FastAPI:
    """Create a FastAPI app with a no-op lifespan and minimal middleware for testing."""
    from fastapi.middleware.cors import CORSMiddleware

    @asynccontextmanager
    async def _noop_lifespan(app: FastAPI):
        yield

    def _test_configure_middleware(app: FastAPI) -> None:
        """Strip Redis/WorkOS middleware — use CORS only so tests don't need Redis."""
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    with (
        patch("app.core.app_factory.lifespan", _noop_lifespan),
        patch("app.core.app_factory.configure_middleware", _test_configure_middleware),
        patch(
            "app.services.payments.payment_service.payment_service.get_user_subscription_status",
            new_callable=AsyncMock,
            return_value=_mock_subscription,
        ),
        patch(
            "app.api.v1.middleware.tiered_rate_limiter.tiered_limiter.check_and_increment",
            new_callable=AsyncMock,
        ),
    ):
        from app.config.settings import get_settings

        get_settings.cache_clear()

        from app.core.app_factory import create_app

        app = create_app()

    # Disable the SlowAPI per-route limiter so payment endpoints don't hit Redis.
    # This must be done after the app is created (the module is imported then).
    from app.api.v1.middleware.rate_limiter import limiter

    limiter.enabled = False

    from app.api.v1.dependencies.oauth_dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER

    return app


# ---------------------------------------------------------------------------
# pytest hooks
# ---------------------------------------------------------------------------


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (fast, no external deps)")
    config.addinivalue_line(
        "markers",
        "integration: Integration tests (compiled graphs, mocked services)",
    )
    config.addinivalue_line(
        "markers",
        "service: Service integration tests (require real Postgres/Redis/MongoDB)",
    )
    config.addinivalue_line(
        "markers", "e2e: End-to-end tests (real or near-real services)"
    )
    config.addinivalue_line(
        "markers", "composio: Composio integration tests (require credentials)"
    )
    config.addinivalue_line("markers", "slow: Slow tests")


def pytest_addoption(parser):
    """Add custom CLI options for test configuration."""
    parser.addoption(
        "--user-id",
        action="store",
        default=None,
        help="User ID for integration tests",
    )
    parser.addoption(
        "--skip-destructive",
        action="store_true",
        default=False,
        help="Skip destructive tests",
    )
    parser.addoption(
        "--yes",
        action="store_true",
        default=False,
        help="Auto-confirm interactive prompts",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def test_app() -> FastAPI:
    """Session-scoped test app (created once, reused across all tests)."""
    return _create_test_app()


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client bound to the test app."""
    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",  # NOSONAR
    ) as ac:
        yield ac


@pytest.fixture
async def unauthed_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Client without auth — requests will get 401."""
    from app.api.v1.dependencies.oauth_dependencies import get_current_user

    original = test_app.dependency_overrides.pop(get_current_user, None)
    try:
        transport = ASGITransport(app=test_app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",  # NOSONAR
        ) as ac:
            yield ac
    finally:
        if original is not None:
            test_app.dependency_overrides[get_current_user] = original


@pytest.fixture
def fake_user() -> dict:
    return FAKE_USER.copy()


@pytest.fixture
def fake_user_2() -> dict:
    return FAKE_USER_2.copy()


@pytest.fixture
def mock_mongodb():
    return AsyncMock()


@pytest.fixture(scope="session")
def user_id(request):
    """Get test user ID from CLI or environment."""
    return request.config.getoption("--user-id") or os.environ.get("EVAL_USER_ID")


@pytest.fixture(scope="session")
def skip_destructive(request):
    """Whether to skip destructive tests."""
    return request.config.getoption("--skip-destructive")
