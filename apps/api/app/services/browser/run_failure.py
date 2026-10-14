"""A finished browser run on its wide event, with the typed reason it did not succeed.

The runner decides that reason where the run ended (a stop, a budget, a handoff,
the agent's own history) and hands it over with the run; nothing is read back
off the event.
"""

from app.services.browser.run_contract import FinishedRun
from shared.py.wide_events import log


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
    if run.failure is not None:
        log.fail(run.failure)
