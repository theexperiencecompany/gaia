"""Tests for Steel session lifecycle — the fail-safe release guarantee."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.browser import session as session_mod
from app.services.browser.exceptions import BrowserUnavailableError
from app.services.browser.session import resolve_cdp_url, steel_session


def _fake_client() -> MagicMock:
    client = MagicMock()
    created = MagicMock()
    created.id = "sess-123"
    created.websocket_url = "ws://steel:3000/v1/cdp/sess-123"  # NOSONAR
    created.debug_url = "http://steel:3000/debug/sess-123"  # NOSONAR
    created.session_viewer_url = "http://steel:3000/view/sess-123"  # NOSONAR
    created.profile_id = None
    client.sessions.create = AsyncMock(return_value=created)
    client.sessions.release = AsyncMock()
    client.close = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# resolve_cdp_url
# ---------------------------------------------------------------------------


def test_resolve_cdp_url_defaults_to_websocket_url(monkeypatch):
    monkeypatch.setattr(session_mod.settings, "STEEL_CDP_CONNECT_URL", None)
    assert resolve_cdp_url("s1", "ws://steel:3000/x") == "ws://steel:3000/x"  # NOSONAR


def test_resolve_cdp_url_override_with_session_placeholder(monkeypatch):
    monkeypatch.setattr(
        session_mod.settings,
        "STEEL_CDP_CONNECT_URL",
        "ws://host:9223/cdp/{session_id}",  # NOSONAR
    )
    assert resolve_cdp_url("s9", "ws://ignored") == "ws://host:9223/cdp/s9"  # NOSONAR


# ---------------------------------------------------------------------------
# steel_session lifecycle
# ---------------------------------------------------------------------------


async def test_session_released_on_success(monkeypatch):
    client = _fake_client()
    monkeypatch.setattr(session_mod, "build_steel_client", lambda: client)

    async with steel_session() as sess:
        assert sess.session_id == "sess-123"
        assert sess.cdp_url == "ws://steel:3000/v1/cdp/sess-123"  # NOSONAR

    client.sessions.release.assert_awaited_once_with("sess-123")
    client.close.assert_awaited_once()


async def test_session_released_on_exception(monkeypatch):
    """A browser is never orphaned when the body raises."""
    client = _fake_client()
    monkeypatch.setattr(session_mod, "build_steel_client", lambda: client)

    with pytest.raises(RuntimeError, match="boom"):
        async with steel_session():
            raise RuntimeError("boom")

    client.sessions.release.assert_awaited_once_with("sess-123")
    client.close.assert_awaited_once()


async def test_create_failure_raises_unavailable_and_closes(monkeypatch):
    client = _fake_client()
    client.sessions.create = AsyncMock(side_effect=ConnectionError("unreachable"))
    monkeypatch.setattr(session_mod, "build_steel_client", lambda: client)

    with pytest.raises(BrowserUnavailableError):
        async with steel_session():
            pass  # pragma: no cover — never entered

    client.sessions.release.assert_not_awaited()
    client.close.assert_awaited_once()


async def test_release_failure_does_not_mask_body_error(monkeypatch):
    client = _fake_client()
    client.sessions.release = AsyncMock(side_effect=RuntimeError("release failed"))
    monkeypatch.setattr(session_mod, "build_steel_client", lambda: client)

    # The body error propagates; the release failure is swallowed (logged).
    with pytest.raises(ValueError, match="original"):
        async with steel_session():
            raise ValueError("original")

    client.close.assert_awaited_once()
