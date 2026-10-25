"""Live, opt-in proof that the toolkit catalog and auth config creation work against real Composio.

Needs COMPOSIO_KEY. Creates one Composio-managed and one API-key auth config in that key's
project and deletes both. Run: mise infisical -- test:one tests/composio/test_toolkit_catalog_live.py
(the tier is skipped by the default -m filter; pass -m composio).
"""

import os

import pytest

from app.services.composio.composio_service import ComposioService
from app.services.composio.toolkit_catalog import _summary, search_toolkits
from app.services.composio.toolkit_enablement import _auth_options, plan_auth

COMPOSIO_KEY = os.environ.get("COMPOSIO_KEY", "")

pytestmark = pytest.mark.skipif(not COMPOSIO_KEY, reason="COMPOSIO_KEY is not set")


@pytest.fixture(scope="module")
def composio() -> ComposioService:
    return ComposioService(api_key=COMPOSIO_KEY)


async def test_the_whole_catalog_lists_and_searches(composio: ComposioService) -> None:
    toolkits = [_summary(item) for item in await composio.list_toolkits()]

    assert len(toolkits) > 1000
    assert len({t.slug for t in toolkits}) == len(toolkits)
    assert [t.slug for t in search_toolkits(toolkits, "attio", None)][0] == "attio"


@pytest.mark.parametrize(("slug", "managed"), [("attio", True), ("coda", False)])
async def test_an_auth_config_is_created_from_the_plan(
    composio: ComposioService, slug: str, managed: bool
) -> None:
    plan = plan_auth(await composio.get_toolkit(slug))
    assert plan.composio_managed is managed
    assert [f for f in plan.fields if f.required] == []

    auth_config_id = await composio.create_auth_config(slug, _auth_options(slug, plan, {}))
    try:
        created = composio.composio.auth_configs.get(auth_config_id)
        assert created.toolkit.slug == slug
        assert created.is_composio_managed is managed
    finally:
        composio.composio.auth_configs.delete(auth_config_id)
