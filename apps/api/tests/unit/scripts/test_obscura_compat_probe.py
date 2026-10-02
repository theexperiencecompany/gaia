"""The compat probe compares the server's answer to its own navigation, never what a page's script did after."""

from __future__ import annotations

from typing import Any

import pytest
from scripts.obscura_compat_probe import _main_response

pytestmark = pytest.mark.unit


def _commit(loader: str, url: str) -> dict[str, Any]:
    return {"method": "Page.frameNavigated", "params": {"frame": {"loaderId": loader, "url": url}}}


def _document(loader: str) -> dict[str, Any]:
    return {
        "method": "Network.responseReceived",
        "params": {"type": "Document", "loaderId": loader, "response": {"status": 200}},
    }


def test_a_script_redirect_after_the_commit_is_not_the_servers_answer() -> None:
    """Chrome ran the page's JS redirect, Obscura did not: read as a different document, it never failed the run."""
    events = [
        _commit("L1", "https://site.test/"),
        _document("L1"),
        _commit("L2", "https://site.test/app"),
        _document("L2"),
    ]

    frame, response = _main_response(events)

    assert frame["url"] == "https://site.test/"
    assert response is not None
    assert response["loaderId"] == "L1"
