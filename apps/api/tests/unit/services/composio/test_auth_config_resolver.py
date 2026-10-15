"""Which Composio auth config each integration connects through on this instance."""

from collections.abc import Iterator
import json

import pytest

from app.config.oauth_config import get_integration_by_id
from app.config.settings import settings
from app.constants.integrations import ComposioAuthConfigSource
from app.db.redis import redis_cache
from app.models.runtime_models import InstanceSettingsDocument
import app.services.composio.auth_config_resolver as resolver
from app.services.composio.auth_config_resolver import (
    integration_for_auth_config,
    resolve_auth_configs,
    save_auth_configs,
)
from app.services.runtime.config_updates import (
    COMPOSIO_AUTH_CONFIGS_SCOPE,
    RUNTIME_CONFIG_CHANNEL,
)

SLACK = get_integration_by_id("slack")


class FakeInstanceSettings:
    """In-memory instance_settings with the two calls the resolver makes."""

    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {}
        self.reads = 0

    async def find_by_key(self, key: str) -> InstanceSettingsDocument | None:
        self.reads += 1
        if key not in self.values:
            return None
        return InstanceSettingsDocument(key=key, value=self.values[key])

    async def set_value(self, key: str, value: dict[str, object]) -> None:
        self.values[key] = value


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeInstanceSettings]:
    fake = FakeInstanceSettings()
    monkeypatch.setattr(resolver, "instance_settings_repository", fake)
    monkeypatch.setattr(settings, "COMPOSIO_AUTH_CONFIG_OVERRIDES", {})
    resolver.invalidate_auth_config_cache()
    yield fake
    resolver.invalidate_auth_config_cache()


def _catalog_id(integration_id: str) -> str:
    integration = get_integration_by_id(integration_id)
    assert integration is not None and integration.composio_config is not None
    return integration.composio_config.auth_config_id


async def test_selfhost_resolves_nothing_from_gaias_catalog(
    store: FakeInstanceSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")

    assert await resolve_auth_configs() == {}


async def test_production_resolves_every_integration_to_its_catalog_id(
    store: FakeInstanceSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", "production")
    store.values[resolver.AUTH_CONFIGS_SETTING_KEY] = {"gmail": "ac_never_read"}

    resolved = await resolve_auth_configs()

    assert resolved["gmail"].auth_config_id == _catalog_id("gmail")
    assert resolved["gmail"].source is ComposioAuthConfigSource.CATALOG
    assert store.reads == 0


async def test_a_stored_id_beats_the_env_override_which_beats_nothing(
    store: FakeInstanceSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(
        settings,
        "COMPOSIO_AUTH_CONFIG_OVERRIDES",
        {"gmail": "ac_env_gmail", "slack": "ac_env_slack"},
    )
    store.values[resolver.AUTH_CONFIGS_SETTING_KEY] = {"gmail": "ac_stored_gmail"}

    resolved = await resolve_auth_configs()

    assert (resolved["gmail"].auth_config_id, resolved["gmail"].source) == (
        "ac_stored_gmail",
        ComposioAuthConfigSource.STORED,
    )
    assert (resolved["slack"].auth_config_id, resolved["slack"].source) == (
        "ac_env_slack",
        ComposioAuthConfigSource.ENV,
    )
    assert "github" not in resolved


async def test_saving_replaces_the_stored_set_and_takes_effect_at_once(
    store: FakeInstanceSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    await save_auth_configs({"gmail": "ac_one", "slack": "ac_two"})
    assert set(await resolve_auth_configs()) == {"gmail", "slack"}

    await save_auth_configs({"slack": " ac_three "})

    resolved = await resolve_auth_configs()
    assert set(resolved) == {"slack"}
    assert resolved["slack"].auth_config_id == "ac_three"


class _RecordingRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


async def test_saving_tells_every_other_pod_to_drop_its_cached_set(
    store: FakeInstanceSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    redis = _RecordingRedis()
    monkeypatch.setattr(redis_cache, "redis", redis)

    await save_auth_configs({"gmail": "ac_one"})

    assert redis.published == [
        (RUNTIME_CONFIG_CHANNEL, json.dumps({"scope": COMPOSIO_AUTH_CONFIGS_SCOPE}))
    ]


@pytest.mark.parametrize(
    ("auth_configs", "message"),
    [
        ({"gmial": "ac_x"}, "names no Composio integration: ['gmial']"),
        ({"deepwiki": "ac_x"}, "names no Composio integration: ['deepwiki']"),
        ({"gmail": "  "}, "has an empty auth config id: ['gmail']"),
    ],
    ids=["typo", "not_composio", "blank"],
)
async def test_saving_refuses_ids_that_could_never_connect(
    store: FakeInstanceSettings,
    monkeypatch: pytest.MonkeyPatch,
    auth_configs: dict[str, str],
    message: str,
) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")

    with pytest.raises(ValueError) as refused:
        await save_auth_configs(auth_configs)
    assert store.values == {}
    assert str(refused.value) == f"The auth config list {message}"


async def test_saving_is_refused_where_the_deployment_reads_env_only(
    store: FakeInstanceSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", "production")

    with pytest.raises(RuntimeError) as refused:
        await save_auth_configs({"gmail": "ac_x"})
    assert store.values == {}
    assert str(refused.value) == (
        "This deployment reads Composio auth configs from the environment only; "
        "the instance store is not writable here"
    )


async def test_the_stored_set_is_read_once_per_ttl(
    store: FakeInstanceSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    clock = [1000.0]
    monkeypatch.setattr(resolver, "monotonic", lambda: clock[0])

    await resolve_auth_configs()
    clock[0] += resolver._CACHE_TTL_SECONDS - 1
    await resolve_auth_configs()
    assert store.reads == 1

    clock[0] += 1
    await resolve_auth_configs()
    assert store.reads == 2


async def test_a_callback_auth_config_maps_back_to_its_integration_through_the_store(
    store: FakeInstanceSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    store.values[resolver.AUTH_CONFIGS_SETTING_KEY] = {"slack": "ac_mine_slack"}

    assert await integration_for_auth_config("ac_mine_slack") == SLACK
    assert await integration_for_auth_config(_catalog_id("gmail")) is None
