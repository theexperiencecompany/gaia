"""
Root test fixtures for the GAIA API test suite.

Provides:
- Environment setup that prevents connections to external services
- A FastAPI test app with mocked lifespan (no real DB/Redis connections)
- Authenticated test client with dependency overrides
- Reusable fake user and auth fixtures
"""

from collections.abc import AsyncGenerator, Callable, Iterator
import contextlib
from contextlib import asynccontextmanager
import importlib
import os
import re
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from hypothesis import HealthCheck, settings as _hypothesis_settings
import pytest

# Hypothesis profiles: PR lanes select "ci" (25 examples) to keep feedback
# short; master/local keep "default" (200). suppress differing_executors
# since mutmut's in-process runner reinstantiates the @given class per mutant.
_hypothesis_settings.register_profile(
    "ci",
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.differing_executors],
)
_hypothesis_settings.register_profile(
    "default",
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.differing_executors],
)
_hypothesis_settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "default"))

# ---------------------------------------------------------------------------
# Environment setup — runs at import time, before any app module is loaded.
# ---------------------------------------------------------------------------

# Env fence + Infisical patch, shared with scripts/export_openapi.py. Imported
# here (not at the top) because it must run before any app module loads.
import tests.offline_env  # isort: skip  # noqa: F401 -- imported for its side effects

# Imported after the env setup above: document models extend MongoDocument,
# pulling in app.config.settings which instantiates settings at import
# time; without ENV set first that resolves to ProductionSettings and fails.
from app.config.posthog import init_posthog
from app.core.lazy_loader import MissingKeyStrategy, providers
from app.models.payment_models import (
    PlanType,
    SubscriptionStatus,
    UserSubscriptionStatus,
)

# Hermetic by default (USE_REAL_SERVICES=0): a bare local run stays offline
# via the global _get_mongodb_instance mock. CI sets USE_REAL_SERVICES=1 so
# integration/service/e2e tests reach the real Postgres/Redis/MongoDB/ChromaDB.

_USE_REAL_SERVICES = os.environ.get("USE_REAL_SERVICES", "0") == "1"

_mock_subscription = MagicMock()
# Mirror the real get_user_subscription_status return type: plan_type is a
# PlanType enum, not a raw str. get_cached_plan_type relies on `.value`.
_mock_subscription.plan_type = PlanType.FREE

# Always mock: Infisical secrets and rate limiting. These are external SaaS
# services that must never be called in any test environment.
_always_patches = [
    patch("app.config.secrets.inject_infisical_secrets", return_value=None),
    # settings.py binds the real function into its own namespace at import,
    # before this conftest's patches start, so the source-module patch above
    # is inert for _ensure_infisical_loaded; patch the settings binding too.
    patch("app.config.settings.inject_infisical_secrets", return_value=None),
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

# Fail loud if the Infisical fence is ever re-pointed at the real vault.
# importlib (not a top-level import) keeps E402 clean after the patch loop.
_secrets_module = importlib.import_module("app.config.secrets")
_settings_module = importlib.import_module("app.config.settings")

assert isinstance(_settings_module.inject_infisical_secrets, MagicMock), (
    "hermetic fence broken: settings.inject_infisical_secrets is not mocked"
)
assert isinstance(_secrets_module.inject_infisical_secrets, MagicMock), (
    "hermetic fence broken: secrets.inject_infisical_secrets is not mocked"
)

# Registers the PostHog provider the way production startup does, since the
# test app's lifespan is a no-op; POSTHOG_PROJECT_TOKEN is blanked above so
# the SILENT-strategy loader no-ops capture calls instead of raising KeyError.
_posthog_module = importlib.import_module("app.config.posthog")
_posthog_module.init_posthog()

# ---------------------------------------------------------------------------
# Hermetic environment fence
# ---------------------------------------------------------------------------

# Any env var whose name matches these fragments could carry a real credential
# from a developer's .env or shell. Blank them all at session start so lazy
# providers, direct os.environ reads, and subprocesses never see a live key.
_CREDENTIAL_ENV_RE = re.compile(r"(API_KEY|TOKEN|SECRET|_KEY|_SECRET)")

# Keys the harness provisions with fake values at import time: test
# fixtures, not developer secrets, backing code paths the suite exercises.
# Blanking them would break the suite, not make it safer.
_HERMETIC_ALLOWLIST = frozenset({"WORKOS_API_KEY", "MCP_ENCRYPTION_KEY", "AGENT_SECRET"})

# Live-credential tiers declare the keys their tests need via
# HERMETIC_ALLOW_KEYS (comma-separated) in their own conftest, before the
# session fence runs; nothing survives the fence by accident, only by declaration.
_HERMETIC_ALLOW_ENV = "HERMETIC_ALLOW_KEYS"


def _hermetic_allowed_keys() -> frozenset[str]:
    declared = {
        key.strip() for key in os.environ.get(_HERMETIC_ALLOW_ENV, "").split(",") if key.strip()
    }
    return _HERMETIC_ALLOWLIST | declared


# Keys that must be PRESENT (non-empty) but never real: three unit modules
# construct (but never invoke) real ChatGoogleGenerativeAI clients whose
# pydantic validation reads GOOGLE_API_KEY directly, so a fake satisfies it.
_HERMETIC_FAKE_KEYS = {
    "GOOGLE_API_KEY": "sk-hermetic-test-key-not-real",  # pragma: allowlist secret
}


@pytest.fixture(scope="session", autouse=True)
def _hermetic_environment() -> Iterator[None]:
    """Fence every test run from real-credential env vars.

    Blanked keys are set to "" rather than popped: settings.py calls
    load_dotenv(override=False) at import, which re-injects .env values for
    keys absent from os.environ — an empty present key blocks that, so a
    get_settings.cache_clear() reload (see _create_test_app) sees no secrets.
    """
    snapshot = os.environ.copy()
    allowed = _hermetic_allowed_keys()
    try:
        for key in list(os.environ):
            if _CREDENTIAL_ENV_RE.search(key) and key not in allowed:
                os.environ[key] = ""
        # After the blanking pass: fake keys must survive it (they match the
        # regex), and must be deterministic regardless of the developer's .env.
        for key, fake in _HERMETIC_FAKE_KEYS.items():
            os.environ[key] = fake
        os.environ["TZ"] = "UTC"
        os.environ["LANG"] = "C.UTF-8"
        os.environ["LC_ALL"] = "C.UTF-8"
        os.environ["PYTHONHASHSEED"] = "0"
        # worker/lifecycle/startup.py setdefaults GAIA_SERVICE_NAME=arq_worker
        # at import; pinning it here keeps a test importing that chain (e.g.
        # test_worker_smoke) from leaking the var and tripping the pollution guard.
        os.environ.setdefault("GAIA_SERVICE_NAME", "")
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)


