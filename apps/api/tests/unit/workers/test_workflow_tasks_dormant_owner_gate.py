"""A workflow whose owner has gone dormant pauses when it would next fire, as a tracked todo does.

The status is read the real way, from the owner's activity dates; only the user row is
doubled. reactivate_user resumes what this pauses, by DeactivationReason.USER_DORMANT.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.briefing import DAILY_BRIEFING_WORKFLOW_KEY
from app.constants.user_activity import DORMANT_AFTER
from app.models.scheduler_models import DeactivationReason
from app.models.user_activity_models import UserActivityDates
from app.models.user_models import UserDocument
from app.services.user_activity.status import activity_status_of
from app.workers.tasks.workflow_tasks import execute_workflow_by_id

MODULE = "app.workers.tasks.workflow_tasks"
OWNER = "6812f0b3c9a14e2b7d5a91dd"


def _workflow(system_workflow_key: str | None = None) -> MagicMock:
    wf = MagicMock()
    wf.id = "wf-1"
    wf.user_id = OWNER
    wf.steps = []
    wf.repeat = None
    wf.activated = True
    wf.system_workflow_key = system_workflow_key
    return wf


def _last_seen(ago: timedelta) -> UserActivityDates:
    return UserActivityDates(last_active_at=datetime.now(UTC) - ago)


@pytest.fixture
def scheduler() -> Iterator[MagicMock]:
    with (
        patch(f"{MODULE}.workflow_scheduler") as scheduler,
        # The real status read, over the owner's activity dates (the conftest defaults it).
        patch(f"{MODULE}.activity_status_of", activity_status_of),
        patch(
            f"{MODULE}.user_repository.get",
            AsyncMock(
                return_value=UserDocument.model_validate({"onboarding": {"completed": True}})
            ),
        ),
        patch(f"{MODULE}._admit_fire", AsyncMock(return_value="admitted")),
    ):
        scheduler.pause_for_reason = AsyncMock()
        yield scheduler


async def _fire(scheduler: MagicMock, workflow: MagicMock, seen: UserActivityDates) -> str:
    scheduler.get_task = AsyncMock(return_value=workflow)
    with patch(
        "app.services.user_activity.status.user_repository.get_activity_dates",
        AsyncMock(return_value=seen),
    ):
        return await execute_workflow_by_id({}, "wf-1", {"trigger_type": "schedule"})


class TestADormantOwnersWorkflowPausesAtItsFire:
    async def test_it_is_skipped_and_paused_for_dormancy(self, scheduler: MagicMock) -> None:
        workflow = _workflow()

        result = await _fire(scheduler, workflow, _last_seen(DORMANT_AFTER + timedelta(days=1)))

        assert result == "Workflow wf-1 skipped — owner dormant"
        scheduler.pause_for_reason.assert_awaited_once_with(
            workflow, DeactivationReason.USER_DORMANT
        )

    async def test_an_active_owners_workflow_goes_on_to_admission(
        self, scheduler: MagicMock
    ) -> None:
        result = await _fire(scheduler, _workflow(), _last_seen(timedelta(hours=1)))

        assert result == "admitted"
        scheduler.pause_for_reason.assert_not_awaited()

    async def test_a_brief_declared_unpausable_is_left_to_its_wind_down(
        self, scheduler: MagicMock
    ) -> None:
        result = await _fire(
            scheduler,
            _workflow(DAILY_BRIEFING_WORKFLOW_KEY),
            _last_seen(DORMANT_AFTER + timedelta(days=1)),
        )

        assert result == "admitted"
        scheduler.pause_for_reason.assert_not_awaited()

    async def test_a_workflow_already_off_keeps_the_reason_it_has(
        self, scheduler: MagicMock
    ) -> None:
        workflow = _workflow()
        workflow.activated = False

        result = await _fire(scheduler, workflow, _last_seen(DORMANT_AFTER + timedelta(days=1)))

        assert result == "Workflow wf-1 skipped — owner dormant"
        scheduler.pause_for_reason.assert_not_awaited()
