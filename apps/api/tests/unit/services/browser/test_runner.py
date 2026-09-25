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
    BROWSER_AGENT_GUIDANCE_MAX,
    BROWSER_CDP_ATTACH_HINT,
    BROWSER_ENGINE_FALLBACK_NOTE,
    BROWSER_ENGINE_FALLBACK_WITHOUT_STATE_NOTE,
    BROWSER_ENGINE_SWITCH_ACK,
    BROWSER_RUN_BLOCKED_SUMMARY,
    BROWSER_RUN_CANCELLED_SUMMARY,
    BROWSER_RUN_DONE_SUMMARY,
    BROWSER_RUN_HANDOFF_COMPLETED_SUMMARY,
    BROWSER_RUN_HANDOFF_ENDED_SUMMARY,
    BROWSER_RUN_HANDOFF_TIMED_OUT,
    BROWSER_RUN_NOT_DONE_SUMMARY,
    BROWSER_RUN_STOPPED_SUMMARY,
    BROWSER_RUN_WALL_CLOCK_SUMMARY,
    BROWSER_STALL_NOTE,
    HANDOFF_AUTORESOLVED_NOTE,
    MAX_HANDOFFS_PER_TASK,
    BrowserRunFailure,
    BrowserSessionStatus,
    EngineFailure,
    EngineSwitchReason,
    HandoffStatus,
    SensitiveCategory,
    StateCarry,
)
from app.schemas.browser import (
    AgentGuidanceRequest,
    BrowserAction,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
    HandoffOutcome,
    HandoffRequest,
)
from app.services.analytics_service import AnalyticsEvents
from app.services.browser import engine_watchdog, runner as runner_mod
from app.services.browser.agent_run import AgentRunSetup
from app.services.browser.exceptions import BrowserHandoffCancelled, BrowserUnavailableError
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.ledger import CallComponent, ModelCall
from app.services.browser.run_contract import BrowserRunConfig, RunHooks, RunOutcome, StepFrame
from app.services.browser.runner import BrowserRunnerCallbacks, BrowserTaskRunner
from app.services.browser.session import BrowserHostSession
from app.services.llm_metering import LLMCallContext, TokenUsage
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

