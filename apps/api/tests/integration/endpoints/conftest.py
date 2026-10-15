"""Fixtures for the setup-API endpoint tests.

Drives the router over ASGITransport with its external seams (provider
credentials service, instance and local repositories, startup-validation seed
checks) rebound to in-memory fakes via monkeypatch on the endpoint module own
namespace, so no test touches Mongo or Redis. Fakes mirror the real APIs
(admin_exists, find_by_key and upsert_value, resolve, upsert, delete, invalidate).

HTTP probes use respx, the repo-wide pattern for mocking httpx.
"""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.endpoints import setup as setup_module
from app.api.v1.endpoints.setup import router as setup_router
from app.api.v1.endpoints.setup_composio import router as setup_composio_router
from app.config.settings import settings
from app.constants.auth import InstanceRole, RegistrationPolicy
from app.constants.providers import PROVIDER_FEATURES, CredentialSource, ProviderFeature
from app.core.exception_handlers import register_exception_handlers
from app.db.repositories.instance_settings import instance_settings_repository
from app.models.auth_models import LocalCredentialDocument
from app.models.runtime_models import InstanceSettingsDocument
from app.models.user_models import AuthenticatedUser
from app.services.providers.feature_status import FeatureStatus
from app.services.providers.provider_credentials_service import (
    CredentialResolution,
    ProviderConfig,
    env_config,
)

FAKE_USER_ID = "65f0c0ffee0000000000a001"
NON_ADMIN_USER_ID = "65f0c0ffee0000000000a002"
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

    async def inspect(self, provider: str) -> CredentialResolution:
        """Mirrors the real precedence: a saved config wins over the environment."""
        from_env = env_config(provider)
        if stored := self.configs.get(provider):
            shadows_env = from_env is not None and from_env["api_key"] != stored["api_key"]
            return CredentialResolution(stored, CredentialSource.STORED, shadows_env)
        source = CredentialSource.UNSET if from_env is None else CredentialSource.ENV
        return CredentialResolution(from_env, source, shadows_env=False)

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


class FakeLocalCredentialsRepository:
    """The single locally-registered admin account (or none).

    admin_user_id is None before first signup, otherwise the row owner.
    Mirrors the real read surface used by the setup module: admin_exists
    and get_by_user_id.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.admin_user_id: str | None = FAKE_USER_ID

    async def admin_exists(self) -> bool:
        return self.admin_user_id is not None

    async def get_by_user_id(self, user_id: str) -> LocalCredentialDocument | None:
        if self.admin_user_id is None or user_id != self.admin_user_id:
            return None
        return LocalCredentialDocument(user_id=user_id, password_hash="bcrypt-hash")


class FakeInstanceSettings:
    """In-memory instance_settings: the key/value store the setup wizard state lives in."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.values: dict[str, dict[str, object]] = {}

    async def find_by_key(self, key: str) -> InstanceSettingsDocument | None:
        value = self.values.get(key)
        return None if value is None else InstanceSettingsDocument(key=key, value=value)

    async def set_value(self, key: str, value: dict[str, object]) -> None:
        self.values[key] = value


class FakeSeedState:
    """Flags backing fake startup_validation seed checks."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.plans_seeded = True


provider_service = FakeProviderService()
local_credentials_repo = FakeLocalCredentialsRepository()
instance_settings = FakeInstanceSettings()
seed_state = FakeSeedState()


async def _fake_feature_statuses() -> dict[ProviderFeature, FeatureStatus]:
    """Report a fresh instance: each built-in engine serves, every other feature is off."""
    return {
        feature: FeatureStatus(
            working=spec.built_in is not None,
            in_use=[spec.built_in.engine] if spec.built_in else [],
        )
        for feature, spec in PROVIDER_FEATURES.items()
    }


async def _fake_is_payment_setup() -> bool:
    return seed_state.plans_seeded


async def _fake_registration_policy() -> RegistrationPolicy:
    return RegistrationPolicy.INVITE_ONLY


@pytest.fixture(autouse=True)
def _bind_fake_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every external seam of the setup module at controlled fakes.

    The admin guard reads settings ENV and AUTH_MODE at call time and refuses
    anything but ENV selfhost plus AUTH_MODE local, so pinning both here keeps
    the suite independent of the local dot-env file.
    """
    monkeypatch.setattr(setup_module, "resolve_provider_config", provider_service.resolve)
    monkeypatch.setattr(setup_module, "inspect_credential", provider_service.inspect)
    monkeypatch.setattr(setup_module, "upsert_provider_config", provider_service.upsert)
    monkeypatch.setattr(setup_module, "delete_provider_config", provider_service.delete)
    monkeypatch.setattr(setup_module, "invalidate_provider_cache", provider_service.invalidate)
    monkeypatch.setattr(setup_module, "local_credentials_repository", local_credentials_repo)
    monkeypatch.setattr(setup_module, "is_payment_setup", _fake_is_payment_setup)
    monkeypatch.setattr(setup_module, "feature_statuses", _fake_feature_statuses)
    monkeypatch.setattr(setup_module, "get_registration_policy", _fake_registration_policy)
    monkeypatch.setattr(instance_settings_repository, "find_by_key", instance_settings.find_by_key)
    monkeypatch.setattr(instance_settings_repository, "set_value", instance_settings.set_value)
    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "AUTH_MODE", "local")


@pytest.fixture(autouse=True)
def _reset_fake_state() -> None:
    provider_service.reset()
    local_credentials_repo.reset()
    instance_settings.reset()
    seed_state.reset()


def _client(
    *,
    authenticated: bool,
    user_id: str = FAKE_USER_ID,
    role: InstanceRole | None = InstanceRole.ADMIN,
) -> AsyncClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(setup_router, prefix=API)
    app.include_router(setup_composio_router, prefix=API)
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            user_id=user_id, role=role
        )
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
    """Authed as a member account, which may not administer the instance."""
    async with _client(
        authenticated=True, user_id=NON_ADMIN_USER_ID, role=InstanceRole.MEMBER
    ) as c:
        yield c


@pytest.fixture
async def anon_client() -> AsyncClient:
    """Client with no auth override — proves which routes are public."""
    async with _client(authenticated=False) as c:
        yield c
