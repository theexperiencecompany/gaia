"""Tests for BrowserTaskRunner — progress, the mid-run handoff, cancel, timeout.

Browser-Use is faked so the tests exercise the runner's orchestration without a
real browser: a scripted FakeAgent invokes the runner's step callback exactly as
Browser-Use does (after the model picks actions, before they execute).
"""

import asyncio
from unittest.mock import AsyncMock

import browser_use
import pytest

from app.constants.browser import BrowserEventKind, BrowserSessionStatus, HandoffStatus
from app.schemas.browser import SensitiveActionVerdict
from app.services.browser import runner as runner_mod
from app.services.browser.runner import BrowserTaskRunner
from app.services.browser.session import SteelBrowserSession


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
    def __init__(self, done=True, successful=True, result="Done."):
        self._done, self._successful, self._result = done, successful, result

    def final_result(self):
        return self._result

    def is_done(self):
        return self._done

    def is_successful(self):
        return self._successful


class FakeAgent:
    script: list[dict] = []
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
    from unittest.mock import AsyncMock

    monkeypatch.setattr(browser_use, "Agent", FakeAgent)
    monkeypatch.setattr(browser_use, "Browser", lambda **kwargs: object())
    # CDN off by default → screenshots fall back to inline data URLs.
    monkeypatch.setattr(runner_mod, "upload_step_screenshot", AsyncMock(return_value=None))
    FakeAgent.script = []
    FakeAgent.history = _History()


def _session() -> SteelBrowserSession:
    return SteelBrowserSession(
        session_id="s1",
        cdp_url="ws://x",  # NOSONAR
        debug_url=None,
        live_view_url="http://v",  # NOSONAR
        profile_id=None,
    )


def _make_runner(*, emit, request_handoff=None, is_cancelled=None, task_timeout=30):
    return BrowserTaskRunner(
        session=_session(),
        conversation_id="c1",
        llm=object(),
        emit=emit,
        request_handoff=request_handoff or AsyncMock(return_value=HandoffStatus.COMPLETED),
        is_cancelled=is_cancelled or AsyncMock(return_value=False),
        max_steps=10,
        max_actions_per_step=5,
        task_timeout_seconds=task_timeout,
        stream_screenshots=True,
        use_vision=True,
        solve_captcha=False,
    )


def _collector():
    events: list = []

    async def emit(snapshot):
        events.append(snapshot)

    return events, emit


def _safe(monkeypatch):
    monkeypatch.setattr(
        runner_mod,
        "classify_step",
        AsyncMock(return_value=SensitiveActionVerdict(requires_approval=False)),
    )


def _sensitive(monkeypatch, category):
    monkeypatch.setattr(
        runner_mod,
        "classify_step",
        AsyncMock(return_value=SensitiveActionVerdict(requires_approval=True, category=category)),
    )


async def test_takeover_completed_lets_agent_continue():
    from unittest.mock import AsyncMock

    _, emit = _collector()
    runner = _make_runner(
        emit=emit, request_handoff=AsyncMock(return_value=HandoffStatus.COMPLETED)
    )
    out = await runner._handle_takeover("Enter your card", "payment")
    assert "continue" in out.lower()
    assert runner._handed_off is True
    assert runner._stopped is False


async def test_takeover_cancelled_stops_run():
    from unittest.mock import AsyncMock

    from app.services.browser.exceptions import BrowserHandoffCancelled

    _, emit = _collector()
    runner = _make_runner(
        emit=emit, request_handoff=AsyncMock(return_value=HandoffStatus.CANCELLED)
    )
    with pytest.raises(BrowserHandoffCancelled):
        await runner._handle_takeover("Enter your card", "payment")
    assert runner._stopped is True
    assert runner._handed_off is False


async def test_takeover_bounded_by_max_handoffs():
    from unittest.mock import AsyncMock

    from app.constants.browser import MAX_HANDOFFS_PER_TASK
    from app.services.browser.exceptions import BrowserHandoffCancelled

    _, emit = _collector()
    runner = _make_runner(
        emit=emit, request_handoff=AsyncMock(return_value=HandoffStatus.COMPLETED)
    )
    for _ in range(MAX_HANDOFFS_PER_TASK):
        await runner._handle_takeover("step", "none")
    with pytest.raises(BrowserHandoffCancelled):
        await runner._handle_takeover("one too many", "none")


