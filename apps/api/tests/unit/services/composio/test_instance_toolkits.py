"""Composio toolkits an instance admin enabled join every reader of the integration catalog."""

from collections.abc import Iterator

import pytest

from app.agents.core.subagents.registry import (
    all_subagents,
    foreign_provider_named_in,
    get_subagent_by_id,
)
from app.config import oauth_config
from app.config.oauth_config import (
    OAUTH_INTEGRATIONS,
    all_integrations,
    get_integration_by_id,
    get_integration_by_tool_slug,
    get_integration_by_toolkit,
    set_instance_integrations,
)
from app.config.settings import settings
from app.models.runtime_models import InstanceSettingsDocument
from app.services.composio import instance_toolkits
from app.services.composio.auth_config_resolver import composio_integrations
from app.services.composio.instance_toolkits import (
    TOOLKITS_SETTING_KEY,
    InstanceToolkitRecord,
    build_instance_integration,
    load_instance_toolkits,
    remove_toolkit,
    save_toolkit,
)
from app.services.integrations.integration_connection_service import build_integrations_config

ATTIO = InstanceToolkitRecord(
    slug="attio",
    name="Attio",
    description="CRM for fast-moving teams",
    logo="https://logos.composio.dev/api/attio",
    category="crm",
    auth_scheme="OAUTH2",
)


class FakeInstanceSettings:
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
    monkeypatch.setattr(instance_toolkits, "instance_settings_repository", fake)
    published: list[str] = []

    async def _publish(scope: str) -> None:
        published.append(scope)

    monkeypatch.setattr(instance_toolkits, "publish_config_update", _publish)
    yield fake
    set_instance_integrations([])


@pytest.fixture
def selfhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")


def test_with_nothing_enabled_the_catalog_is_exactly_the_code_catalog() -> None:
    set_instance_integrations([])

    assert list(all_integrations()) == list(OAUTH_INTEGRATIONS)


async def test_gaia_cloud_never_reads_the_store_and_keeps_the_code_catalog(
    store: FakeInstanceSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", "production")
    store.values[TOOLKITS_SETTING_KEY] = {"attio": ATTIO.model_dump()}

    await load_instance_toolkits()

    assert store.reads == 0
    assert list(all_integrations()) == list(OAUTH_INTEGRATIONS)
    assert get_integration_by_id("attio") is None


async def test_a_loaded_toolkit_reaches_every_catalog_reader(
    store: FakeInstanceSettings, selfhost: None
) -> None:
    store.values[TOOLKITS_SETTING_KEY] = {"attio": ATTIO.model_dump()}
    build_integrations_config()
    all_subagents()

    await load_instance_toolkits()

    integration = get_integration_by_id("attio")
    assert integration is not None
    assert integration.origin == "instance"
    assert get_integration_by_toolkit("ATTIO") is integration
    assert get_integration_by_tool_slug("ATTIO_LIST_RECORDS") is integration
    assert integration in composio_integrations()
    subagent = get_subagent_by_id("attio")
    assert subagent is not None
    assert subagent.managed_by == "composio"
    assert subagent.config.tool_space == "attio"
    assert foreign_provider_named_in("add the deal to Attio", "gmail") == subagent
    config_item = next(i for i in build_integrations_config().integrations if i.id == "attio")
    assert config_item.origin == "instance"
    assert config_item.icon_url == ATTIO.logo


async def test_a_stored_toolkit_now_defined_in_code_yields_to_the_code_entry(
    store: FakeInstanceSettings, selfhost: None
) -> None:
    gmail = ATTIO.model_copy(update={"slug": "gmail", "name": "Gmail (instance)"})
    store.values[TOOLKITS_SETTING_KEY] = {"gmail": gmail.model_dump(), "attio": ATTIO.model_dump()}

    await load_instance_toolkits()

    resolved = get_integration_by_id("gmail")
    assert resolved is not None
    assert resolved.origin == "code"
    assert get_integration_by_id("attio") is not None


def test_installing_an_integration_that_shadows_a_code_one_is_refused() -> None:
    shadow = build_instance_integration(ATTIO.model_copy(update={"slug": "github"}))

    with pytest.raises(ValueError, match="github"):
        set_instance_integrations([shadow])


async def test_save_then_remove_round_trips_through_the_store(
    store: FakeInstanceSettings, selfhost: None
) -> None:
    saved = await save_toolkit(ATTIO)

    assert saved.id == "attio"
    assert get_integration_by_id("attio") is not None
    assert await remove_toolkit("attio") is True
    assert get_integration_by_id("attio") is None
    assert await remove_toolkit("attio") is False


async def test_saving_a_code_toolkit_is_refused(
    store: FakeInstanceSettings, selfhost: None
) -> None:
    with pytest.raises(ValueError, match="built-in"):
        await save_toolkit(ATTIO.model_copy(update={"slug": "slack"}))
    assert TOOLKITS_SETTING_KEY not in store.values


def test_catalog_version_changes_on_every_install() -> None:
    before = oauth_config.instance_catalog_version()

    set_instance_integrations([])

    assert oauth_config.instance_catalog_version() == before + 1
