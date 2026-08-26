"""Fixtures for the setup-API endpoint tests.

Drives the router over ASGITransport with its parallel-agent seams (provider
credentials service, instance/local repositories, startup-validation seed
checks) rebound to in-memory fakes via ``monkeypatch`` on the endpoint module's
own namespace — so no test touches Mongo/Redis and nothing leaks past the test.
Fakes mirror the real APIs (``any_exists``, ``find_by_key``/``upsert_value``,
``resolve``/``upsert``/``delete``/``invalidate``).

HTTP probes use ``respx`` — the repo-wide pattern for mocking ``httpx``.
"""

from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.v1.dependencies import instance_admin as instance_admin_module
from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.endpoints import setup as setup_module
from app.api.v1.endpoints.setup import router as setup_router
from app.config.settings import settings
from app.models.auth_models import LocalCredentialDocument
from app.models.runtime_models import InstanceSettingsDocument
from app.services.providers.provider_credentials_service import ProviderConfig

FAKE_USER_ID = "setup-test-admin"
NON_ADMIN_USER_ID = "setup-test-second-user"
API = "/api/v1/setup"


class FakeProviderService:
    """In-memory stand-in for the provider credentials service."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.configs: dict[str, ProviderConfig] = {}
        self.invalidated: list[str] = []

    async def resolve(self, provider: str) -> ProviderConfig | None:
        return self.configs.get(provider)

    async def stored_exists(self, provider: str) -> bool:
        """Mirrors the repo's existence probe for the status endpoint."""
        return provider in self.configs

    async def upsert(
        self,
        provider: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        preset: str | None = None,
    ) -> None:
        self.configs[provider] = {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "preset": preset,
        }

    async def delete(self, provider: str) -> None:
        self.configs.pop(provider, None)

    async def invalidate(self, provider: str) -> None:
        self.invalidated.append(provider)


class FakeInstanceSettingsRepository:
    """Key → JSON-value docs; ``find_by_key`` yields a real document model."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    def reset(self) -> None:
        self.docs.clear()

    async def find_by_key(self, key: str) -> InstanceSettingsDocument | None:
        value = self.docs.get(key)
        return InstanceSettingsDocument(key=key, value=value) if value is not None else None

    async def upsert_value(self, key: str, value: dict[str, Any]) -> InstanceSettingsDocument:
        self.docs[key] = dict(value)
        return InstanceSettingsDocument(key=key, value=dict(value))


class FakeLocalCredentialsRepository:
    """The single locally-registered admin account (or none).

    ``admin_user_id`` is ``None`` before first signup; otherwise the row's
    owner. Mirrors the real repository's read surface used by the setup
    module: ``any_exists`` and ``get_by_user_id``.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.admin_user_id: str | None = FAKE_USER_ID

    async def any_exists(self) -> bool:
        return self.admin_user_id is not None

    async def get_by_user_id(self, user_id: str) -> LocalCredentialDocument | None:
        if self.admin_user_id is None or user_id != self.admin_user_id:
            return None
        return LocalCredentialDocument(user_id=user_id, password_hash="bcrypt-hash")


class FakeSeedState:
    """Flags backing fake ``startup_validation`` seed checks."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.plans_seeded = True


provider_service = FakeProviderService()
instance_settings_repo = FakeInstanceSettingsRepository()
local_credentials_repo = FakeLocalCredentialsRepository()
seed_state = FakeSeedState()


async def _fake_is_payment_setup() -> bool:
    return seed_state.plans_seeded


@pytest.fixture(autouse=True)
def _bind_fake_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every external seam of the setup module at controlled fakes.

    The setup endpoints run under their design environment (self-host); the
    admin-guard dependency reads ``settings.ENV`` at call time, so pinning it
    here keeps the suite independent of the local ``.env``. Individual tests
    override with their own ``monkeypatch.setattr`` as needed.
    """
    monkeypatch.setattr(setup_module, "resolve_provider_config", provider_service.resolve)
    monkeypatch.setattr(setup_module, "stored_credential_exists", provider_service.stored_exists)
    monkeypatch.setattr(setup_module, "upsert_provider_config", provider_service.upsert)
    monkeypatch.setattr(setup_module, "delete_provider_config", provider_service.delete)
    monkeypatch.setattr(setup_module, "invalidate_provider_cache", provider_service.invalidate)
    monkeypatch.setattr(setup_module, "instance_settings_repository", instance_settings_repo)
    monkeypatch.setattr(setup_module, "local_credentials_repository", local_credentials_repo)
    monkeypatch.setattr(
        instance_admin_module, "local_credentials_repository", local_credentials_repo
    )
    monkeypatch.setattr(setup_module, "is_payment_setup", _fake_is_payment_setup)
    monkeypatch.setattr(settings, "ENV", "selfhost")


@pytest.fixture(autouse=True)
def _reset_fake_state() -> None:
    provider_service.reset()
    instance_settings_repo.reset()
    local_credentials_repo.reset()
    seed_state.reset()


def _client(*, authenticated: bool, user_id: str = FAKE_USER_ID) -> AsyncClient:
    app = FastAPI()
    app.include_router(setup_router, prefix=API)
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: {"user_id": user_id}
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",  # NOSONAR
    )


@pytest.fixture
async def client() -> AsyncClient:
    """Authed as the instance admin against a minimal app mounting the router."""
    async with _client(authenticated=True) as c:
        yield c


@pytest.fixture
async def nonadmin_client() -> AsyncClient:
    """Authed as a second principal that owns no local credential row."""
    async with _client(authenticated=True, user_id=NON_ADMIN_USER_ID) as c:
        yield c


@pytest.fixture
async def anon_client() -> AsyncClient:
    """Client with no auth override — proves which routes are public."""
    async with _client(authenticated=False) as c:
        yield c
