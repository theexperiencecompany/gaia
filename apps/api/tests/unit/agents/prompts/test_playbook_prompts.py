"""The playbook check brief's examples, held to the builder and validator that judge a real write.

The brief once showed an activate_integration step the validator does not
know, and every run that copied it was refused (prod, Oct 2026). Each example
is a record and the write picked from it; here the write is built over that
record and validated against the real tool registry, as write_playbook does.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.prompts.playbook_prompts import (
    PLAYBOOK_CHECK_BRIEF,
    PLAYBOOK_EXAMPLE_RECORD,
    PLAYBOOK_EXAMPLE_WRITE,
    PLAYBOOK_FOR_EACH_RECORD,
    PLAYBOOK_FOR_EACH_WRITE,
)
from app.agents.tools.core.registry import ToolRegistry
from app.models.playbook_models import ForEachStep, ToolStep
from app.models.workflow_execution_models import RecordedCall
from app.services.workflow.playbook.parser import validate_playbook
from app.services.workflow.playbook.record import PlaybookPick, build_playbook, number_record

PARSER = "app.services.workflow.playbook.parser"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
EXAMPLES = [
    (PLAYBOOK_EXAMPLE_RECORD, PLAYBOOK_EXAMPLE_WRITE),
    (PLAYBOOK_FOR_EACH_RECORD, PLAYBOOK_FOR_EACH_WRITE),
]


@pytest.fixture(scope="module")
def registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry._initialize_categories()
    return registry


@pytest.mark.parametrize(("record", "write"), EXAMPLES, ids=["flat", "for_each"])
async def test_each_example_write_builds_over_its_record_and_validates(
    record: list[RecordedCall], write: dict[str, object], registry: ToolRegistry
) -> None:
    steps = write["steps"]
    assert isinstance(steps, list)
    built = build_playbook(
        str(write["description"]),
        [PlaybookPick.model_validate(step) for step in steps],
        str(write["result_brief"]),
        number_record(record, ()),
    )
    assert built.issues == []
    assert built.body is not None

    with patch(f"{PARSER}.get_tool_registry", new=AsyncMock(return_value=registry)):
        validation = await validate_playbook(built.body, USER_ID, built.sources)
    assert validation.issues == []


def test_the_for_each_example_repeats_one_draft_call_over_the_picked_threads() -> None:
    steps = PLAYBOOK_FOR_EACH_WRITE["steps"]
    assert isinstance(steps, list)
    built = build_playbook(
        "d",
        [PlaybookPick.model_validate(step) for step in steps],
        "r",
        number_record(PLAYBOOK_FOR_EACH_RECORD, ()),
    )
    assert built.body is not None
    fetch, drafts = built.body.steps
    assert isinstance(fetch, ToolStep)
    assert isinstance(drafts, ForEachStep)
    assert drafts.args["tool_name"] == "GMAIL_CREATE_EMAIL_DRAFT"


def test_the_brief_never_shows_activate_integration() -> None:
    assert "activate_integration" not in PLAYBOOK_CHECK_BRIEF
