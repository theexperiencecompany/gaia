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

# Hypothesis profiles. Profiled: 20 hypothesis tests were 10.4s of the 10.8s
# of test time in tests/unit/utils — 100 examples each. PR lanes select the
# "ci" profile (HYPOTHESIS_PROFILE=ci) to keep the feedback loop short; the
# default (full) profile runs on master and locally, so nothing is lost.
# The property tests do not set ``max_examples`` themselves (a per-test value
# would silently override the profile); ``deadline=None`` stays per-test.
# differing_executors: hypothesis flags a @given method whose class is
# instantiated anew between calls — exactly what mutmut's in-process runner
# does when it re-runs the suite per mutant (the "clean" run of the registry
# shard failed on test_property_cron_datetime). The explicit per-test
# @settings(max_examples=...) used to mask it; the profiles carry it now.
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

os.environ["ENV"] = "development"
# Force the dev auth bypass OFF for the suite: a machine set up for agent-driven
# e2e has DEV_AUTH_BYPASS_EMAIL in apps/api/.env, which would short-circuit
# WorkOSAuthMiddleware — including in the tests that exercise that middleware.
# Force an empty (falsy) value rather than popping: an empty value keeps the
# prod-guard off, and because the key is now present, load_dotenv(override=False)
# — called at settings import — will not re-inject a value from the developer's .env.
os.environ["DEV_AUTH_BYPASS_EMAIL"] = ""
# Same problem, same fix, for the other dev overrides that change behaviour
# rather than carry a secret — the credential fence below never sees them
# because they are not credential-shaped, and it would run too late anyway:
# get_settings() is lru_cached and already resolved during collection.
# DEV_UNLIMITED_RATE_LIMITS lifts the limits the rate-limiter tests assert (11
# false failures on a machine that sets it); GAIA_SIM_MODE routes every LLM
# call to the local stub. Both are typed `bool`, so the neutral value must be
# parseable — "" is a pydantic bool_parsing error, not an "off".
os.environ["DEV_UNLIMITED_RATE_LIMITS"] = "false"
os.environ["GAIA_SIM_MODE"] = "false"
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

# chromadb phones home on every client start and collection create, and its
# telemetry client is a background thread doing network I/O. Beyond being an
# external call the suite never asserts on, that thread is what makes the
# process fork-hostile: mutmut re-runs a test file inside a fork, and the
# child died on SIGTRAP (exit -5) before writing a byte, so every mutant of
# chroma_store came back "suspicious" and the module could never be graded.
os.environ["ANONYMIZED_TELEMETRY"] = "False"
# darwin getproxies() falls through to the SystemConfiguration framework
# (_scproxy), which is not fork-safe: mutmut forks a child per mutant, and any
# child that builds an httpx client segfaults inside that native call, leaving
# the mutant without a verdict. A non-empty proxy var makes
# getproxies_environment() truthy and short-circuits the native path, and
# NO_PROXY=* is behavior-neutral: httpx returns no proxies for it, which is
# what a hermetic suite gets on Linux anyway.
os.environ["no_proxy"] = "*"
os.environ["NO_PROXY"] = "*"

# HOST leaks into the model's context: fetchers.py renders the public artifact
# URL from it, so the effective prompt — and the recorded context snapshots —
# differ between a dev box with apps/api/.env (localhost) and CI without one
# (the production default). Pinned so the rendered context is the same
# everywhere; the snapshots were recorded against this value.
os.environ["HOST"] = "http://localhost:8000"

# Same reasoning for PostHog: analytics capture must never reach a live
# project from the suite. Forced off (not setdefault) BEFORE the settings
# import below — the provider's required_keys are bound at decoration time
# from the settings singleton, so a developer's .env token must not leak in.
os.environ["POSTHOG_PROJECT_TOKEN"] = ""
os.environ["POSTHOG_HOST"] = ""

# Arm the Infisical fence BEFORE any app import: settings.py calls get_settings()
# at import time (via the module-level `settings` singleton), and the import
# chain below (payment_models -> ... -> app.config.settings) would dial the real
# vault before any later patch could intercept. shared.py.secrets imports
# cleanly, so patching its binding first means every re-export downstream
# (app/config/secrets.py, settings.py:25) binds the mock by construction.
_early_infisical_patch = patch("shared.py.secrets.inject_infisical_secrets", return_value=None)
_early_infisical_patch.start()

# Imported AFTER the env setup above, not with the top-level imports: document
# models now extend MongoDocument, so importing any of them pulls in
# app.db.repositories.base -> app.db.redis -> app.config.settings, which
# instantiates settings at import time. Without ENV set first, that resolves to
# ProductionSettings and fails validation (CI has no production keys).
from app.config.posthog import init_posthog
from app.core.lazy_loader import MissingKeyStrategy, providers
from app.models.payment_models import (
    PlanType,
    SubscriptionStatus,
    UserSubscriptionStatus,
)

