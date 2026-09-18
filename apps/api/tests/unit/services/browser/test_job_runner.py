"""One browser task end to end, off the request path.

The half of the old browser_task that has no stream writer, no LangGraph config
and no tool result: runner wiring, cards, handoffs, cancellation, history and
bot mirroring, driven the way the ARQ worker drives it.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, NamedTuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.constants.browser import (
    BROWSER_TASK_EVENT,
    BrowserSessionStatus,
    HandoffStatus,
    SensitiveCategory,
)
from app.constants.log_tags import LogTag
from app.models.chat_models import ConversationSource
from app.schemas.browser import (
    BrowserAction,
    BrowserActionOutput,
    BrowserHandoffSnapshot,
    BrowserResultSnapshot,
    BrowserSessionSnapshot,
    BrowserStepSnapshot,
    HandoffOutcome,
    HandoffRequest,
)
from app.schemas.browser_job import BrowserJobRequest, BrowserJobState, BrowserJobStatus
from app.services.analytics_service import AnalyticsEvents
from app.services.browser import job_runner as jr
from app.services.browser.exceptions import BrowserConcurrencyLimit, BrowserUnavailableError
from app.services.browser.fingerprint import current_fingerprint_seed, seed_for_user
from app.services.browser.runner import BrowserRunConfig, BrowserRunnerCallbacks
from app.services.browser.tasks import BrowserTaskRecord

pytestmark = pytest.mark.unit


def _request(**overrides: Any) -> BrowserJobRequest:
    """Build the payload the tool enqueues for a web run, varying whatever this case needs."""
    fields: dict[str, Any] = {
        "job_id": "job-1",
        "user_id": "u1",
        "conversation_id": "c1",
        "task": "x",
        "stream_id": "s1",
        "source_category": "ui",
    }
    return BrowserJobRequest.model_validate(fields | overrides)


def _bot_request(**overrides: Any) -> BrowserJobRequest:
    bot: dict[str, Any] = {
        "source_category": "bot",
        "conversation_source": ConversationSource.DISCORD,
    }
    return _request(**(bot | overrides))


async def _run(h: "Harness", request: BrowserJobRequest) -> str:
    """Run the job body and read its outcome the way the worker and the join tool do."""
    return jr.agent_result_message(await jr.execute_browser_job(request, publish=h.publish))


def _failed_card(summary: str) -> dict[str, Any]:
    return {
        "kind": "result",
        "status": "failed",
        "success": False,
        "summary": summary,
        "steps": 0,
        "replay_url": None,
    }


# ---------------------------------------------------------------------------
# agent_result_message — the exact guidance handed back to the executor
# ---------------------------------------------------------------------------

# Repeated verbatim (not imported) so a change to the copy has to be made twice
# on purpose: these strings are the tool's whole user-visible contract.
NO_META = (
    "The step-by-step screenshots were already shown to the user in this chat, so do "
    "NOT mention screenshots, tools, steps, or 'browser vision'. Speak only to the outcome."
)


def _completed_message(summary: str) -> str:
    return (
        f"{summary}\n\n"
        "The browser task finished, and the text above is its own final answer. "
        f"Reply with a short, natural confirmation of what you found or did. {NO_META}"
    )


def _failed_message(summary: str) -> str:
    return (
        f"BROWSER TASK DID NOT COMPLETE. Last state: {summary}.\n\n"
        "Do not run the browser again for this request; tell the user what happened. "
        f"Tell the user honestly and briefly that it couldn't be finished, and why "
        f"if it's clear. Do not fabricate a result. {NO_META}"
    )


CANCELLED_MESSAGE = (
    "BROWSER TASK STOPPED BY THE USER before it finished. It did NOT complete, so "
    "there is no result and you must not claim one.\n\n"
    "Briefly acknowledge you've stopped and ask if they'd like you to try again or "
    f"do something else. {NO_META}"
)


def _result(
    status: BrowserSessionStatus, success: bool, summary: str, steps: int = 0
) -> BrowserResultSnapshot:
    return BrowserResultSnapshot(status=status, success=success, summary=summary, steps=steps)


def test_a_done_runs_own_answer_is_what_the_executor_hears() -> None:
    """The executor re-ran a finished task because the answer never reached it: the tool result must lead with the run's own final text, from Browser-Use's history to the tool's return."""
    from app.services.browser.agent_run import outcome_from_history

    answer = "The page title is Reddit - Dive into anything"

    class _History:
        def final_result(self):
            return answer

        def is_done(self):
            return True

        def is_successful(self):
            return True

        usage = None

    outcome = outcome_from_history(_History())
    out = jr.agent_result_message(
        _result(BrowserSessionStatus.COMPLETED, outcome.success, outcome.summary)
    )

    assert answer in out
    assert out.startswith(answer)


def test_a_failed_run_tells_the_executor_not_to_run_the_browser_again() -> None:
    out = jr.agent_result_message(_result(BrowserSessionStatus.FAILED, False, "Timed out"))

    assert "Do not run the browser again for this request; tell the user what happened." in out


def test_result_message_completed_success_is_exact() -> None:
    out = jr.agent_result_message(
        _result(BrowserSessionStatus.COMPLETED, True, "  Booked the table.  ")
    )
    assert out == _completed_message("Booked the table.")


def test_result_message_completed_without_success_reports_failure() -> None:
    """Status == COMPLETED and success: a completed-but-unsuccessful run must never be reported as an accomplishment."""
    out = jr.agent_result_message(_result(BrowserSessionStatus.COMPLETED, False, "Login wall"))
    assert out == _failed_message("Login wall")


def test_result_message_success_flag_alone_is_not_completion() -> None:
    out = jr.agent_result_message(_result(BrowserSessionStatus.FAILED, True, "Crashed"))
    assert out == _failed_message("Crashed")


def test_result_message_completed_with_blank_summary_uses_fallback() -> None:
    out = jr.agent_result_message(_result(BrowserSessionStatus.COMPLETED, True, "   "))
    assert out == _completed_message("The task finished.")


def test_result_message_failure_with_blank_summary_uses_fallback() -> None:
    out = jr.agent_result_message(_result(BrowserSessionStatus.FAILED, False, ""))
    assert out == _failed_message("the task could not be finished")


def test_result_message_cancelled_is_exact_and_ignores_summary() -> None:
    out = jr.agent_result_message(_result(BrowserSessionStatus.CANCELLED, False, "half done"))
    assert out == CANCELLED_MESSAGE


