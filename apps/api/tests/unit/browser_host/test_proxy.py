"""Regression: the CDP proxy did not allowlist navigation schemes.

Before the fix, ``Page.navigate``/``Target.createTarget`` requests reached
Chromium unfiltered. The agent renders attacker-influenced pages, so a
prompt-injected link could steer the browser at ``file:///etc/passwd`` or
``chrome://settings`` — ``Network.setBlockedURLs`` only filters subresources,
never a top-level navigation, so this has to be enforced in the proxy itself.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.browser_host.proxy import _is_load_event, _refusal_reason, _refused_navigation_url


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
    """A client cannot re-enable downloads the host denied at context creation.

    browser-use's DownloadsWatchdog sends ``behavior: "allow"`` on every run, so
    without this the per-context deny only survives by accident.
    """
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
    """A session must not mint or dispose contexts itself — the host owns the
    context lifecycle so untracked contexts can't escape capacity/reaper math."""
    for method in ("Target.createBrowserContext", "Target.disposeBrowserContext"):
        msg = {"id": 1, "method": method, "params": {}}
        reason = _refusal_reason(msg)
        assert reason is not None
        assert "context lifecycle" in reason


@pytest.mark.unit
@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        (json.dumps({"method": "Page.loadEventFired", "params": {"timestamp": 1.0}}), True),
        (json.dumps({"method": "Page.frameNavigated", "params": {}}), False),
        # The substring guard alone would misread a page's own data as the event.
        (json.dumps({"id": 3, "result": {"value": "Page.loadEventFired"}}), False),
    ],
)
def test_load_event_detection(frame: str, expected: bool) -> None:
    """Navigation timing closes on the load event — and only on the real one."""
    assert _is_load_event(frame) is expected
