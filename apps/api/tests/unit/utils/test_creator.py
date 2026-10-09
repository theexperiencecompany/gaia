"""Unit tests for app.utils.creator."""

import pytest

from app.constants.vfs import SYSTEM_USER_ID
from app.models.workflow_models import PublicWorkflowRow, WorkflowCreatorInfo
from app.utils.creator import SYSTEM_CREATOR_NAME, UNKNOWN_CREATOR_NAME, format_creator


def _row(
    created_by: str, creator_info: list[WorkflowCreatorInfo] | None = None
) -> PublicWorkflowRow:
    return PublicWorkflowRow.model_validate(
        {
            "user_id": created_by,
            "created_by": created_by,
            "title": "Morning briefing",
            "description": "d",
            "prompt": "do the thing",
            "steps": [{"title": "step", "category": "gmail", "description": "d"}],
            "trigger_config": {"type": "manual"},
            "creator_info": creator_info or [],
        }
    )


@pytest.mark.parametrize(
    ("created_by", "name"),
    [(SYSTEM_USER_ID, SYSTEM_CREATOR_NAME), ("64abc123def4567890abcdef", UNKNOWN_CREATOR_NAME)],
    ids=["template-owner", "deleted-user"],
)
def test_a_creator_with_no_user_row_falls_back_by_who_owns_it(created_by: str, name: str) -> None:
    assert format_creator(_row(created_by)) == {"id": created_by, "name": name, "avatar": None}


def test_a_joined_user_row_names_the_creator() -> None:
    info = WorkflowCreatorInfo(name="Ada", picture="https://example.com/a.png")
    assert format_creator(_row("64abc123def4567890abcdef", [info]))["name"] == "Ada"