def test_result_message_cancelled_wins_over_success_flag() -> None:
    out = jr.agent_result_message(_result(BrowserSessionStatus.CANCELLED, True, "x"))
    assert out == CANCELLED_MESSAGE


# ---------------------------------------------------------------------------
# execute_browser_job — harness
# ---------------------------------------------------------------------------

LLM_SENTINEL = object()

RunBody = Callable[["Harness"], Awaitable[BrowserResultSnapshot]]


class Harness:
    """Everything the job body hands to its seams, captured for assertion."""

    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []
        self.session = MagicMock(session_id="sess-1", live_view_url="https://live/abc")
        self.session_kwargs: dict[str, Any] = {}
        self.runner_kwargs: dict[str, Any] = {}
        self.run_task: str | None = None
        self.record_calls: list[dict[str, Any]] = []
        self.spawn_names: list[str | None] = []
        self.delivery_kwargs: list[dict[str, Any]] = []
        self.delivered: list[tuple[str, Any]] = []
        self.handoffs_created: list[tuple[Any, ...]] = []
        self.handoffs_awaited: list[tuple[Any, ...]] = []
        self.cancel_checks: list[str] = []
        self.job_cancel_checks: list[str] = []
        self.states: list[BrowserJobState] = []

    async def publish(self, payload: dict[str, Any]) -> None:
        """Stand in for the job's feed, the way the worker's publisher is wired in."""
        self.writes.append(payload)

    @property
    def cards(self) -> list[dict[str, Any]]:
        """The card payloads the run published, in order."""
        return [w[BROWSER_TASK_EVENT] for w in self.writes]

    @property
    def rows(self) -> list[dict[str, Any]]:
        """The thread-mirror action rows."""
        return [w["tool_data"] for w in self.writes if "tool_data" in w]

    @property
    def outputs(self) -> list[dict[str, Any]]:
        """The thread-mirror action results."""
        return [w["tool_output"] for w in self.writes if "tool_output" in w]

    @property
    def callbacks(self) -> BrowserRunnerCallbacks:
        """The seam bundle the job body handed the runner."""
        cb: BrowserRunnerCallbacks = self.runner_kwargs["callbacks"]
        return cb

    async def emit(self, snapshot: object) -> None:
        await self.callbacks.emit(snapshot)

    async def is_cancelled(self) -> bool:
        result: bool = await self.callbacks.is_cancelled()
        return result

    async def request_handoff(self, req: HandoffRequest) -> HandoffOutcome:
        outcome: HandoffOutcome = await self.callbacks.request_handoff(req)
        return outcome

    async def action_results(self, step_index: int, outputs: object) -> None:
        # The job body wires this to the mirror's `results`; the runner calls it
        # from `on_step_end`. Driving it directly mirrors that call.
        assert self.callbacks.action_results is not None
        await self.callbacks.action_results(step_index, outputs)


class RecordingDelivery:
    def __init__(self, harness: Harness) -> None:
        self._h = harness

    async def step(self, snapshot: object) -> None:
        self._h.delivered.append(("step", snapshot))

    async def result(self, snapshot: object) -> None:
        self._h.delivered.append(("result", snapshot))

    async def handoff(self, snapshot: object) -> None:
        self._h.delivered.append(("handoff", snapshot))

    async def session(self, snapshot: object) -> None:
        self._h.delivered.append(("session", snapshot))


async def _noop() -> None:
    return None


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: BrowserResultSnapshot | None = None,
    run_body: RunBody | None = None,
    session_error: Exception | None = None,
    handoff_outcome: HandoffOutcome | None = None,
    job_cancelled: bool = False,
) -> Harness:
    """Wire every seam of execute_browser_job to a recorder and return the recording."""
    h = Harness()
    final = result if result is not None else _result(BrowserSessionStatus.COMPLETED, True, "Done")

    monkeypatch.setattr(jr, "build_browser_llm", lambda: LLM_SENTINEL)

    async def _put_state(state: BrowserJobState) -> None:
        h.states.append(state)

    monkeypatch.setattr(jr, "put_job_state", _put_state)

    async def _cancel_requested(job_id: str) -> bool:
        h.job_cancel_checks.append(job_id)
        return job_cancelled

    monkeypatch.setattr(jr, "job_cancel_requested", _cancel_requested)

    @asynccontextmanager
    async def _session(**kwargs: Any) -> AsyncIterator[MagicMock]:
        h.session_kwargs = kwargs
        if session_error is not None:
            raise session_error
        yield h.session

    monkeypatch.setattr(jr, "browser_session", _session)

    class _Runner:
        def __init__(self, **kwargs: Any) -> None:
            h.runner_kwargs = kwargs

        async def run(self, task: str) -> BrowserResultSnapshot:
            h.run_task = task
            if run_body is not None:
                return await run_body(h)
            return final

    monkeypatch.setattr(jr, "BrowserTaskRunner", _Runner)

    def _record(
        record: BrowserTaskRecord,
        result: BrowserResultSnapshot,
        *,
        step_goals: list[str] | None = None,
        step_screenshots: list[str] | None = None,
    ) -> Any:
        h.record_calls.append(
            {
                "record": record,
                "result": result,
                "step_goals": step_goals,
                "step_screenshots": step_screenshots,
            }
        )
        return _noop()

    monkeypatch.setattr(jr, "record_browser_task", _record)

    real_spawn = jr.spawn_background_task

    def _spawn(coro: Any, **kwargs: Any) -> Any:
        h.spawn_names.append(kwargs.get("name"))
        return real_spawn(coro, **kwargs)

    monkeypatch.setattr(jr, "spawn_background_task", _spawn)

    def _delivery(**kwargs: Any) -> RecordingDelivery:
        h.delivery_kwargs.append(kwargs)
        return RecordingDelivery(h)

    monkeypatch.setattr(jr, "BotProgressDelivery", _delivery)

    async def _create_pending(*args: Any) -> None:
        h.handoffs_created.append(args)

    monkeypatch.setattr(jr, "create_pending_handoff", _create_pending)

    async def _await_handoff(*args: Any) -> HandoffOutcome:
        h.handoffs_awaited.append(args)
        return handoff_outcome or HandoffOutcome(status=HandoffStatus.COMPLETED)

    monkeypatch.setattr(jr, "await_handoff", _await_handoff)

    async def _is_cancelled(stream_id: str) -> bool:
        h.cancel_checks.append(stream_id)
        return True

    monkeypatch.setattr(jr.stream_manager, "is_cancelled", _is_cancelled)
    return h


