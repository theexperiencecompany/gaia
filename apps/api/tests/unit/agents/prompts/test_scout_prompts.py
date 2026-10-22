"""The scout prompts: a learn run is asked for its app's own terms, never handed an example kind."""

import pytest

from app.agents.prompts.scout_prompts import SCOUT_LEARN_PROMPT, SIGNAL_JUDGE_PROMPT
from app.models.scout_models import Signal

_LEARN = SCOUT_LEARN_PROMPT.format(app="Todoist", today="2026-10-22", timezone="Asia/Kolkata")


@pytest.mark.regression
def test_no_example_kind_reaches_the_learn_run() -> None:
    """Personal Todoist tasks came back as "issue assigned to you", the prompt's own example."""
    for leaked in ("issue", "assigned to you"):
        assert leaked not in _LEARN
        assert leaked not in (Signal.model_fields["kind"].description or "")


def test_the_learn_run_is_asked_for_kinds_in_the_apps_own_terms() -> None:
    assert "in a few words of Todoist's own terms" in _LEARN


def test_the_learn_run_is_asked_for_the_criteria_its_replays_are_judged_by() -> None:
    assert '"criteria": "<how to tell, in Todoist, which items need this user' in _LEARN


def test_the_judge_prompt_takes_every_app_criteria_and_item_in_one_call() -> None:
    prompt = SIGNAL_JUDGE_PROMPT.format(
        today="2026-10-22", timezone="UTC", criteria="- A: x\n- B: y", items="1. one\n2. two"
    )

    assert "- A: x\n- B: y" in prompt
    assert "1. one\n2. two" in prompt
    assert "Give EVERY number one verdict" in prompt
