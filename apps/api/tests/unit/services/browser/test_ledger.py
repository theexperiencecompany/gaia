"""The run's executed-action count: Jev's actions and the agent's own, each counted once."""

import pytest

from app.services.browser.ledger import CallComponent, ExecutedAction, RunLedger

pytestmark = pytest.mark.unit


def test_the_action_count_sums_jevs_actions_and_each_agent_steps_own() -> None:
    ledger = RunLedger()
    ledger.executed(
        ExecutedAction(component=CallComponent.JEV, description="CLICK Submit", duration_ms=10)
    )
    ledger.executed(
        ExecutedAction(component=CallComponent.JEV, description="TYPE_TEXT Name", duration_ms=10)
    )
    ledger.executed(
        ExecutedAction(
            component=CallComponent.AGENT,
            description="input, input, click",
            duration_ms=900,
            count=3,
        )
    )
    ledger.executed(
        ExecutedAction(component=CallComponent.AGENT, description="jev", duration_ms=5000, count=0)
    )

    assert ledger.action_count == 5