# ---------------------------------------------------------------------------
# execute_browser_job — gating and early returns
# ---------------------------------------------------------------------------


async def test_llm_unavailable_ends_the_run_with_a_failed_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nobody is holding a tool call to hear an exception, so an unusable model is a terminal card carrying the reason."""
    h = _install(monkeypatch)
    monkeypatch.setattr(
        jr,
        "build_browser_llm",
        MagicMock(side_effect=BrowserUnavailableError("no API key for 'google'")),
    )
    fake_log = MagicMock()
    monkeypatch.setattr(jr, "log", fake_log)

    out = await _run(h, _request(task="do it"))

    assert out == _failed_message("no API key for 'google'")
    assert h.cards == [_failed_card("no API key for 'google'")]
    assert h.session_kwargs == {}
    fake_log.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Browser LLM unavailable", error_type="BrowserUnavailableError"
    )


async def test_capacity_limit_is_reported_as_a_terminal_card_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The host's own refusal is the whole story the user gets; a paraphrase would lose the "try again shortly"."""
    h = _install(
        monkeypatch,
        session_error=BrowserConcurrencyLimit("Too many browser tasks already running."),
    )

    out = await _run(h, _request(task="x"))

    assert h.cards == [_failed_card("Too many browser tasks already running.")]
    assert out == _failed_message("Too many browser tasks already running.")


async def test_session_unavailable_emits_failed_card_and_explains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch, session_error=BrowserUnavailableError("host is down"))
    fake_log = MagicMock()
    monkeypatch.setattr(jr, "log", fake_log)
    out = await _run(h, _request(task="x"))

    assert out == _failed_message("host is down")
    assert h.cards == [_failed_card("host is down")]
    fake_log.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Browser session unavailable", error_type="BrowserUnavailableError"
    )
    # UI runs have no bot_delivery, so emitting the failed card above must not
    # touch it — the closure's initial value must be `None`, not a falsy
    # sentinel a snapshot could be handed to and blow up against.
    fake_log.error.assert_not_called()


# ---------------------------------------------------------------------------
# execute_browser_job — the task text and the session it opens
# ---------------------------------------------------------------------------


async def test_task_is_passed_through_unchanged_without_a_start_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    await _run(h, _request(task="book a table"))
    assert h.run_task == "book a table"
    assert h.session_kwargs == {"user_id": "u1", "start_url": None}


async def test_start_url_is_appended_to_the_task_and_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    await _run(h, _request(task="book a table", start_url="https://resy.com"))
    assert h.run_task == "book a table\n\nStart at: https://resy.com"
    assert h.session_kwargs == {"user_id": "u1", "start_url": "https://resy.com"}


