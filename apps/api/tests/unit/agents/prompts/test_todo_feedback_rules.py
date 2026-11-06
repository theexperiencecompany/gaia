"""Where the user's feedback on a todo is kept is written once and read in every place that teaches it."""

from pathlib import Path

import pytest

import app
from app.agents.prompts import todo_prompts
from app.agents.workspace import operational_docs

pytestmark = pytest.mark.unit

TASK_TRACKING_SKILL = (
    Path(app.__file__).parent / "agents/skills/builtin/gaia-task-tracking/SKILL.md"
)


def test_the_executor_prompt_and_the_manual_carry_the_one_rule() -> None:
    rule = todo_prompts.TODO_FEEDBACK_RULES

    assert rule in todo_prompts.TODO_SYSTEM_PROMPT
    assert rule in operational_docs.TRACKED_TODOS_DOC


@pytest.mark.regression
def test_the_task_tracking_skill_points_to_the_rule_instead_of_restating_it() -> None:
    """Regression: three hand-kept copies of this rule had to be edited in step and could drift."""
    skill = TASK_TRACKING_SKILL.read_text()

    assert "THE USER'S FEEDBACK ON A TODO" in skill
    assert "| Feedback | Where it goes |" not in skill
    assert "update_user_instructions" not in skill
