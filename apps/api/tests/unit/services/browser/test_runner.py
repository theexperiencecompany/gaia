"""The runner's invariants: budgets, handoff limits, the stall note, the recap, metering and engine moves.

The journeys through the whole job (cards on the stream, bot photos, handoff
notes, guidance, a dead engine's fallback, a login carried across engines) are
proven in tests/e2e/test_browser_task_background.py and are not repeated here.
Each test drives the real BrowserTaskRunner over a scripted agent run standing
in at the one seam the runner builds it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from typing import Any, ClassVar
from unittest.mock import AsyncMock

import pytest

from app.constants.browser import (
    BROWSER_ENGINE_FALLBACK_NOTE,
    BROWSER_ENGINE_FALLBACK_WITHOUT_STATE_NOTE,
    BROWSER_ENGINE_SWITCH_ACK,
    BROWSER_RUN_HANDOFF_TIMED_OUT,
    BROWSER_STALL_NOTE,
    HANDOFF_AUTORESOLVED_NOTE,
    MAX_HANDOFFS_PER_TASK,
    BrowserSessionStatus,
    EngineSwitchReason,
    HandoffStatus,
    SensitiveCategory,
)
from app.schemas.browser import (
    BrowserResultSnapshot,
    BrowserStepSnapshot,
    HandoffOutcome,
    HandoffRequest,
)
from app.services.analytics_service import AnalyticsEvents
from app.services.browser import engine_watchdog, runner as runner_mod
from app.services.browser.exceptions import BrowserHandoffCancelled, BrowserUnavailableError
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.ledger import CallComponent, ModelCall
from app.services.browser.run_contract import BrowserRunConfig, RunHooks, RunOutcome, StepFrame
from app.services.browser.runner import BrowserRunnerCallbacks, BrowserTaskRunner
from app.services.browser.session import BrowserHostSession
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

PAGE = "https://example.test/book"

#: What one scripted run does with the hooks the runner handed it.
Script = Callable[["_ScriptedRun"], Awaitable[RunOutcome]]


def _session(session_id: str = "s-primary") -> BrowserHostSession:
    return BrowserHostSession(
        session_id=session_id,
        cdp_url=f"ws://{session_id}",
        live_view_url=f"http://{session_id}/live",
        context_id="ctx",
        host_url=f"http://{session_id}-host",
    )


class _ScriptedRun:
    """Stands in for BrowserAgentRun: each run the runner builds plays the next script."""

    scripts: ClassVar[list[Script]] = []
    made: ClassVar[list[_ScriptedRun]] = []

    def __init__(
        self, *, session: BrowserHostSession, hooks: RunHooks, steps_before: int, **_: Any
    ) -> None:
        self.session = session
        self.hooks = hooks
        self.steps_before = steps_before
        self.last_url: str | None = PAGE
        self.abandoned = False
        self.stopped = False
        self.answers = True
        type(self).made.append(self)

    async def execute(self, task: str) -> RunOutcome:
        return await type(self).scripts[len(type(self).made) - 1](self)

    def step(self, index: int, screenshot: str | None = None) -> None:
        self.hooks.step(
            StepFrame(
                index=index,
                session_id=self.session.session_id,
                goal=f"step {index}",
                actions=[],
                url=PAGE,
                title=None,
                raw_screenshot=screenshot,
                since_prev_ms=0,
            )
        )

    async def connection_answers(self) -> bool:
        return self.answers

    async def abandon(self) -> None:
        self.abandoned = True

    def stop(self) -> None:
        self.stopped = True


async def _done(run: _ScriptedRun) -> RunOutcome:
    run.step(run.steps_before + 1)
    return RunOutcome(success=True, summary="booked")


@pytest.fixture(autouse=True)
def scripted(monkeypatch: pytest.MonkeyPatch) -> None:
    _ScriptedRun.scripts = []
    _ScriptedRun.made = []
    monkeypatch.setattr(runner_mod, "BrowserAgentRun", _ScriptedRun)
    monkeypatch.setattr(runner_mod, "get_budget_stop_reason", AsyncMock(return_value=None))
    monkeypatch.setattr(runner_mod, "create_replay_link", AsyncMock(return_value=None))
    monkeypatch.setattr(runner_mod, "record_llm_call", AsyncMock())
    monkeypatch.setattr(engine_watchdog, "BROWSER_ENGINE_WATCH_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(engine_watchdog, "BROWSER_ENGINE_WATCH_CANCEL_GRACE_SECONDS", 0.1)

    async def _host_says_live(session: BrowserHostSession) -> None:
        return None

    monkeypatch.setattr(engine_watchdog, "engine_failure", _host_says_live)
    monkeypatch.setattr(runner_mod, "engine_failure", _host_says_live)


def _runner(
    *scripts: Script,
    task_timeout: int = 30,
    stream_screenshots: bool = False,
    handoff: HandoffOutcome | None = None,
    fallback: bool = False,
    note: AsyncMock | None = None,
    user_id: str | None = "user-1",
) -> tuple[BrowserTaskRunner, dict[str, Any]]:
    _ScriptedRun.scripts = list(scripts)
    seen: dict[str, Any] = {"emitted": [], "handoffs": []}

    async def _emit(snapshot: object) -> None:
        seen["emitted"].append(snapshot)

    async def _request_handoff(
        request: HandoffRequest, session: BrowserHostSession
    ) -> HandoffOutcome:
        seen["handoffs"].append(request)
        return handoff or HandoffOutcome(status=HandoffStatus.COMPLETED)

    open_fallback = AsyncMock(return_value=_session("s-fallback"))
    seen["open_fallback"] = open_fallback
    runner = BrowserTaskRunner(
        session=_session(),
        callbacks=BrowserRunnerCallbacks(
            emit=_emit,
            request_handoff=_request_handoff,
            is_cancelled=AsyncMock(return_value=False),
            user_waiting=AsyncMock(return_value=False),
            take_user_messages=AsyncMock(return_value=[]),
            note=note,
            open_fallback_session=open_fallback if fallback else None,
        ),
        config=BrowserRunConfig(
            max_steps=10,
            max_actions_per_step=5,
            task_timeout_seconds=task_timeout,
            step_timeout_seconds=180,
            handoff_timeout_seconds=60,
            stream_screenshots=stream_screenshots,
            solve_captcha=False,
        ),
        secrets=RunSecrets({}, []),
        user_id=user_id,
    )
    return runner, seen


async def _run(runner: BrowserTaskRunner) -> BrowserResultSnapshot:
    return await asyncio.wait_for(runner.run("book a table"), timeout=5)


# ---------------------------------------------------------------------------
# Budgets: time spent waiting on the user is not work; the cost budget binds mid-run
# ---------------------------------------------------------------------------


async def test_time_waiting_on_the_user_does_not_count_against_the_work_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(runner_mod, "perf_counter", lambda: clock[0])

    async def _long_handoff(run: _ScriptedRun) -> RunOutcome:
        clock[0] += 5  # five seconds of work
        await run.hooks.takeover("Sign in and come back", "credentials")
        run.stop_after_wait = await run.hooks.should_stop()
        clock[0] += 30  # more work than the whole budget
        run.stop_after_work = await run.hooks.should_stop()
        return RunOutcome(success=True, summary="booked")

    runner, seen = _runner(_long_handoff, task_timeout=20)

    async def _slow_user(request: HandoffRequest, session: BrowserHostSession) -> HandoffOutcome:
        clock[0] += 600  # ten minutes signing in
        return HandoffOutcome(status=HandoffStatus.COMPLETED)

    runner._request_handoff = _slow_user

    result = await _run(runner)

    # Five seconds of work around a ten-minute wait is inside the budget; 35 is not.
    [run] = _ScriptedRun.made
    assert (run.stop_after_wait, run.stop_after_work) == (False, True)
    assert (result.status, result.summary) == (
        BrowserSessionStatus.FAILED,
        "Browser task timed out after 20s of work.",
    )


async def test_a_run_past_the_users_cost_budget_stops_with_that_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = type("_Check", (), {"stop_reason": "You've reached today's AI usage limit."})()
    monkeypatch.setattr(runner_mod, "get_budget_stop_reason", AsyncMock(return_value=stop))

    async def _checks(run: _ScriptedRun) -> RunOutcome:
        return RunOutcome(success=not await run.hooks.should_stop(), summary="")

    result = await _run(_runner(_checks)[0])

    assert (result.status, result.summary) == (
        BrowserSessionStatus.FAILED,
        "You've reached today's AI usage limit.",
    )


# ---------------------------------------------------------------------------
# Handoffs
# ---------------------------------------------------------------------------


async def test_the_handoff_past_the_limit_never_reaches_the_user() -> None:
    async def _asks_too_often(run: _ScriptedRun) -> RunOutcome:
        for _ in range(MAX_HANDOFFS_PER_TASK):
            await run.hooks.takeover("Enter the code", "credentials")
        with pytest.raises(BrowserHandoffCancelled):
            await run.hooks.takeover("Enter the code again", "credentials")
        return RunOutcome(success=False, summary="")

    runner, seen = _runner(_asks_too_often)

    await _run(runner)

    assert len(seen["handoffs"]) == MAX_HANDOFFS_PER_TASK


async def test_a_timed_out_handoff_fails_the_run_even_when_browser_use_swallows_the_cancel() -> (
    None
):
    async def _swallows(run: _ScriptedRun) -> RunOutcome:
        # Browser-Use turns the raise into an action error and runs on.
        with contextlib.suppress(BrowserHandoffCancelled):
            await run.hooks.takeover("Pay the deposit", "payment")
        return RunOutcome(success=True, summary="looks done")

    runner, _ = _runner(_swallows, handoff=HandoffOutcome(status=HandoffStatus.TIMEOUT))

    result = await _run(runner)

    assert (result.status, result.summary) == (
        BrowserSessionStatus.FAILED,
        BROWSER_RUN_HANDOFF_TIMED_OUT,
    )


async def test_the_auto_resolvers_resume_note_is_never_taken_for_a_users_instruction() -> None:
    async def _hands_over(run: _ScriptedRun) -> RunOutcome:
        run.note = await run.hooks.takeover("Sign in", "credentials")
        return RunOutcome(success=True, summary="booked")

    runner, _ = _runner(
        _hands_over,
        handoff=HandoffOutcome(status=HandoffStatus.COMPLETED, message=HANDOFF_AUTORESOLVED_NOTE),
    )

    result = await _run(runner)

    assert result.user_notes == []


async def test_an_unknown_takeover_category_is_treated_as_irreversible() -> None:
    async def _hands_over(run: _ScriptedRun) -> RunOutcome:
        await run.hooks.takeover("Confirm the order", "shipping")
        return RunOutcome(success=True, summary="ordered")

    runner, seen = _runner(_hands_over)

    await _run(runner)

    assert [request.category for request in seen["handoffs"]] == [SensitiveCategory.IRREVERSIBLE]


# ---------------------------------------------------------------------------
# The stall note: once per silence, re-armed by the next step, never during a wait
# ---------------------------------------------------------------------------


async def test_each_silence_gets_one_note_and_a_repeat_names_the_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_mod, "_STALL_POLL_SECONDS", 0.01)
    monkeypatch.setattr(runner_mod, "BROWSER_STALL_NOTE_AFTER_SECONDS", 0.05)

    async def _slow(run: _ScriptedRun) -> RunOutcome:
        run.step(1)
        await asyncio.sleep(0.3)
        run.step(2)
        await asyncio.sleep(0.3)
        return RunOutcome(success=True, summary="done")

    note = AsyncMock()
    await _run(_runner(_slow, note=note)[0])

    said = [call.args[0] for call in note.await_args_list]
    assert said[0] == BROWSER_STALL_NOTE
    assert len(said) == 2
    assert said[1].startswith("Still on step 2")


async def test_waiting_on_the_user_is_not_a_stall(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_mod, "_STALL_POLL_SECONDS", 0.01)
    monkeypatch.setattr(runner_mod, "BROWSER_STALL_NOTE_AFTER_SECONDS", 0.05)

    async def _hands_over(run: _ScriptedRun) -> RunOutcome:
        run.step(1)
        await run.hooks.takeover("Sign in", "credentials")
        return RunOutcome(success=True, summary="done")

    runner, _ = _runner(_hands_over, note=(note := AsyncMock()))

    async def _slow_user(request: HandoffRequest, session: BrowserHostSession) -> HandoffOutcome:
        await asyncio.sleep(0.3)
        return HandoffOutcome(status=HandoffStatus.COMPLETED)

    runner._request_handoff = _slow_user

    await _run(runner)

    note.assert_not_awaited()


# ---------------------------------------------------------------------------
# The recap and the metering
# ---------------------------------------------------------------------------


async def test_only_uploaded_frames_become_recap_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    uploads = iter(["https://cdn.test/1.png", None])

    async def _publish(image: bytes, session_id: str, index: int) -> str | None:
        return next(uploads)

    monkeypatch.setattr(runner_mod, "publish_step_screenshot", _publish)
    recap = AsyncMock(return_value="https://gaia.test/replay/r")
    monkeypatch.setattr(runner_mod, "create_replay_link", recap)

    async def _two_frames(run: _ScriptedRun) -> RunOutcome:
        run.step(1, screenshot="c2hvdA==")
        run.step(2, screenshot="c2hvdA==")
        return RunOutcome(success=True, summary="done")

    runner, seen = _runner(_two_frames, stream_screenshots=True)
    result = await _run(runner)

    steps = [card for card in seen["emitted"] if isinstance(card, BrowserStepSnapshot)]
    # The step whose upload failed still shows its photo inline, but a recap never promises it.
    assert steps[1].screenshot.startswith("data:image/png;base64,")
    recap.assert_awaited_once_with("s-primary", ["https://cdn.test/1.png"])
    assert result.replay_url == "https://gaia.test/replay/r"


async def test_each_model_call_is_charged_to_the_user_with_the_cost_the_gateway_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = AsyncMock()
    monkeypatch.setattr(runner_mod, "record_llm_call", record)
    runner, _ = _runner(_done, user_id="user-7")

    runner.ledger.add(
        ModelCall(
            component=CallComponent.JEV,
            provider="openrouter",
            model="~typesafe/jev",
            latency_ms=400,
            input_tokens=1500,
            output_tokens=12,
            cost_usd=0.0021,
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    [call] = record.await_args_list
    assert call.kwargs["user_id"] == "user-7"
    assert call.kwargs["model_name"] == "~typesafe/jev"
    assert (call.kwargs["usage"]["input_tokens"], call.kwargs["usage"]["output_tokens"]) == (
        1500,
        12,
    )
    assert call.kwargs["provider_cost"] == 0.0021
    assert call.kwargs["context"].charge_to_budget is True


# ---------------------------------------------------------------------------
# Failures that are not the task's
# ---------------------------------------------------------------------------


async def test_a_run_that_cannot_attach_over_cdp_says_the_browser_is_unreachable() -> None:
    async def _refused(run: _ScriptedRun) -> RunOutcome:
        raise ConnectionRefusedError("cdp refused")

    with pytest.raises(BrowserUnavailableError, match="Could not attach to the browser over CDP"):
        await _run(_runner(_refused)[0])


async def test_an_unexpected_failure_ends_failed_with_its_reason() -> None:
    async def _crashes(run: _ScriptedRun) -> RunOutcome:
        raise RuntimeError("history unreadable")

    result = await _run(_runner(_crashes)[0])

    assert result.status == BrowserSessionStatus.FAILED
    assert "history unreadable" in result.summary


# ---------------------------------------------------------------------------
# Moving engines: a wedged page, an agent that finds the fast engine broken
# ---------------------------------------------------------------------------


async def test_a_page_that_wedges_its_own_connection_moves_the_run_and_counts_on() -> None:
    async def _wedged(run: _ScriptedRun) -> RunOutcome:
        run.answers = False
        run.step(1)
        run.step(2)
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    note = AsyncMock()
    runner, seen = _runner(_wedged, _done, fallback=True, note=note)

    result = await _run(runner)

    primary, on_fallback = _ScriptedRun.made
    assert primary.abandoned is True
    # A wedged engine gives no live state: the fallback opens with saved logins only.
    seen["open_fallback"].assert_awaited_once_with(PAGE, None)
    note.assert_awaited_once_with(BROWSER_ENGINE_FALLBACK_WITHOUT_STATE_NOTE)
    assert on_fallback.steps_before == 2
    assert (result.status, result.summary, result.steps) == (
        BrowserSessionStatus.COMPLETED,
        "booked",
        3,
    )


async def test_an_agent_that_finds_the_fast_engine_broken_moves_to_chrome_still_signed_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carried = object()
    monkeypatch.setattr(runner_mod, "hand_over_state", AsyncMock(return_value=carried))
    captured: list[tuple[Any, ...]] = []
    monkeypatch.setattr(runner_mod, "capture_event", lambda *args: captured.append(args))

    async def _switches(run: _ScriptedRun) -> RunOutcome:
        run.step(1)
        assert run.hooks.switch_engine is not None
        run.answer = await run.hooks.switch_engine(
            EngineSwitchReason.STAYS_EMPTY, "https://app.example.test/d?user=a%40b.test"
        )
        return RunOutcome(success=False, summary="")

    async def _finishes(run: _ScriptedRun) -> RunOutcome:
        run.offered = run.hooks.switch_engine is not None
        return await _done(run)

    note = AsyncMock()
    runner, seen = _runner(_switches, _finishes, fallback=True, note=note)

    async with captured_wide_event() as event:
        result = await _run(runner)

    primary, on_fallback = _ScriptedRun.made
    assert primary.answer == BROWSER_ENGINE_SWITCH_ACK
    seen["open_fallback"].assert_awaited_once_with(PAGE, carried)
    note.assert_awaited_once_with(BROWSER_ENGINE_FALLBACK_NOTE)
    # The run on Chrome cannot move again, and numbers its steps on.
    assert (on_fallback.offered, on_fallback.steps_before) == (False, 1)
    assert (result.success, result.steps) == (True, 2)
    # Which sites the fast engine fails, by host only: never the page or who opened it.
    assert captured == [
        (
            "user-1",
            AnalyticsEvents.BROWSER_ENGINE_SWITCHED,
            {"reason": "stays_empty", "host": "app.example.test", "engine": "obscura"},
        )
    ]
    assert event["browser"]["engine_switch_host"] == "app.example.test"


async def test_a_run_on_chrome_is_never_offered_the_full_browser() -> None:
    async def _looks(run: _ScriptedRun) -> RunOutcome:
        run.offered = run.hooks.switch_engine is not None
        return RunOutcome(success=True, summary="done")

    await _run(_runner(_looks, fallback=False)[0])

    assert _ScriptedRun.made[0].offered is False


async def test_a_run_the_user_stopped_never_moves_even_with_its_engine_wedged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _wedged(run: _ScriptedRun) -> RunOutcome:
        run.answers = False
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    runner, seen = _runner(_wedged, fallback=True)
    monkeypatch.setattr(runner, "_is_cancelled", AsyncMock(return_value=True))

    result = await _run(runner)

    seen["open_fallback"].assert_not_awaited()
    assert result.status == BrowserSessionStatus.CANCELLED


async def test_a_run_past_its_budget_never_moves_even_with_its_engine_wedged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = type("_Check", (), {"stop_reason": "limit"})()

    async def _wedged(run: _ScriptedRun) -> RunOutcome:
        run.answers = False
        monkeypatch.setattr(runner_mod, "get_budget_stop_reason", AsyncMock(return_value=stop))
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    runner, seen = _runner(_wedged, fallback=True)

    result = await _run(runner)

    seen["open_fallback"].assert_not_awaited()
    assert result.summary == "limit"
    assert result.status == BrowserSessionStatus.FAILED
