"""The short live-view capability link: bare slug behind a vhost, /live/{code} in dev."""

from unittest.mock import AsyncMock

import pytest

from app.services.browser import live_view


@pytest.mark.unit
async def test_link_is_bare_slug_when_a_vhost_is_configured(monkeypatch):
    monkeypatch.setattr(live_view, "mint_live_code", AsyncMock(return_value="Xk3p9qR2mN4t"))
    monkeypatch.setattr(
        live_view.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.heygaia.io"
    )

    link = await live_view.create_live_view_link("sess-abc", "user-1")

    # No /live/ prefix, no session id, no ?t= token — the vhost rewrites /{code}.
    assert link == "https://browser.heygaia.io/Xk3p9qR2mN4t"


@pytest.mark.unit
async def test_link_keeps_live_prefix_without_a_vhost(monkeypatch):
    monkeypatch.setattr(live_view, "mint_live_code", AsyncMock(return_value="Xk3p9qR2mN4t"))
    monkeypatch.setattr(live_view.settings, "BROWSER_LIVE_VIEW_BASE_URL", None)
    monkeypatch.setattr(live_view.settings, "HOST", "http://localhost:8000")

    link = await live_view.create_live_view_link("sess-abc", "user-1")

    # Dev: the app serves /live/{code} directly (no vhost to rewrite the bare slug).
    assert link == "http://localhost:8000/live/Xk3p9qR2mN4t"
