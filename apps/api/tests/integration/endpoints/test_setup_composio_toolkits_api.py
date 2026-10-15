"""The admin's Composio catalog: browse, enable one toolkit, and see it join the integrations config."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

from composio_client.types.toolkit_list_response import Item as ToolkitListItem
import fakeredis.aioredis
from httpx import AsyncClient
import pytest

from app.api.v1.endpoints import setup_composio_toolkits as endpoint_module
from app.config.oauth_config import set_instance_integrations
from app.services.composio import auth_config_resolver, toolkit_catalog, toolkit_enablement
from app.services.integrations.integration_connection_service import build_integrations_config
from shared.py.analytics.catalog.integrations import IntegrationToolkitEnabled
from tests.integration.endpoints.conftest import API

TOOLKITS = f"{API}/composio/toolkits"


def _item(slug: str, name: str, managed: bool) -> ToolkitListItem:
    return ToolkitListItem.model_validate(
        {
            "deprecated": {"toolkitId": slug},
            "is_local_toolkit": False,
            "name": name,
            "slug": slug,
            "auth_schemes": ["OAUTH2"],
            "composio_managed_auth_schemes": ["OAUTH2"] if managed else [],
            "no_auth": False,
            "meta": {
                "categories": [{"id": "crm", "name": "crm"}],
                "created_at": "",
                "description": f"{name} description",
                "logo": f"https://logos.composio.dev/api/{slug}",
                "tools_count": 10,
                "triggers_count": 0,
                "updated_at": "",
                "version": "1",
            },
        }
    )


def _retrieved(managed: bool) -> SimpleNamespace:
    field = SimpleNamespace(
        name="client_id", display_name="Client id", description="", is_secret=False
    )
    creation = SimpleNamespace(required=[] if managed else [field], optional=[])
    return SimpleNamespace(
        composio_managed_auth_schemes=["OAUTH2"] if managed else [],
        auth_config_details=[
            SimpleNamespace(mode="OAUTH2", fields=SimpleNamespace(auth_config_creation=creation))
        ],
    )


@pytest.fixture
async def composio(
    monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> AsyncIterator[SimpleNamespace]:
    fake = SimpleNamespace(
        list_toolkits=AsyncMock(
            return_value=[_item("attio", "Attio", True), _item("affinity", "Affinity", False)]
        ),
        get_toolkit=AsyncMock(side_effect=lambda slug: _retrieved(slug == "attio")),
        create_auth_config=AsyncMock(return_value="ac_created"),
    )
    monkeypatch.setattr(toolkit_catalog, "get_composio_service", lambda: fake)
    monkeypatch.setattr(toolkit_enablement, "get_composio_service", lambda: fake)
    monkeypatch.setattr(toolkit_enablement, "_index_toolkit_tools", AsyncMock())
    monkeypatch.setattr(auth_config_resolver.settings, "COMPOSIO_AUTH_CONFIG_OVERRIDES", {})
    auth_config_resolver.invalidate_auth_config_cache()
    yield fake
    set_instance_integrations([])
    auth_config_resolver.invalidate_auth_config_cache()


async def test_enabling_a_catalog_toolkit_makes_it_an_integration_users_can_connect(
    client: AsyncClient, composio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[object] = []
    monkeypatch.setattr(endpoint_module, "capture", lambda _user, event: captured.append(event))

    listed = await client.get(TOOLKITS, params={"q": "att"})
    detail = await client.get(f"{TOOLKITS}/attio")
    enabled = await client.post(f"{TOOLKITS}/attio", json={})
    relisted = await client.get(TOOLKITS, params={"q": "att"})

    assert listed.status_code == 200
    assert [(e["slug"], e["status"]) for e in listed.json()["items"]] == [("attio", "available")]
    assert detail.json()["fields"] == []
    assert detail.json()["composio_managed"] is True
    assert enabled.status_code == 201
    assert enabled.json() == {
        "integration_id": "attio",
        "auth_config_id": "ac_created",
        "origin": "instance",
        "composio_managed": True,
    }
    [entry] = relisted.json()["items"]
    assert (entry["status"], entry["set_up"]) == ("enabled", True)
    item = next(i for i in build_integrations_config().integrations if i.id == "attio")
    assert (item.managed_by, item.origin) == ("composio", "instance")
    assert captured == [
        IntegrationToolkitEnabled(toolkit="attio", origin="instance", composio_managed=True)
    ]


async def test_a_toolkit_needing_credentials_names_the_missing_fields(
    client: AsyncClient, composio: SimpleNamespace
) -> None:
    detail = await client.get(f"{TOOLKITS}/affinity")
    refused = await client.post(f"{TOOLKITS}/affinity", json={"credentials": {}})

    assert [f["name"] for f in detail.json()["fields"]] == ["client_id"]
    assert refused.status_code == 422
    assert refused.json()["code"] == "composio_auth_fields_missing"
    assert refused.json()["missing_fields"] == ["Client id"]
    composio.create_auth_config.assert_not_awaited()


async def test_disabling_an_enabled_toolkit_is_a_204_and_a_second_is_a_404(
    client: AsyncClient, composio: SimpleNamespace
) -> None:
    await client.post(f"{TOOLKITS}/attio", json={})

    first = await client.delete(f"{TOOLKITS}/attio")
    second = await client.delete(f"{TOOLKITS}/attio")

    assert first.status_code == 204
    assert second.status_code == 404
    assert all(i.id != "attio" for i in build_integrations_config().integrations)


async def test_only_the_instance_admin_may_browse_or_enable(
    nonadmin_client: AsyncClient, composio: SimpleNamespace
) -> None:
    assert (await nonadmin_client.get(TOOLKITS)).status_code == 403
    assert (await nonadmin_client.post(f"{TOOLKITS}/attio", json={})).status_code == 403
    composio.create_auth_config.assert_not_awaited()
