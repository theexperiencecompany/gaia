"""Tests for BrowserTaskRunner — progress, the agent-driven handoff, cancel, timeout.

Browser-Use is faked so the tests exercise the runner's orchestration without a
real browser: a scripted FakeAgent invokes the runner's step callback exactly as
Browser-Use does (after the model picks actions, before they execute). The runner
no longer judges sensitivity itself — the agent hands off for itself by calling
``_handle_takeover`` (the ``request_human_takeover`` / ``solve_captcha_with_help``
actions), which is what the takeover tests below exercise directly.
"""

import asyncio
from typing import ClassVar
from unittest.mock import AsyncMock

import browser_use
import pytest

from app.constants.browser import BrowserEventKind, BrowserSessionStatus, HandoffStatus
from app.schemas.browser import HandoffOutcome
from app.services.browser import runner as runner_mod
from app.services.browser.runner import BrowserTaskRunner
from app.services.browser.session import BrowserHostSession


class _Action:
    def __init__(self, name: str, params: dict):
        self._name = name
        self._params = params

    def model_dump(self, exclude_none: bool = False):
        return {self._name: self._params}


class _Output:
    def __init__(self, goal: str, actions: list[_Action]):
        self.next_goal = goal
        self.thinking = goal
        self.action = actions


class _State:
    def __init__(self, url: str):
        self.url = url
        self.title = "Page"
        self.screenshot = "ZmFrZQ=="


class _History:
    def __init__(self, done=True, successful=True, result="Done.", usage=None):
        self._done, self._successful, self._result = done, successful, result
        self.usage = usage

    def final_result(self):
        return self._result

    def is_done(self):
        return self._done

    def is_successful(self):
        return self._successful


class FakeAgent:
    script: ClassVar[list[dict]] = []
    history = _History()

    def __init__(self, **kwargs):
        self._on_step = kwargs["register_new_step_callback"]
        self._should_stop = kwargs["register_should_stop_callback"]
        self.stopped = False
        self.executed: list[str] = []

    def stop(self):
        self.stopped = True

    async def run(self, max_steps: int):
        for i, step in enumerate(type(self).script, start=1):
            if await self._should_stop() or self.stopped:
                break
            output = _Output(step["goal"], [_Action(n, p) for n, p in step["actions"]])
            await self._on_step(_State(step.get("url", "https://x")), output, i)
            if self.stopped:
                break
            self.executed.append(step["goal"])
        return type(self).history


@pytest.fixture
def patch_browser(monkeypatch):
    monkeypatch.setattr(browser_use, "Agent", FakeAgent)
    # The runner constructs a Browser over CDP; the fake needs an awaitable stub.
    monkeypatch.setattr(browser_use, "Browser", lambda **kwargs: AsyncMock())
    # CDN off by default → screenshots fall back to inline data URLs.
    monkeypatch.setattr(runner_mod, "upload_step_screenshot", AsyncMock(return_value=None))
    FakeAgent.script = []
    FakeAgent.history = _History()


def _session() -> BrowserHostSession:
    return BrowserHostSession(
        session_id="s1",
        cdp_url="ws://x",  # NOSONAR
        live_view_url="http://v",  # NOSONAR
        context_id="ctx-1",
    )


def _make_runner(*, emit, request_handoff=None, is_cancelled=None, task_timeout=30):
    return BrowserTaskRunner(
        session=_session(),
        conversation_id="c1",
        llm=object(),
        emit=emit,
        request_handoff=request_handoff
        or AsyncMock(return_value=HandoffOutcome(status=HandoffStatus.COMPLETED)),
        is_cancelled=is_cancelled or AsyncMock(return_value=False),
        max_steps=10,
        max_actions_per_step=5,
        task_timeout_seconds=task_timeout,
        step_timeout_seconds=180,
        # 0 so the wall-clock stays equal to task_timeout in these tests (the real
        # runner adds a per-handoff allowance on top).
        handoff_timeout_seconds=0,
        stream_screenshots=True,
        use_vision=True,
        solve_captcha=False,
    )


def _collector():
    events: list = []

    async def emit(snapshot):
        events.append(snapshot)

    return events, emit


