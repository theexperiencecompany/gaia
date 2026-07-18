"""Tests for the browser_task tool — gating, concurrency, wiring."""

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
    monkeypatch.setattr(tool_mod, "get_profile_id", AsyncMock(return_value=None))
    monkeypatch.setattr(tool_mod, "save_profile_id", AsyncMock())
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_ENABLED", True)

    @asynccontextmanager
    async def _slot():
        yield

    monkeypatch.setattr(tool_mod, "session_slot", _slot)


def _patch_runner(monkeypatch, result: BrowserResultSnapshot):
    fake_session = MagicMock(session_id="s1", live_view_url="http://v", profile_id=None)  # NOSONAR

    @asynccontextmanager
    async def _fake_session(**kwargs):
        yield fake_session

    monkeypatch.setattr(tool_mod, "steel_session", _fake_session)
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
    assert out == "Booked the table."
    runner.run.assert_awaited_once()


async def test_concurrency_limit_returns_message(monkeypatch):
    monkeypatch.setattr(tool_mod, "build_browser_llm", lambda: object())

    class _FullSlot:
        async def __aenter__(self) -> None:
            raise BrowserConcurrencyLimit("Too many browser tasks are running right now.")

        async def __aexit__(self, *exc: object) -> bool:
            return False

    monkeypatch.setattr(tool_mod, "session_slot", lambda: _FullSlot())
    out = await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)
    assert "too many browser tasks" in out.lower()


async def test_profile_saved_on_success(monkeypatch):
    _patch_runner(
        monkeypatch,
        BrowserResultSnapshot(status=BrowserSessionStatus.COMPLETED, success=True, summary="done"),
    )
    # session has a profile_id and the start_url gives a domain → persist it.
    fake_session = MagicMock(
        session_id="s1",
        live_view_url="http://v",  # NOSONAR
        profile_id="prof-1",
    )

    @asynccontextmanager
    async def _sess(**kwargs):
        yield fake_session

    monkeypatch.setattr(tool_mod, "steel_session", _sess)
    save = AsyncMock()
    monkeypatch.setattr(tool_mod, "save_profile_id", save)

    await browser_task.ainvoke(
        {"task": "log in", "start_url": "https://example.com/login"}, config=UI_CONFIG
    )
    save.assert_awaited_once()
    assert save.await_args.args[1] == "example.com"
