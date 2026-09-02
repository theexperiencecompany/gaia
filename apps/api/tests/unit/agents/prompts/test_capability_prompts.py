"""The capability block is generated from the registries, so what the comms
agent says GAIA can do is exactly what the product ships."""

import pytest

from app.agents.prompts.capability_prompts import (
    CAPABILITY_SECTION_HEADER,
    build_capability_block,
)
from app.agents.prompts.comms_prompts import COMMS_AGENT_PROMPT
from app.config.oauth_config import get_integration_by_id
from app.models.workflow_models import TriggerType
from app.services.system_workflows.definitions import SYSTEM_WORKFLOWS_BY_INTEGRATION


@pytest.mark.unit
class TestCapabilityBlock:
    def test_every_registered_system_workflow_is_described_with_its_trigger(self) -> None:
        block = build_capability_block()
        for integration_id, entries in SYSTEM_WORKFLOWS_BY_INTEGRATION.items():
            integration = get_integration_by_id(integration_id)
            assert integration is not None, integration_id
            for _, factory in entries:
                workflow = factory()
                assert f"- {integration.name}: {workflow.title}," in block
                assert (workflow.description or "").rstrip(".") in block

    def test_schedules_and_event_triggers_read_as_times_not_cron(self) -> None:
        block = build_capability_block()
        assert "every day at 08:00 in their timezone" in block
        assert "60 minutes before any calendar event" in block
        assert "10 minutes before any calendar event" in block
        assert "0 8 * * *" not in block

    def test_every_trigger_type_is_explained(self) -> None:
        block = build_capability_block()
        for kind in TriggerType:
            assert kind.value in block

    def test_todos_cover_the_tracked_and_recurring_shape(self) -> None:
        block = build_capability_block()
        assert "TRACKED" in block
        assert "recurrence" in block
        assert "cron expression" in block

    def test_the_comms_prompt_carries_the_block_and_the_connect_rule(self) -> None:
        assert CAPABILITY_SECTION_HEADER in COMMS_AGENT_PROMPT
        assert "12. CONNECT MEANS A LINK:" in COMMS_AGENT_PROMPT
        # The rule sits with the other non-negotiables, ahead of the voice.
        assert COMMS_AGENT_PROMPT.index("12. CONNECT MEANS A LINK:") < COMMS_AGENT_PROMPT.index(
            "## Voice"
        )