async def test_happy_path_emits_steps_and_result(patch_browser, monkeypatch):
    _safe(monkeypatch)
    FakeAgent.script = [
        {"goal": "Open site", "actions": [("go_to_url", {"url": "x"})]},
        {"goal": "Read results", "actions": [("extract_content", {})]},
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
    from unittest.mock import AsyncMock

    _safe(monkeypatch)
    monkeypatch.setattr(
        runner_mod,
        "upload_step_screenshot",
        AsyncMock(return_value="https://cdn.example.com/browser_steps/c1/step_1.png?sig=abc"),
    )
    FakeAgent.script = [{"goal": "Open", "actions": [("go_to_url", {"url": "x"})]}]
    events, emit = _collector()
    await _make_runner(emit=emit).run("x")

    step = next(e for e in events if e.kind == BrowserEventKind.STEP)
    assert step.screenshot.startswith("https://cdn.example.com/")


async def test_handoff_completed_marks_completed(patch_browser, monkeypatch):
    from app.constants.browser import HandoffStrategy, SensitiveCategory

    _sensitive(monkeypatch, SensitiveCategory.PAYMENT)
    monkeypatch.setattr(
        runner_mod,
        "resolve_strategy",
        lambda cat, autonomous_override=None: HandoffStrategy.HANDOFF,
    )
    FakeAgent.script = [{"goal": "Confirm & Pay", "actions": [("click_element", {"text": "Pay"})]}]
    events, emit = _collector()
    handoff = AsyncMock(return_value=HandoffStatus.COMPLETED)

    runner = _make_runner(emit=emit, request_handoff=handoff)
    result = await runner.run("pay")
    handoff.assert_awaited_once()
    assert result.status == BrowserSessionStatus.COMPLETED
    # The agent never executed the sensitive action itself.
    assert runner._agent.executed == []


async def test_handoff_cancelled_marks_cancelled(patch_browser, monkeypatch):
    from app.constants.browser import HandoffStrategy, SensitiveCategory

    _sensitive(monkeypatch, SensitiveCategory.PAYMENT)
    monkeypatch.setattr(
        runner_mod,
        "resolve_strategy",
        lambda cat, autonomous_override=None: HandoffStrategy.HANDOFF,
    )
    FakeAgent.script = [{"goal": "Confirm & Pay", "actions": [("click_element", {"text": "Pay"})]}]
    events, emit = _collector()
    handoff = AsyncMock(return_value=HandoffStatus.CANCELLED)

    runner = _make_runner(emit=emit, request_handoff=handoff)
    result = await runner.run("pay")
    assert result.status == BrowserSessionStatus.CANCELLED
    assert runner._agent.executed == []


async def test_proceed_strategy_runs_action(patch_browser, monkeypatch):
    from app.constants.browser import HandoffStrategy, SensitiveCategory

    _sensitive(monkeypatch, SensitiveCategory.PAYMENT)
    monkeypatch.setattr(
        runner_mod,
        "resolve_strategy",
        lambda cat, autonomous_override=None: HandoffStrategy.PROCEED,
    )
    FakeAgent.script = [{"goal": "Pay with agent card", "actions": [("click_element", {})]}]
    events, emit = _collector()
    handoff = AsyncMock()

    runner = _make_runner(emit=emit, request_handoff=handoff)
    result = await runner.run("pay")
    handoff.assert_not_awaited()  # autonomous — no handoff
    assert runner._agent.executed == ["Pay with agent card"]
    assert result.status == BrowserSessionStatus.COMPLETED


async def test_cancellation_stops_run(patch_browser, monkeypatch):
    _safe(monkeypatch)
    FakeAgent.script = [{"goal": "step", "actions": [("go_to_url", {})]}]
    events, emit = _collector()
    result = await _make_runner(emit=emit, is_cancelled=AsyncMock(return_value=True)).run("x")
    assert result.status == BrowserSessionStatus.CANCELLED


async def test_timeout_marks_failed(patch_browser, monkeypatch):
    _safe(monkeypatch)

    async def _slow_run(self, max_steps):
        await asyncio.sleep(1)
        return _History()

    monkeypatch.setattr(FakeAgent, "run", _slow_run)
    events, emit = _collector()
    result = await _make_runner(emit=emit, task_timeout=0.01).run("x")
    assert result.status == BrowserSessionStatus.FAILED
    assert "timed out" in result.summary
