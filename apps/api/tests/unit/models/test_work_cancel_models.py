"""WorkCancelled.combined_with: a Stop's logged and unlogged halves reported as one cancel."""

import pytest

from app.constants.browser import BrowserStopOutcome
from app.models.work_cancel_models import WorkCancelled


def test_both_halves_are_reported_together_each_subagent_once() -> None:
    logged = WorkCancelled(
        executor_stopped=True,
        executor_task_id="t1",
        pending_task_ids=["q1"],
        subagent_ids=["s1", "s2"],
        approval_ids=["a1"],
        replay_ids=["playbook_1"],
    )
    unlogged = WorkCancelled(
        pending_task_ids=["q2"],
        subagent_ids=["s2", "s3"],
        approval_ids=["a2"],
        browser_jobs={"job-1": BrowserStopOutcome.STOPPED},
        replay_ids=["playbook_2"],
    )

    assert logged.combined_with(unlogged) == WorkCancelled(
        executor_stopped=True,
        executor_task_id="t1",
        pending_task_ids=["q1", "q2"],
        subagent_ids=["s1", "s2", "s3"],
        approval_ids=["a1", "a2"],
        browser_jobs={"job-1": BrowserStopOutcome.STOPPED},
        replay_ids=["playbook_1", "playbook_2"],
    )


@pytest.mark.parametrize(("first", "second"), [(True, False), (False, True)])
def test_a_run_either_half_spared_is_reported_spared(first: bool, second: bool) -> None:
    combined = WorkCancelled(executor_spared=first).combined_with(
        WorkCancelled(executor_spared=second)
    )

    assert combined.executor_spared is True
