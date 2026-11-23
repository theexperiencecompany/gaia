"""A scout report's step becomes the step the playbook runner executes."""

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from app.models.playbook_models import MAX_FOR_EACH_ITEMS, ForEachStep, PlaybookBody, ToolStep
from app.models.scout_models import ScoutCriteria, ScoutDocument, ScoutStatus, ScoutStep
from tests.factories import make_user_id

_PLAYBOOK = PlaybookBody(
    description="open issues",
    steps=[ToolStep(id="assigned", tool="list_issues")],
    result_brief="-",
)
_CRITERIA = ScoutCriteria(
    needs_you="open issues assigned to the user", important="due today", leave_out="closed ones"
)


def _scout(
    status: ScoutStatus, playbook: PlaybookBody | None, criteria: ScoutCriteria | None
) -> ScoutDocument:
    return ScoutDocument(
        user_id=make_user_id(),
        integration_id="linear",
        status=status,
        tool_fingerprint="fp-1",
        playbook=playbook,
        criteria=criteria,
        learned_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


class TestAWatchIsComplete:
    @pytest.mark.parametrize(
        ("playbook", "criteria"), [(None, _CRITERIA), (_PLAYBOOK, None), (None, None)]
    )
    def test_a_watching_scout_missing_its_playbook_or_criteria_is_refused(
        self, playbook: PlaybookBody | None, criteria: ScoutCriteria | None
    ) -> None:
        with pytest.raises(ValidationError) as raised:
            _scout(ScoutStatus.WATCHING, playbook, criteria)

        assert raised.value.errors()[0]["msg"] == (
            "Value error, a watching scout needs its playbook and its criteria"
        )

    def test_a_complete_watch_is_kept(self) -> None:
        scout = _scout(ScoutStatus.WATCHING, _PLAYBOOK, _CRITERIA)

        assert (scout.playbook, scout.criteria) == (_PLAYBOOK, _CRITERIA)

    def test_a_scout_that_is_not_watching_needs_neither(self) -> None:
        scout = _scout(ScoutStatus.LEARN_FAILED, None, None)

        assert (scout.playbook, scout.criteria) == (None, None)


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