async def test_takeover_completed_lets_agent_continue():
    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        request_handoff=AsyncMock(return_value=HandoffOutcome(status=HandoffStatus.COMPLETED)),
    )
    out = await runner._handle_takeover("Enter your card", "payment")
    assert "verify" in out.lower() or "continue" in out.lower()
    assert runner._handed_off is True
    assert runner._stopped is False


async def test_takeover_cancelled_stops_run():
    from app.services.browser.exceptions import BrowserHandoffCancelled

    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        request_handoff=AsyncMock(return_value=HandoffOutcome(status=HandoffStatus.CANCELLED)),
    )
    with pytest.raises(BrowserHandoffCancelled):
        await runner._handle_takeover("Enter your card", "payment")
    assert runner._stopped is True
    assert runner._handed_off is False


async def test_takeover_bounded_by_max_handoffs():
    from app.constants.browser import MAX_HANDOFFS_PER_TASK
    from app.services.browser.exceptions import BrowserHandoffCancelled

    _, emit = _collector()
    runner = _make_runner(
        emit=emit,
        request_handoff=AsyncMock(return_value=HandoffOutcome(status=HandoffStatus.COMPLETED)),
    )
    for _ in range(MAX_HANDOFFS_PER_TASK):
        await runner._handle_takeover("step", "none")
    with pytest.raises(BrowserHandoffCancelled):
        await runner._handle_takeover("one too many", "none")


async def test_happy_path_emits_steps_and_result(patch_browser):
    FakeAgent.script = [
        {"goal": "Open site", "actions": [("navigate", {"url": "x"})]},
        {"goal": "Read results", "actions": [("extract", {})]},
    ]
    events, emit = _collector()
    result = await _make_runner(emit=emit).run("do a thing")

    kinds = [e.kind for e in events]
    assert kinds.count(BrowserEventKind.STEP) == 2
    assert kinds[0] == BrowserEventKind.SESSION
    assert result.status == BrowserSessionStatus.COMPLETED
    step = next(e for e in events if e.kind == BrowserEventKind.STEP)
    assert step.screenshot.startswith("data:image/png;base64,")


async def test_screenshot_uses_cdn_url_when_available(patch_browser, monkeypatch):
    monkeypatch.setattr(
        runner_mod,
        "upload_step_screenshot",
        AsyncMock(return_value="https://cdn.example.com/browser_steps/c1/step_1.png?sig=abc"),
    )
    FakeAgent.script = [{"goal": "Open", "actions": [("navigate", {"url": "x"})]}]
    events, emit = _collector()
    await _make_runner(emit=emit).run("x")

    step = next(e for e in events if e.kind == BrowserEventKind.STEP)
    assert step.screenshot.startswith("https://cdn.example.com/")


async def test_cancellation_stops_run(patch_browser):
    FakeAgent.script = [{"goal": "step", "actions": [("navigate", {})]}]
    events, emit = _collector()
    result = await _make_runner(emit=emit, is_cancelled=AsyncMock(return_value=True)).run("x")
    assert result.status == BrowserSessionStatus.CANCELLED


async def test_timeout_marks_failed(patch_browser, monkeypatch):
    async def _slow_run(self, max_steps):
        await asyncio.sleep(1)
        return _History()

    monkeypatch.setattr(FakeAgent, "run", _slow_run)
    events, emit = _collector()
    result = await _make_runner(emit=emit, task_timeout=0.01).run("x")
    assert result.status == BrowserSessionStatus.FAILED
    assert "timed out" in result.summary


async def test_unexpected_agent_error_finishes_failed(patch_browser, monkeypatch):
    """An unexpected runtime failure must not leave the card stuck in RUNNING.

    A terminal FAILED result is emitted so the UI resolves and the user gets an
    honest summary instead of a forever-spinning progress card.
    """

    async def _boom(self, max_steps: int):
        raise RuntimeError("LLM provider exploded")

    monkeypatch.setattr(FakeAgent, "run", _boom)
    events, emit = _collector()
    result = await _make_runner(emit=emit).run("do a thing")
    assert result.status == BrowserSessionStatus.FAILED
    assert "failed" in result.summary.lower()
    # The result snapshot ends the run — the card never stays in RUNNING.
    assert events[-1].kind == BrowserEventKind.RESULT
    assert events[-1].status == BrowserSessionStatus.FAILED