# ---------------------------------------------------------------------------
# Infrastructure mock strategy
#
# Hermetic by default: a bare local run (no Docker) must be fully offline, so
# USE_REAL_SERVICES defaults to "0" and the global _get_mongodb_instance mock
# keeps the suite hermetic. CI (the Dagger service container, see
# .dagger/src/gaia_ci/main.py _service_test_container) sets USE_REAL_SERVICES=1
# explicitly, and only then do integration/service/e2e tests reach the real
# Postgres/Redis/MongoDB/ChromaDB.
#
# Unit tests that need isolated DB behaviour use the mock_mongodb fixture
# (tests/unit/conftest.py), which patches _get_collection at a higher level
# and is unaffected by this decision.
# ---------------------------------------------------------------------------

_USE_REAL_SERVICES = os.environ.get("USE_REAL_SERVICES", "0") == "1"

_mock_subscription = MagicMock()
# Mirror the real get_user_subscription_status return type: plan_type is a
# PlanType enum, not a raw str. get_cached_plan_type relies on `.value`.
_mock_subscription.plan_type = PlanType.FREE

# Always mock: Infisical secrets and rate limiting. These are external SaaS
# services that must never be called in any test environment.
_always_patches = [
    patch("app.config.secrets.inject_infisical_secrets", return_value=None),
    # settings.py binds the real function into its own namespace at import
    # (line 25), before this conftest's patches start — so the source-module
    # patch above is inert for the _ensure_infisical_loaded call path. Patch
    # the settings-module binding too, or every run dials the real vault.
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

# Fail loud if the Infisical fence is ever re-pointed at the real vault: a
# future refactor that binds or resolves inject_infisical_secrets at import
# time inside settings.py would silently defeat every patch above. These
# asserts pin the two bindings that matter. importlib (not a top-level
# import) so the E402 rule stays clean: a from-import here
# would also be a module-level import after the patch loop.
_secrets_module = importlib.import_module("app.config.secrets")
_settings_module = importlib.import_module("app.config.settings")

assert isinstance(_settings_module.inject_infisical_secrets, MagicMock), (
    "hermetic fence broken: settings.inject_infisical_secrets is not mocked"
)
assert isinstance(_secrets_module.inject_infisical_secrets, MagicMock), (
    "hermetic fence broken: secrets.inject_infisical_secrets is not mocked"
)

# Register the PostHog provider the way production startup does
# (unified_startup -> provider_registration -> init_posthog). The test app's
# lifespan is a no-op, so without this the provider is never registered and
# every capture_context_event/capture_event call raises KeyError from
# providers.get("posthog") — turning instrumented endpoints into 500s. With
# POSTHOG_PROJECT_TOKEN blanked above, the SILENT-strategy loader resolves to
# None: capture calls no-op (log.debug + return) instead of raising. Tests
# that assert specific capture behavior patch the endpoint's own binding, so
# they are unaffected. importlib (not a top-level import) for the same reason
# as the settings imports above.
_posthog_module = importlib.import_module("app.config.posthog")
_posthog_module.init_posthog()

# ---------------------------------------------------------------------------
# Hermetic environment fence
# ---------------------------------------------------------------------------

# Any env var whose name matches these fragments could carry a real credential
# from a developer's .env or shell. Blank them all at session start so lazy
# providers, direct os.environ reads, and subprocesses never see a live key.
_CREDENTIAL_ENV_RE = re.compile(r"(API_KEY|TOKEN|SECRET|_KEY|_SECRET)")

# Keys the harness itself provisions with fake values at import time (above).
# They are test fixtures, not developer secrets: WORKOS_API_KEY is required by
# DevelopmentSettings, and the encryption/signing keys back code paths the
# suite exercises. Blanking them would break the suite, not make it safer.
_HERMETIC_ALLOWLIST = frozenset({"WORKOS_API_KEY", "MCP_ENCRYPTION_KEY", "AGENT_SECRET"})

# Live-credential tiers (composio, model_onboarding) declare the keys their
# tests legitimately need by setting HERMETIC_ALLOW_KEYS (comma-separated) in
# their own conftest at import time — before the session fence runs. The fence
# then leaves those keys untouched. This is the explicit opt-in: nothing is
# allowed to survive the fence by accident, only by declaration.
_HERMETIC_ALLOW_ENV = "HERMETIC_ALLOW_KEYS"


def _hermetic_allowed_keys() -> frozenset[str]:
    declared = {
        key.strip() for key in os.environ.get(_HERMETIC_ALLOW_ENV, "").split(",") if key.strip()
    }
    return _HERMETIC_ALLOWLIST | declared


# Keys that must be PRESENT (non-empty) at test time but never real. Today
# GOOGLE_API_KEY is the only one: three pre-existing unit modules
# (tests/unit/override/test_langgraph_bigtool.py, test_hook_chain.py and
# tests/unit/agents/test_agent_routing.py) construct real
# ChatGoogleGenerativeAI clients through app code, and langchain's pydantic
# validation reads the env var directly. The clients are constructed but never
# invoked, so a deterministic fake satisfies validation without leaking a real
# key into the test env — and any genuine network call fails loudly on the
# invalid key instead of silently billing a live credential. The root fix (the
# tests injecting their own fake key or mocking the LLM factory) belongs to the
# test-ownership work.
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
        # Process identity the worker stamps at import (app/workers/lifecycle/
        # startup.py setdefaults GAIA_SERVICE_NAME=arq_worker before its app
        # imports, so the first emitted log line already carries the Promtail
        # label). Any test importing that chain would otherwise leak the var and
        # trip the pollution guard below — e.g. test_worker_smoke, or any
        # single-file selection that is the only importer of app.worker. Pinning
        # it here keeps the guard's baseline complete: under tests the process
        # is not the worker, and env_context() falls through "" to the default
        # service name.
        os.environ.setdefault("GAIA_SERVICE_NAME", "")
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)


