"""The morning brief lists every open action todo the desk opened, its own run's included."""

import pytest

from app.agents.prompts.todo_prompts import INBOX_DESK_RUN_GUIDANCE
from app.constants import todos as todo_constants


@pytest.mark.regression
def test_the_desk_opens_an_action_todo_the_brief_lists_as_needing_the_user() -> None:
    """Regression: a run opened Kotak and Cloudflare action todos, then left them out as old news."""
    assert f'labels=["{todo_constants.ACTION_NEEDED_LABEL}"]' in INBOX_DESK_RUN_GUIDANCE
    assert todo_constants.ACTION_NEEDED_LABEL in todo_constants.NEEDS_USER_LABELS
