"""A finished run's wide event carries the reason the runner gave it, and a successful one none."""

from typing import Any

import pytest

from app.constants.browser import BrowserRunFailure, BrowserSessionStatus
from app.schemas.browser import BrowserResultSnapshot
from app.services.browser.run_contract import FinishedRun
from app.services.browser.run_failure import record_run_result
from shared.py.wide_events import log, log_context

pytestmark = pytest.mark.unit


async def _event_after(success: bool, failure: BrowserRunFailure | None) -> dict[str, Any]:
    result = BrowserResultSnapshot(
        status=BrowserSessionStatus.COMPLETED if success else BrowserSessionStatus.FAILED,
        success=success,
        summary="s",
        steps=3,
    )
    async with log_context("run_browser_job"):
        record_run_result(
            FinishedRun(
                result=result,
                session_id="s1",
                actions=5,
                engine_fallback=True,
                run_ms=1,
                failure=failure,
            )
        )
        return dict(log.get())


async def test_an_unsuccessful_run_is_failed_with_the_reason_it_was_given() -> None:
    event = await _event_after(False, BrowserRunFailure.STEP_LIMIT)

    assert (event["outcome"], event["reason"]) == ("failed", BrowserRunFailure.STEP_LIMIT)
    assert (event["browser"]["steps"], event["browser"]["actions"]) == (3, 5)


async def test_a_successful_run_is_not_failed() -> None:
    event = await _event_after(True, None)

    assert "reason" not in event
    assert event["browser"]["success"] is True
