"""Unit tests for resolving a Composio tool slug to the integration that owns it."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.config import oauth_config
from app.config.oauth_config import get_integration_by_tool_slug


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

    @pytest.mark.parametrize("order", [("google", "google_maps"), ("google_maps", "google")])
    def test_the_longest_toolkit_claims_a_slug_both_prefix(self, order: tuple[str, str]) -> None:
        integrations = [_integration("no_composio", None)] + [
            _integration(toolkit, toolkit) for toolkit in order
        ]
        with patch.object(oauth_config, "OAUTH_INTEGRATIONS", integrations):
            maps = get_integration_by_tool_slug("GOOGLE_MAPS_GEOCODE")
            search = get_integration_by_tool_slug("GOOGLE_SEARCH")

        assert maps is not None
        assert maps.id == "google_maps"
        assert search is not None
        assert search.id == "google"