async def test_blank_start_url_is_not_appended(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _install(monkeypatch)
    await _run(h, _request(task="book a table", start_url=""))
    assert h.run_task == "book a table"


# ---------------------------------------------------------------------------
# execute_browser_job — runner wiring
# ---------------------------------------------------------------------------


async def test_runner_is_configured_from_settings_and_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every knob the runner gets must come from its own setting — not a neighbouring one, and not a hardcoded default."""
    h = _install(monkeypatch)
    monkeypatch.setattr(jr.settings, "BROWSER_USE_MAX_STEPS", 7)
    monkeypatch.setattr(jr.settings, "BROWSER_USE_MAX_ACTIONS_PER_STEP", 3)
    monkeypatch.setattr(jr.settings, "BROWSER_USE_TASK_TIMEOUT_SECONDS", 111)
    monkeypatch.setattr(jr.settings, "BROWSER_USE_STEP_TIMEOUT_SECONDS", 22)
    monkeypatch.setattr(jr.settings, "BROWSER_USE_HANDOFF_TIMEOUT_SECONDS", 333)
    monkeypatch.setattr(jr.settings, "BROWSER_USE_STREAM_SCREENSHOTS", False)
    monkeypatch.setattr(jr.settings, "BROWSER_USE_SOLVE_CAPTCHA", False)
    # Deliberately the opposite of ``BrowserRunConfig.flash_mode``'s own default:
    # pinned to the default, a config that never forwards the setting at all
    # looks identical to one that does.
    monkeypatch.setattr(jr.settings, "BROWSER_USE_FLASH_MODE", False)

    await _run(h, _request(conversation_id="conv-9", root_request_id="req-42"))

    kwargs = dict(h.runner_kwargs)
    callbacks = kwargs.pop("callbacks")
    for seam in ("emit", "request_handoff", "is_cancelled", "action_results"):
        assert callable(getattr(callbacks, seam))
    assert kwargs.pop("config") == BrowserRunConfig(
        max_steps=7,
        max_actions_per_step=3,
        task_timeout_seconds=111,
        step_timeout_seconds=22,
        handoff_timeout_seconds=333,
        stream_screenshots=False,
        solve_captcha=False,
        flash_mode=False,
    )
    assert kwargs == {
        "session": h.session,
        "llm": LLM_SENTINEL,
        "user_id": "u1",
        "root_request_id": "req-42",
    }


async def test_missing_identifiers_degrade_to_blank_and_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    await _run(h, _request(user_id="", conversation_id="", stream_id=None))
    assert h.runner_kwargs["user_id"] is None
    assert h.runner_kwargs["root_request_id"] is None
    assert h.session_kwargs == {"user_id": "", "start_url": None}


# ---------------------------------------------------------------------------
# execute_browser_job — cancellation seam
# ---------------------------------------------------------------------------


async def test_is_cancelled_consults_the_stream_manager_for_this_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def body(h: Harness) -> BrowserResultSnapshot:
        assert await h.is_cancelled() is True
        return _result(BrowserSessionStatus.CANCELLED, False, "stopped")

    h = _install(monkeypatch, run_body=body)
    await _run(h, _request(task="x"))
    assert h.cancel_checks == ["s1"]


async def test_is_cancelled_is_false_without_a_stream_and_never_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No stream id means no cancel flag to read — the runner must not be told it was cancelled just because the lookup would have said so."""

    async def body(h: Harness) -> BrowserResultSnapshot:
        assert await h.is_cancelled() is False
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    await _run(h, _request(stream_id=None))
    assert h.cancel_checks == []


async def test_is_cancelled_reports_a_live_stream_as_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def body(h: Harness) -> BrowserResultSnapshot:
        assert await h.is_cancelled() is False
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    monkeypatch.setattr(jr.stream_manager, "is_cancelled", AsyncMock(return_value=False))
    await _run(h, _request(task="x"))


# ---------------------------------------------------------------------------
# execute_browser_job — card emission
# ---------------------------------------------------------------------------


async def test_step_card_is_written_as_json_under_the_browser_event_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(
            BrowserStepSnapshot(
                index=2,
                goal="find the menu",
                actions=[BrowserAction(name="click", inputs={"index": 2})],
                url="https://x",
                title="Menu",
                screenshot="https://cdn/2.png",
            )
        )
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    await _run(h, _request(task="x"))
    assert list(h.writes[0]) == [BROWSER_TASK_EVENT]
    # JSON mode, not python mode: the payload goes onto the SSE wire, so the
    # discriminator must be a plain string rather than an enum member.
    assert type(h.cards[0]["kind"]) is str
    assert h.cards[0] == {
        "kind": "step",
        "index": 2,
        "goal": "find the menu",
        "actions": [{"name": "click", "inputs": {"index": 2}, "target": None, "point": None}],
        "url": "https://x",
        "title": "Menu",
        "screenshot": "https://cdn/2.png",
        "elapsed_ms": None,
    }


async def test_mirrored_action_row_names_the_element_it_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the resolved target on the tool-thread row, like the step caption does, so two different clicks don't both render as "Clicking"."""

    async def body(h: Harness) -> BrowserResultSnapshot:
        # The mirror opens its group on the session snapshot; without one there
        # is no group to hang the action rows off.
        await h.emit(
            BrowserSessionSnapshot(task="x", status=BrowserSessionStatus.RUNNING, session_id="s1")
        )
        await h.emit(
            BrowserStepSnapshot(
                index=1,
                goal="submit the form",
                actions=[BrowserAction(name="click", inputs={"index": 7}, target="Submit")],
                url="https://x",
                title="Form",
                screenshot=None,
            )
        )
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    await _run(h, _request(task="x"))

    rows = h.rows
    messages = [r["data"]["message"] for r in rows]
    assert 'Clicking "Submit"' in messages, messages


async def test_action_output_lands_on_the_row_for_that_step_and_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Match the row by {group}:{step}:{position}; the row lands before the action runs, the output arrives later via on_step_end."""

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(
            BrowserSessionSnapshot(task="x", status=BrowserSessionStatus.RUNNING, session_id="s1")
        )
        await h.emit(
            BrowserStepSnapshot(
                index=3,
                goal="read the total",
                actions=[BrowserAction(name="extract", inputs={"index": 4}, target="Total")],
                url="https://x",
                title="Cart",
                screenshot=None,
            )
        )
        # The tool hands the mirror's `results` callback to the runner; call it
        # the way the runner would after the step executes.
        await h.action_results(3, [BrowserActionOutput(position=0, output="Total: $42.00")])
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    await _run(h, _request(task="x"))

    rows = h.rows
    outs = h.outputs
    row_id = rows[0]["data"]["tool_call_id"]
    assert len(outs) == 1
    assert outs[0]["tool_call_id"] == row_id, (outs[0]["tool_call_id"], row_id)
    assert outs[0]["output"] == "Total: $42.00"


async def test_action_output_arriving_before_its_row_is_buffered_then_flushed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Buffer the output when results arrives before its row, roughly a 1s screenshot-upload delay, then flush it once the row lands."""

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(
            BrowserSessionSnapshot(task="x", status=BrowserSessionStatus.RUNNING, session_id="s1")
        )
        # Result first — the row for step 2 has NOT been emitted yet.
        await h.action_results(2, [BrowserActionOutput(position=0, output="Total: $42.00")])
        assert h.outputs == []  # buffered, not emitted
        # Now the row lands; the buffered output flushes with it.
        await h.emit(
            BrowserStepSnapshot(
                index=2,
                goal="read the total",
                actions=[BrowserAction(name="extract", inputs={"index": 4}, target="Total")],
                url="https://x",
                title="Cart",
                screenshot=None,
            )
        )
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    await _run(h, _request(task="x"))

    rows = h.rows
    outs = h.outputs
    assert len(outs) == 1
    assert outs[0]["tool_call_id"] == rows[0]["data"]["tool_call_id"]
    assert outs[0]["output"] == "Total: $42.00"


async def test_action_output_for_an_unknown_row_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An output whose row never arrives (an errored step emits no rows) stays buffered and never produces an orphan frame the UI cannot attach."""

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(
            BrowserSessionSnapshot(task="x", status=BrowserSessionStatus.RUNNING, session_id="s1")
        )
        await h.action_results(9, [BrowserActionOutput(position=0, output="orphan")])
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    await _run(h, _request(task="x"))

    assert h.outputs == []


# ---------------------------------------------------------------------------
# execute_browser_job — mid-run handoff
# ---------------------------------------------------------------------------


async def test_handoff_registers_emits_pending_then_resolution_and_returns_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = HandoffOutcome(status=HandoffStatus.CANCELLED, message="not now")

    async def body(h: Harness) -> BrowserResultSnapshot:
        outcome = await h.request_handoff(
            HandoffRequest(category=SensitiveCategory.PAYMENT, reason="card details needed")
        )
        assert outcome is resolved
        return _result(BrowserSessionStatus.CANCELLED, False, "user cancelled")

    h = _install(monkeypatch, run_body=body, handoff_outcome=resolved)
    monkeypatch.setattr(jr.settings, "BROWSER_USE_HANDOFF_TIMEOUT_SECONDS", 333)
    await _run(h, _request(conversation_id="conv-9"))

    (created,) = h.handoffs_created
    handoff_id = created[0]
    assert len(handoff_id) == 32
    assert created == (handoff_id, "u1", "conv-9", "card details needed")
    assert h.handoffs_awaited == [(handoff_id, 333)]
    assert h.cards == [
        {
            "kind": "handoff",
            "handoff_id": handoff_id,
            "category": "payment",
            "reason": "card details needed",
            "session_id": "sess-1",
            "live_view_url": "https://live/abc",
            "status": "pending",
        },
        {
            "kind": "handoff",
            "handoff_id": handoff_id,
            "category": "payment",
            "reason": "card details needed",
            "session_id": "sess-1",
            "live_view_url": "https://live/abc",
            "status": "cancelled",
        },
    ]


async def test_handoff_keepalive_is_cancelled_after_the_handoff_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """request_handoff spawns a keepalive to hold the host's idle clock open; cancel it once the handoff resolves so it stops touching an abandoned session."""
    tasks: list[asyncio.Task[None]] = []

    async def _fake_keep_alive(session_id: str) -> None:
        await asyncio.Event().wait()  # runs until cancelled

    def _spawn(coro: Any, **kwargs: Any) -> asyncio.Task[None]:
        task = asyncio.create_task(coro)
        if kwargs.get("name") == "browser_handoff_keepalive":
            tasks.append(task)
        return task

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.request_handoff(HandoffRequest(reason="verify"))
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    monkeypatch.setattr(jr, "keep_session_alive", _fake_keep_alive)
    monkeypatch.setattr(jr, "spawn_background_task", _spawn)

    await _run(h, _request(task="x"))
    await asyncio.sleep(0)

    assert len(tasks) == 1
    assert tasks[0].cancelled()


async def test_handoff_keepalive_is_cancelled_when_await_handoff_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancel the keepalive on the failure path too; a raised await_handoff must not leak the keepalive task running forever."""
    tasks: list[asyncio.Task[None]] = []

    async def _fake_keep_alive(session_id: str) -> None:
        await asyncio.Event().wait()

    def _spawn(coro: Any, **kwargs: Any) -> asyncio.Task[None]:
        task = asyncio.create_task(coro)
        if kwargs.get("name") == "browser_handoff_keepalive":
            tasks.append(task)
        return task

    async def _boom_await_handoff(*args: Any) -> HandoffOutcome:
        raise RuntimeError("redis down")

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.request_handoff(HandoffRequest(reason="verify"))
        return _result(BrowserSessionStatus.COMPLETED, True, "unreachable")

    h = _install(monkeypatch, run_body=body)
    monkeypatch.setattr(jr, "keep_session_alive", _fake_keep_alive)
    monkeypatch.setattr(jr, "spawn_background_task", _spawn)
    monkeypatch.setattr(jr, "await_handoff", _boom_await_handoff)

    with pytest.raises(RuntimeError, match="redis down"):
        await _run(h, _request())
    await asyncio.sleep(0)

    assert len(tasks) == 1
    assert tasks[0].cancelled()


async def test_each_handoff_gets_its_own_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.request_handoff(HandoffRequest(reason="one"))
        await h.request_handoff(HandoffRequest(reason="two"))
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    await _run(h, _request(task="x"))
    assert h.handoffs_created[0][0] != h.handoffs_created[1][0]


# ---------------------------------------------------------------------------
# execute_browser_job — history recording
# ---------------------------------------------------------------------------


async def test_history_records_step_captions_and_uploaded_screenshots_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Steps are 1-indexed, gaps stay blank, and a data-URL fallback is never stored — it would render as a permanently broken thumbnail in the recap."""

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(BrowserStepSnapshot(index=1, goal="open", screenshot="https://cdn/1.png"))
        await h.emit(BrowserStepSnapshot(index=2, goal="", screenshot="data:image/png;base64,zz"))
        await h.emit(BrowserStepSnapshot(index=3, goal="submit", screenshot=None))
        await h.emit(BrowserStepSnapshot(index=4, goal="done", screenshot="http://cdn/4.png"))
        return _result(BrowserSessionStatus.COMPLETED, True, "done", steps=4)

    h = _install(monkeypatch, run_body=body)
    await _run(
        h,
        _request(
            task="book a table",
            start_url="https://resy.com",
            conversation_id="conv-9",
            conversation_source=ConversationSource.WEB,
        ),
    )

    # Awaited, never spawned: in the worker the task body is the lifetime, so a
    # fire-and-forget history write can be cut off by process exit.
    assert h.spawn_names == []
    (call,) = h.record_calls
    assert call["record"] == BrowserTaskRecord(
        user_id="u1",
        conversation_id="conv-9",
        task="book a table",
        session_id="sess-1",
        source="web",
    )
    assert call["result"] == _result(BrowserSessionStatus.COMPLETED, True, "done", steps=4)
    assert call["step_goals"] == ["open", "", "submit", "done"]
    assert call["step_screenshots"] == ["https://cdn/1.png", "", "", "http://cdn/4.png"]


async def test_history_lists_are_sized_by_the_reported_step_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(BrowserStepSnapshot(index=1, goal="open", screenshot="https://cdn/1.png"))
        await h.emit(BrowserStepSnapshot(index=2, goal="close", screenshot="https://cdn/2.png"))
        return _result(BrowserSessionStatus.COMPLETED, True, "done", steps=1)

    h = _install(monkeypatch, run_body=body)
    await _run(h, _request(task="x"))
    assert h.record_calls[0]["step_goals"] == ["open"]
    assert h.record_calls[0]["step_screenshots"] == ["https://cdn/1.png"]


async def test_history_source_is_blank_for_an_unknown_conversation_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    await _run(h, _request(conversation_source=None))
    assert h.record_calls[0]["record"].source == ""


async def test_no_history_is_recorded_for_an_anonymous_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    out = await _run(h, _request(user_id=""))
    assert h.record_calls == []
    assert out == _completed_message("Done")


async def test_history_is_recorded_for_a_failed_run_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch, result=_result(BrowserSessionStatus.FAILED, False, "blocked"))
    out = await _run(h, _request(task="x"))
    assert h.record_calls[0]["result"].status == BrowserSessionStatus.FAILED
    assert out == _failed_message("blocked")


