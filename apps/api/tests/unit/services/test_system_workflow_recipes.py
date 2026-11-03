"""The playbooks system workflows ship with: valid against the real registry, stored on provision and reset."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.core.registry import ToolRegistry
from app.agents.tools.execute.unwrap import unwrap_execute_call
from app.models.calendar_models import GetEventInput
from app.models.composio_schemas.google_calendar import GoogleCalendarEventStartingSoonPayload
from app.models.playbook_models import PlaybookBody, PlaybookDocument, ToolStep
from app.models.workflow_models import WorkflowStep
from app.services.system_workflows.definitions import (
    SYSTEM_RECIPES,
    SYSTEM_WORKFLOWS_BY_INTEGRATION,
)
from app.services.system_workflows.recipes import install_recipe
from app.services.workflow.playbook.evaluator import PlaybookUser, RunContext, resolve_args
from app.services.workflow.playbook.parser import validate_playbook
from app.services.workflow.playbook.workflow_hash import workflow_hash

PARSER = "app.services.workflow.playbook.parser"
RECIPES = "app.services.system_workflows.recipes"
USER_ID = "507f1f77bcf86cd799439011"
#: The custom tools a recipe reaches through execute, by the input model they validate against.
LOCAL_INPUTS = {"GOOGLECALENDAR_CUSTOM_GET_EVENT": GetEventInput}
STARTING_SOON = {
    "event_id": "evt_42",
    "calendar_id": "dana@acme.com",
    "summary": "Design review",
    "start_time": "2026-11-20T10:00:00+00:00",
}


@pytest.fixture
def registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry._initialize_categories()
    return registry


@pytest.mark.parametrize("key", sorted(SYSTEM_RECIPES))
async def test_each_recipe_validates_against_the_real_registry(
    key: str, registry: ToolRegistry
) -> None:
    body = SYSTEM_RECIPES[key]()

    with patch(f"{PARSER}.get_tool_registry", new=AsyncMock(return_value=registry)):
        validation = await validate_playbook(body, USER_ID)

    assert validation.issues == []


@pytest.mark.parametrize("key", sorted(SYSTEM_RECIPES))
def test_every_call_a_recipe_proxies_takes_the_args_its_tool_accepts(key: str) -> None:
    proxied = [
        unwrap_execute_call(step.tool, step.args)
        for step in SYSTEM_RECIPES[key]().steps
        if isinstance(step, ToolStep) and step.tool == "execute"
    ]

    assert proxied, "a calendar recipe reaches the calendar through execute"
    for name, data in proxied:
        LOCAL_INPUTS[name].model_validate(data)


def test_every_recipe_belongs_to_a_shipped_system_workflow() -> None:
    shipped = {key for entries in SYSTEM_WORKFLOWS_BY_INTEGRATION.values() for key, _ in entries}

    assert set(SYSTEM_RECIPES) <= shipped


def test_the_reminder_looks_up_the_very_event_the_trigger_is_about() -> None:
    step = SYSTEM_RECIPES["calendar:meeting_reminder"]().steps[0]
    assert isinstance(step, ToolStep)
    GoogleCalendarEventStartingSoonPayload.model_validate(STARTING_SOON)
    context = RunContext(
        user=PlaybookUser(email="dana@acme.com", name="Dana", timezone="UTC"),
        now=datetime(2026, 11, 20, 9, 50, tzinfo=UTC),
        trigger={"trigger_type": "integration", "trigger_data": STARTING_SOON},
    )

    resolved = resolve_args(step.args, context)

    assert resolved["data"] == {"events": [{"event_id": "evt_42", "calendar_id": "dana@acme.com"}]}


async def test_installing_a_recipe_stores_it_against_the_workflow_as_provisioned() -> None:
    steps = [WorkflowStep(id="s1", title="Prepare", category="gaia", description="d")]
    store = MagicMock()
    store.upsert_for_workflow = AsyncMock(side_effect=lambda document: document)

    with patch(f"{RECIPES}.playbook_repository", store):
        stored = await install_recipe(
            "calendar:meeting_reminder", "wf_1", USER_ID, "Send a reminder.", steps
        )

    assert isinstance(stored, PlaybookDocument)
    assert stored.workflow_hash == workflow_hash("Send a reminder.", steps)
    assert stored.authored_run == "recipe:calendar:meeting_reminder"
    expected = SYSTEM_RECIPES["calendar:meeting_reminder"]()
    assert (
        PlaybookBody.model_validate(stored.model_dump(include=set(PlaybookBody.model_fields)))
        == expected
    )


async def test_a_key_that_ships_no_recipe_stores_nothing() -> None:
    store = MagicMock()
    store.upsert_for_workflow = AsyncMock()

    with patch(f"{RECIPES}.playbook_repository", store):
        stored = await install_recipe("gmail:email_intelligence", "wf_1", USER_ID, "p", [])

    assert stored is None
    store.upsert_for_workflow.assert_not_awaited()
