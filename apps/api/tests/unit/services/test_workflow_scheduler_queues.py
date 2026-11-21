"""A scheduled fire takes the queue its workflow declares, and starts its run-ahead work ahead of it."""

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import time_machine

from app.constants.brief_slots import BRIEF_QUEUE, SCOUT_QUEUE
from app.constants.briefing import DAILY_BRIEFING_WORKFLOW_KEY, WEEKLY_DIGEST_WORKFLOW_KEY
from app.constants.scouts import REFRESH_SCOUTS_TASK, SCOUT_REFRESH_LEAD
from app.constants.workflows import EXECUTE_WORKFLOW_TASK
from app.services.workflow.scheduler import WorkflowScheduler
from app.utils.occurrence import occurrence_stamp
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 11, 18, 6, 0, tzinfo=UTC)


@pytest.fixture
def scheduler() -> WorkflowScheduler:
    svc = WorkflowScheduler()
    svc.arq_pool = AsyncMock()
    return svc


def _stored(system_workflow_key: str | None) -> MagicMock:
    workflow = MagicMock()
    workflow.system_workflow_key = system_workflow_key
    return workflow


def _pool(scheduler: WorkflowScheduler) -> AsyncMock:
    return cast(AsyncMock, scheduler.arq_pool)


def _jobs(scheduler: WorkflowScheduler) -> list[tuple[str, str | None, datetime | None]]:
    """Each enqueued job as (function, queue, defer_until)."""
    return [
        (call.args[0], call.kwargs["_queue_name"], call.kwargs["_defer_until"])
        for call in _pool(scheduler).enqueue_job.await_args_list
    ]


@pytest.mark.parametrize("key", [DAILY_BRIEFING_WORKFLOW_KEY, WEEKLY_DIGEST_WORKFLOW_KEY])
async def test_a_brief_fires_on_the_brief_queue_with_its_scouts_refreshed_ahead_on_theirs(
    scheduler: WorkflowScheduler, key: str
) -> None:
    fire = _NOW + timedelta(hours=2)
    stored = AsyncMock(return_value=_stored(key))
    with (
        time_machine.travel(_NOW, tick=False),
        patch("app.services.workflow.scheduler.workflow_repository.get", stored),
    ):
        async with captured_wide_event() as event:
            armed = await scheduler.schedule_workflow_execution("wf_1", fire, repeat="0 7 * * *")

    assert armed is True
    stored.assert_awaited_once_with("wf_1")
    assert event["workflow"]["run_ahead"] == "enqueued"
    assert _pool(scheduler).enqueue_job.await_args_list[0].args[1] == "wf_1"
    assert _jobs(scheduler) == [
        (EXECUTE_WORKFLOW_TASK, BRIEF_QUEUE, fire),
        (REFRESH_SCOUTS_TASK, SCOUT_QUEUE, fire - SCOUT_REFRESH_LEAD),
    ]
    refresh = _pool(scheduler).enqueue_job.await_args_list[1]
    stamp = occurrence_stamp(fire)
    assert refresh.args[1:3] == ("wf_1", stamp)
    assert refresh.kwargs["_job_id"] == f"{REFRESH_SCOUTS_TASK}:wf_1:{stamp}"


@pytest.mark.parametrize("key", [None, "some_other_system_workflow"])
async def test_any_other_workflow_fires_on_the_shared_queue_and_starts_nothing_ahead(
    scheduler: WorkflowScheduler, key: str | None
) -> None:
    fire = _NOW + timedelta(hours=2)
    with (
        time_machine.travel(_NOW, tick=False),
        patch(
            "app.services.workflow.scheduler.workflow_repository.get",
            AsyncMock(return_value=_stored(key)),
        ),
    ):
        armed = await scheduler.schedule_workflow_execution("wf_1", fire)

    assert armed is True
    assert _jobs(scheduler) == [(EXECUTE_WORKFLOW_TASK, None, fire)]


async def test_a_brief_due_sooner_than_the_lead_runs_its_scouts_itself(
    scheduler: WorkflowScheduler,
) -> None:
    fire = _NOW + SCOUT_REFRESH_LEAD
    with (
        time_machine.travel(_NOW, tick=False),
        patch(
            "app.services.workflow.scheduler.workflow_repository.get",
            AsyncMock(return_value=_stored(DAILY_BRIEFING_WORKFLOW_KEY)),
        ),
    ):
        async with captured_wide_event() as event:
            await scheduler.schedule_workflow_execution("wf_1", fire)

    assert _jobs(scheduler) == [(EXECUTE_WORKFLOW_TASK, BRIEF_QUEUE, fire)]
    assert event["workflow"]["run_ahead"] == "too_close"


async def test_a_brief_fire_already_enqueued_enqueues_no_second_refresh(
    scheduler: WorkflowScheduler,
) -> None:
    _pool(scheduler).enqueue_job.return_value = None
    with (
        time_machine.travel(_NOW, tick=False),
        patch(
            "app.services.workflow.scheduler.workflow_repository.get",
            AsyncMock(return_value=_stored(DAILY_BRIEFING_WORKFLOW_KEY)),
        ),
    ):
        armed = await scheduler.schedule_workflow_execution("wf_1", _NOW + timedelta(hours=2))

    assert armed is False
    assert [job for job, _, _ in _jobs(scheduler)] == [EXECUTE_WORKFLOW_TASK]


async def test_a_naive_brief_fire_is_read_as_utc_for_its_refresh(
    scheduler: WorkflowScheduler,
) -> None:
    """The scheduler's own enqueue takes a naive armed time as UTC; the refresh must agree."""
    fire = (_NOW + timedelta(hours=2)).replace(tzinfo=None)
    with (
        time_machine.travel(_NOW, tick=False),
        patch(
            "app.services.workflow.scheduler.workflow_repository.get",
            AsyncMock(return_value=_stored(DAILY_BRIEFING_WORKFLOW_KEY)),
        ),
    ):
        await scheduler._enqueue_task("wf_1", fire)

    expected_start = fire.replace(tzinfo=UTC) - SCOUT_REFRESH_LEAD
    assert _jobs(scheduler)[1] == (REFRESH_SCOUTS_TASK, SCOUT_QUEUE, expected_start)


async def test_a_refresh_already_enqueued_for_the_fire_is_said_so(
    scheduler: WorkflowScheduler,
) -> None:
    fire = _NOW + timedelta(hours=2)
    _pool(scheduler).enqueue_job.side_effect = [MagicMock(job_id="fire"), None]
    with (
        time_machine.travel(_NOW, tick=False),
        patch(
            "app.services.workflow.scheduler.workflow_repository.get",
            AsyncMock(return_value=_stored(DAILY_BRIEFING_WORKFLOW_KEY)),
        ),
    ):
        async with captured_wide_event() as event:
            await scheduler.schedule_workflow_execution("wf_1", fire)

    assert event["workflow"]["run_ahead"] == "already_enqueued"


async def test_a_scheduler_with_no_pool_enqueues_nothing_ahead(
    scheduler: WorkflowScheduler,
) -> None:
    scheduler.arq_pool = None
    with patch(
        "app.services.workflow.scheduler.workflow_repository.get",
        AsyncMock(return_value=_stored(DAILY_BRIEFING_WORKFLOW_KEY)),
    ):
        assert await scheduler._enqueue_task("wf_1", _NOW + timedelta(hours=2)) is False