# ---------------------------------------------------------------------------
# execute_browser_job — bot mirroring
# ---------------------------------------------------------------------------


async def test_bot_delivery_is_built_for_the_originating_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    monkeypatch.setattr(jr.settings, "BROWSER_USE_STREAM_SCREENSHOTS", False)
    await _run(h, _bot_request(task="x"))
    assert h.delivery_kwargs == [
        {
            "platform": ConversationSource.DISCORD,
            "user_id": "u1",
            "conversation_id": "c1",
            "stream_screenshots": False,
        }
    ]


async def test_every_snapshot_kind_is_mirrored_to_its_own_delivery_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    step = BrowserStepSnapshot(index=1, goal="g")
    session = BrowserSessionSnapshot(task="x", status=BrowserSessionStatus.RUNNING)
    handoff = BrowserHandoffSnapshot(handoff_id="h1", reason="r", status=HandoffStatus.PENDING)
    final = _result(BrowserSessionStatus.COMPLETED, True, "done")

    async def body(h: Harness) -> BrowserResultSnapshot:
        for snapshot in (session, step, handoff, final):
            await h.emit(snapshot)
        return final

    h = _install(monkeypatch, run_body=body)
    await _run(h, _bot_request(task="x"))
    assert h.delivered == [
        ("session", session),
        ("step", step),
        ("handoff", handoff),
        ("result", final),
    ]


