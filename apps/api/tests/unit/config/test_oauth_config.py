"""The integration catalog's lookups: tool slug to integration, Composio providers, catalog cache."""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.config import oauth_config
from app.config.oauth_config import (
    CatalogCached,
    get_composio_integrations_by_provider,
    get_integration_by_tool_slug,
    set_instance_integrations,
)
from app.services.composio.instance_toolkits import (
    InstanceToolkitRecord,
    build_instance_integration,
)


def _integration(integration_id: str, toolkit: str | None) -> SimpleNamespace:
    composio = SimpleNamespace(toolkit=toolkit) if toolkit is not None else None
    return SimpleNamespace(id=integration_id, composio_config=composio)


@pytest.mark.unit
class TestGetIntegrationByToolSlug:
    @pytest.mark.parametrize(
        ("slug", "integration_id"),
        [
            ("GMAIL_SEND_EMAIL", "gmail"),
            ("GOOGLECALENDAR_EVENTS_LIST", "googlecalendar"),
            ("GOOGLE_MAPS_GEOCODE", "google_maps"),
        ],
    )
    def test_a_slug_resolves_to_its_toolkits_integration(
        self, slug: str, integration_id: str
    ) -> None:
        integration = get_integration_by_tool_slug(slug)
        assert integration is not None
        assert integration.id == integration_id

    @pytest.mark.parametrize("slug", ["GMAILBOX_SEND", "GMAIL", "web_search", ""])
    def test_a_slug_without_a_toolkit_prefix_resolves_to_nothing(self, slug: str) -> None:
        assert get_integration_by_tool_slug(slug) is None

    # Case differs so the longest toolkit is not also the greatest string.
    @pytest.mark.parametrize("order", [("google", "GOOGLE_MAPS"), ("GOOGLE_MAPS", "google")])
    def test_the_longest_toolkit_claims_a_slug_both_prefix(self, order: tuple[str, str]) -> None:
        integrations = [_integration("no_composio", None)] + [
            _integration(toolkit, toolkit) for toolkit in order
        ]
        with patch.object(oauth_config, "OAUTH_INTEGRATIONS", integrations):
            maps = get_integration_by_tool_slug("GOOGLE_MAPS_GEOCODE")
            search = get_integration_by_tool_slug("GOOGLE_SEARCH")

        assert maps is not None
        assert maps.id == "GOOGLE_MAPS"
        assert search is not None
        assert search.id == "google"


_ATTIO = InstanceToolkitRecord(
    slug="attio", name="Attio", description="CRM", category="crm", auth_scheme="OAUTH2"
)


@pytest.fixture
def instance_attio() -> Iterator[None]:
    set_instance_integrations([build_instance_integration(_ATTIO)])
    yield
    set_instance_integrations([])


@pytest.mark.unit
class TestCatalogCached:
    def test_builds_once_until_the_instance_set_changes_or_is_cleared(self) -> None:
        builds: list[int] = []

        def build_count() -> int:
            """Count the builds."""
            builds.append(len(builds))
            return len(builds)

        cached = CatalogCached(build_count)

        assert (cached(), cached()) == (1, 1)
        set_instance_integrations([])
        assert (cached(), cached()) == (2, 2)
        cached.cache_clear()
        assert cached() == 3
        assert len(builds) == 3

    def test_keeps_the_builders_name_and_doc(self) -> None:
        def all_widgets() -> list[str]:
            """Return every widget."""
            return []

        cached = CatalogCached(all_widgets)

        assert cached.__name__ == "all_widgets"
        assert cached.__doc__ == "Return every widget."
        assert cached.__wrapped__ is all_widgets


@pytest.mark.unit
def test_composio_providers_cover_instance_toolkits_and_skip_mcp_integrations(
    instance_attio: None,
) -> None:
    by_provider = get_composio_integrations_by_provider()

    assert by_provider["attio"].origin == "instance"
    assert by_provider["gmail"].id == "gmail"
    assert "deepwiki" not in by_provider
