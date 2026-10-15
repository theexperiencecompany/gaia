"""The admin's Composio setup: detect auth configs in their project, save, connect."""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock

import composio_client
from composio_client.types.auth_config_list_response import Item as AuthConfigItem
import httpx
from httpx import AsyncClient
import pytest

from app.api.v1.endpoints import setup_composio as endpoint_module
from app.models.runtime_models import InstanceSettingsDocument
import app.services.composio.auth_config_resolver as resolver
import app.services.composio.auth_config_setup as setup_service
from app.services.providers.provider_credentials_service import ProviderConfig
from shared.py.analytics.catalog.integrations import IntegrationInstanceSetupSaved
from shared.py.wide_events import log
from tests.helpers import captured_wide_event
from tests.integration.endpoints.conftest import API, FAKE_USER_ID

COMPOSIO = f"{API}/composio"


def _auth_config(
    ac_id: str, toolkit: str, status: Literal["ENABLED", "DISABLED"] = "ENABLED"
) -> AuthConfigItem:
    return AuthConfigItem.model_validate(
        {
            "id": ac_id,
            "name": f"{toolkit} auth",
            "no_of_connections": 0,
            "status": status,
            "tool_access_config": {},
            "toolkit": {"logo": "", "slug": toolkit},
            "type": "custom",
            "uuid": f"uuid-{ac_id}",
        }
    )


class FakeInstanceSettings:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {}

    async def find_by_key(self, key: str) -> InstanceSettingsDocument | None:
        value = self.values.get(key)
        return InstanceSettingsDocument(key=key, value=value) if value is not None else None

    async def set_value(self, key: str, value: dict[str, object]) -> None:
        self.values[key] = value


