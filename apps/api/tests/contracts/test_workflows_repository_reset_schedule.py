"""``reset_system_workflow`` must rewrite the top-level schedule, not just the trigger.

Its own file, and not part of ``test_workflows_repository.py``, for one reason:
these are ``@pytest.mark.regression`` tests, so ``pytest.sh regression-proof``
runs them against the PR's base to prove they fail there. That file imports
``WorkflowRearm``, which this PR introduces, so on base it cannot even be
collected — and a collection error is not proof, it only shows the harness
broke. Everything imported here resolves on both revisions:
``SystemWorkflowDefinition`` is defined in ``db.repositories.workflows`` on base
and re-exported from it here, so this path is stable across the move.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.db.repositories.workflows import SystemWorkflowDefinition, WorkflowsRepository
from app.models.workflow_models import (
    TriggerConfig,
    TriggerType,
    WorkflowDocument,
    WorkflowStep,
)

ORIGINAL_CRON = "0 3 * * *"
RESET_CRON = "0 9 * * *"


def _scheduled_system_workflow() -> WorkflowDocument:
    return WorkflowDocument(
        user_id=f"u_{uuid.uuid4().hex[:12]}",
        title="Test Workflow",
        prompt="do the thing",
        steps=[WorkflowStep(title="step", category="gmail", description="d")],
        is_system_workflow=True,
        trigger_config=TriggerConfig(
            type=TriggerType.SCHEDULE, enabled=True, cron_expression=ORIGINAL_CRON
        ),
    )


def _definition(trigger_config: TriggerConfig) -> SystemWorkflowDefinition:
    return SystemWorkflowDefinition(
        title="Fresh",
        description="fresh desc",
        prompt="fresh prompt",
        steps=[WorkflowStep(title="s2", category="notion", description="d2")],
        trigger_config=trigger_config,
        composio_trigger_ids=[],
    )


@pytest.fixture
def repo(raw_collection: AsyncIOMotorCollection) -> WorkflowsRepository:
    return WorkflowsRepository()


class TestResetRewritesTheSchedule:
    @pytest.mark.regression
    async def test_reset_repersists_the_top_level_schedule_fields(
        self, repo: WorkflowsRepository, raw_collection: AsyncIOMotorCollection
    ) -> None:
        """A reset must rewrite ``repeat``/``scheduled_at``, not just ``trigger_config``.

        The re-arm path reads the top-level fields: ``_rearm_if_scheduled`` gates
        on ``workflow.repeat`` and ``handle_recurring_task`` computes every next
        occurrence from it, while ``schedule_task`` only enqueues — so the
        repository ``$set`` is the only writer. Rewriting only ``trigger_config``
        restored the first fire from the new cron and every later one from the
        old, surfacing as "reset to default did not restore my schedule".
        """
        # Mongo stores datetimes at millisecond resolution; drop the microseconds
        # so the round-trip compares exactly instead of on a truncation artifact.
        next_run = (datetime.now(UTC) + timedelta(hours=1)).replace(microsecond=0)
        wf = await repo.create(_scheduled_system_workflow())
        assert wf.repeat == ORIGINAL_CRON

        updated = await repo.reset_system_workflow(
            wf.id,
            _definition(
                TriggerConfig(
                    type=TriggerType.SCHEDULE,
                    enabled=True,
                    cron_expression=RESET_CRON,
                    next_run=next_run,
                )
            ),
        )

        assert updated is not None
        assert updated.repeat == RESET_CRON
        assert updated.scheduled_at == next_run
        raw = await raw_collection.find_one({"_id": wf.id})
        assert raw is not None and raw["repeat"] == RESET_CRON

    @pytest.mark.regression
    async def test_reset_to_a_non_schedule_definition_clears_the_schedule_fields(
        self, repo: WorkflowsRepository
    ) -> None:
        """A definition whose trigger is no longer a schedule must leave nothing
        armable behind — a stale ``repeat`` would keep re-arming a workflow the
        default definition says is manual."""
        wf = await repo.create(_scheduled_system_workflow())
        assert wf.repeat == ORIGINAL_CRON

        updated = await repo.reset_system_workflow(
            wf.id, _definition(TriggerConfig(type=TriggerType.MANUAL))
        )

        assert updated is not None
        assert updated.repeat is None
        assert updated.scheduled_at is None
