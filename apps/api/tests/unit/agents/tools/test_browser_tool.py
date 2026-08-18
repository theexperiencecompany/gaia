"""Tests for the browser_task tool — gating, capacity, wiring, delivery resilience."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

from langchain_core.runnables.config import RunnableConfig
import pytest

from app.agents.tools import browser_tool as tool_mod
from app.agents.tools.browser_tool import browser_task
from app.constants.browser import BrowserSessionStatus
from app.schemas.browser import BrowserResultSnapshot, BrowserStepSnapshot
from app.services.browser.exceptions import BrowserConcurrencyLimit, BrowserUnavailableError

UI_CONFIG: RunnableConfig = {
    "configurable": {"user_id": "u1", "thread_id": "c1", "stream_id": "s1", "source_category": "ui"}
}
BOT_CONFIG: RunnableConfig = {
    "configurable": {
        "user_id": "u1",
        "conversation_id": "c1",
        "stream_id": "s1",
        "source_category": "bot",
        "conversation_source": "discord",
    }
}

EmitFn = Callable[[object], Awaitable[None]]


@pytest.fixture(autouse=True)
def base_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_mod, "get_stream_writer", lambda: lambda payload: None)
    monkeypatch.setattr(tool_mod.stream_manager, "is_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr(tool_mod, "create_pending_handoff", AsyncMock())
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_ENABLED", True)


def _patch_runner(monkeypatch: pytest.MonkeyPatch, result: BrowserResultSnapshot) -> MagicMock:
    fake_session = MagicMock(
        session_id="s1",
        cdp_url="ws://x",  # NOSONAR
        live_view_url="http://v",  # NOSONAR
        context_id="ctx-1",
    )

    @asynccontextmanager
    async def _fake_session(**kwargs: object) -> AsyncIterator[MagicMock]:
        yield fake_session

    monkeypatch.setattr(tool_mod, "browser_session", _fake_session)
    monkeypatch.setattr(tool_mod, "build_browser_llm", lambda: object())
    runner = MagicMock()
    runner.run = AsyncMock(return_value=result)
    monkeypatch.setattr(tool_mod, "BrowserTaskRunner", MagicMock(return_value=runner))
    return runner


async def test_disabled_returns_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_ENABLED", False)
    out = await browser_task.ainvoke({"task": "do it"}, config=UI_CONFIG)
    assert "disabled" in out.lower()


async def test_llm_unavailable_returns_clean_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tool_mod, "build_browser_llm", MagicMock(side_effect=BrowserUnavailableError("no key"))
    )
    out = await browser_task.ainvoke({"task": "do it"}, config=UI_CONFIG)
    assert "can't use the browser" in out.lower()


async def test_happy_path_runs_and_returns_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


async def test_capacity_limit_returns_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_mod, "build_browser_llm", lambda: object())

    @asynccontextmanager
    async def _at_capacity(**kwargs: object) -> AsyncIterator[MagicMock]:
        raise BrowserConcurrencyLimit("The browser host is at capacity; try again shortly.")
        yield MagicMock()  # pragma: no cover — never reached

    monkeypatch.setattr(tool_mod, "browser_session", _at_capacity)
    out = await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)
    assert "at capacity" in out.lower()


async def test_bot_delivery_outage_does_not_abort_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A messaging/platform outage must never kill the in-flight browser run.

    The web card is already on the SSE stream before the bot mirror runs, so a
    failing platform delivery is logged and skipped — the tool still returns the
    result summary instead of surfacing a delivery exception.
    """

    class _FailingDelivery:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def session(self, snapshot: object) -> None:
            raise RuntimeError("rabbitmq down")

        async def step(self, snapshot: object) -> None:
            raise RuntimeError("rabbitmq down")

        async def handoff(self, snapshot: object) -> None:
            raise RuntimeError("rabbitmq down")

        async def result(self, snapshot: object) -> None:
            raise RuntimeError("rabbitmq down")

    class _Runner:
        def __init__(self, *, emit: EmitFn, **kwargs: object) -> None:
            self._emit = emit

        async def run(self, task: str) -> BrowserResultSnapshot:
            await self._emit(
                BrowserStepSnapshot(
                    index=1, goal="g", action="a", url="https://x", title="t", screenshot=None
                )
            )
            await self._emit(
                BrowserResultSnapshot(
                    status=BrowserSessionStatus.COMPLETED, success=True, summary="Done it."
                )
            )
            return BrowserResultSnapshot(
                status=BrowserSessionStatus.COMPLETED, success=True, summary="Done it."
            )

    monkeypatch.setattr(tool_mod, "BotProgressDelivery", _FailingDelivery)
    monkeypatch.setattr(tool_mod, "BrowserTaskRunner", _Runner)
    monkeypatch.setattr(tool_mod, "build_browser_llm", lambda: object())

    fake_session = MagicMock(
        session_id="s1",
        cdp_url="ws://x",  # NOSONAR
        live_view_url="http://v",  # NOSONAR
        context_id="ctx-1",
    )

    @asynccontextmanager
    async def _fake_session(**kwargs: object) -> AsyncIterator[MagicMock]:
        yield fake_session

    monkeypatch.setattr(tool_mod, "browser_session", _fake_session)

    out = await browser_task.ainvoke({"task": "do it"}, config=BOT_CONFIG)
    assert "Done it." in out
