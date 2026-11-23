"""The base browser links are built on: this host, under the browser routers' API prefix."""

import pytest

from app.config.settings import settings
from app.services.browser.links import browser_link_base

pytestmark = pytest.mark.unit


@pytest.mark.regression
def test_links_sit_under_the_api_prefix_the_proxies_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for GAIA-715: a root-mounted link path reached no proxy that forwards to the API."""
    monkeypatch.setattr(settings, "HOST", "https://gaia.example.com/BOX/")

    assert browser_link_base() == "https://gaia.example.com/BOX/api/v1/browser"
