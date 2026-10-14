"""The daily brief and weekly digest workflows every user gets are built as the product shows them.

They are provisioned at onboarding, not on connect, and the user meets them as two
cards in their workflow list. The provisioner's tests pass fake factories, so a wrong
title, a dropped description or a disabled trigger here would first surface on a
real user's workflow page.
"""

from __future__ import annotations

import pytest

from app.constants.briefing import (
    DAILY_BRIEFING_WORKFLOW_KEY,
    WEEKLY_DIGEST_CRON,
    WEEKLY_DIGEST_WORKFLOW_KEY,
)
from app.constants.workflows import WorkflowDelivery
from app.models.notification.notification_models import default_quiet_hours
from app.models.workflow_models import CreateWorkflowRequest, TriggerType
from app.services.briefing.schedule import daily_briefing_cron
from app.services.system_workflows.definitions.briefing import BRIEFING_SYSTEM_WORKFLOWS


def _built(key: str) -> CreateWorkflowRequest:
    return next(factory() for registered, factory in BRIEFING_SYSTEM_WORKFLOWS if registered == key)


@pytest.mark.unit
class TestBriefingSystemWorkflows:
    def test_the_registry_holds_exactly_the_daily_brief_and_the_weekly_digest(self) -> None:
        assert [key for key, _ in BRIEFING_SYSTEM_WORKFLOWS] == [
            DAILY_BRIEFING_WORKFLOW_KEY,
            WEEKLY_DIGEST_WORKFLOW_KEY,
        ]

    @pytest.mark.parametrize("key", [DAILY_BRIEFING_WORKFLOW_KEY, WEEKLY_DIGEST_WORKFLOW_KEY])
    def test_each_is_a_silent_enabled_schedule_system_workflow_under_its_key(
        self, key: str
    ) -> None:
        built = _built(key)

        assert built.system_workflow_key == key
        assert built.is_system_workflow is True
        # The brief delivers itself; a notifying run would double every morning.
        assert built.delivery is WorkflowDelivery.SILENT
        assert built.trigger_config is not None
        assert built.trigger_config.type is TriggerType.SCHEDULE
        assert built.trigger_config.enabled is True

    def test_the_daily_brief_card_reads_as_the_morning_brief(self) -> None:
        built = _built(DAILY_BRIEFING_WORKFLOW_KEY)

        assert built.title == "Daily Briefing"
        assert built.description == (
            "Your morning brief: curates your list, looks back at yesterday, and plans today."
        )
        assert built.prompt == (
            "Generate the user's daily briefing: curate the todo list, compare yesterday's "
            "plan to what actually happened, and plan today's work within budget. Emit one "
            "structured briefing payload."
        )
        assert [(step.title, step.category, step.description) for step in built.steps or []] == [
            (
                "Curate, look back, and plan",
                "gaia",
                "Compare yesterday's briefing to completed todos and workflow runs, "
                "then plan today's items within budget.",
            )
        ]

    def test_the_weekly_digest_card_reads_as_the_sunday_zoom_out(self) -> None:
        built = _built(WEEKLY_DIGEST_WORKFLOW_KEY)

        assert built.title == "Weekly Digest"
        assert built.description == "Sunday zoom-out: your week's completed work."
        assert built.prompt == (
            "Generate the user's weekly digest: summarize the week's completed work (by GAIA "
            "and by the user). Emit one structured payload."
        )
        assert [(step.title, step.category, step.description) for step in built.steps or []] == [
            (
                "Summarize the week",
                "gaia",
                "Aggregate the week's completed todos (GAIA's and the user's) and "
                "compile the weekly digest payload.",
            )
        ]

    def test_the_daily_brief_defaults_to_the_default_quiet_hours_slot(self) -> None:
        trigger = _built(DAILY_BRIEFING_WORKFLOW_KEY).trigger_config

        assert trigger is not None
        assert trigger.cron_expression == daily_briefing_cron(default_quiet_hours())

    def test_the_weekly_digest_runs_on_the_weekly_cron(self) -> None:
        trigger = _built(WEEKLY_DIGEST_WORKFLOW_KEY).trigger_config

        assert trigger is not None
        assert trigger.cron_expression == WEEKLY_DIGEST_CRON

    @pytest.mark.parametrize("key", [DAILY_BRIEFING_WORKFLOW_KEY, WEEKLY_DIGEST_WORKFLOW_KEY])
    def test_a_fresh_build_mints_new_step_ids_so_two_users_never_share_one(self, key: str) -> None:
        first = [step.id for step in _built(key).steps or []]
        second = [step.id for step in _built(key).steps or []]

        assert all(first)
        assert set(first).isdisjoint(second)