@pytest.fixture
def seams(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    store = FakeInstanceSettings()
    composio = SimpleNamespace(
        list_enabled_auth_configs=AsyncMock(
            return_value=[
                _auth_config("ac_mine_gmail", "gmail"),
                _auth_config("ac_mine_slack_a", "slack"),
                _auth_config("ac_mine_slack_b", "slack"),
            ]
        )
    )
    composio_key: list[ProviderConfig | None] = [
        ProviderConfig(api_key="ak_x", base_url=None, model=None, preset=None)
    ]

    async def resolve_key(provider: str) -> ProviderConfig | None:
        assert provider == "composio"
        return composio_key[0]

    monkeypatch.setattr(resolver, "instance_settings_repository", store)
    monkeypatch.setattr(setup_service, "resolve_provider_config", resolve_key)
    monkeypatch.setattr(setup_service, "get_composio_service", lambda: composio)
    monkeypatch.setattr(resolver.settings, "COMPOSIO_AUTH_CONFIG_OVERRIDES", {})
    resolver.invalidate_auth_config_cache()
    yield SimpleNamespace(store=store, composio=composio, composio_key=composio_key)
    resolver.invalidate_auth_config_cache()


def _by_id(body: dict[str, list[dict[str, object]]]) -> dict[str, dict[str, object]]:
    return {str(row["integration_id"]): row for row in body["integrations"]}


async def test_detected_auth_configs_are_offered_per_integration_until_saved(
    client: AsyncClient, seams: SimpleNamespace
) -> None:
    resp = await client.get(COMPOSIO)

    assert resp.status_code == 200
    body = resp.json()
    assert body["composio_configured"] is True
    rows = _by_id(body)
    assert rows["gmail"]["auth_config_id"] is None
    assert rows["gmail"]["source"] is None
    assert rows["gmail"]["detected"] == [{"id": "ac_mine_gmail", "name": "gmail auth"}]
    assert rows["slack"]["detected"] == [
        {"id": "ac_mine_slack_a", "name": "slack auth"},
        {"id": "ac_mine_slack_b", "name": "slack auth"},
    ]
    assert rows["github"]["detected"] == []


async def test_saved_ids_take_effect_and_report_their_source(
    client: AsyncClient, seams: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[object] = []
    monkeypatch.setattr(endpoint_module, "capture", lambda _user, event: captured.append(event))

    resp = await client.put(
        f"{COMPOSIO}/auth-configs", json={"auth_configs": {"gmail": "ac_mine_gmail"}}
    )

    assert resp.status_code == 200
    rows = _by_id(resp.json())
    assert (rows["gmail"]["auth_config_id"], rows["gmail"]["source"]) == (
        "ac_mine_gmail",
        "stored",
    )
    assert rows["slack"]["auth_config_id"] is None
    assert seams.store.values == {"composio_auth_configs": {"gmail": "ac_mine_gmail"}}
    assert captured == [
        IntegrationInstanceSetupSaved(stored_count=1, set_up_count=1, total_count=len(rows))
    ]


async def test_an_id_for_no_composio_integration_is_a_422_and_nothing_is_saved(
    client: AsyncClient, seams: SimpleNamespace
) -> None:
    resp = await client.put(f"{COMPOSIO}/auth-configs", json={"auth_configs": {"gmial": "ac_x"}})

    assert resp.status_code == 422
    assert "names no Composio integration: ['gmial']" in resp.json()["message"]
    assert seams.store.values == {}


async def test_without_a_composio_key_nothing_is_detected(
    client: AsyncClient, seams: SimpleNamespace
) -> None:
    seams.composio_key[0] = None

    resp = await client.get(COMPOSIO)

    assert resp.status_code == 200
    assert resp.json()["composio_configured"] is False
    assert all(row["detected"] == [] for row in resp.json()["integrations"])
    seams.composio.list_enabled_auth_configs.assert_not_awaited()


async def test_a_key_composio_rejects_is_a_422_naming_the_key(
    client: AsyncClient, seams: SimpleNamespace
) -> None:
    seams.composio.list_enabled_auth_configs.side_effect = composio_client.AuthenticationError(
        "bad key",
        response=httpx.Response(401, request=httpx.Request("GET", "https://composio.test")),
        body=None,
    )

    resp = await client.get(COMPOSIO)

    assert resp.status_code == 422
    assert resp.json()["code"] == "composio_key_rejected"


async def test_only_the_instance_admin_may_read_or_save(
    nonadmin_client: AsyncClient, seams: SimpleNamespace
) -> None:
    assert (await nonadmin_client.get(COMPOSIO)).status_code == 403
    put = await nonadmin_client.put(
        f"{COMPOSIO}/auth-configs", json={"auth_configs": {"gmail": "ac_x"}}
    )
    assert put.status_code == 403
    assert seams.store.values == {}


async def test_saving_auth_configs_leaves_an_audit_record_naming_the_integrations(
    client: AsyncClient, seams: SimpleNamespace
) -> None:
    log.reset()
    try:
        resp = await client.put(
            f"{COMPOSIO}/auth-configs", json={"auth_configs": {"gmail": "ac_mine_gmail"}}
        )
        assert resp.status_code == 200
        [entry] = log.get()["audit"]
    finally:
        log.reset()

    assert entry["msg"] == "composio auth configs saved"
    assert entry["actor"] == FAKE_USER_ID
    assert entry["integrations"] == ["gmail"]
    assert "ac_mine_gmail" not in str(entry)


async def test_reading_the_setup_stamps_the_wide_event(
    client: AsyncClient, seams: SimpleNamespace
) -> None:
    async with captured_wide_event() as live:
        assert (await client.get(COMPOSIO)).status_code == 200
        event = dict(live)  # before the boundary stamps its own outcome on exit

    assert event["user"] == {"id": FAKE_USER_ID}
    assert event["operation"] == "get_composio_setup"
    assert event["outcome"] == "success"


async def test_saving_stamps_how_many_were_saved_and_set_up(
    client: AsyncClient, seams: SimpleNamespace
) -> None:
    async with captured_wide_event() as live:
        resp = await client.put(
            f"{COMPOSIO}/auth-configs", json={"auth_configs": {"gmail": "ac_mine_gmail"}}
        )
        assert resp.status_code == 200
        event = dict(live)  # before the boundary stamps its own outcome on exit

    assert event["user"] == {"id": FAKE_USER_ID}
    assert event["operation"] == "put_composio_auth_configs"
    assert event["outcome"] == "success"
    assert (event["composio_setup"]["saved"], event["composio_setup"]["set_up"]) == (1, 1)
