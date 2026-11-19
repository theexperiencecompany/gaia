"""A scout report's step becomes the step the playbook runner executes."""

import pytest

from app.models.playbook_models import MAX_FOR_EACH_ITEMS, ForEachStep, ToolStep
from app.models.scout_models import ScoutStep


class TestScoutStepToStep:
    def test_a_plain_call_becomes_a_tool_step(self) -> None:
        step = ScoutStep(id="open", tool="list_issues", args={"assignee": "me"})

        assert step.to_step() == ToolStep(id="open", tool="list_issues", args={"assignee": "me"})

    def test_a_repeated_call_becomes_a_for_each_step_keeping_every_field(self) -> None:
        step = ScoutStep(
            id="details",
            tool="get_issue",
            args={"id": "$item"},
            for_each="$steps.open.items",
            max_items=5,
        )

        assert step.to_step() == ForEachStep(
            id="details",
            tool="get_issue",
            args={"id": "$item"},
            for_each="$steps.open.items",
            max_items=5,
        )

    @pytest.mark.parametrize(("step_id", "named"), [("details", "details"), ("", "get_issue")])
    def test_a_for_each_with_no_cap_is_refused_naming_the_step(
        self, step_id: str, named: str
    ) -> None:
        step = ScoutStep(id=step_id, tool="get_issue", for_each="$steps.open.items")

        with pytest.raises(ValueError) as raised:
            step.to_step()

        assert str(raised.value) == (
            f"step {named}: for_each needs max_items, at most {MAX_FOR_EACH_ITEMS}, "
            "so the replay's cost is known before it runs"
        )
