"""A session that takes its own step photo gets state reads without a screenshot."""

from __future__ import annotations

import gc
import inspect
from typing import Any
from unittest.mock import AsyncMock

from browser_use.browser.session import BrowserSession
import pytest

from app.patches import browser_use_deferred_screenshot_patch as patch_mod

pytestmark = pytest.mark.unit


def _library_read(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    original = AsyncMock(return_value="state")
    monkeypatch.setattr(patch_mod, "_original_get_browser_state_summary", original)
    return original


async def _state_read(monkeypatch: pytest.MonkeyPatch, session: BrowserSession) -> dict[str, Any]:
    original = _library_read(monkeypatch)
    await patch_mod._get_browser_state_summary(session, include_screenshot=True, cached=True)
    assert original.await_args.args == (session,)
    kwargs: dict[str, Any] = original.await_args.kwargs
    return kwargs


async def test_a_registered_session_reads_state_without_a_screenshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = BrowserSession()
    patch_mod.defer_screenshots_for(session)

    kwargs = await _state_read(monkeypatch, session)

    assert kwargs["include_screenshot"] is False
    assert kwargs["cached"] is True


async def test_an_unregistered_session_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = await _state_read(monkeypatch, BrowserSession())

    assert kwargs["include_screenshot"] is True


async def test_an_unregistered_sessions_read_keeps_browser_uses_own_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wrapper replaces the library method, so every other caller relies on its defaults."""
    defaults = {
        name: param.default
        for name, param in inspect.signature(
            patch_mod._original_get_browser_state_summary
        ).parameters.items()
        if param.default is not inspect.Parameter.empty
    }
    original = _library_read(monkeypatch)

    await patch_mod._get_browser_state_summary(BrowserSession())

    assert original.await_args.kwargs == defaults


async def test_recent_events_are_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    original = _library_read(monkeypatch)

    await patch_mod._get_browser_state_summary(BrowserSession(), include_recent_events=True)

    assert original.await_args.kwargs["include_recent_events"] is True


def test_a_session_that_is_gone_leaves_no_registration_behind() -> None:
    """Every run registers its session; without the weak callback the registry grows forever."""
    session = BrowserSession()
    key = id(session)
    patch_mod.defer_screenshots_for(session)

    del session
    gc.collect()

    assert key not in patch_mod._deferred


def test_apply_routes_every_state_read_through_the_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(BrowserSession, "get_browser_state_summary", None)

    patch_mod.apply()

    assert BrowserSession.get_browser_state_summary is patch_mod._get_browser_state_summary
