"""The compat probe compares the server's answer to its own navigation, and fails on a site it could not read."""

from __future__ import annotations

from typing import Any

import pytest
from scripts.obscura_compat_probe import (
    Document,
    PageReport,
    ProbeResult,
    _main_response,
    _report_site,
    _verdict,
)

pytestmark = pytest.mark.unit

URL = "https://site.test/"


def _commit(loader: str, url: str) -> dict[str, Any]:
    return {"method": "Page.frameNavigated", "params": {"frame": {"loaderId": loader, "url": url}}}


def _document(loader: str) -> dict[str, Any]:
    return {
        "method": "Network.responseReceived",
        "params": {"type": "Document", "loaderId": loader, "response": {"status": 200}},
    }


def test_the_document_is_the_one_the_probes_own_navigation_committed() -> None:
    """Obscura re-commits the blank tab first, and a page script may navigate after: neither is the answer."""
    events = [
        _commit("blank", "about:blank"),
        _commit("L1", URL),
        _document("L1"),
        _commit("L2", "https://site.test/app"),
        _document("L2"),
    ]

    frame, response = _main_response(events, "L1")

    assert frame["url"] == URL
    assert response is not None
    assert response["loaderId"] == "L1"


def test_a_site_a_browser_loaded_without_a_document_read_fails_the_run() -> None:
    """Obscura's document read None on every site, so no site could ever be told apart as the server's."""
    result = ProbeResult()
    read = PageReport(fingerprint={"links": 5}, document=Document(200, URL, 2048))

    _report_site(result, URL, PageReport(fingerprint={"links": 1}), read)

    assert result.probe_errors == [f"{URL}: obscura loaded it, but the probe read no main document"]
    assert (result.rendered_differently, result.served_different_document) == (set(), {})
    assert _verdict([URL], result, None) == 2
