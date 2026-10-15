"""Enabling a Composio toolkit creates its auth config and makes it connectable on the instance."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import composio_client
from composio_client.types.toolkit_list_response import Item as ToolkitListItem
import fakeredis.aioredis
import httpx
import pytest

from app.config.oauth_config import get_integration_by_id, set_instance_integrations
from app.config.settings import settings
from app.constants.cache import MY_INTEGRATIONS_SNAPSHOT_KEY
from app.db.redis import redis_cache
from app.models.runtime_models import InstanceSettingsDocument
from app.schemas.integrations.composio_setup import ComposioToolkit
from app.services.composio import (
    auth_config_resolver,
    instance_toolkits,
    toolkit_catalog,
    toolkit_enablement,
)
from app.services.composio.auth_config_resolver import resolve_auth_configs
from app.services.composio.instance_toolkits import InstanceToolkitRecord
from app.services.composio.toolkit_catalog import catalog_page, search_toolkits
from app.services.composio.toolkit_enablement import (
    AuthPlan,
    disable_toolkit,
    enable_toolkit,
    plan_auth,
    toolkit_detail,
)
from app.utils.errors import AppError
from tests.helpers import captured_wide_event


def _item(
    slug: str, name: str, *, managed: bool, schemes: list[str], no_auth: bool = False
) -> ToolkitListItem:
    return ToolkitListItem.model_validate(
        {
            "deprecated": {"toolkitId": slug},
            "is_local_toolkit": False,
            "name": name,
            "slug": slug,
            "auth_schemes": schemes,
            "composio_managed_auth_schemes": schemes if managed else [],
            "no_auth": no_auth,
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


def _field(name: str, *, secret: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        name=name, display_name=name.replace("_", " ").title(), description=name, is_secret=secret
    )


def _retrieved(
    *, managed: list[str], mode: str, required: list[SimpleNamespace] | None = None
) -> SimpleNamespace:
    creation = SimpleNamespace(
        required=required or [], optional=[_field("scopes")] if required else []
    )
    return SimpleNamespace(
        composio_managed_auth_schemes=managed,
        auth_config_details=[
            SimpleNamespace(mode=mode, fields=SimpleNamespace(auth_config_creation=creation))
        ],
    )


CATALOG = [
    _item("attio", "Attio", managed=True, schemes=["OAUTH2"]),
    _item("coda", "Coda", managed=False, schemes=["API_KEY"]),
    _item("affinity", "Affinity", managed=False, schemes=["OAUTH2"]),
    _item("hackernews", "Hacker News", managed=False, schemes=["NO_AUTH"], no_auth=True),
    _item("github", "GitHub", managed=True, schemes=["OAUTH2"]),
]

RETRIEVED = {
    "attio": _retrieved(managed=["OAUTH2"], mode="OAUTH2"),
    "coda": _retrieved(managed=[], mode="API_KEY"),
    "affinity": _retrieved(
        managed=[],
        mode="OAUTH2",
        required=[_field("client_id"), _field("client_secret", secret=True)],
    ),
    "hackernews": _retrieved(managed=[], mode="NO_AUTH"),
    "github": _retrieved(managed=["OAUTH2"], mode="OAUTH2"),
}


class FakeInstanceSettings:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {}

    async def find_by_key(self, key: str) -> InstanceSettingsDocument | None:
        if key not in self.values:
            return None
        return InstanceSettingsDocument(key=key, value=self.values[key])

    async def set_value(self, key: str, value: dict[str, object]) -> None:
        self.values[key] = value


class FakeComposio:
    def __init__(self) -> None:
        self.created: list[tuple[str, dict[str, object]]] = []
        self.store = FakeInstanceSettings()
        self.index_toolkit_tools = AsyncMock()

    async def list_toolkits(self) -> list[ToolkitListItem]:
        return CATALOG

    async def get_toolkit(self, slug: str) -> SimpleNamespace:
        return RETRIEVED[slug]

    async def create_auth_config(self, slug: str, options: dict[str, object]) -> str:
        self.created.append((slug, options))
        return f"ac_{slug}"


@pytest.fixture
async def composio(
    monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> AsyncIterator[FakeComposio]:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "COMPOSIO_AUTH_CONFIG_OVERRIDES", {})
    fake = FakeComposio()
    monkeypatch.setattr(instance_toolkits, "instance_settings_repository", fake.store)
    monkeypatch.setattr(auth_config_resolver, "instance_settings_repository", fake.store)
    monkeypatch.setattr(toolkit_catalog, "get_composio_service", lambda: fake)
    monkeypatch.setattr(toolkit_enablement, "get_composio_service", lambda: fake)
    monkeypatch.setattr(toolkit_enablement, "_index_toolkit_tools", fake.index_toolkit_tools)
    auth_config_resolver.invalidate_auth_config_cache()
    yield fake
    set_instance_integrations([])
    auth_config_resolver.invalidate_auth_config_cache()


def test_a_managed_toolkit_plans_composios_own_app_with_no_fields() -> None:
    plan = plan_auth(RETRIEVED["attio"])

    assert (plan.scheme, plan.composio_managed, plan.fields) == ("OAUTH2", True, [])


def test_an_api_key_toolkit_plans_custom_auth_with_no_creation_fields() -> None:
    plan = plan_auth(RETRIEVED["coda"])

    assert (plan.scheme, plan.composio_managed, plan.fields) == ("API_KEY", False, [])


def test_an_unmanaged_oauth_toolkit_asks_for_exactly_its_creation_fields() -> None:
    plan = plan_auth(RETRIEVED["affinity"])

    assert plan.scheme == "OAUTH2"
    assert [(f.name, f.required, f.is_secret) for f in plan.fields] == [
        ("client_id", True, False),
        ("client_secret", True, True),
        ("scopes", False, False),
    ]


def test_a_no_auth_toolkit_has_no_plan() -> None:
    assert plan_auth(RETRIEVED["hackernews"]) == AuthPlan(
        scheme=None, composio_managed=False, fields=[]
    )


@pytest.mark.parametrize(
    ("managed", "scheme"),
    [(["API_KEY", "OAUTH2"], "OAUTH2"), (["API_KEY", "BASIC"], "API_KEY")],
)
def test_a_managed_toolkit_prefers_oauth_else_composios_first_scheme(
    managed: list[str], scheme: str
) -> None:
    assert plan_auth(_retrieved(managed=managed, mode="OAUTH2")).scheme == scheme


async def test_the_detail_names_the_scheme_and_the_fields_enabling_needs(
    composio: FakeComposio,
) -> None:
    detail = await toolkit_detail("affinity")

    assert detail.toolkit.slug == "affinity"
    assert (detail.auth_scheme, detail.composio_managed) == ("OAUTH2", False)
    assert [f.name for f in detail.fields] == ["client_id", "client_secret", "scopes"]


async def test_enabling_a_toolkit_not_in_code_makes_it_a_connectable_integration(
    composio: FakeComposio,
) -> None:
    async with captured_wide_event() as event:
        result = await enable_toolkit("attio", {})

    assert (result.integration_id, result.auth_config_id, result.origin) == (
        "attio",
        "ac_attio",
        "instance",
    )
    assert composio.created == [
        ("attio", {"type": "use_composio_managed_auth", "name": "GAIA Attio"})
    ]
    integration = get_integration_by_id("attio")
    assert integration is not None and integration.origin == "instance"
    assert (await resolve_auth_configs())["attio"].auth_config_id == "ac_attio"
    assert await instance_toolkits.stored_toolkits() == {
        "attio": InstanceToolkitRecord(
            slug="attio",
            name="Attio",
            description="Attio description",
            logo="https://logos.composio.dev/api/attio",
            category="crm",
            auth_scheme="OAUTH2",
        )
    }
    composio.index_toolkit_tools.assert_called_once_with(integration)
    assert event["composio_toolkit"] == {
        "slug": "attio",
        "integration_id": "attio",
        "origin": "instance",
        "composio_managed": True,
        "auth_scheme": "OAUTH2",
    }


async def test_a_toolkit_composio_files_under_no_category_is_stored_uncategorised(
    composio: FakeComposio, monkeypatch: pytest.MonkeyPatch
) -> None:
    coda = CATALOG[1]
    uncategorised = coda.model_copy(
        update={"meta": coda.meta.model_copy(update={"categories": []})}
    )
    monkeypatch.setattr(composio, "list_toolkits", AsyncMock(return_value=[uncategorised]))

    await enable_toolkit("coda", {})

    stored = await instance_toolkits.stored_toolkits()
    assert stored["coda"].category == "other"  # Composio's own name for its uncategorised toolkits


async def test_enabling_a_built_in_toolkit_sets_up_the_code_integration(
    composio: FakeComposio,
) -> None:
    result = await enable_toolkit("github", {})

    assert (result.integration_id, result.origin) == ("github", "code")
    assert (await resolve_auth_configs())["github"].auth_config_id == "ac_github"
    assert await instance_toolkits.stored_toolkits() == {}
    composio.index_toolkit_tools.assert_not_called()


async def test_an_unmanaged_oauth_toolkit_sends_the_supplied_credentials(
    composio: FakeComposio,
) -> None:
    await enable_toolkit("affinity", {"client_id": "id-1", "client_secret": " s3 ", "other": "x"})

    assert composio.created == [
        (
            "affinity",
            {
                "type": "use_custom_auth",
                "auth_scheme": "OAUTH2",
                "name": "GAIA Affinity",
                "credentials": {"client_id": "id-1", "client_secret": "s3"},
            },
        )
    ]


async def test_a_missing_required_field_is_refused_before_composio_is_called(
    composio: FakeComposio,
) -> None:
    with pytest.raises(AppError) as raised:
        await enable_toolkit("affinity", {"client_id": " "})

    assert raised.value == AppError(
        message="Affinity needs Client Id, Client Secret to create its auth config",
        fix="Fill in every required field and enable it again",
        status_code=422,
        code="composio_auth_fields_missing",
        public={"missing_fields": ["Client Id", "Client Secret"]},
    )
    assert composio.created == []
    assert get_integration_by_id("affinity") is None


async def test_a_no_auth_toolkit_is_refused(composio: FakeComposio) -> None:
    with pytest.raises(AppError) as raised:
        await enable_toolkit("hackernews", {})

    assert raised.value == AppError(
        message="Hacker News needs no sign-in, which GAIA cannot connect yet",
        status_code=422,
        code="composio_toolkit_unsupported",
    )
    assert composio.created == []


async def test_an_unknown_slug_is_a_404(composio: FakeComposio) -> None:
    with pytest.raises(AppError) as raised:
        await toolkit_detail("nope")

    assert raised.value == AppError(
        message="Composio has no toolkit 'nope'",
        status_code=404,
        code="composio_toolkit_not_found",
    )


def _composio_error(
    error: type[composio_client.APIStatusError], status: int
) -> composio_client.APIStatusError:
    request = httpx.Request("POST", "https://composio.test")
    return error("bad key", response=httpx.Response(status, request=request), body=None)


async def test_a_key_composio_rejects_while_reading_a_toolkit_names_the_key(
    composio: FakeComposio, monkeypatch: pytest.MonkeyPatch
) -> None:
    rejected = _composio_error(composio_client.AuthenticationError, 401)
    monkeypatch.setattr(composio, "get_toolkit", AsyncMock(side_effect=rejected))

    with pytest.raises(AppError) as raised:
        await toolkit_detail("attio")

    assert (raised.value.code, raised.value.why) == ("composio_key_rejected", "bad key")


async def test_a_key_composio_rejects_while_creating_the_auth_config_names_the_key(
    composio: FakeComposio, monkeypatch: pytest.MonkeyPatch
) -> None:
    rejected = _composio_error(composio_client.AuthenticationError, 401)
    monkeypatch.setattr(composio, "create_auth_config", AsyncMock(side_effect=rejected))

    with pytest.raises(AppError) as raised:
        await enable_toolkit("attio", {})

    assert (raised.value.code, raised.value.why) == ("composio_key_rejected", "bad key")
    assert get_integration_by_id("attio") is None


async def test_an_auth_config_composio_refuses_is_a_422_with_its_reason(
    composio: FakeComposio, monkeypatch: pytest.MonkeyPatch
) -> None:
    refused = _composio_error(composio_client.BadRequestError, 400)
    monkeypatch.setattr(composio, "create_auth_config", AsyncMock(side_effect=refused))

    with pytest.raises(AppError) as raised:
        await enable_toolkit("attio", {})

    assert raised.value == AppError(
        message="Composio refused to create an auth config for Attio",
        why=str(refused),
        status_code=422,
        code="composio_auth_config_rejected",
    )
    assert raised.value.__cause__ is refused


async def test_disabling_removes_the_integration_and_its_auth_config(
    composio: FakeComposio,
) -> None:
    await enable_toolkit("coda", {})

    await disable_toolkit("coda")

    assert get_integration_by_id("coda") is None
    assert "coda" not in await resolve_auth_configs()
    assert composio.store.values[auth_config_resolver.AUTH_CONFIGS_SETTING_KEY] == {}
    with pytest.raises(AppError) as raised:
        await disable_toolkit("coda")
    assert raised.value == AppError(
        message="'coda' is not a toolkit enabled on this instance",
        status_code=404,
        code="composio_toolkit_not_enabled",
    )


async def test_the_catalog_marks_each_toolkits_state_on_the_instance(
    composio: FakeComposio,
) -> None:
    await enable_toolkit("attio", {})

    page = await catalog_page("", None, 0, 50)

    states = {e.slug: (e.status, e.integration_id, e.set_up) for e in page.items}
    assert states == {
        "attio": ("enabled", "attio", True),
        "coda": ("available", None, False),
        "affinity": ("available", None, False),
        "hackernews": ("unsupported", None, False),
        "github": ("built_in", "github", False),
    }
    assert page.total == 5
    assert page.categories == ["crm"]


async def test_search_ranks_name_prefix_matches_first(composio: FakeComposio) -> None:
    toolkits = await toolkit_catalog.cached_toolkits()

    found = search_toolkits(toolkits, "a", None)

    assert [t.slug for t in found][:2] == ["attio", "affinity"]
    assert [t.slug for t in search_toolkits(toolkits, "hacker", None)] == ["hackernews"]
    assert search_toolkits(toolkits, "", "nothing") == []


def _toolkit(name: str, slug: str, category: str, description: str) -> ComposioToolkit:
    return ComposioToolkit(
        slug=slug,
        name=name,
        description=description,
        logo=None,
        categories=[category],
        auth_schemes=["OAUTH2"],
        composio_managed=True,
        no_auth=False,
        tools_count=1,
        triggers_count=0,
    )


def test_search_orders_prefix_then_infix_then_category_then_description_matches() -> None:
    toolkits = [
        _toolkit("Zeta", "zeta", "misc", "Talks to your CRM"),
        _toolkit("Yotta", "yotta", "CRM", "x"),
        _toolkit("Super CRM Tool", "supertool", "misc", "x"),
        _toolkit("Hub", "hubcrm", "misc", "x"),
        _toolkit("Alpha", "crmalpha", "misc", "x"),
        _toolkit("CRM One", "one", "misc", "x"),
        _toolkit("Other", "other", "misc", "x"),
    ]

    found = search_toolkits(toolkits, " CRM ", None)

    assert [t.slug for t in found] == ["crmalpha", "one", "supertool", "hubcrm", "yotta", "zeta"]


async def test_the_catalog_keeps_each_toolkits_logo_schemes_and_managed_flag(
    composio: FakeComposio, monkeypatch: pytest.MonkeyPatch
) -> None:
    logo_less = CATALOG[1].model_copy(
        update={"meta": CATALOG[1].meta.model_copy(update={"logo": ""})}
    )
    monkeypatch.setattr(composio, "list_toolkits", AsyncMock(return_value=[CATALOG[0], logo_less]))

    attio, coda = await toolkit_catalog.cached_toolkits()

    assert (attio.logo, attio.auth_schemes, attio.composio_managed) == (
        "https://logos.composio.dev/api/attio",
        ["OAUTH2"],
        True,
    )
    assert (coda.logo, coda.auth_schemes, coda.composio_managed) == (None, ["API_KEY"], False)


async def test_a_key_composio_rejects_while_listing_the_catalog_names_the_key(
    composio: FakeComposio, monkeypatch: pytest.MonkeyPatch
) -> None:
    rejected = _composio_error(composio_client.AuthenticationError, 401)
    monkeypatch.setattr(composio, "list_toolkits", AsyncMock(side_effect=rejected))

    with pytest.raises(AppError) as raised:
        await toolkit_catalog.cached_toolkits()

    assert (raised.value.code, raised.value.why) == ("composio_key_rejected", "bad key")


async def test_a_catalog_page_filters_by_category_and_stamps_its_counts(
    composio: FakeComposio,
) -> None:
    async with captured_wide_event() as event:
        page = await catalog_page("a", "crm", 1, 2)

    assert [e.slug for e in page.items] == ["affinity", "coda"]
    assert event["composio_catalog"] == {"total": 5, "matches": 4, "page": 2}
    assert (await catalog_page("a", "productivity", 0, 50)).items == []


async def test_a_page_cached_while_composio_creates_the_auth_config_is_dropped(
    composio: FakeComposio, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot_key = MY_INTEGRATIONS_SNAPSHOT_KEY.format(user_id="u1")
    create = composio.create_auth_config

    async def create_while_a_page_loads(slug: str, options: dict[str, object]) -> str:
        await redis_cache.set(snapshot_key, "the integrations page without attio")
        return await create(slug, options)

    monkeypatch.setattr(composio, "create_auth_config", create_while_a_page_loads)

    await enable_toolkit("attio", {})

    assert await redis_cache.get(snapshot_key) is None
