"""Tests for browser_session lifecycle — including the registry-write gate."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.browser import session as session_mod
from app.services.browser.exceptions import BrowserUnavailableError


def _make_session_fakes(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    host = MagicMock(
        session_id="s1",
        context_id="ctx-1",
        cdp_ws="ws://x",  # NOSONAR
        live_ws="ws://live",  # NOSONAR
    )
    monkeypatch.setattr(session_mod.host_client, "create_session", AsyncMock(return_value=host))
    monkeypatch.setattr(session_mod.host_client, "delete_session", AsyncMock())
    monkeypatch.setattr(session_mod, "load_storage_state", AsyncMock(return_value=None))
    monkeypatch.setattr(session_mod, "save_storage_state", AsyncMock())
    monkeypatch.setattr(session_mod, "register_session", AsyncMock(return_value=True))
    monkeypatch.setattr(session_mod, "unregister_session", AsyncMock())
    return host


async def test_registry_write_failure_aborts_before_yield(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed ownership write must fail the session (releasing the host context)
    instead of handing the user a live-view link that can never authorize."""
    _make_session_fakes(monkeypatch)
    monkeypatch.setattr(session_mod, "register_session", AsyncMock(return_value=False))

    with pytest.raises(BrowserUnavailableError, match="register"):
        async with session_mod.browser_session(user_id="u1", start_url="https://x"):
            pytest.fail("browser_session yielded despite the failed registration")

    # The host context was still released on the way out — never orphaned.
    session_mod.host_client.delete_session.assert_awaited()
    session_mod.unregister_session.assert_awaited()


async def test_registry_write_success_yields_and_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: registration succeeds, the session yields, and release runs."""
    _make_session_fakes(monkeypatch)

    async with session_mod.browser_session(user_id="u1", start_url="https://x") as s:
        assert s.session_id == "s1"
    session_mod.host_client.delete_session.assert_awaited_once()
    session_mod.unregister_session.assert_awaited_once()
