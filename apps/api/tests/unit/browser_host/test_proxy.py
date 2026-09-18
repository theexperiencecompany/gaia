"""Regression: the CDP proxy did not allowlist navigation schemes.

Before the fix, Page.navigate/Target.createTarget requests reached
Chromium unfiltered. The agent renders attacker-influenced pages, so a
prompt-injected link could steer the browser at file:///etc/passwd or
chrome://settings — Network.setBlockedURLs only filters subresources,
never a top-level navigation, so this has to be enforced in the proxy itself.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.browser_host import proxy
from app.browser_host.proxy import (
    _navigation_url,
    _refusal_reason,
    _refused_navigation_url,
    _refused_private_target,
)
from app.config.settings import settings


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "url", "expected_refusal"),
    [
        ("Page.navigate", "file:///etc/passwd", "file:///etc/passwd"),
        ("Target.createTarget", "chrome://settings", "chrome://settings"),
        ("Page.navigate", "https://example.com", None),
        ("Target.createTarget", "http://example.com", None),
        ("Page.navigate", "about:blank", None),
        ("Page.navigate", None, None),
        ("Page.enable", "file:///etc/passwd", None),
    ],
    ids=[
        "file-scheme-refused",
        "chrome-scheme-refused",
        "https-allowed",
        "http-allowed",
        "about-blank-allowed",
        "navigate-with-no-url-allowed",
        "non-navigation-method-never-refused",
    ],
)
def test_refused_navigation_url(method: str, url: str | None, expected_refusal: str | None) -> None:
    params: dict[str, Any] = {} if url is None else {"url": url}
    message = {"id": 1, "method": method, "params": params}

    assert _refused_navigation_url(message) == expected_refusal


@pytest.mark.unit
@pytest.mark.parametrize(
    "method",
    ["Browser.setDownloadBehavior", "Page.setDownloadBehavior"],
)
def test_setdownloadbehavior_is_refused(method: str) -> None:
    """A client cannot re-enable downloads the host denied at context creation, even though DownloadsWatchdog sends behavior allow on every run."""
    message = {
        "id": 7,
        "method": method,
        "params": {"behavior": "allow", "downloadPath": "/tmp/browser-use-downloads"},
    }

    reason = _refusal_reason(message)

    assert reason is not None
    assert "downloads are denied" in reason


@pytest.mark.unit
def test_ordinary_command_is_forwarded() -> None:
    """The refusal check must not block anything browser-use legitimately sends."""
    assert _refusal_reason({"id": 8, "method": "Page.enable", "params": {}}) is None
    assert (
        _refusal_reason(
            {"id": 9, "method": "Page.navigate", "params": {"url": "https://example.com"}}
        )
        is None
    )


def test_context_lifecycle_is_refused() -> None:
    """A session must not mint or dispose contexts itself — the host owns the context lifecycle so untracked contexts can't escape capacity/reaper math."""
    for method in ("Target.createBrowserContext", "Target.disposeBrowserContext"):
        msg = {"id": 1, "method": method, "params": {}}
        reason = _refusal_reason(msg)
        assert reason is not None
        assert "context lifecycle" in reason


# ---------------------------------------------------------------------------
# _refused_private_target — the SSRF guard on explicit navigations
# ---------------------------------------------------------------------------


async def test_a_target_resolving_to_a_private_address_is_refused(monkeypatch) -> None:
    guard = AsyncMock(
        side_effect=ValueError("refusing to connect to non-public address 169.254.169.254")
    )
    monkeypatch.setattr(proxy, "assert_public_http_url", guard)

    reason = await _refused_private_target(
        {"id": 3, "method": "Page.navigate", "params": {"url": "http://metadata.internal/latest"}}
    )

    assert reason == (
        "navigation to http://metadata.internal/latest refused: "
        "refusing to connect to non-public address 169.254.169.254"
    )
    guard.assert_awaited_once_with("http://metadata.internal/latest")


async def test_a_public_target_is_forwarded(monkeypatch) -> None:
    guard = AsyncMock()
    monkeypatch.setattr(proxy, "assert_public_http_url", guard)

    assert (
        await _refused_private_target(
            {"id": 3, "method": "Target.createTarget", "params": {"url": "https://example.com"}}
        )
        is None
    )
    guard.assert_awaited_once_with("https://example.com")


async def test_non_navigations_relative_urls_and_foreign_schemes_skip_the_resolver(
    monkeypatch,
) -> None:
    guard = AsyncMock()
    monkeypatch.setattr(proxy, "assert_public_http_url", guard)

    for message in (
        {"id": 1, "method": "Page.enable", "params": {}},
        {"id": 2, "method": "Page.navigate", "params": {"url": "/relative/path"}},
        {"id": 3, "method": "Page.navigate", "params": {"url": "file:///etc/passwd"}},
        {"id": 4, "method": "Page.navigate", "params": {"url": "about:blank"}},
    ):
        assert await _refused_private_target(message) is None
    guard.assert_not_awaited()


async def test_the_private_network_switch_disables_the_guard(monkeypatch) -> None:
    guard = AsyncMock(side_effect=ValueError("non-public"))
    monkeypatch.setattr(proxy, "assert_public_http_url", guard)
    monkeypatch.setattr(settings, "BROWSER_HOST_ALLOW_PRIVATE_NETWORK", True)

    message = {"id": 3, "method": "Page.navigate", "params": {"url": "http://10.0.0.5/admin"}}
    assert await _refused_private_target(message) is None
    guard.assert_not_awaited()


def test_navigation_url_is_the_target_or_none_for_blank_missing_or_non_string() -> None:
    assert _navigation_url({"method": "Page.navigate", "params": {"url": "https://a.test"}}) == (
        "https://a.test"
    )
    assert _navigation_url({"method": "Page.navigate", "params": {"url": ""}}) is None
    assert _navigation_url({"method": "Page.navigate", "params": {"url": "about:blank"}}) is None
    assert _navigation_url({"method": "Page.navigate", "params": {"url": 123}}) is None
    assert _navigation_url({"method": "Page.navigate", "params": {}}) is None
    assert _navigation_url({"method": "Page.enable", "params": {"url": "https://a.test"}}) is None


def test_refusal_reason_names_the_foreign_scheme_navigation_it_refuses() -> None:
    assert (
        _refusal_reason(
            {"id": 1, "method": "Page.navigate", "params": {"url": "file:///etc/passwd"}}
        )
        == "navigation to file:///etc/passwd refused: only http and https are allowed"
    )
