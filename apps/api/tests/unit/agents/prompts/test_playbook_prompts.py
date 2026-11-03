"""The playbook check brief's examples, held to the validator that judges a real write.

The brief once showed an activate_integration step the validator does not
know, and every run that copied it was refused (prod, Oct 2026). These run
each example through validate_playbook against the real tool registry and a
run that made exactly the example's calls, so the two cannot disagree again.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.prompts.playbook_prompts import (
    PLAYBOOK_CHECK_BRIEF,
    PLAYBOOK_EXAMPLE,
    PLAYBOOK_FOR_EACH_EXAMPLE,
)
from app.agents.tools.core.registry import ToolRegistry
from app.models.playbook_models import ForEachStep, PlaybookBody, ToolStep
from app.services.workflow.playbook.parser import RecordedResult, dump_playbook, validate_playbook

PARSER = "app.services.workflow.playbook.parser"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"


@pytest.fixture(scope="module")
def registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry._initialize_categories()
    return registry


def _concrete(value: object) -> object:
    """Return what the authoring run sent where the example holds a slot or placeholder."""
    if isinstance(value, dict):
        if "$ask" in value:
            return "written at authoring"
        return {key: _concrete(item) for key, item in value.items()}
    if isinstance(value, str) and value.startswith("$"):
        return "thread-1"
    return value


def _run_that_made(body: PlaybookBody) -> list[RecordedResult]:
    calls = []
    for step in body.steps:
        assert isinstance(step, ToolStep | ForEachStep)
        calls.append(
            RecordedResult(
                tool_name=step.tool,
                args={key: _concrete(value) for key, value in step.args.items()},
                result={"successful": True, "data": {"items": [{"id": "thread-1"}]}},
            )
        )
    return calls


@pytest.mark.parametrize(
    "body", [PLAYBOOK_EXAMPLE, PLAYBOOK_FOR_EACH_EXAMPLE], ids=["flat", "for_each"]
)
async def test_a_run_that_made_the_examples_calls_can_write_the_example(
    body: PlaybookBody, registry: ToolRegistry
) -> None:
    with patch(f"{PARSER}.get_tool_registry", new=AsyncMock(return_value=registry)):
        validation = await validate_playbook(body, USER_ID, _run_that_made(body))
    assert validation.issues == []


@pytest.mark.parametrize(
    "body", [PLAYBOOK_EXAMPLE, PLAYBOOK_FOR_EACH_EXAMPLE], ids=["flat", "for_each"]
)
def test_the_brief_shows_each_example_as_read_playbook_renders_it(body: PlaybookBody) -> None:
    assert dump_playbook(body) in PLAYBOOK_CHECK_BRIEF


def test_the_brief_never_shows_activate_integration_as_a_step() -> None:
    assert "tool: activate_integration" not in PLAYBOOK_CHECK_BRIEF
