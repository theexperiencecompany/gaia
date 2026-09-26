"""
Root test fixtures for the GAIA API test suite.

Provides:
- Environment setup that prevents connections to external services
- A FastAPI test app with mocked lifespan (no real DB/Redis connections)
- Authenticated test client with dependency overrides
- Reusable fake user and auth fixtures
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Iterator
import contextlib
from contextlib import asynccontextmanager
import importlib
import os
import re
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
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
from app.config.settings import settings as app_settings
from app.core.lazy_loader import MissingKeyStrategy, providers
from app.db.redis import redis_cache
from app.models.payment_models import (
    PlanType,
    SubscriptionStatus,
    UserSubscriptionStatus,
)
from app.models.user_models import AuthenticatedUser

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
]

# Started by the _rate_limiting_fence fixture, NOT the import-time loop below:
# patch() resolves its target only when start() runs, and rate_limiting drags in
# workos, langgraph and the payment services — ~3 s a collection need not pay.
_rate_limiting_patches = [
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

# ---------------------------------------------------------------------------
# Redis fence — mirror of the MongoDB fence, at the same gate.

# The unit tier is hermetic, but Redis was not fenced: any path reaching
# redis_cache.client opened a real socket, which hangs where the port is
# firewalled. The mutation lane runs each module's test files in ISOLATION.

# The seam is redis.asyncio.from_url, NOT the app's _new_client wrapper around
# it: patching the wrapper leaves RedisCache's construction unrun and defeats
# the three unit/db tests that patch from_url themselves.

# Not fakeredis, though it is a dev dependency. A module-level FakeServer binds
# its asyncio primitives to one event loop, so per-test loops fail and real
# SET-NX semantics reroute control flow — 121 failures measured.

# Benign defaults keep hermetic tests correct: reads report nothing there,
# writes report success, pipeline() is an async CM. Tests needing specific
# behaviour opt in via mock_redis or patch.object, which rebind and win.

_REDIS_COMMAND_RESULTS: dict[str, object] = {
    "ping": True,
    "get": None,
    "set": True,
    "setex": True,
    "getdel": None,
    "delete": 0,
    "exists": 0,
    "expire": True,
    "ttl": -2,
    "keys": [],
    "incr": 1,
    "llen": 0,
    "lpop": None,
    "lrange": [],
    "ltrim": True,
    "rpush": 1,
    "hset": 1,
    "hgetall": {},
    "publish": 0,
    "xadd": "0-0",
    "xread": [],
    "eval": None,
}


class _FenceRedisPipeline:
    """Async-CM pipeline: each buffered command yields its benign default on execute()."""

    def __init__(self) -> None:
        self._queued: list[str] = []

    async def __aenter__(self) -> "_FenceRedisPipeline":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __getattr__(self, name: str) -> Callable[..., "_FenceRedisPipeline"]:
        def _buffer(*_args: object, **_kwargs: object) -> _FenceRedisPipeline:
            self._queued.append(name)
            return self

        return _buffer

    async def execute(self) -> list[object]:
        await asyncio.sleep(0)
        results = [_REDIS_COMMAND_RESULTS.get(name) for name in self._queued]
        self._queued.clear()
        return results

    async def reset(self) -> None:
        self._queued.clear()


class _FenceRedisPubSub:
    """No-op async pub/sub — never yields a message, never opens a socket."""

    async def __aenter__(self) -> "_FenceRedisPubSub":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_message(
        self, *_args: object, timeout: float | None = None, **_kwargs: object
    ) -> None:
        # Honor the poll timeout as real pubsub does: sleep, then report no
        # message. A tight return-None loop never suspends, so a while-True
        # consumer could never be cancelled — cancel() needs a suspension point.
        await asyncio.sleep(timeout if isinstance(timeout, (int, float)) and timeout > 0 else 0)

    def __getattr__(self, name: str) -> Callable[..., Awaitable[None]]:
        async def _noop(*_args: object, **_kwargs: object) -> None:
            await asyncio.sleep(0)

        return _noop


class _FenceRedisLock:
    """No-op async lock — acquisition always succeeds, release is a no-op."""

    async def __aenter__(self) -> "_FenceRedisLock":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def acquire(self, *_args: object, **_kwargs: object) -> bool:
        await asyncio.sleep(0)
        return True

    async def release(self, *_args: object, **_kwargs: object) -> None:
        await asyncio.sleep(0)


class _FenceAsyncRedis:
    """In-process stand-in for redis.asyncio.Redis (see the fence comment above).

    Awaited commands return benign defaults and never open a socket; pipeline(),
    pubsub() and lock() hand back their own no-op async helpers.
    """

    def pipeline(self, transaction: bool = True) -> _FenceRedisPipeline:
        return _FenceRedisPipeline()

    def pubsub(self, **_kwargs: object) -> _FenceRedisPubSub:
        return _FenceRedisPubSub()

    def lock(self, *_args: object, **_kwargs: object) -> _FenceRedisLock:
        return _FenceRedisLock()

    async def aclose(self) -> None:
        return None

    def __getattr__(self, name: str) -> Callable[..., Awaitable[object]]:
        result = _REDIS_COMMAND_RESULTS.get(name)

        async def _command(*_args: object, **_kwargs: object) -> object:
            # Yield to the loop before returning, as a real awaited command
            # always suspends, so a while-True polling loop stays cancellable
            # instead of spinning with no suspension point for cancel().
            await asyncio.sleep(0)
            return result

        return _command


_fence_redis_client = _FenceAsyncRedis()

# Only mock MongoDB/Redis when real services are NOT available. When
# USE_REAL_SERVICES=1 the Dagger container has real MongoDB/Redis running and
# integration/e2e/service tests should reach them.
_infra_patches = (
    []
    if _USE_REAL_SERVICES
    else [
        patch(
            "app.db.mongodb.collections._get_mongodb_instance",
            return_value=MagicMock(),
        ),
        patch(
            "app.db.redis.redis.from_url",
            return_value=_fence_redis_client,
        ),
    ]
)

_patches = [*_always_patches, *_infra_patches]
for p in _patches:
    p.start()

# RedisCache builds its client eagerly in __init__, and the imports above ran
# that constructor before the patch started. The patch fences future
# construction; re-point the singleton built at import so every path is fenced.
if not _USE_REAL_SERVICES:
    _redis_module = importlib.import_module("app.db.redis")
    _redis_module.redis_cache.redis = _fence_redis_client
    assert _redis_module.redis_cache.client is _fence_redis_client, (
        "hermetic fence broken: redis_cache is not bound to the in-process fake"
    )

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


@pytest.fixture
async def fake_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    """Back the redis_cache singleton with a per-test fakeredis, for real key/TTL semantics."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_cache, "redis", client)
    yield client
    await client.flushall()
    await client.connection_pool.disconnect()