@pytest.fixture(scope="session", autouse=True)
def _env_pollution_guard(_hermetic_environment: Iterator[None]) -> Iterator[None]:
    """Fail if any test leaked os.environ mutations.

    Depends on the fence fixture so it tears down BEFORE the fence restores
    the original environment (which would otherwise mask leaks silently).
    """
    baseline = os.environ.copy()
    yield
    leaked = {
        key: (baseline.get(key), os.environ.get(key))
        for key in set(os.environ) | set(baseline)
        if key.startswith(("PYTEST_", "KMP_")) is False and baseline.get(key) != os.environ.get(key)
    }
    # KMP_*: set by the OpenMP runtime (onnxruntime/fastembed) on first import,
    # not by a test. Only visible when embeddings run in-process (no sidecar,
    # i.e. GitHub-hosted lanes).
    assert not leaked, f"tests leaked environment changes: {leaked}"


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

# Real UserSubscriptionStatus shape for a paying subscriber. The root
# conftest's global patch pins get_user_subscription_status to a FREE plan,
# so PRO-tier tests opt in by patching it with this object.
PRO_USER_SUBSCRIPTION: UserSubscriptionStatus = UserSubscriptionStatus(
    user_id="507f1f77bcf86cd799439033",
    current_plan=None,
    subscription=None,
    is_subscribed=True,
    days_remaining=None,
    can_upgrade=True,
    can_downgrade=True,
    has_subscription=True,
    plan_type=PlanType.PRO,
    status=SubscriptionStatus.ACTIVE,
)

