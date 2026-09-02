"""The capability block is generated from the registries, so what the comms
agent says GAIA can do is exactly what the product ships."""

import pytest

from app.agents.prompts.capability_prompts import (
    CAPABILITY_SECTION_HEADER,
    _describe_cron,
    _describe_trigger,
    _describe_workflow,
    build_capability_block,
)
from app.agents.prompts.comms_prompts import COMMS_AGENT_PROMPT
from app.config.oauth_config import get_integration_by_id
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
    WorkflowStep,
)
from app.services.system_workflows.definitions import SYSTEM_WORKFLOWS_BY_INTEGRATION


def _workflow(
    description: str | None = "Reads the inbox and files the noise.",
    steps: list[str] | None = None,
) -> CreateWorkflowRequest:
    return CreateWorkflowRequest(
        title="Inbox Triage",
        description=description,
        prompt="Do the thing.",
        trigger_config=TriggerConfig(type=TriggerType.MANUAL),
        steps=[
            WorkflowStep(id=f"s{i}", title=title, category="gmail", description="step")
            for i, title in enumerate(steps or [])
        ]
        or None,
    )


@pytest.mark.unit
class TestDescribeCron:
    """Cron is rendered as a clock, never handed to the model raw, and only for
    the shapes the renderer understands."""

    @pytest.mark.parametrize(
        ("cron", "expected"),
        [
            ("0 8 * * *", "every day at 08:00 in their timezone"),
            ("30 9 * * 1-5", "on cron days 1-5 at 09:30 in their timezone"),
            # Day-of-month or month set: not a daily shape, fall back to the raw cron.
            ("0 8 1 * *", "on the cron schedule 0 8 1 * * in their timezone"),
            ("0 8 * 6 *", "on the cron schedule 0 8 * 6 * in their timezone"),
            # Step minutes cannot be a clock; and a 4-field string is not cron.
            ("*/15 8 * * *", "on the cron schedule */15 8 * * * in their timezone"),
            ("0 8 * *", "on the cron schedule 0 8 * * in their timezone"),
        ],
    )
    def test_renders_the_shapes_it_understands_and_falls_back_otherwise(
        self, cron: str, expected: str
    ) -> None:
        assert _describe_cron(cron) == expected


@pytest.mark.unit
class TestDescribeTrigger:
    def test_manual_reads_as_the_user_running_it(self) -> None:
        assert _describe_trigger(TriggerConfig(type=TriggerType.MANUAL)) == "when the user runs it"

    def test_a_manual_trigger_with_a_stray_cron_is_still_manual(self) -> None:
        trigger = TriggerConfig(type=TriggerType.MANUAL, cron_expression="0 8 * * *")
        assert _describe_trigger(trigger) == "when the user runs it"

    def test_integration_names_its_event(self) -> None:
        trigger = TriggerConfig(type=TriggerType.INTEGRATION, trigger_name="gmail_new_email")
        assert _describe_trigger(trigger) == "on the gmail_new_email event"

    def test_integration_without_a_name_says_integration(self) -> None:
        assert (
            _describe_trigger(TriggerConfig(type=TriggerType.INTEGRATION))
            == "on the integration event"
        )


@pytest.mark.unit
class TestDescribeWorkflow:
    def test_full_line_lists_steps_without_doubled_periods(self) -> None:
        line = _describe_workflow(
            "Gmail", _workflow(steps=["Fetch the last day's emails.", "Draft replies"])
        )
        assert line == (
            "- Gmail: Inbox Triage, when the user runs it. Reads the inbox and files the noise. "
            "Steps: Fetch the last day's emails, Draft replies."
        )

    def test_only_the_trailing_period_is_trimmed(self) -> None:
        """A title or description ending in a capital is kept whole."""
        line = _describe_workflow(
            "Gmail", _workflow(description="Escalates anything from X.", steps=["Ping X"])
        )
        assert line == (
            "- Gmail: Inbox Triage, when the user runs it. Escalates anything from X. Steps: Ping X."
        )

    def test_no_steps_means_no_steps_clause(self) -> None:
        assert (
            _describe_workflow("Gmail", _workflow())
            == "- Gmail: Inbox Triage, when the user runs it. Reads the inbox and files the noise."
        )

    def test_no_description_means_no_empty_sentence(self) -> None:
        assert (
            _describe_workflow("Gmail", _workflow(description=None, steps=["Fetch"]))
            == "- Gmail: Inbox Triage, when the user runs it. Steps: Fetch."
        )


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
        # The tracked-todo kinds are explained, not just named.
        assert "scheduled_todo, a tracked todo firing on its own schedule" in block
        assert "todo_trigger, a tracked todo woken by an integration event it watches" in block
        assert "TRIGGERS: a run starts one of these ways: manual, run when the user asks;" in block

    def test_built_in_workflows_are_one_per_line_under_an_exact_header(self) -> None:
        block = build_capability_block()
        header = (
            "BUILT-IN WORKFLOWS: the moment an integration is connected, GAIA provisions these "
            "for the user automatically (each can be paused, edited or reset to default):\n- "
        )
        assert header in block
        listing = block.split(header, 1)[1]
        lines = listing.split("\n")
        assert len(lines) >= 2
        assert all(line.startswith("- ") for line in lines[1:])

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