@pytest.fixture(scope="session", autouse=True)
def _rate_limiting_fence() -> Iterator[None]:
    """Mock the tiered limiter and the subscription lookup for the whole session."""
    for p in _rate_limiting_patches:
        p.start()
    try:
        yield
    finally:
        for p in reversed(_rate_limiting_patches):
            p.stop()


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
def _default_rate_limit_off() -> None:
    """Keep the app-wide slowapi limit off for the whole hermetic run.

    The limiter counts against Redis, which this run never starts, so a request
    through the real app would 500 on the first count. A test that exercises the
    middleware builds its own app with a memory-backed Limiter instead.
    """
    from app.api.v1.middleware.rate_limiter import limiter

    limiter.enabled = False


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

FAKE_USER = AuthenticatedUser(
    user_id="507f1f77bcf86cd799439011",
    email="test@example.com",
    name="Test User",
    picture=None,
    auth_provider="workos",
    timezone="UTC",
)

FAKE_USER_2 = AuthenticatedUser(
    user_id="507f1f77bcf86cd799439022",
    email="other@example.com",
    name="Other User",
    picture=None,
    auth_provider="workos",
    timezone="America/New_York",
)

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

PRO_USER = AuthenticatedUser(
    user_id="507f1f77bcf86cd799439033",
    email="pro@example.com",
    name="Pro User",
    picture=None,
    auth_provider="workos",
    timezone="UTC",
)


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
def fake_user() -> AuthenticatedUser:
    return FAKE_USER


@pytest.fixture
def fake_user_2() -> AuthenticatedUser:
    return FAKE_USER_2


@pytest.fixture
def pro_user() -> AuthenticatedUser:
    """Return an authenticated user for a paying PRO user.

    FAKE_USER-shaped; PRO_USER_SUBSCRIPTION is the real UserSubscriptionStatus
    for its PRO plan. The global get_user_subscription_status patch always
    reports FREE, so PRO-tier tests patch that seam with PRO_USER_SUBSCRIPTION.
    """
    return PRO_USER


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
def core_tool_registry() -> Iterator[None]:
    """Serve MCP connects GAIA's real core tool registry, whose names they rename around."""
    from app.agents.tools.core.registry import ToolRegistry

    registry = ToolRegistry()
    registry.setup()
    with patch(
        "app.services.mcp.mcp_client.get_tool_registry",
        new_callable=AsyncMock,
        return_value=registry,
    ):
        yield


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


@pytest.fixture
def hil_barrier_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate on the interrupt barrier: HIL_LEDGER's kill-switch path, not the shipped default."""
    monkeypatch.setattr(app_settings, "ENABLE_HIL_LEDGER", False)


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
