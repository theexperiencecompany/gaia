"""Cover browser_link_base, the one base every browser link is built on.

Live view, recap and step screenshots all hand a user a URL built from it, so a
wrong base is only discovered by someone clicking a dead link.
"""

import pytest

from app.services.browser import links


@pytest.mark.unit
def test_browser_link_base_prefers_configured_base_url_over_host(monkeypatch):
    monkeypatch.setattr(links.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.heygaia.io")
    monkeypatch.setattr(links.settings, "HOST", "https://api.heygaia.io")

    assert links.browser_link_base() == "https://browser.heygaia.io"


@pytest.mark.unit
def test_browser_link_base_falls_back_to_host_when_unset(monkeypatch):
    monkeypatch.setattr(links.settings, "BROWSER_LIVE_VIEW_BASE_URL", None)
    monkeypatch.setattr(links.settings, "HOST", "https://api.heygaia.io")

    assert links.browser_link_base() == "https://api.heygaia.io"


@pytest.mark.unit
def test_browser_link_base_falls_back_to_host_when_base_url_is_empty_string(monkeypatch):
    # "" is falsy but not None — the fallback is an `or`, not an `is None` check.
    monkeypatch.setattr(links.settings, "BROWSER_LIVE_VIEW_BASE_URL", "")
    monkeypatch.setattr(links.settings, "HOST", "https://api.heygaia.io")

    assert links.browser_link_base() == "https://api.heygaia.io"


@pytest.mark.unit
def test_browser_link_base_strips_trailing_slash_from_configured_base_url(monkeypatch):
    monkeypatch.setattr(links.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.heygaia.io/")
    monkeypatch.setattr(links.settings, "HOST", "https://api.heygaia.io")

    assert links.browser_link_base() == "https://browser.heygaia.io"


@pytest.mark.unit
def test_browser_link_base_rstrip_only_strips_slash_not_other_trailing_chars(monkeypatch):
    # Pins the exact character set passed to rstrip(): "/" only. A mutant padding
    # it to "XX/XX" would also strip "X", so a base URL ending in "X/" tells the
    # two apart.
    monkeypatch.setattr(
        links.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.heygaia.ioX/"
    )
    monkeypatch.setattr(links.settings, "HOST", "https://api.heygaia.io")

    assert links.browser_link_base() == "https://browser.heygaia.ioX"


@pytest.mark.unit
def test_browser_link_base_strips_trailing_slash_from_host_fallback(monkeypatch):
    monkeypatch.setattr(links.settings, "BROWSER_LIVE_VIEW_BASE_URL", None)
    monkeypatch.setattr(links.settings, "HOST", "https://api.heygaia.io/")

    assert links.browser_link_base() == "https://api.heygaia.io"