@pytest.fixture(scope="session", autouse=True)
def _env_pollution_guard(_hermetic_environment: Iterator[None]) -> Iterator[None]:
    """Fail if any test leaked os.environ mutations.

    The fence restores the original environment at teardown, which silently
    masks leaks; this guard depends on the fence so it tears down BEFORE the
    restore and compares the environment a test left behind against the
    post-fence baseline. Any key added, changed, or removed by a test fails
    the run with the exact diff.
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

# Real UserSubscriptionStatus shape, as get_user_subscription_status returns it
# for a paying subscriber (payment_service.get_user_subscription_status
# constructs exactly this model). The root conftest's global patch pins
# get_user_subscription_status to a FREE plan, so PRO-tier tests opt in by
# patching it with this object.
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

    # Import app_factory explicitly BEFORE patching it: mock.patch resolves
    # "app.core.app_factory" via getattr on the app.core package, which only
    # has the attribute once the submodule has been imported. In the normal
    # suite something imports it first; under mutmut's mutants/ isolation the
    # import order differs and the patch target AttributeErrors.
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
    """Authenticated user dict for a paying PRO user.

    FAKE_USER-shaped, plus a ``subscription`` key holding the real
    ``UserSubscriptionStatus`` for a PRO plan. The global
    ``get_user_subscription_status`` patch always reports FREE, so PRO-tier
    tests patch that seam with ``pro_user["subscription"]``.
    """
    return PRO_USER.copy()


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


@pytest.fixture
def posthog_provider() -> Iterator[Callable[..., None]]:
    """Install a controllable "posthog" provider under the real registry.

    The env fence blanks ``POSTHOG_PROJECT_TOKEN``, so the production provider
    is unavailable for the whole suite. Tests go through the real registry
    rather than patching ``providers`` because the provider NAME is part of
    what they pin: a lookup under any other key finds nothing, and the code
    under test then silently attributes nobody. Production's provider is
    re-registered on teardown.
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
    # Imported here, not at module level: limit_upsell -> email senders ->
    # constants.llm -> langchain_core.language_models, whose ``base`` module
    # eagerly imports ``transformers`` (~0.85s). Collection and workers that
    # never run a test should not pay for it.
    from app.services.limit_upsell import LimitHitOrigin, mark_run_origin

    mark_run_origin(LimitHitOrigin.INTERACTIVE)


@pytest.fixture(autouse=True)
def _isolate_wide_event_state() -> Iterator[None]:
    """Keep one test's wide-event boundary from leaking into the next.

    ``log.reset()`` (used bare in ~8 unit test files to simulate a request)
    seeds the runner ContextVar with a shared, MUTABLE ``_EventState``. A later
    async test's ``log.set(...)`` mutates that same object in place — the async
    context copy shares the reference — so its fields surface back in the sync
    runner context and bleed into subsequent tests. That is how a workflow
    execution id set in one test made ``current_workflow_execution_id()`` return
    non-None in a test that opened no boundary at all. Reset to the module
    defaults after every test so no shared object survives.
    """
    from shared.py import wide_events

    yield
    wide_events._event_state.set(None)
    wide_events._trace_id.set("")
