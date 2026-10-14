"""The base browser links are built on: the configured vhost or this host, never a trailing slash."""

import pytest

from app.config.settings import settings
from app.services.browser.links import browser_link_base

pytestmark = pytest.mark.unit


def test_a_configured_base_is_used_without_its_trailing_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.example.com//")
    monkeypatch.setattr(settings, "HOST", "https://api.example.com")

    assert browser_link_base() == "https://browser.example.com"


def test_without_a_configured_base_the_links_use_this_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_LIVE_VIEW_BASE_URL", None)
    monkeypatch.setattr(settings, "HOST", "https://gaia.example.com/BOX/")

    assert browser_link_base() == "https://gaia.example.com/BOX"
