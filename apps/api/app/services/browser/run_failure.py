"""A finished browser run on its wide event, with the typed reason it did not succeed.

The decision points (runner, Jev, handoffs) leave facts on the event's browser
namespace as the run goes; this reads them back once the run has ended.
"""

from pydantic import BaseModel, ConfigDict

from app.constants.browser import BrowserRunFailure, BrowserSessionStatus, HandoffStatus
from app.schemas.browser import BrowserResultSnapshot
from app.services.browser.run_contract import FinishedRun
from shared.py.wide_events import OUTCOME_FAILED, log


class _RunFacts(BaseModel):
    """What the run recorded about how it went, as the browser namespace holds it."""

    model_config = ConfigDict(extra="ignore")

    blocked: BrowserRunFailure | None = None
    llm_error: str | None = None
    handoff_result: HandoffStatus | None = None


class _RunEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    outcome: str | None = None
    browser: _RunFacts = _RunFacts()


def record_run_result(run: FinishedRun) -> None:
    """Put a finished run on its event; one that did not succeed is failed with its reason."""
    result = run.result
    log.set_ns(
        "browser",
        status=result.status.value,
        success=result.success,
        steps=result.steps,
        actions=run.actions,
        run_ms=run.run_ms,
        engine_fallback=run.engine_fallback,
    )
    if result.success:
        return
    event = _RunEvent.model_validate(log.get())
    # A decision point that ended the run already said why.
    if event.outcome != OUTCOME_FAILED:
        log.fail(_unsuccessful_reason(result, event.browser))


def _unsuccessful_reason(result: BrowserResultSnapshot, facts: _RunFacts) -> BrowserRunFailure:
    if result.status is BrowserSessionStatus.CANCELLED:
        return BrowserRunFailure.CANCELLED
    if facts.handoff_result is HandoffStatus.TIMEOUT:
        return BrowserRunFailure.HANDOFF_TIMEOUT
    if facts.blocked is not None:
        return facts.blocked
    if facts.llm_error is not None:
        return BrowserRunFailure.LLM_ERROR
    return BrowserRunFailure.GOAL_NOT_ACHIEVED