async def test_ui_runs_are_not_mirrored_to_a_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(BrowserStepSnapshot(index=1, goal="g"))
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    await _run(h, _request(task="x"))
    assert h.delivery_kwargs == []
    assert h.delivered == []


async def test_bot_run_without_a_known_platform_is_not_mirrored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    await _run(h, _bot_request(conversation_source=None))
    assert h.delivery_kwargs == []


async def test_bot_run_without_a_user_is_not_mirrored(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _install(monkeypatch)
    await _run(h, _bot_request(user_id=""))
    assert h.delivery_kwargs == []


async def test_bot_run_without_a_conversation_is_not_mirrored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _install(monkeypatch)
    await _run(h, _bot_request(conversation_id=""))
    assert h.delivery_kwargs == []


async def test_failed_mirror_is_logged_with_the_snapshot_that_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The card is already on the stream, so a platform outage is a logged warning — but it must say which snapshot and which error."""

    class _Failing:
        async def step(self, snapshot: object) -> None:
            raise RuntimeError("rabbitmq down")

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(BrowserStepSnapshot(index=1, goal="g"))
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    monkeypatch.setattr(jr, "BotProgressDelivery", lambda **kwargs: _Failing())
    fake_log = MagicMock()
    monkeypatch.setattr(jr, "log", fake_log)

    out = await _run(h, _bot_request(task="x"))

    assert out == _completed_message("done")
    assert len(h.cards) == 1
    (error_call,) = fake_log.error.call_args_list
    assert error_call.args == (f"{LogTag.BROWSER} Bot delivery failed; continuing browser task",)
    assert error_call.kwargs == {
        "error_type": "RuntimeError",
        "browser": {"snapshot_type": "BrowserStepSnapshot"},
    }


async def test_the_session_the_run_opened_is_logged_onto_the_wide_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every browser-host line for this job is read back by its session id; unlogged, a failing run cannot be traced to a session at all."""
    h = _install(monkeypatch)
    fake_log = MagicMock()
    monkeypatch.setattr(jr, "log", fake_log)

    await _run(h, _bot_request(task="x"))

    logged = [call.kwargs["browser"] for call in fake_log.set.call_args_list]
    assert {"session_id": "sess-1"} in logged


# ---------------------------------------------------------------------------
# _spawn_handoff_watchers -- which background watchers a paused session gets
# ---------------------------------------------------------------------------


class _Watchers(NamedTuple):
    spawned: list[tuple[Any, str | None]]
    keep_alive: MagicMock
    auto_resolve: MagicMock


def _record_watchers(monkeypatch: pytest.MonkeyPatch) -> _Watchers:
    """Capture (coroutine, name) for each spawned watcher without running it."""
    spawned: list[tuple[Any, str | None]] = []

    def _spawn(coro: Any, *, name: str | None = None) -> MagicMock:
        spawned.append((coro, name))
        return MagicMock()

    keep_alive = MagicMock(name="keep_session_alive")
    auto_resolve = MagicMock(name="auto_resolve_handoff_on_navigation")
    monkeypatch.setattr(jr, "spawn_background_task", _spawn)
    monkeypatch.setattr(jr, "keep_session_alive", keep_alive)
    monkeypatch.setattr(jr, "auto_resolve_handoff_on_navigation", auto_resolve)
    return _Watchers(spawned, keep_alive, auto_resolve)


async def test_credentials_handoff_also_watches_for_the_navigation_that_ends_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A login handoff resolves itself when the page navigates off the sign-in URL, so it gets the auto-resolve watcher on top of the keepalive -- and both must be aimed at the session/handoff actually being waited on."""
    w = _record_watchers(monkeypatch)

    watchers = jr._spawn_handoff_watchers(
        "handoff-7",
        HandoffRequest(category=SensitiveCategory.CREDENTIALS, reason="log in"),
        "s-9",
        "u1",
    )

    assert len(watchers) == 2
    assert [name for _, name in w.spawned] == [
        "browser_handoff_keepalive",
        "browser_handoff_autoresolve",
    ]
    w.keep_alive.assert_called_once_with("s-9")
    w.auto_resolve.assert_called_once_with("handoff-7", "s-9", "u1")
    assert [coro for coro, _ in w.spawned] == [
        w.keep_alive.return_value,
        w.auto_resolve.return_value,
    ]


@pytest.mark.parametrize(
    "category", [SensitiveCategory.PAYMENT, SensitiveCategory.IRREVERSIBLE, SensitiveCategory.NONE]
)
async def test_non_credentials_handoff_gets_only_the_keepalive(
    monkeypatch: pytest.MonkeyPatch, category: SensitiveCategory
) -> None:
    """Only a credentials handoff has a navigation that means "done" -- auto- resolving a payment or confirmation would close one the user never answered."""
    w = _record_watchers(monkeypatch)

    watchers = jr._spawn_handoff_watchers(
        "handoff-7", HandoffRequest(category=category, reason="confirm"), "s-9", "u1"
    )

    assert len(watchers) == 1
    assert [name for _, name in w.spawned] == ["browser_handoff_keepalive"]
    w.auto_resolve.assert_not_called()


async def test_handoff_watchers_are_aimed_at_this_run_handoff_session_and_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The watchers are only useful if they name the run that paused: the wrong (or a missing) session id keeps the wrong browser alive, and the wrong handoff/user id resolves a handoff nobody is waiting on."""

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.request_handoff(
            HandoffRequest(category=SensitiveCategory.CREDENTIALS, reason="log in")
        )
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    w = _record_watchers(monkeypatch)

    await _run(h, _request(task="x"))

    handoff_id = h.handoffs_created[0][0]
    w.keep_alive.assert_called_once_with("sess-1")
    w.auto_resolve.assert_called_once_with(handoff_id, "sess-1", "u1")


# ---------------------------------------------------------------------------
# persist_run_outcome — analytics attribution
# ---------------------------------------------------------------------------


async def test_finished_run_is_captured_against_the_user_who_ran_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A graph-background run has no request context, so the id has to be passed explicitly -- otherwise the event lands on an anonymous profile and never shows up in that user's funnel."""
    captured: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        jr,
        "capture_event",
        lambda user_id, event, props: captured.append((user_id, event, props)),
    )
    h = _install(monkeypatch, result=_result(BrowserSessionStatus.COMPLETED, True, "done", steps=3))

    await _run(h, _request(task="x"))

    (user_id, event, props) = captured[0]
    assert len(captured) == 1
    assert user_id == "u1"
    assert event == AnalyticsEvents.BROWSER_TASK_FINISHED
    assert props["status"] == "completed"
    assert props["success"] is True
    assert props["steps"] == 3


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    captured: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        jr,
        "capture_event",
        lambda user_id, event, props: captured.append((user_id, event, props)),
    )
    return captured


