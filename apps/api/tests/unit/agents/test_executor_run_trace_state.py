"""The state a run's trace ends in, from how the executor run or its background subagent ended."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.agents.core.background.executor_runner import _trace_state as executor_trace_state
from app.agents.core.subagents.delegation import _trace_state as subagent_trace_state
from app.agents.core.subagents.subagent_runner import SubagentOutcome
from app.constants.executor import EXECUTOR_PAUSED
from app.models.run_trace_models import RunState


@pytest.mark.parametrize(
    ("result_type", "stopped", "state"),
    [
        ("final", False, RunState.FINISHED),
        ("final", True, RunState.CANCELLED),
        ("error", False, RunState.FAILED),
        (EXECUTOR_PAUSED, False, RunState.PAUSED),
    ],
)
def test_an_executor_run_ends_in_the_state_its_result_names(
    result_type: str, stopped: bool, state: RunState
) -> None:
    assert executor_trace_state(result_type, stopped=stopped) is state


@pytest.mark.parametrize(
    ("outcome", "state"),
    [
        (None, RunState.FAILED),
        (SimpleNamespace(paused=True, stopped=False), RunState.PAUSED),
        (SimpleNamespace(paused=False, stopped=True), RunState.CANCELLED),
        (SimpleNamespace(paused=False, stopped=False), RunState.FINISHED),
    ],
    ids=["raised", "parked", "stopped", "done"],
)
def test_a_background_subagent_run_ends_in_the_state_its_outcome_names(
    outcome: SimpleNamespace | None, state: RunState
) -> None:
    assert subagent_trace_state(cast("SubagentOutcome | None", outcome)) is state
