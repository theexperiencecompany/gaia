"""The calendar system workflows GAIA provisions on connect are built, not just registered.

Same gap as the Gmail definitions: the provisioner's own tests pass a fake
factory, so a typo in these would first surface for a user who had just
connected their calendar.
"""

from __future__ import annotations

import pytest

from app.models.workflow_models import CreateWorkflowRequest, TriggerType
from app.services.system_workflows.definitions import SYSTEM_WORKFLOWS_BY_INTEGRATION
from app.services.system_workflows.definitions.calendar import CALENDAR_SYSTEM_WORKFLOWS


def _built(key: str) -> CreateWorkflowRequest:
    return next(factory() for registered, factory in CALENDAR_SYSTEM_WORKFLOWS if registered == key)


@pytest.mark.unit
class TestCalendarSystemWorkflows:
    def test_the_registry_offers_them_under_the_integration_id(self) -> None:
        assert SYSTEM_WORKFLOWS_BY_INTEGRATION["googlecalendar"] == CALENDAR_SYSTEM_WORKFLOWS

    def test_every_factory_builds_a_valid_request_keyed_by_its_registry_key(self) -> None:
        for key, factory in CALENDAR_SYSTEM_WORKFLOWS:
            built = factory()
            assert isinstance(built, CreateWorkflowRequest)
            # A mismatch would provision a workflow nothing can find again.
            assert built.system_workflow_key == key
            assert built.is_system_workflow is True
            assert built.source_integration == "googlecalendar"
            assert built.steps

    def test_the_reminder_fires_off_the_calendar_trigger_rather_than_a_schedule(self) -> None:
        trigger = _built("calendar:meeting_reminder").trigger_config

        assert trigger is not None
        assert trigger.type is TriggerType.INTEGRATION
        assert trigger.trigger_name == "calendar_event_starting_soon"
        assert trigger.enabled is True

    def test_the_reminder_asks_for_a_heads_up_rather_than_a_briefing(self) -> None:
        """The prep workflow is the briefing; this one must stay short or it duplicates it."""
        prompt = _built("calendar:meeting_reminder").prompt

        assert (
            "Include the event title, time, and join link or location if available. "
            "Keep it to 2-3 lines. This is just a heads-up, not a full briefing." in prompt
        )

    def test_a_fresh_build_mints_new_step_ids_so_two_users_never_share_one(self) -> None:
        first = [step.id for step in _built("calendar:meeting_prep").steps]
        second = [step.id for step in _built("calendar:meeting_prep").steps]

        assert set(first).isdisjoint(second)
