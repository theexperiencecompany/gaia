"""A direct dev run that parks on a HIL approval must fail loud, not answer empty.

When a run pauses, ``SubagentOutcome.text`` is ``""`` — returning it would present
an empty string as the agent's answer. A direct run has no approval channel to
resume on, so the only honest outcome is an error naming that.
"""

import pytest

from app.agents.core.subagents.subagent_runner import SubagentOutcome
from app.services.dev_agent_service import _reject_pause
from app.utils.errors import AppError


def test_a_paused_outcome_raises_conflict_instead_of_returning_empty_text() -> None:
    paused = SubagentOutcome(text="", interrupt={"type": "hil_approval", "approval_id": "a1"})

    with pytest.raises(AppError) as excinfo:
        _reject_pause(paused, "executor_agent")

    assert excinfo.value.status_code == 409


def test_a_finished_outcome_passes_through() -> None:
    assert _reject_pause(SubagentOutcome(text="done"), "executor_agent") is None
