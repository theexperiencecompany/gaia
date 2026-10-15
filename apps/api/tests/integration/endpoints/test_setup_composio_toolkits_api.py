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
from app.constants.integrations import (
    COMPOSIO_CATALOG_DEFAULT_PAGE_SIZE,
    COMPOSIO_CATALOG_MAX_PAGE_SIZE,
)
from app.schemas.integrations.composio_setup import ComposioCatalogResponse
from app.services.composio import auth_config_resolver, toolkit_catalog, toolkit_enablement
from app.services.integrations.integration_connection_service import build_integrations_config
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import (
    IntegrationToolkitDisabled,
    IntegrationToolkitEnabled,
)
from tests.conftest import FAKE_USER
from tests.helpers import captured_wide_event
from tests.integration.endpoints.conftest import API, FAKE_USER_ID

TOOLKITS = f"{API}/composio/toolkits"


def _item(slug: str, name: str, managed: bool, category: str = "crm") -> ToolkitListItem:
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
                "categories": [{"id": category, "name": category}],
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


async def test_listing_without_paging_returns_the_default_page_from_the_start(
    client: AsyncClient, composio: SimpleNamespace
) -> None:
    count = COMPOSIO_CATALOG_DEFAULT_PAGE_SIZE + 5
    composio.list_toolkits.return_value = [
        _item(f"kit{i:03d}", f"Kit {i:03d}", True) for i in range(count)
    ]

    body = (await client.get(TOOLKITS)).json()

    assert body["total"] == count
    slugs = [e["slug"] for e in body["items"]]
    assert slugs == [f"kit{i:03d}" for i in range(COMPOSIO_CATALOG_DEFAULT_PAGE_SIZE)]


async def test_the_handler_defaults_to_an_unfiltered_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Called without paging, as FastAPI's own defaults are bypassed under mutmut's trampoline."""
    page = ComposioCatalogResponse(items=[], total=0, categories=[])
    fetch = AsyncMock(return_value=page)
    monkeypatch.setattr(endpoint_module, "catalog_page", fetch)

    assert await endpoint_module.list_composio_toolkits(user=FAKE_USER) is page
    fetch.assert_awaited_once_with("", None, 0, COMPOSIO_CATALOG_DEFAULT_PAGE_SIZE)


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({"limit": 0}, 422),
        ({"limit": 1}, 200),
        ({"limit": COMPOSIO_CATALOG_MAX_PAGE_SIZE}, 200),
        ({"limit": COMPOSIO_CATALOG_MAX_PAGE_SIZE + 1}, 422),
        ({"offset": -1}, 422),
        ({"q": "a" * 101}, 422),
        ({"category": "c" * 101}, 422),
    ],
)
async def test_listing_bounds_the_page_and_the_search_text(
    client: AsyncClient, composio: SimpleNamespace, params: dict[str, object], status: int
) -> None:
    assert (await client.get(TOOLKITS, params=params)).status_code == status


async def test_listing_filters_by_category_and_stamps_the_search_shape(
    client: AsyncClient, composio: SimpleNamespace
) -> None:
    composio.list_toolkits.return_value = [
        _item("attio", "Attio", True),
        _item("asana", "Asana", True, category="productivity"),
        _item("affinity", "Affinity", False),
    ]

    async with captured_wide_event() as live:
        resp = await client.get(TOOLKITS, params={"q": "a", "category": "crm", "offset": 1})
        event = dict(live)  # before the boundary stamps its own outcome on exit

    assert [e["slug"] for e in resp.json()["items"]] == ["affinity"]
    assert event["user"] == {"id": FAKE_USER_ID}
    assert event["operation"] == "list_composio_toolkits"
    assert event["composio_catalog"] == {
        "query_length": 1,
        "category": "crm",
        "offset": 1,
        "total": 3,
        "matches": 2,
        "page": 1,
    }
    assert event["outcome"] == "success"


async def test_reading_a_toolkit_lowercases_the_slug_and_stamps_its_field_count(
    client: AsyncClient, composio: SimpleNamespace
) -> None:
    async with captured_wide_event() as live:
        resp = await client.get(f"{TOOLKITS}/Affinity")
        event = dict(live)  # before the boundary stamps its own outcome on exit

    assert resp.status_code == 200
    composio.get_toolkit.assert_awaited_with("affinity")
    assert event["user"] == {"id": FAKE_USER_ID}
    assert event["operation"] == "get_composio_toolkit"
    assert event["toolkit"] == "Affinity"
    assert event["composio_toolkit"] == {"fields": 1}
    assert event["outcome"] == "success"


async def test_enabling_a_toolkit_is_audited_and_stamped(
    client: AsyncClient, composio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[tuple[object, object]] = []
    monkeypatch.setattr(
        endpoint_module, "capture", lambda user, event: captured.append((user, event))
    )

    async with captured_wide_event() as live:
        resp = await client.post(f"{TOOLKITS}/Attio", json={})
        event = dict(live)  # before the boundary stamps its own outcome on exit

    assert resp.status_code == 201
    assert resp.json()["integration_id"] == "attio"
    assert event["user"] == {"id": FAKE_USER_ID}
    assert event["operation"] == "enable_composio_toolkit"
    assert event["toolkit"] == "Attio"
    assert event["integration"] == {"id": "attio"}
    assert event["outcome"] == "success"
    assert event["audit"] == [
        {
            "msg": "composio toolkit enabled",
            "actor": FAKE_USER_ID,
            "toolkit": "Attio",
            "integration_id": "attio",
        }
    ]
    assert captured == [
        (
            UserId(FAKE_USER_ID),
            IntegrationToolkitEnabled(toolkit="attio", origin="instance", composio_managed=True),
        )
    ]


async def test_disabling_a_toolkit_is_audited_and_stamped(
    client: AsyncClient, composio: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.post(f"{TOOLKITS}/attio", json={})
    captured: list[tuple[object, object]] = []
    monkeypatch.setattr(
        endpoint_module, "capture", lambda user, event: captured.append((user, event))
    )

    async with captured_wide_event() as live:
        resp = await client.delete(f"{TOOLKITS}/ATTIO")
        event = dict(live)  # before the boundary stamps its own outcome on exit

    assert resp.status_code == 204
    assert all(i.id != "attio" for i in build_integrations_config().integrations)
    assert event["user"] == {"id": FAKE_USER_ID}
    assert event["operation"] == "disable_composio_toolkit"
    assert event["toolkit"] == "ATTIO"
    assert event["outcome"] == "success"
    assert event["audit"] == [
        {"msg": "composio toolkit disabled", "actor": FAKE_USER_ID, "toolkit": "ATTIO"}
    ]
    assert captured == [(UserId(FAKE_USER_ID), IntegrationToolkitDisabled(toolkit="attio"))]