PAGE = "https://example.test/book"
SECRETS = RunSecrets({"password": "hunter2"}, ["example.test"])

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
        self,
        *,
        session: BrowserHostSession,
        config: BrowserRunConfig,
        hooks: RunHooks,
        setup: AgentRunSetup,
    ) -> None:
        self.session = session
        self.config = config
        self.hooks = hooks
        self.setup = setup
        self.steps_before = setup.steps_before
        self.task: str | None = None
        self.last_url: str | None = PAGE
        self.abandoned = False
        self.stopped = False
        self.answers = True
        type(self).made.append(self)

    async def execute(self, task: str) -> RunOutcome:
        self.task = task
        return await type(self).scripts[type(self).made.index(self)](self)

    def step(self, index: int, screenshot: str | None = None, since_prev_ms: int = 0) -> None:
        self.hooks.step(
            StepFrame(
                index=index,
                session_id=self.session.session_id,
                goal=f"step {index}",
                actions=[BrowserAction(name="click", inputs={"index": index}, target="Next")],
                url=PAGE,
                title="Book a table",
                raw_screenshot=screenshot,
                since_prev_ms=since_prev_ms,
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
    task_timeout: float = 30,
    handoff_timeout: float = 60,
    stream_screenshots: bool = False,
    handoff: HandoffOutcome | None = None,
    fallback: bool = False,
    user_id: str | None = "user-1",
    **callbacks: Any,
) -> tuple[BrowserTaskRunner, dict[str, Any]]:
    """Build a runner over the scripts; callbacks override the runner's seams (note, is_cancelled, ...)."""
    _ScriptedRun.scripts = list(scripts)
    seen: dict[str, Any] = {"emitted": [], "handoffs": []}

    async def _emit(snapshot: object) -> None:
        seen["emitted"].append(snapshot)

    async def _request_handoff(
        request: HandoffRequest, session: BrowserHostSession
    ) -> HandoffOutcome:
        seen["handoffs"].append((request, session))
        return handoff or HandoffOutcome(status=HandoffStatus.COMPLETED)

    open_fallback = AsyncMock(return_value=_session("s-fallback"))
    seen["open_fallback"] = open_fallback
    runner = BrowserTaskRunner(
        session=_session(),
        callbacks=BrowserRunnerCallbacks(
            **{
                "emit": _emit,
                "request_handoff": _request_handoff,
                "is_cancelled": AsyncMock(return_value=False),
                "user_waiting": AsyncMock(return_value=False),
                "take_user_messages": AsyncMock(return_value=[]),
                "open_fallback_session": open_fallback if fallback else None,
                **callbacks,
            }
        ),
        config=BrowserRunConfig(
            max_steps=10,
            max_actions_per_step=5,
            task_timeout_seconds=task_timeout,  # type: ignore[arg-type]  # sub-second budgets keep the clock tests fast
            step_timeout_seconds=180,
            handoff_timeout_seconds=handoff_timeout,  # type: ignore[arg-type]  # as above
            stream_screenshots=stream_screenshots,
            solve_captcha=False,
        ),
        secrets=SECRETS,
        user_id=user_id,
        root_request_id="req-1",
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

    assert (result.status, result.success, result.summary) == (
        BrowserSessionStatus.FAILED,
        False,
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

    assert [request.category for request, _ in seen["handoffs"]] == [SensitiveCategory.IRREVERSIBLE]


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


# ---------------------------------------------------------------------------
# What the agent run is given, and what the run shows first and last
# ---------------------------------------------------------------------------


async def test_the_agent_run_works_for_this_runs_user_ledger_secrets_and_hooks() -> None:
    action_results = AsyncMock()
    user_waiting = AsyncMock(return_value=False)
    runner, _ = _runner(
        _done, user_id="user-7", action_results=action_results, user_waiting=user_waiting
    )

    await _run(runner)

    [run] = _ScriptedRun.made
    assert run.task == "book a table"
    assert (run.setup.user_id, run.setup.ledger, run.setup.secrets) == (
        "user-7",
        runner.ledger,
        SECRETS,
    )
    assert run.config.max_actions_per_step == 5
    assert (run.hooks.action_results, run.hooks.user_waiting) == (action_results, user_waiting)
    assert runner.used_fallback is False


async def test_the_run_opens_on_its_session_and_ends_with_its_result() -> None:
    runner, seen = _runner(_done)

    result = await _run(runner)

    assert seen["emitted"][0] == BrowserSessionSnapshot(
        task="book a table",
        status=BrowserSessionStatus.RUNNING,
        session_id="s-primary",
        live_view_url="http://s-primary/live",
    )
    assert seen["emitted"][-1] == result


async def test_the_users_mid_task_messages_reach_the_agent_and_the_result() -> None:
    async def _reads(run: _ScriptedRun) -> RunOutcome:
        run.heard = await run.hooks.take_user_messages()
        return RunOutcome(success=True, summary="booked")

    runner, _ = _runner(_reads, take_user_messages=AsyncMock(return_value=["for four, not two"]))

    result = await _run(runner)

    assert _ScriptedRun.made[0].heard == ["for four, not two"]
    assert result.user_notes == ["for four, not two"]


@pytest.mark.parametrize(
    ("outcome", "status", "summary"),
    [
        (RunOutcome(True, ""), BrowserSessionStatus.COMPLETED, BROWSER_RUN_DONE_SUMMARY),
        (RunOutcome(False, ""), BrowserSessionStatus.FAILED, BROWSER_RUN_NOT_DONE_SUMMARY),
        (RunOutcome(False, "No such table."), BrowserSessionStatus.FAILED, "No such table."),
    ],
)
async def test_a_result_the_agent_wrote_nothing_for_still_says_how_it_ended(
    outcome: RunOutcome, status: BrowserSessionStatus, summary: str
) -> None:
    async def _ends(run: _ScriptedRun) -> RunOutcome:
        return outcome

    result = await _run(_runner(_ends)[0])

    assert (result.status, result.success, result.summary, result.steps) == (
        status,
        outcome.success,
        summary,
        0,
    )


async def test_background_work_is_named_for_the_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    names: list[str | None] = []
    real_spawn = runner_mod.spawn_background_task

    def _spawn(coro: Any, *, name: str | None = None) -> asyncio.Task[Any]:
        names.append(name)
        return real_spawn(coro, name=name)

    monkeypatch.setattr(runner_mod, "spawn_background_task", _spawn)
    runner, _ = _runner(_done)
    runner.ledger.add(
        ModelCall(CallComponent.JEV, "openrouter", "jev", 1, input_tokens=1, output_tokens=1)
    )

    await _run(runner)

    assert set(names) == {"browser_stall_watch", "browser_step_emit", "browser_meter_call"}


# ---------------------------------------------------------------------------
# Step cards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("since_prev_ms", "elapsed_ms"), [(0, None), (250, 250)])
async def test_a_step_card_carries_the_frames_page_actions_and_time(
    since_prev_ms: int, elapsed_ms: int | None
) -> None:
    async def _one(run: _ScriptedRun) -> RunOutcome:
        run.step(1, since_prev_ms=since_prev_ms)
        return RunOutcome(True, "booked")

    runner, seen = _runner(_one)
    await _run(runner)

    [card] = [c for c in seen["emitted"] if isinstance(c, BrowserStepSnapshot)]
    assert (card.index, card.goal, card.url, card.title, card.elapsed_ms) == (
        1,
        "step 1",
        PAGE,
        "Book a table",
        elapsed_ms,
    )
    assert card.actions == [BrowserAction(name="click", inputs={"index": 1}, target="Next")]


async def test_a_frames_photo_is_uploaded_as_the_image_it_carries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploaded: list[tuple[bytes, str, int]] = []

    async def _publish(image: bytes, session_id: str, index: int) -> str:
        uploaded.append((image, session_id, index))
        return "https://cdn.test/3.png"

    monkeypatch.setattr(runner_mod, "publish_step_screenshot", _publish)

    async def _one(run: _ScriptedRun) -> RunOutcome:
        run.step(3, screenshot="c2hvdA==")
        return RunOutcome(True, "booked")

    await _run(_runner(_one, stream_screenshots=True)[0])

    assert uploaded == [(b"shot", "s-primary", 3)]


async def test_with_screenshots_off_no_photo_is_uploaded_or_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish = AsyncMock(return_value="https://cdn.test/1.png")
    monkeypatch.setattr(runner_mod, "publish_step_screenshot", publish)

    async def _one(run: _ScriptedRun) -> RunOutcome:
        run.step(1, screenshot="c2hvdA==")
        return RunOutcome(True, "booked")

    runner, seen = _runner(_one, stream_screenshots=False)
    await _run(runner)

    [card] = [c for c in seen["emitted"] if isinstance(c, BrowserStepSnapshot)]
    assert card.screenshot is None
    publish.assert_not_awaited()


async def test_a_step_card_that_fails_to_send_does_not_lose_the_result() -> None:
    async def _one(run: _ScriptedRun) -> RunOutcome:
        run.step(1)
        return RunOutcome(True, "booked")

    runner, seen = _runner(_one)
    real_emit = runner._emit

    async def _flaky(snapshot: object) -> None:
        if isinstance(snapshot, BrowserStepSnapshot):
            raise ConnectionError("stream closed")
        await real_emit(snapshot)

    runner._emit = _flaky

    result = await _run(runner)

    assert (result.success, result.summary, result.steps) == (True, "booked", 1)


# ---------------------------------------------------------------------------
# Clocks and budgets
# ---------------------------------------------------------------------------


async def test_the_wall_clock_leaves_room_for_every_permitted_handoff() -> None:
    async def _slow(run: _ScriptedRun) -> RunOutcome:
        await asyncio.sleep(0.02 * MAX_HANDOFFS_PER_TASK / 2)
        return RunOutcome(True, "booked")

    result = await _run(_runner(_slow, task_timeout=0, handoff_timeout=0.02)[0])

    assert (result.success, result.summary) == (True, "booked")


async def test_a_run_past_the_wall_clock_is_stopped_and_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _never(run: _ScriptedRun) -> RunOutcome:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    runner, _ = _runner(_never, task_timeout=0, handoff_timeout=0.01)

    async with captured_wide_event() as event:
        result = await _run(runner)

    assert _ScriptedRun.made[0].stopped is True
    assert (result.status, result.success, result.summary) == (
        BrowserSessionStatus.FAILED,
        False,
        BROWSER_RUN_WALL_CLOCK_SUMMARY.format(seconds=0),
    )
    assert event["reason"] == BrowserRunFailure.TASK_TIMEOUT


@pytest.mark.parametrize(("work", "stops"), [(20.0, False), (20.5, True)])
async def test_the_work_budget_ends_a_run_only_once_passed(
    monkeypatch: pytest.MonkeyPatch, work: float, stops: bool
) -> None:
    clock = [0.0]
    monkeypatch.setattr(runner_mod, "perf_counter", lambda: clock[0])

    async def _works(run: _ScriptedRun) -> RunOutcome:
        clock[0] += work
        run.stops = await run.hooks.should_stop()
        return RunOutcome(True, "booked")

    runner, _ = _runner(_works, task_timeout=20)
    async with captured_wide_event() as event:
        await _run(runner)

    assert _ScriptedRun.made[0].stops is stops
    assert (event.get("reason") == BrowserRunFailure.TASK_TIMEOUT) is stops


async def test_waiting_on_the_user_twice_is_not_counted_twice_as_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(runner_mod, "perf_counter", lambda: clock[0])

    async def _two_handoffs(run: _ScriptedRun) -> RunOutcome:
        clock[0] += 5
        await run.hooks.takeover("Sign in", "credentials")
        clock[0] += 5
        await run.hooks.takeover("Enter the code", "credentials")
        run.after_waits = await run.hooks.should_stop()
        clock[0] += 15
        run.after_work = await run.hooks.should_stop()
        return RunOutcome(True, "booked")

    runner, _ = _runner(_two_handoffs, task_timeout=20)

    async def _slow_user(request: HandoffRequest, session: BrowserHostSession) -> HandoffOutcome:
        clock[0] += 600
        return HandoffOutcome(status=HandoffStatus.COMPLETED)

    runner._request_handoff = _slow_user

    await _run(runner)

    [run] = _ScriptedRun.made
    assert (run.after_waits, run.after_work) == (False, True)


async def test_the_cost_budget_is_read_for_this_user_and_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check = AsyncMock(return_value=None)
    monkeypatch.setattr(runner_mod, "get_budget_stop_reason", check)

    async def _checks(run: _ScriptedRun) -> RunOutcome:
        await run.hooks.should_stop()
        return RunOutcome(True, "booked")

    await _run(_runner(_checks, user_id="user-7")[0])

    check.assert_awaited_with("user-7", None, "req-1")


async def test_a_run_silent_from_its_start_gets_the_stall_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(runner_mod, "perf_counter", lambda: clock[0])
    monkeypatch.setattr(runner_mod, "_STALL_POLL_SECONDS", 0.01)
    monkeypatch.setattr(runner_mod, "BROWSER_STALL_NOTE_AFTER_SECONDS", 5.0)

    async def _silent(run: _ScriptedRun) -> RunOutcome:
        # Exactly the threshold of silence is a stall.
        clock[0] = 5.0
        await asyncio.sleep(0.1)
        return RunOutcome(True, "booked")

    note = AsyncMock()
    await _run(_runner(_silent, note=note)[0])

    note.assert_awaited_once_with(BROWSER_STALL_NOTE)


async def test_steps_arriving_in_time_are_never_a_stall(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_mod, "_STALL_POLL_SECONDS", 0.01)
    monkeypatch.setattr(runner_mod, "BROWSER_STALL_NOTE_AFTER_SECONDS", 0.2)

    async def _steady(run: _ScriptedRun) -> RunOutcome:
        for n in range(1, 6):
            run.step(n)
            await asyncio.sleep(0.03)
        return RunOutcome(True, "booked")

    note = AsyncMock()
    await _run(_runner(_steady, note=note)[0])

    note.assert_not_awaited()


# ---------------------------------------------------------------------------
# Handoffs: the note, the category, the session, the endings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "note", "notes"),
    [
        ("  Use my work card  ", "Use my work card", ["Use my work card"]),
        ("   ", None, []),
        (None, None, []),
    ],
)
async def test_the_users_note_from_a_handoff_reaches_the_agent_and_the_result(
    message: str | None, note: str | None, notes: list[str]
) -> None:
    async def _hands_over(run: _ScriptedRun) -> RunOutcome:
        run.note = await run.hooks.takeover("Pay the deposit", "payment")
        return RunOutcome(True, "booked")

    runner, seen = _runner(
        _hands_over, handoff=HandoffOutcome(status=HandoffStatus.COMPLETED, message=message)
    )

    result = await _run(runner)

    assert _ScriptedRun.made[0].note == note
    assert result.user_notes == notes
    [(request, session)] = seen["handoffs"]
    assert (request.category, request.reason, session) == (
        SensitiveCategory.PAYMENT,
        "Pay the deposit",
        runner.session,
    )


async def test_the_handoff_past_the_limit_stops_the_run() -> None:
    async def _asks_too_often(run: _ScriptedRun) -> RunOutcome:
        for _ in range(MAX_HANDOFFS_PER_TASK):
            await run.hooks.takeover("Enter the code", "credentials")
        try:
            await run.hooks.takeover("Enter the code again", "credentials")
        except BrowserHandoffCancelled as exc:
            run.refusal = str(exc)
        return RunOutcome(False, "")

    result = await _run(_runner(_asks_too_often)[0])

    assert _ScriptedRun.made[0].refusal == "max-handoffs"
    # The user did complete the earlier handoffs.
    assert (result.status, result.success, result.summary) == (
        BrowserSessionStatus.COMPLETED,
        True,
        BROWSER_RUN_STOPPED_SUMMARY,
    )


async def test_a_handoff_the_user_cancelled_stops_the_run_even_when_the_cancel_is_swallowed() -> (
    None
):
    async def _swallows(run: _ScriptedRun) -> RunOutcome:
        try:
            await run.hooks.takeover("Sign in", "credentials")
        except BrowserHandoffCancelled as exc:
            run.why = str(exc)
        return RunOutcome(True, "looks done")

    runner, _ = _runner(_swallows, handoff=HandoffOutcome(status=HandoffStatus.CANCELLED))

    result = await _run(runner)

    assert _ScriptedRun.made[0].why == HandoffStatus.CANCELLED.value
    assert (result.status, result.success, result.summary) == (
        BrowserSessionStatus.CANCELLED,
        False,
        BROWSER_RUN_STOPPED_SUMMARY,
    )


@pytest.mark.parametrize(
    ("first", "status", "success", "summary"),
    [
        (
            HandoffStatus.COMPLETED,
            BrowserSessionStatus.COMPLETED,
            True,
            BROWSER_RUN_HANDOFF_COMPLETED_SUMMARY,
        ),
        (
            HandoffStatus.CANCELLED,
            BrowserSessionStatus.CANCELLED,
            False,
            BROWSER_RUN_HANDOFF_ENDED_SUMMARY,
        ),
    ],
)
async def test_a_run_a_cancelled_handoff_ended_says_whether_the_user_did_the_step_first(
    first: HandoffStatus, status: BrowserSessionStatus, success: bool, summary: str
) -> None:
    async def _two_handoffs(run: _ScriptedRun) -> RunOutcome:
        await run.hooks.takeover("Sign in", "credentials")
        await run.hooks.takeover("Pay", "payment")
        raise AssertionError("the second handoff ends the run")

    runner, _ = _runner(_two_handoffs)
    outcomes = iter([first, HandoffStatus.CANCELLED])

    async def _answers(request: HandoffRequest, session: BrowserHostSession) -> HandoffOutcome:
        return HandoffOutcome(status=next(outcomes))

    runner._request_handoff = _answers

    result = await _run(runner)

    assert (result.status, result.success, result.summary) == (status, success, summary)


async def test_a_handoff_that_timed_out_fails_the_run() -> None:
    async def _hands_over(run: _ScriptedRun) -> RunOutcome:
        await run.hooks.takeover("Sign in", "credentials")
        raise AssertionError("the timeout ends the run")

    runner, _ = _runner(_hands_over, handoff=HandoffOutcome(status=HandoffStatus.TIMEOUT))

    result = await _run(runner)

    assert (result.status, result.success, result.summary) == (
        BrowserSessionStatus.FAILED,
        False,
        BROWSER_RUN_HANDOFF_TIMED_OUT,
    )


async def test_a_cancelled_run_that_finished_anyway_is_reported_cancelled() -> None:
    runner, _ = _runner(_done, is_cancelled=AsyncMock(return_value=True))

    result = await _run(runner)

    assert (result.status, result.success, result.summary) == (
        BrowserSessionStatus.CANCELLED,
        False,
        BROWSER_RUN_CANCELLED_SUMMARY,
    )


async def test_a_run_past_its_cost_budget_after_it_finished_still_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = type("_Check", (), {"stop_reason": "limit"})()
    monkeypatch.setattr(runner_mod, "get_budget_stop_reason", AsyncMock(return_value=stop))

    async def _checks_then_claims(run: _ScriptedRun) -> RunOutcome:
        await run.hooks.should_stop()
        return RunOutcome(True, "booked")

    result = await _run(_runner(_checks_then_claims)[0])

    assert (result.status, result.success, result.summary) == (
        BrowserSessionStatus.FAILED,
        False,
        "limit",
    )


# ---------------------------------------------------------------------------
# Guidance from the agent that started the run
# ---------------------------------------------------------------------------


def _guided(*answers: HandoffOutcome, joined: bool = True) -> dict[str, Any]:
    asked: list[AgentGuidanceRequest] = []
    replies = iter(answers)

    async def _request_guidance(request: AgentGuidanceRequest) -> HandoffOutcome:
        asked.append(request)
        return next(replies)

    return {
        "request_guidance": _request_guidance,
        "agent_joined": AsyncMock(return_value=joined),
        "asked": asked,
    }


async def test_a_blocked_run_is_guided_with_what_the_user_said_so_far() -> None:
    guided = _guided(HandoffOutcome(status=HandoffStatus.COMPLETED, message="  Use search  "))
    asked = guided.pop("asked")

    async def _blocked(run: _ScriptedRun) -> RunOutcome:
        await run.hooks.take_user_messages()
        assert run.hooks.guidance_allowed is not None and run.hooks.guidance is not None
        run.allowed = await run.hooks.guidance_allowed()
        run.instruction = await run.hooks.guidance(AgentGuidanceRequest(reason="stuck", task="t"))
        return RunOutcome(True, "booked")

    runner, _ = _runner(
        _blocked, take_user_messages=AsyncMock(return_value=["not the red one"]), **guided
    )

    await _run(runner)

    [run] = _ScriptedRun.made
    assert (run.allowed, run.instruction) == (True, "Use search")
    assert [request.user_notes for request in asked] == [["not the red one"]]


@pytest.mark.parametrize("carries_on", [True, False])
@pytest.mark.parametrize(
    "reply",
    [
        HandoffOutcome(status=HandoffStatus.COMPLETED, message="   "),
        HandoffOutcome(status=HandoffStatus.COMPLETED, message=None),
        HandoffOutcome(status=HandoffStatus.TIMEOUT, message="use search"),
    ],
)
async def test_a_blocked_run_with_no_instruction_ends_blocked_even_if_the_agent_carries_on(
    reply: HandoffOutcome, carries_on: bool
) -> None:
    guided = _guided(reply)
    guided.pop("asked")

    async def _blocked(run: _ScriptedRun) -> RunOutcome:
        assert run.hooks.guidance is not None
        try:
            await run.hooks.guidance(AgentGuidanceRequest(reason="stuck", task="t"))
        except BrowserHandoffCancelled as exc:
            if not carries_on:
                raise
            run.why = str(exc)
        # The agent's next check stops it.
        run.stops = await run.hooks.should_stop()
        return RunOutcome(True, "booked anyway")

    runner, _ = _runner(_blocked, **guided)

    async with captured_wide_event() as event:
        result = await _run(runner)

    assert (result.status, result.success, result.summary) == (
        BrowserSessionStatus.FAILED,
        False,
        BROWSER_RUN_BLOCKED_SUMMARY,
    )
    assert event["browser"]["blocked"] == BrowserRunFailure.BLOCKED.value
    if carries_on:
        [run] = _ScriptedRun.made
        assert (run.why, run.stops) == (reply.status.value, True)


async def test_a_run_may_ask_for_guidance_only_so_often_and_only_while_an_agent_is_joined() -> None:
    answers = [HandoffOutcome(status=HandoffStatus.COMPLETED, message="try again")] * (
        BROWSER_AGENT_GUIDANCE_MAX
    )
    guided = _guided(*answers)
    guided.pop("asked")

    async def _asks(run: _ScriptedRun) -> RunOutcome:
        assert run.hooks.guidance_allowed is not None and run.hooks.guidance is not None
        run.allowed = []
        for _ in range(BROWSER_AGENT_GUIDANCE_MAX + 1):
            run.allowed.append(await run.hooks.guidance_allowed())
            if run.allowed[-1]:
                await run.hooks.guidance(AgentGuidanceRequest(reason="stuck", task="t"))
        return RunOutcome(True, "booked")

    await _run(_runner(_asks, **guided)[0])

    assert _ScriptedRun.made[0].allowed == [True] * BROWSER_AGENT_GUIDANCE_MAX + [False]


@pytest.mark.parametrize("missing", ["request_guidance", "agent_joined", "gone"])
async def test_with_no_agent_to_ask_guidance_is_not_offered(missing: str) -> None:
    guided = _guided(joined=missing != "gone")
    guided.pop("asked")
    if missing != "gone":
        guided.pop(missing)

    async def _asks(run: _ScriptedRun) -> RunOutcome:
        assert run.hooks.guidance_allowed is not None
        run.allowed = await run.hooks.guidance_allowed()
        return RunOutcome(True, "booked")

    await _run(_runner(_asks, **guided)[0])

    assert _ScriptedRun.made[0].allowed is False


async def test_guidance_asked_with_no_channel_ends_the_run() -> None:
    async def _asks(run: _ScriptedRun) -> RunOutcome:
        assert run.hooks.guidance is not None
        try:
            await run.hooks.guidance(AgentGuidanceRequest(reason="stuck", task="t"))
        except BrowserHandoffCancelled as exc:
            run.why = str(exc)
            raise
        raise AssertionError("no channel ends the run")

    result = await _run(_runner(_asks)[0])

    assert _ScriptedRun.made[0].why == "no-guidance-channel"
    assert result.status == BrowserSessionStatus.CANCELLED


async def test_waiting_on_the_agent_twice_is_not_counted_as_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(runner_mod, "perf_counter", lambda: clock[0])
    guided = _guided(*[HandoffOutcome(status=HandoffStatus.COMPLETED, message="go on")] * 2)
    guided.pop("asked")

    async def _slow_agent(request: AgentGuidanceRequest) -> HandoffOutcome:
        clock[0] += 600
        return HandoffOutcome(status=HandoffStatus.COMPLETED, message="go on")

    guided["request_guidance"] = _slow_agent

    async def _two_asks(run: _ScriptedRun) -> RunOutcome:
        assert run.hooks.guidance is not None
        clock[0] += 5
        await run.hooks.guidance(AgentGuidanceRequest(reason="stuck", task="t"))
        clock[0] += 5
        await run.hooks.guidance(AgentGuidanceRequest(reason="stuck", task="t"))
        run.after_waits = await run.hooks.should_stop()
        clock[0] += 15
        run.after_work = await run.hooks.should_stop()
        return RunOutcome(True, "booked")

    await _run(_runner(_two_asks, task_timeout=20, **guided)[0])

    [run] = _ScriptedRun.made
    assert (run.after_waits, run.after_work) == (False, True)


async def test_waiting_on_the_agent_pauses_the_watchdog() -> None:
    guided = _guided()
    guided.pop("asked")

    async def _slow_agent(request: AgentGuidanceRequest) -> HandoffOutcome:
        await asyncio.sleep(0.2)
        return HandoffOutcome(status=HandoffStatus.COMPLETED, message="go on")

    guided["request_guidance"] = _slow_agent

    async def _asks(run: _ScriptedRun) -> RunOutcome:
        assert run.hooks.guidance is not None
        run.answers = False
        await run.hooks.guidance(AgentGuidanceRequest(reason="stuck", task="t"))
        run.answers = True
        return RunOutcome(True, "booked")

    runner, seen = _runner(_asks, _done, fallback=True, **guided)

    result = await _run(runner)

    seen["open_fallback"].assert_not_awaited()
    assert result.summary == "booked"


async def test_a_run_the_user_stopped_is_not_moved_after_it_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _gone(session: BrowserHostSession) -> EngineFailure | None:
        return EngineFailure.SESSION_GONE

    monkeypatch.setattr(runner_mod, "engine_failure", _gone)

    async def _gives_up(run: _ScriptedRun) -> RunOutcome:
        return RunOutcome(False, "")

    runner, seen = _runner(
        _gives_up, _done, fallback=True, is_cancelled=AsyncMock(return_value=True)
    )

    result = await _run(runner)

    seen["open_fallback"].assert_not_awaited()
    assert result.status == BrowserSessionStatus.CANCELLED


# ---------------------------------------------------------------------------
# Metering and failures
# ---------------------------------------------------------------------------


async def test_a_model_call_is_metered_as_browser_spend_against_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = AsyncMock()
    monkeypatch.setattr(runner_mod, "record_llm_call", record)
    runner, _ = _runner(_done)

    runner.ledger.add(
        ModelCall(CallComponent.AGENT, "openrouter", "luna", 1, input_tokens=10, output_tokens=2)
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    [call] = record.await_args_list
    assert call.kwargs["usage"] == TokenUsage(
        input_tokens=10, output_tokens=2, cached_tokens=0, reasoning_tokens=0
    )
    assert call.kwargs["root_request_id"] == "req-1"
    assert call.kwargs["context"] == LLMCallContext(
        agent_name="browser_task", background=False, charge_to_budget=True
    )


async def test_a_run_that_cannot_attach_names_the_url_and_what_to_check() -> None:
    async def _refused(run: _ScriptedRun) -> RunOutcome:
        raise ConnectionRefusedError("cdp refused")

    with pytest.raises(BrowserUnavailableError) as raised:
        await _run(_runner(_refused)[0])

    message = str(raised.value)
    assert "ws://s-primary" in message
    assert "cdp refused" in message
    assert message.endswith(BROWSER_CDP_ATTACH_HINT)


async def test_an_unexpected_failure_is_logged_with_its_type_and_session() -> None:
    async def _crashes(run: _ScriptedRun) -> RunOutcome:
        raise RuntimeError("history unreadable")

    async with captured_wide_event() as event:
        result = await _run(_runner(_crashes)[0])

    assert result.success is False
    assert event["reason"] == BrowserRunFailure.RUN_CRASHED
    [error] = event["errors"]
    assert "failed unexpectedly" in error["msg"]
    assert (error["error_type"], error["error"], error["browser"]) == (
        "RuntimeError",
        "history unreadable",
        {"session_id": "s-primary"},
    )


# ---------------------------------------------------------------------------
# Moving to the fallback engine
# ---------------------------------------------------------------------------


async def test_a_run_moved_to_the_fallback_resumes_at_the_page_it_was_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_mod, "hand_over_state", AsyncMock(return_value=object()))

    async def _switches(run: _ScriptedRun) -> RunOutcome:
        assert run.hooks.switch_engine is not None
        await run.hooks.switch_engine(EngineSwitchReason.RENDERS_WRONG, None)
        return RunOutcome(False, "")

    captured: list[tuple[Any, ...]] = []
    monkeypatch.setattr(runner_mod, "capture_event", lambda *args: captured.append(args))
    runner, seen = _runner(_switches, _done, fallback=True)

    async with captured_wide_event() as event:
        await _run(runner)

    primary, on_fallback = _ScriptedRun.made
    assert (on_fallback.config.start_url, on_fallback.task) == (PAGE, "book a table")
    assert on_fallback.session.session_id == "s-fallback"
    assert (
        BrowserSessionSnapshot(
            task="book a table",
            status=BrowserSessionStatus.RUNNING,
            session_id="s-fallback",
            live_view_url="http://s-fallback/live",
        )
        in seen["emitted"]
    )
    assert runner.used_fallback is True
    assert event["browser"]["primary_session_id"] == "s-primary"
    assert event["browser"]["engine_switch"] == "renders_wrong"
    assert event["browser"]["state_carry"] == StateCarry.CARRIED.value
    # A switch with no page to name reports no host.
    assert captured[0][2]["host"] == ""


async def test_the_primarys_state_is_read_from_the_primary_and_an_unreadable_one_is_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_from: list[str] = []

    async def _unreadable(session: BrowserHostSession) -> object:
        read_from.append(session.session_id)
        raise BrowserUnavailableError("the engine gave no state")

    monkeypatch.setattr(runner_mod, "hand_over_state", _unreadable)

    async def _switches(run: _ScriptedRun) -> RunOutcome:
        assert run.hooks.switch_engine is not None
        await run.hooks.switch_engine(EngineSwitchReason.CONTROL_BROKEN, PAGE)
        return RunOutcome(False, "")

    runner, seen = _runner(_switches, _done, fallback=True)

    async with captured_wide_event() as event:
        await _run(runner)

    assert read_from == ["s-primary"]
    seen["open_fallback"].assert_awaited_once_with(PAGE, None)
    assert event["browser"]["state_carry"] == StateCarry.UNREADABLE.value
    [warning] = [w for w in event["warnings"] if w.get("error_type") == "BrowserUnavailableError"]
    assert "state" in warning["msg"]
    assert warning["browser"] == {"session_id": "s-primary", "operation": "hand_over_state"}


async def test_an_engine_that_failed_under_a_run_is_named_and_carries_no_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _gone(session: BrowserHostSession) -> EngineFailure | None:
        return EngineFailure.SESSION_GONE if session.session_id == "s-primary" else None

    monkeypatch.setattr(runner_mod, "engine_failure", _gone)
    hand_over = AsyncMock()
    monkeypatch.setattr(runner_mod, "hand_over_state", hand_over)

    async def _gives_up(run: _ScriptedRun) -> RunOutcome:
        return RunOutcome(False, "The page never loaded.")

    runner, seen = _runner(_gives_up, _done, fallback=True)

    async with captured_wide_event() as event:
        result = await _run(runner)

    hand_over.assert_not_awaited()
    seen["open_fallback"].assert_awaited_once_with(PAGE, None)
    assert result.summary == "booked"
    assert event["browser"]["fallback_reason"] == EngineFailure.SESSION_GONE.value
    assert event["browser"]["state_carry"] == StateCarry.ENGINE_FAILED.value
    [warning] = [w for w in event["warnings"] if "engine_failure" in w]
    assert "failed under the run" in warning["msg"]
    assert (warning["engine_failure"], warning["browser"]) == (
        EngineFailure.SESSION_GONE.value,
        {"session_id": "s-primary", "operation": "engine_failure"},
    )


@pytest.mark.parametrize(
    ("outcome", "engine_failed"),
    [(RunOutcome(True, "booked"), True), (RunOutcome(False, "No table."), False)],
)
async def test_a_run_moves_only_when_it_failed_and_its_engine_failed_too(
    monkeypatch: pytest.MonkeyPatch, outcome: RunOutcome, engine_failed: bool
) -> None:
    async def _host(session: BrowserHostSession) -> EngineFailure | None:
        return EngineFailure.SESSION_GONE if engine_failed else None

    monkeypatch.setattr(runner_mod, "engine_failure", _host)

    async def _ends(run: _ScriptedRun) -> RunOutcome:
        return outcome

    runner, seen = _runner(_ends, _done, fallback=True)

    result = await _run(runner)

    seen["open_fallback"].assert_not_awaited()
    assert result.summary == outcome.summary


@pytest.mark.parametrize("engine_failed", [True, False])
async def test_a_run_that_could_not_attach_moves_only_when_its_engine_failed(
    monkeypatch: pytest.MonkeyPatch, engine_failed: bool
) -> None:
    async def _host(session: BrowserHostSession) -> EngineFailure | None:
        return (
            EngineFailure.SESSION_GONE
            if engine_failed and session.session_id == "s-primary"
            else None
        )

    monkeypatch.setattr(runner_mod, "engine_failure", _host)

    async def _cannot_attach(run: _ScriptedRun) -> RunOutcome:
        raise ConnectionRefusedError("cdp refused")

    runner, seen = _runner(_cannot_attach, _done, fallback=True)

    async with captured_wide_event() as event:
        if engine_failed:
            result = await _run(runner)
            assert (result.success, result.summary) == (True, "booked")
            assert _ScriptedRun.made[1].task == "book a table"
            [warning] = [w for w in event["warnings"] if "could not run" in w["msg"]]
            assert (warning["error_type"], warning["browser"]) == (
                "ConnectionRefusedError",
                {"session_id": "s-primary"},
            )
        else:
            with pytest.raises(BrowserUnavailableError):
                await _run(runner)
            seen["open_fallback"].assert_not_awaited()


async def test_a_handoff_on_a_run_with_a_fallback_pauses_the_watchdog() -> None:
    async def _waits(run: _ScriptedRun) -> RunOutcome:
        run.answers = False
        await run.hooks.takeover("Sign in", "credentials")
        run.answers = True
        return RunOutcome(True, "booked")

    runner, seen = _runner(_waits, _done, fallback=True)

    async def _slow_user(request: HandoffRequest, session: BrowserHostSession) -> HandoffOutcome:
        await asyncio.sleep(0.2)
        return HandoffOutcome(status=HandoffStatus.COMPLETED)

    runner._request_handoff = _slow_user

    result = await _run(runner)

    seen["open_fallback"].assert_not_awaited()
    assert (result.success, result.summary) == (True, "booked")
    assert _ScriptedRun.made[0].task == "book a table"