async def test_anonymous_run_is_not_captured_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """No user id means no profile to attribute to -- capturing anyway would invent an anonymous person per background run and inflate the funnel."""
    captured = _capture(monkeypatch)
    h = _install(monkeypatch)

    await _run(h, _request(user_id=""))

    assert captured == []


async def test_capture_source_falls_back_to_web_when_the_run_has_no_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture(monkeypatch)
    h = _install(monkeypatch)

    await _run(h, _request(source_category=None))

    assert captured[0][2]["source"] == "web"


async def test_capture_source_is_the_surface_the_run_came_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture(monkeypatch)
    h = _install(monkeypatch)

    await _run(h, _bot_request(task="x"))

    assert captured[0][2]["source"] == "bot"


async def test_capture_duration_measures_the_run_not_the_whole_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """duration_ms is milliseconds between starting and finishing the agent loop; the clock is read after the session is open, so setup time is not charged to the run."""
    captured = _capture(monkeypatch)
    h = _install(monkeypatch)
    # Reads, in order: the thread mirror's start, run_t0, then the persist clock.
    ticks = iter([10.0, 100.0, 100.75])
    monkeypatch.setattr(jr, "perf_counter", lambda: next(ticks))

    await _run(h, _request(task="x"))

    assert captured[0][2]["duration_ms"] == 750


# ---------------------------------------------------------------------------
# execute_browser_job — per-user fingerprint seed
# ---------------------------------------------------------------------------


async def test_run_presents_the_users_own_device_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the canvas/audio seed to the user for the run and release it after; use the raw coroutine, not ainvoke, since the seed rides a contextvar that a task-based call would only see a copy of."""
    seen: list[int] = []

    async def body(h: Harness) -> BrowserResultSnapshot:
        seen.append(current_fingerprint_seed())
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    h = _install(monkeypatch, run_body=body)
    before = current_fingerprint_seed()

    await _run(h, _request())

    assert seen == [seed_for_user("u1")]
    assert seen[0] != before
    assert current_fingerprint_seed() == before


async def test_fingerprint_seed_is_released_even_when_the_session_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A leaked seed would make every later run in this context impersonate the user whose run happened to blow up."""
    h = _install(monkeypatch, session_error=BrowserUnavailableError("host is down"))
    before = current_fingerprint_seed()

    await _run(h, _request())

    assert current_fingerprint_seed() == before


# ---------------------------------------------------------------------------
# BrowserThreadMirror — the "Browser" group in the chat tool thread
# ---------------------------------------------------------------------------


def _mirror() -> tuple[jr.BrowserThreadMirror, list[dict[str, Any]]]:
    writes: list[dict[str, Any]] = []

    async def publish(payload: dict[str, Any]) -> None:
        writes.append(payload)

    return jr.BrowserThreadMirror(publish), writes


def _session_snapshot(session_id: str | None = "sess-1") -> BrowserSessionSnapshot:
    return BrowserSessionSnapshot(
        task="x", status=BrowserSessionStatus.RUNNING, session_id=session_id
    )


async def test_a_fresh_mirror_belongs_to_no_group() -> None:
    """None, not a falsy placeholder: the group id is emitted as subagent_id on every row, so an empty string would ship as a real, unattachable group the moment a guard let it through."""
    mirror, _ = _mirror()

    assert mirror._group_id is None


async def test_a_closed_mirror_belongs_to_no_group_again() -> None:
    """Closing returns the mirror to its fresh state so the next session opens a real group -- not one carrying a leftover placeholder."""
    mirror, _ = _mirror()

    await mirror.mirror(_session_snapshot())
    await mirror.mirror(_result(BrowserSessionStatus.COMPLETED, True, "done"))

    assert mirror._group_id is None


async def test_mirror_opens_a_browser_group_keyed_on_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The group is what nests the browser agent's own actions under one "Browser" row instead of leaving them loose in the thread."""
    mirror, writes = _mirror()

    await mirror.mirror(_session_snapshot())

    (start,) = [w["subagent_start"] for w in writes]
    assert start["subagent_id"] == "browser:sess-1"
    assert start["subagent_name"] == "Browser"
    assert start["agent_type"] == "spawned"
    assert start["tool_category"] == "browser"


async def test_mirror_without_a_session_id_opens_no_group_and_drops_its_rows() -> None:
    """No session id means no stable group id, so opening one would strand every action row under an id the result can never close."""
    mirror, writes = _mirror()

    await mirror.mirror(_session_snapshot(session_id=None))
    await mirror.mirror(
        BrowserStepSnapshot(index=1, goal="g", actions=[BrowserAction(name="click", inputs={})])
    )
    await mirror.mirror(_result(BrowserSessionStatus.COMPLETED, True, "done"))

    assert writes == []


async def test_mirror_opens_the_group_once_for_a_re_reported_session() -> None:
    """The runner re-emits the session card as its status changes; a second subagent_start would render a duplicate Browser row."""
    mirror, writes = _mirror()

    await mirror.mirror(_session_snapshot())
    await mirror.mirror(_session_snapshot(session_id="sess-2"))

    starts = [w["subagent_start"] for w in writes if "subagent_start" in w]
    assert [s["subagent_id"] for s in starts] == ["browser:sess-1"]


