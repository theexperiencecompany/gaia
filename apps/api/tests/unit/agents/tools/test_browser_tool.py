"""Tests for the browser_task tool — gating, capacity, wiring."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.tools import browser_tool as tool_mod
from app.agents.tools.browser_tool import browser_task
from app.constants.browser import BrowserSessionStatus
from app.schemas.browser import BrowserResultSnapshot
from app.services.browser.exceptions import BrowserConcurrencyLimit, BrowserUnavailableError

UI_CONFIG = {
    "configurable": {"user_id": "u1", "thread_id": "c1", "stream_id": "s1", "source_category": "ui"}
}


@pytest.fixture(autouse=True)
def base_patches(monkeypatch):
    monkeypatch.setattr(tool_mod, "get_stream_writer", lambda: lambda payload: None)
    monkeypatch.setattr(tool_mod.stream_manager, "is_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr(tool_mod, "create_pending_handoff", AsyncMock())
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_ENABLED", True)


def _patch_runner(monkeypatch, result: BrowserResultSnapshot):
    fake_session = MagicMock(
        session_id="s1",
        cdp_url="ws://x",  # NOSONAR
        live_view_url="http://v",  # NOSONAR
        context_id="ctx-1",
    )

    @asynccontextmanager
    async def _fake_session(**kwargs):
        yield fake_session

    monkeypatch.setattr(tool_mod, "browser_session", _fake_session)
    monkeypatch.setattr(tool_mod, "build_browser_llm", lambda: object())
    runner = MagicMock()
    runner.run = AsyncMock(return_value=result)
    monkeypatch.setattr(tool_mod, "BrowserTaskRunner", MagicMock(return_value=runner))
    return runner


async def test_disabled_returns_message(monkeypatch):
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_ENABLED", False)
    out = await browser_task.ainvoke({"task": "do it"}, config=UI_CONFIG)
    assert "disabled" in out.lower()


async def test_llm_unavailable_returns_clean_message(monkeypatch):
    monkeypatch.setattr(
        tool_mod, "build_browser_llm", MagicMock(side_effect=BrowserUnavailableError("no key"))
    )
    out = await browser_task.ainvoke({"task": "do it"}, config=UI_CONFIG)
    assert "can't use the browser" in out.lower()


async def test_happy_path_runs_and_returns_summary(monkeypatch):
    runner = _patch_runner(
        monkeypatch,
        BrowserResultSnapshot(
            status=BrowserSessionStatus.COMPLETED, success=True, summary="Booked the table."
        ),
    )
    out = await browser_task.ainvoke({"task": "book a table"}, config=UI_CONFIG)
    # The tool returns the runner's summary wrapped in outcome-specific guidance,
    # so the assistant confirms a real result instead of narrating the mechanics.
    assert "Booked the table." in out
    assert "COMPLETED" in out
    runner.run.assert_awaited_once()


async def test_capacity_limit_returns_message(monkeypatch):
    monkeypatch.setattr(tool_mod, "build_browser_llm", lambda: object())

    @asynccontextmanager
    async def _at_capacity(**kwargs):
        raise BrowserConcurrencyLimit("The browser host is at capacity; try again shortly.")
        yield  # pragma: no cover — never reached

    monkeypatch.setattr(tool_mod, "browser_session", _at_capacity)
    out = await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)
    assert "at capacity" in out.lower()
