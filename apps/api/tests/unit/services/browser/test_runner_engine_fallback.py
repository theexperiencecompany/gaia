"""A run whose own page connection stops answering moves to the fallback engine in seconds, and counts on."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar
from unittest.mock import AsyncMock

import pytest

from app.constants.browser import (
    BROWSER_ENGINE_FALLBACK_NOTE,
    BROWSER_ENGINE_FALLBACK_WITHOUT_STATE_NOTE,
    BROWSER_ENGINE_SWITCH_ACK,
    EngineSwitchReason,
)
from app.schemas.browser import BrowserSessionStatus
from app.services.analytics_service import AnalyticsEvents
from app.services.browser import engine_watchdog, runner as runner_mod
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.run_contract import BrowserRunConfig, RunOutcome, StepFrame
from app.services.browser.runner import BrowserRunnerCallbacks, BrowserTaskRunner
from app.services.browser.session import BrowserHostSession
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

_WEDGED_ON = "https://en.wikipedia.org/wiki/Chile"


def _session(session_id: str) -> BrowserHostSession:
    return BrowserHostSession(
        session_id=session_id,
        cdp_url=f"ws://{session_id}",
        live_view_url=f"http://{session_id}/live",
        context_id="ctx",
        host_url=f"http://{session_id}-host",
    )


class _WedgedThenFine:
    """Browser-Use on each engine in turn: the primary's page wedges its connection after two steps."""

    made: ClassVar[list[_WedgedThenFine]] = []

    def __init__(
        self, *, session: BrowserHostSession, hooks: Any, steps_before: int, **_: Any
    ) -> None:
        self.session = session
        self.hooks = hooks
        self.steps_before = steps_before
        self.last_url: str | None = _WEDGED_ON
        self.abandoned = False
        type(self).made.append(self)

    @property
    def _primary(self) -> bool:
        return type(self).made[0] is self

    async def execute(self, task: str) -> RunOutcome:
        if not self._primary:
            return RunOutcome(success=True, summary="Oslo, Santiago, Nairobi")
        for index in (1, 2):
            self.hooks.step(
                StepFrame(
                    index=index,
                    session_id=self.session.session_id,
                    goal="open the next article",
                    actions=[],
                    url=_WEDGED_ON,
                    title=None,
                    raw_screenshot=None,
                    since_prev_ms=0,
                )
            )
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def connection_answers(self) -> bool:
        return not self._primary

    async def abandon(self) -> None:
        self.abandoned = True

    def stop(self) -> None:
        return None


