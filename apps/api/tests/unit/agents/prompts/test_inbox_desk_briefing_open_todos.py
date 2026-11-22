"""The desk's briefing lists every open action task, including those its own run created."""

import pytest

from app.agents.prompts.inbox_desk_prompts import INBOX_DESK_RUN_GUIDANCE
from app.constants.tasks import TaskFlag


@pytest.mark.regression
def test_needs_you_lists_the_action_todos_this_run_created_even_when_a_briefing_named_them() -> (
    None
):
    """Regression: a run opened Kotak and Cloudflare action todos, then left them out as old news."""
    assert (
        "Needs you and Waiting on others list what is open now, in every briefing, even when an "
        "earlier one listed it, since the user still owes it or still waits, the subtasks this "
        "run created included"
    ) in INBOX_DESK_RUN_GUIDANCE
    assert (
        f"\nNeeds you: your subtasks flagged {TaskFlag.ACTION_NEEDED.value} first"
        in INBOX_DESK_RUN_GUIDANCE
    )