PRO_USER: dict = {
    "user_id": "507f1f77bcf86cd799439033",
    "email": "pro@example.com",
    "name": "Pro User",
    "picture": None,
    "auth_provider": "workos",
    "timezone": "UTC",
    "subscription": PRO_USER_SUBSCRIPTION,
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

    # Import app_factory explicitly before patching it: mock.patch resolves
    # it via getattr on app.core, which needs the submodule already imported
    # or mutmut's isolation hits an AttributeError on the patch target.
    __import__("app.core.app_factory", fromlist=["lifespan"])

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
async def gated_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Client with the real EntitlementMiddleware in front of the app.

    The test app strips every middleware, so a route's 402 contract cannot
    be proved through client. This stacks the gate around the same app as
    production does, so a test asserts what a FREE caller really gets.
    """
    from starlette.middleware.base import BaseHTTPMiddleware

    from app.api.v1.middleware.entitlement import EntitlementMiddleware

    class _AuthedState(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user = FAKE_USER
            return await call_next(request)

    gated = _AuthedState(app=EntitlementMiddleware(app=test_app))
    transport = ASGITransport(app=gated, raise_app_exceptions=False)
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
def pro_user() -> dict:
    """Return an authenticated user dict for a paying PRO user.

    FAKE_USER-shaped, plus a subscription key holding the real
    UserSubscriptionStatus for a PRO plan. The global
    get_user_subscription_status patch always reports FREE, so PRO-tier
    tests patch that seam with pro_user["subscription"].
    """
    return PRO_USER.copy()


@pytest.fixture
def pro_plan() -> Iterator[MagicMock]:
    """Make the paid-only gate see a PRO caller for the duration of a test.

    Patches the single seam every gate reads — get_cached_plan_type — so it
    covers EntitlementMiddleware, require_active_subscription and is_paid at
    once. Deliberately NOT autouse: a dozen tests assert the 402 that falls
    out of the suite's default FREE caller.
    """
    from app.models.payment_models import PlanType

    with patch(
        "app.services.payments.payment_service.payment_service.get_cached_plan_type",
        new_callable=AsyncMock,
        return_value=PlanType.PRO,
    ) as mocked:
        yield mocked


@pytest.fixture
def free_plan() -> Iterator[MagicMock]:
    """Pin the paid-only gate to a FREE caller — the explicit form of the default.

    Use this rather than relying on the ambient default whenever a test is
    *about* the paywall: it survives someone changing what the unpatched lookup
    resolves to, and it never touches Redis.
    """
    from app.models.payment_models import PlanType

    with patch(
        "app.services.payments.payment_service.payment_service.get_cached_plan_type",
        new_callable=AsyncMock,
        return_value=PlanType.FREE,
    ) as mocked:
        yield mocked


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

    Composio no longer returns access_token in connected-account credentials.
    The patched CustomTool.__call__ injects only user_id. Tests that exercise
    custom tools should use this fixture instead of hand-rolling a bearer token.
    """
    return {"user_id": "test_user_123"}


# No shared `mock_proxy_request_sync` fixture: consumers import
# proxy_request_sync by name, binding it at the call-site module, so
# patching the source module would not intercept it. Patch the call site directly.


# enqueue_worker_job is imported by name into each call site, so patching
# the source module would not intercept it. Keep in sync with
# `grep -rl "from app.workers.queue import"`.
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
    """Route the wide-event enqueue wrapper through pool.enqueue_job.

    Services enqueue ARQ jobs through enqueue_worker_job, which wraps
    pool.enqueue_job; a test that mocks the pool directly never sees the
    call otherwise. Patches the wrapper at every call site with a
    forwarding side effect so pool.enqueue_job mocks stay authoritative.
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


@pytest.fixture
def posthog_provider() -> Iterator[Callable[..., None]]:
    """Install a controllable "posthog" provider under the real registry.

    The env fence blanks POSTHOG_PROJECT_TOKEN, so the production provider
    is unavailable for the suite. Uses the real registry, not a patch,
    since the provider NAME is part of what tests pin; re-registered on teardown.
    """

    def install(*, available: bool, client: object | None) -> None:
        providers.register(
            name="posthog",
            loader_func=lambda: client,
            required_keys=[] if available else [""],
            strategy=MissingKeyStrategy.SILENT,
        )

    yield install
    init_posthog()


@pytest.fixture(autouse=True)
def _reset_limit_origin() -> Iterator[None]:
    """Keep a run's limit origin from leaking between tests.

    arq gives each job its own task, so a job cannot leak into the next one.
    Tests share one, so a case that marks a background run would otherwise make
    later cases mail the wrong email.
    """
    yield
    # Imported here, not at module level: the import chain eagerly pulls in
    # transformers (~0.85s), a cost collection and no-test workers should
    # not pay.
    from app.services.limit_upsell import LimitHitOrigin, mark_run_origin

    mark_run_origin(LimitHitOrigin.INTERACTIVE)


@pytest.fixture(autouse=True)
def _isolate_wide_event_state() -> Iterator[None]:
    """Keep one test's wide-event boundary from leaking into the next.

    log.reset() seeds the runner ContextVar with a shared, MUTABLE
    _EventState; a later async test's log.set(...) mutates the same object,
    which once made a workflow execution id leak into a test that opened no
    boundary at all. Reset after every test so no shared object survives.
    """
    from shared.py import wide_events

    yield
    wide_events._event_state.set(None)
    wide_events._trace_id.set("")