@pytest.fixture
def two_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    _WedgedThenFine.made = []
    monkeypatch.setattr(runner_mod, "BrowserAgentRun", _WedgedThenFine)
    monkeypatch.setattr(engine_watchdog, "BROWSER_ENGINE_WATCH_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(engine_watchdog, "BROWSER_ENGINE_WATCH_CANCEL_GRACE_SECONDS", 0.1)

    async def _engine_answers_the_host(session: BrowserHostSession) -> None:
        return None

    monkeypatch.setattr(engine_watchdog, "engine_failure", _engine_answers_the_host)


async def test_a_page_that_wedges_its_own_connection_moves_the_run_to_the_fallback_and_counts_on(
    two_engines: None,
) -> None:
    fallback = _session("s-fallback")
    open_fallback = AsyncMock(return_value=fallback)
    note = AsyncMock()
    runner = BrowserTaskRunner(
        session=_session("s-primary"),
        callbacks=BrowserRunnerCallbacks(
            emit=AsyncMock(),
            request_handoff=AsyncMock(),
            is_cancelled=AsyncMock(return_value=False),
            user_waiting=AsyncMock(return_value=False),
            take_user_messages=AsyncMock(return_value=[]),
            note=note,
            open_fallback_session=open_fallback,
        ),
        config=BrowserRunConfig(
            max_steps=10,
            max_actions_per_step=5,
            task_timeout_seconds=30,
            step_timeout_seconds=180,
            handoff_timeout_seconds=0,
            stream_screenshots=False,
            solve_captcha=False,
        ),
        secrets=RunSecrets({}, []),
    )

    result = await asyncio.wait_for(runner.run("capitals of Norway, Chile and Kenya"), timeout=5)

    primary, on_fallback = _WedgedThenFine.made
    assert primary.abandoned is True
    # Resumed on the page the run was on; the engine that failed has no live state to give.
    open_fallback.assert_awaited_once_with(_WEDGED_ON, None)
    note.assert_awaited_once_with(BROWSER_ENGINE_FALLBACK_WITHOUT_STATE_NOTE)
    assert (on_fallback.session, on_fallback.steps_before) == (fallback, 2)
    assert runner.used_fallback is True
    assert (result.status, result.success, result.summary) == (
        BrowserSessionStatus.COMPLETED,
        True,
        "Oslo, Santiago, Nairobi",
    )


class _SwitchesThenFine(_WedgedThenFine):
    """The primary's agent finds a page the fast engine renders wrong and asks for the full browser."""

    async def execute(self, task: str) -> RunOutcome:
        if not self._primary:
            self.offered_switch = self.hooks.switch_engine is not None
            return RunOutcome(success=True, summary="Signed in; the dashboard shows 3 invoices")
        self.hooks.step(
            StepFrame(
                index=1,
                session_id=self.session.session_id,
                goal="open the dashboard",
                actions=[],
                url=_BROKEN,
                title=None,
                raw_screenshot=None,
                since_prev_ms=0,
            )
        )
        self.answer = await self.hooks.switch_engine(EngineSwitchReason.STAYS_EMPTY, _BROKEN)
        # Browser-Use's run returns, not done, once the switch stopped it.
        return RunOutcome(success=False, summary="")


_BROKEN = "https://app.example.test/dashboard?user=someone%40example.test"


async def test_an_agent_that_finds_the_fast_engine_broken_moves_to_chrome_still_signed_in(
    two_engines: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_mod, "BrowserAgentRun", _SwitchesThenFine)
    primary_session = _session("s-primary")
    carried = object()
    read_from: list[BrowserHostSession] = []

    async def _hand_over(session: BrowserHostSession) -> object:
        read_from.append(session)
        return carried

    monkeypatch.setattr(runner_mod, "hand_over_state", _hand_over)
    captured: list[tuple[Any, ...]] = []
    monkeypatch.setattr(runner_mod, "capture_event", lambda *args: captured.append(args))
    open_fallback = AsyncMock(return_value=_session("s-fallback"))
    note = AsyncMock()
    runner = BrowserTaskRunner(
        session=primary_session,
        callbacks=BrowserRunnerCallbacks(
            emit=AsyncMock(),
            request_handoff=AsyncMock(),
            is_cancelled=AsyncMock(return_value=False),
            user_waiting=AsyncMock(return_value=False),
            take_user_messages=AsyncMock(return_value=[]),
            note=note,
            open_fallback_session=open_fallback,
        ),
        config=BrowserRunConfig(
            max_steps=10,
            max_actions_per_step=5,
            task_timeout_seconds=30,
            step_timeout_seconds=180,
            handoff_timeout_seconds=0,
            stream_screenshots=False,
            solve_captcha=False,
        ),
        secrets=RunSecrets({}, []),
        user_id="user-1",
    )

    async with captured_wide_event() as event:
        result = await asyncio.wait_for(runner.run("count my invoices"), timeout=5)

    primary, on_fallback = _WedgedThenFine.made
    assert primary.answer == BROWSER_ENGINE_SWITCH_ACK
    # The fast engine still answers: its live logins come along, and the user is told so.
    assert read_from == [primary_session]
    open_fallback.assert_awaited_once_with(_WEDGED_ON, carried)
    note.assert_awaited_once_with(BROWSER_ENGINE_FALLBACK_NOTE)
    assert (on_fallback.steps_before, on_fallback.offered_switch) == (1, False)
    assert (result.success, result.summary) == (True, "Signed in; the dashboard shows 3 invoices")
    # Which sites the fast engine fails, by host only: never the page or who opened it.
    [(user_id, name, props)] = captured
    assert (user_id, name) == ("user-1", AnalyticsEvents.BROWSER_ENGINE_SWITCHED)
    assert props == {"reason": "stays_empty", "host": "app.example.test", "engine": "obscura"}
    assert (event["browser"]["engine_switch"], event["browser"]["engine_switch_host"]) == (
        "stays_empty",
        "app.example.test",
    )
