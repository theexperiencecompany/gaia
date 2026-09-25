"""The reason an unsuccessful browser run's wide event carries, from the facts the run left."""

from typing import Any

import pytest

from app.constants.browser import BrowserRunFailure, BrowserSessionStatus
from app.schemas.browser import BrowserResultSnapshot
from app.services.browser.run_contract import FinishedRun
from app.services.browser.run_failure import record_run_result
from shared.py.wide_events import log, log_context

pytestmark = pytest.mark.unit


async def _event_after(
    result: BrowserResultSnapshot, facts: dict[str, Any] | None = None
) -> dict[str, Any]:
    async with log_context("run_browser_job"):
        if facts:
            log.set_ns("browser", **facts)
        record_run_result(
            FinishedRun(result=result, session_id="s1", actions=0, engine_fallback=False, run_ms=1)
        )
        return dict(log.get())


def _failed(status: BrowserSessionStatus = BrowserSessionStatus.FAILED) -> BrowserResultSnapshot:
    return BrowserResultSnapshot(status=status, success=False, summary="no")


@pytest.mark.parametrize(
    ("result", "facts", "reason"),
    [
        (_failed(BrowserSessionStatus.CANCELLED), None, BrowserRunFailure.CANCELLED),
        (_failed(), {"handoff_result": "timeout"}, BrowserRunFailure.HANDOFF_TIMEOUT),
        (_failed(), {"blocked": "never_opened"}, BrowserRunFailure.NEVER_OPENED),
        (_failed(), {"blocked": "blocked"}, BrowserRunFailure.BLOCKED),
        (_failed(), {"llm_error": "JevGatewayError"}, BrowserRunFailure.LLM_ERROR),
        (_failed(), None, BrowserRunFailure.GOAL_NOT_ACHIEVED),
    ],
)
async def test_an_unsuccessful_run_is_failed_with_the_reason_its_facts_give(
    result: BrowserResultSnapshot, facts: dict[str, Any] | None, reason: BrowserRunFailure
) -> None:
    event = await _event_after(result, facts)

    assert event["outcome"] == "failed"
    assert event["reason"] == reason


async def test_a_reason_the_run_already_gave_is_kept() -> None:
    async with log_context("run_browser_job"):
        log.fail(BrowserRunFailure.TASK_TIMEOUT)
        record_run_result(
            FinishedRun(
                result=_failed(), session_id="s1", actions=0, engine_fallback=True, run_ms=1
            )
        )
        event = dict(log.get())

    assert event["reason"] == BrowserRunFailure.TASK_TIMEOUT
    assert event["browser"]["engine_fallback"] is True


async def test_a_successful_run_carries_no_reason() -> None:
    result = BrowserResultSnapshot(
        status=BrowserSessionStatus.COMPLETED, success=True, summary="ok"
    )

    event = await _event_after(result, {"llm_error": "JevGatewayError"})

    assert "reason" not in event
    assert event["browser"]["success"] is True


async def test_a_finished_run_puts_its_status_steps_actions_and_run_time_on_the_event() -> None:
    result = BrowserResultSnapshot(
        status=BrowserSessionStatus.FAILED, success=False, summary="no", steps=7
    )

    async with log_context("run_browser_job"):
        record_run_result(
            FinishedRun(
                result=result, session_id="s1", actions=23, engine_fallback=False, run_ms=4200
            )
        )
        browser = dict(log.get())["browser"]

    assert browser["status"] == "failed"
    assert browser["steps"] == 7
    assert browser["actions"] == 23
    assert browser["run_ms"] == 4200
    assert browser["engine_fallback"] is False