async def test_mirror_numbers_each_action_within_its_step() -> None:
    """Rows are keyed {group}:{step}:{position}, which is what a later output frame matches on -- two actions in one step must not collide."""
    mirror, writes = _mirror()

    await mirror.mirror(_session_snapshot())
    await mirror.mirror(
        BrowserStepSnapshot(
            index=4,
            goal="fill it in",
            actions=[
                BrowserAction(name="click", inputs={"index": 1}),
                BrowserAction(name="input_text", inputs={"index": 2}),
            ],
        )
    )

    rows = [w["tool_data"] for w in writes if "tool_data" in w]
    assert [r["data"]["tool_call_id"] for r in rows] == ["browser:sess-1:4:0", "browser:sess-1:4:1"]
    # The tag is what nests each row under the run's Browser group; untagged, the
    # actions render as loose top-level rows in the thread.
    assert [r["subagent_id"] for r in rows] == ["browser:sess-1", "browser:sess-1"]


async def test_mirror_tags_each_action_output_with_the_group_it_belongs_to() -> None:
    """Without the subagent id the output frame renders outside the Browser group, detached from the row it describes."""

    mirror, writes = _mirror()

    await mirror.mirror(_session_snapshot())
    await mirror.mirror(
        BrowserStepSnapshot(index=1, goal="g", actions=[BrowserAction(name="click", inputs={})])
    )
    await mirror.results(1, [BrowserActionOutput(position=0, output="ok")])

    (output,) = [w["tool_output"] for w in writes if "tool_output" in w]
    assert output == {
        "tool_call_id": "browser:sess-1:1:0",
        "output": "ok",
        "subagent_id": "browser:sess-1",
    }


async def test_mirror_closes_the_group_on_the_result_with_the_run_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Construction, then the group opening (which restarts the clock), then close:
    # the reported duration is the group's lifetime, not the mirror's.
    ticks = iter([0.0, 1.0, 3.5])
    monkeypatch.setattr(jr, "perf_counter", lambda: next(ticks))
    mirror, writes = _mirror()

    await mirror.mirror(_session_snapshot())
    await mirror.mirror(_result(BrowserSessionStatus.COMPLETED, True, "done"))

    (end,) = [w["subagent_end"] for w in writes if "subagent_end" in w]
    assert end["subagent_id"] == "browser:sess-1"
    assert end["duration_ms"] == 2500


async def test_mirror_closes_the_group_only_once() -> None:
    """The result card can be re-emitted; a second subagent_end would close a group that no longer exists and collapse the wrong row."""
    mirror, writes = _mirror()

    await mirror.mirror(_session_snapshot())
    final = _result(BrowserSessionStatus.COMPLETED, True, "done")
    await mirror.mirror(final)
    await mirror.mirror(final)

    assert len([w for w in writes if "subagent_end" in w]) == 1


async def test_mirror_result_without_an_open_group_closes_nothing() -> None:
    mirror, writes = _mirror()

    await mirror.mirror(_result(BrowserSessionStatus.FAILED, False, "never started"))

    assert writes == []


# ---------------------------------------------------------------------------
# the job's own feed — what a relay in another process replays
# ---------------------------------------------------------------------------


async def test_a_card_reaches_the_jobs_feed_in_the_shape_the_wire_expects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normalized once, at the producer: the relay republishes these frames verbatim, so an un-normalized card would reach the browser card renderer as an unknown event and never render."""

    final = _result(BrowserSessionStatus.COMPLETED, True, "done")

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(BrowserStepSnapshot(index=1, goal="open", url="https://x"))
        await h.emit(final)
        return final

    _install(monkeypatch, run_body=body)
    published: list[tuple[str, dict[str, Any]]] = []

    async def _publish(job_id: str, payload: dict[str, Any]) -> None:
        published.append((job_id, payload))

    monkeypatch.setattr(jr, "publish_job_event", _publish)

    await jr.execute_browser_job(_request(task="x"))

    assert [job_id for job_id, _ in published] == ["job-1", "job-1"]
    card, final = (payload["tool_data"] for _, payload in published)
    assert card["tool_name"] == BROWSER_TASK_EVENT
    assert card["data"]["goal"] == "open"
    assert card["timestamp"]
    assert final["data"]["kind"] == "result"


async def test_an_already_normalized_mirror_frame_is_published_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normalizing twice would nest the entry inside itself; the mirror already emits the wire shape."""

    async def body(h: Harness) -> BrowserResultSnapshot:
        await h.emit(
            BrowserSessionSnapshot(task="x", status=BrowserSessionStatus.RUNNING, session_id="s1")
        )
        return _result(BrowserSessionStatus.COMPLETED, True, "done")

    _install(monkeypatch, run_body=body)
    published: list[dict[str, Any]] = []

    async def _publish(job_id: str, payload: dict[str, Any]) -> None:
        published.append(payload)

    monkeypatch.setattr(jr, "publish_job_event", _publish)

    await jr.execute_browser_job(_request(task="x"))

    (start,) = [p["subagent_start"] for p in published if "subagent_start" in p]
    assert start["subagent_id"] == "browser:s1"


# ---------------------------------------------------------------------------
# the job's durable state and its cancel flag
# ---------------------------------------------------------------------------


async def test_the_open_session_is_written_into_the_job_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A joiner and a restarted API read the run's live-view link off this state, not off the turn that started it."""
    h = _install(monkeypatch)

    await _run(h, _request(task="book a table"))

    (state,) = h.states
    assert state == BrowserJobState(
        job_id="job-1",
        status=BrowserJobStatus.RUNNING,
        task="book a table",
        session_id="sess-1",
        live_view_url="https://live/abc",
    )


async def test_a_run_whose_turn_has_ended_still_stops_on_its_own_cancel_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stop after the turn is over has no stream signal left to set, so the job's own flag is the only thing the run can hear."""

    async def body(h: Harness) -> BrowserResultSnapshot:
        assert await h.is_cancelled() is True
        return _result(BrowserSessionStatus.CANCELLED, False, "stopped")

    h = _install(monkeypatch, run_body=body, job_cancelled=True)

    await _run(h, _request(stream_id=None))

    assert h.job_cancel_checks == ["job-1"]
    assert h.cancel_checks == []
