"""Tests for the authenticated live-view token endpoint — ownership + token scope."""

import pytest

from app.api.v1.endpoints import browser as browser_ep
from app.config.settings import settings
from app.services.browser import takeover_token as tt

_SECRET = "x" * 40


@pytest.fixture(autouse=True)
def _takeover_secret(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_TAKEOVER_TOKEN_SECRET", _SECRET, raising=False)


def _mock_owner(monkeypatch, owner: str | None) -> None:
    async def _session_owner(session_id: str) -> str | None:
        return owner

    monkeypatch.setattr(browser_ep.registry, "session_owner", _session_owner)


async def test_owner_gets_scoped_token(monkeypatch):
    _mock_owner(monkeypatch, "user-1")
    resp = await browser_ep.get_live_view_token("sess-1", {"user_id": "user-1"})
    assert resp.expires_in > 0
    claims = tt.verify_takeover_token(resp.token)
    assert claims["session_id"] == "sess-1"
    assert claims["user_id"] == "user-1"


async def test_non_owner_is_forbidden(monkeypatch):
    _mock_owner(monkeypatch, "someone-else")
    with pytest.raises(browser_ep.HTTPException) as exc:
        await browser_ep.get_live_view_token("sess-1", {"user_id": "user-1"})
    assert exc.value.status_code == 403


async def test_unregistered_session_is_forbidden(monkeypatch):
    _mock_owner(monkeypatch, None)
    with pytest.raises(browser_ep.HTTPException) as exc:
        await browser_ep.get_live_view_token("sess-1", {"user_id": "user-1"})
    assert exc.value.status_code == 403


async def test_missing_user_id_is_bad_request(monkeypatch):
    _mock_owner(monkeypatch, "user-1")
    with pytest.raises(browser_ep.HTTPException) as exc:
        await browser_ep.get_live_view_token("sess-1", {})
    assert exc.value.status_code == 400
