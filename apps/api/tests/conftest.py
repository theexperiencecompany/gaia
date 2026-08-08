"""
Root test fixtures for the GAIA API test suite.

Provides:
- Environment setup that prevents connections to external services
- A FastAPI test app with mocked lifespan (no real DB/Redis connections)
- Authenticated test client with dependency overrides
- Reusable fake user and auth fixtures
"""

from collections.abc import AsyncGenerator
import contextlib
from contextlib import asynccontextmanager
import os
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

# ---------------------------------------------------------------------------
# Environment setup — runs at import time, before any app module is loaded.
# ---------------------------------------------------------------------------

os.environ["ENV"] = "development"
# Force the dev auth bypass OFF for the suite: a machine set up for agent-driven
# e2e has DEV_AUTH_BYPASS_EMAIL in apps/api/.env, which would short-circuit
# WorkOSAuthMiddleware — including in the tests that exercise that middleware.
# Force an empty (falsy) value rather than popping: an empty value keeps the
# prod-guard off, and because the key is now present, load_dotenv(override=False)
# — called at settings import — will not re-inject a value from the developer's .env.
os.environ["DEV_AUTH_BYPASS_EMAIL"] = ""
os.environ.setdefault(
    "MONGO_DB",
    "mongodb://localhost:27017/gaia_test?serverSelectionTimeoutMS=100&connectTimeoutMS=100",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("WORKOS_API_KEY", "sk_test_fake")
os.environ.setdefault("WORKOS_CLIENT_ID", "client_fake")
os.environ.setdefault("WORKOS_COOKIE_PASSWORD", "a" * 32)
os.environ.setdefault("RESEND_API_KEY", "re_test_fake")
os.environ.setdefault("RESEND_AUDIENCE_ID", "aud_fake")
os.environ.setdefault("EMAIL_UNSUBSCRIBE_SECRET", "test-unsubscribe-secret-" + "x" * 16)
os.environ.setdefault(
    "MCP_ENCRYPTION_KEY",
    "dGVzdF9lbmNyeXB0aW9uX2tleV8zMl9ieXRlcw==",  # pragma: allowlist secret
)
os.environ.setdefault("AGENT_SECRET", "test-agent-secret-" + "x" * 32)  # pragma: allowlist secret

# LangChain ships every graph run to LangSmith when these are truthy, and a
# developer's .env turns them on. That makes the suite depend on an external
# service it never asserts against: runs get rate-limited (429s), the exporter
# retries on shutdown, and each agent test pays the latency. Forced off rather
# than setdefault — the point is to override the .env, not defer to it.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

# Same reasoning for Langfuse, which activates only when all three of these are
# set (app/config/langfuse.py) — so blanking one disables it. A developer's .env
# supplies them, and the exporter then blocks on shutdown retrying spans against
# a host the suite has no business contacting.
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
os.environ["LANGFUSE_HOST"] = ""

# Imported AFTER the env setup above, not with the top-level imports: document
# models now extend MongoDocument, so importing any of them pulls in
# app.db.repositories.base -> app.db.redis -> app.config.settings, which
# instantiates settings at import time. Without ENV set first, that resolves to
# ProductionSettings and fails validation (CI has no production keys).
from app.models.payment_models import PlanType  # noqa: E402

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
# Mirror the real get_user_subscription_status return type: plan_type is a
# PlanType enum, not a raw str. get_cached_plan_type relies on `.value`.
_mock_subscription.plan_type = PlanType.FREE

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
    config.addinivalue_line("markers", "e2e: End-to-end tests (real or near-real services)")
    config.addinivalue_line("markers", "composio: Composio integration tests (require credentials)")
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


@pytest.fixture
def fake_auth_credentials() -> dict:
    """Auth credentials shape that matches the post-migration contract.

    Composio no longer returns `access_token` in connected-account credentials.
    The patched `CustomTool.__call__` injects only `user_id`. Tests that exercise
    custom tools should use this fixture instead of hand-rolling a bearer token.
    """
    return {"user_id": "test_user_123"}


# Note: There is intentionally no shared `mock_proxy_request_sync` fixture.
# Every consumer does `from app.services.composio.proxy_client import
# proxy_request_sync`, which binds the symbol at the call-site module's
# namespace. A fixture that patches `app.services.composio.proxy_client.
# proxy_request_sync` would NOT intercept those bindings — the tests would
# pass without exercising the mock. Tests must patch the call site directly
# (e.g. `app.services.calendar_service.proxy_request_sync`,
# `app.utils.twitter_utils.proxy_request_sync`).


# The enqueue wrapper is imported into each service module at its call site
# (`from app.workers.queue import enqueue_worker_job`), so patching the source
# module would NOT intercept the already-bound names. Patch every known call
# site. Keep this list in sync with `grep -rl "from app.workers.queue import"`.
_ENQUEUE_CALL_SITES = (
    "app.workers.tasks.tracked_todo_tasks",
    "app.services.workflow.queue_service",
    "app.services.oauth.oauth_service",
    "app.services.tracked_todo_service",
    "app.services.scheduler_service",
    "app.services.onboarding.intelligence_job",
    "app.workers.tasks.memory_backfill_tasks",
)


@pytest.fixture
def route_enqueue_via_pool():
    """Route the wide-event enqueue wrapper through ``pool.enqueue_job``.

    Services enqueue ARQ jobs through ``enqueue_worker_job`` (the wide-event
    wrapper in ``app.workers.queue``), which forwards to the pool's
    ``enqueue_job`` with the same args. Tests that mock the pool directly
    (``pool.enqueue_job = AsyncMock(...)``) therefore never see the call
    unless the wrapper is routed through the pool. Requesting this fixture
    patches the wrapper at every call site with a forwarding side effect so
    the tests' existing ``pool.enqueue_job`` mocks and assertions stay
    authoritative.
    """
    with contextlib.ExitStack() as stack:

        async def _forward(pool, *args, **kwargs):
            return await pool.enqueue_job(*args, **kwargs)

        for module in _ENQUEUE_CALL_SITES:
            # create=True: the module may not be imported in every test context;
            # the attribute is patched when the module first loads.
            stack.enter_context(
                patch(f"{module}.enqueue_worker_job", side_effect=_forward, create=True)
            )
        yield
