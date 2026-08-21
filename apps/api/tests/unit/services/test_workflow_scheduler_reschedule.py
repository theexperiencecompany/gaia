"""Regression tests: a rescheduled workflow must not fire at its old time.

Editing a scheduled workflow's cron enqueues a NEW deferred ARQ job, but the
old job (armed for the original time) is still sitting in Redis — ARQ has no
cancellation. When it fires, the claim gate only checked liveness
(``activated``) and run-state (``status="scheduled"``), both of which are true
after a reschedule, so the workflow executed at the ORIGINAL time anyway.

The fix stamps every scheduler-originated fire with the occurrence it was
armed for (``scheduled_for``) and rejects a fire whose stamp no longer matches
the workflow's current ``trigger_config.next_run``.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.workflow.scheduler import WorkflowScheduler


@pytest.fixture(autouse=True)
def _no_real_analytics():
    """Keep every test hermetic: WORKFLOW_EXECUTED never reaches a real PostHog."""
    with patch("app.workers.tasks.workflow_tasks.capture_event"):
        yield


@pytest.fixture(autouse=True)
def _onboarded_user():
    """Default every test's user to a finished-onboarding one so the
    system-initiated-run gate stays out of the way."""
    user = MagicMock()
    user.onboarding = {"completed": True}
    with patch(
        "app.workers.tasks.workflow_tasks.user_repository.get",
        AsyncMock(return_value=user),
    ):
        yield


@pytest.fixture
def scheduler() -> WorkflowScheduler:
    with patch(
        "app.services.scheduler_service.settings",
        MagicMock(REDIS_URL="redis://localhost:6379/0"),
    ):
        svc = WorkflowScheduler(redis_settings=MagicMock())
        svc.arq_pool = AsyncMock()
        return svc


@pytest.mark.unit
class TestScheduledFireStamping:
    async def test_scheduler_jobs_carry_their_intended_fire_time(
        self, scheduler: WorkflowScheduler
    ):
        """Every scheduler-originated ARQ job is stamped with the occurrence it
        was armed for, so a stale job can be recognized after a reschedule."""
        armed_for = datetime.now(UTC) + timedelta(hours=5)

        args = scheduler._build_job_args("wf_1", armed_for)

        task_id, context = args
        assert task_id == "wf_1"
        assert context["trigger_type"] == "schedule"
        assert context["scheduled_for"] == int(armed_for.timestamp())

    async def test_enqueue_passes_armed_time_to_job_args(self, scheduler: WorkflowScheduler):
        """_enqueue_task hands the armed time (not the past-due-shifted one) to
        _build_job_args, so the stamp always matches what the DB holds."""
        past = datetime.now(UTC) - timedelta(hours=1)
        mock_job = MagicMock(job_id="j")
        captured: dict[str, Any] = {}

        def _capture_build(task_id: str, scheduled_at: datetime) -> tuple[str, dict[str, Any]]:
            captured["task_id"] = task_id
            captured["scheduled_at"] = scheduled_at
            return (task_id, {"scheduled_for": int(scheduled_at.timestamp())})

        with (
            patch(
                "app.services.scheduler_service.enqueue_worker_job",
                new=AsyncMock(return_value=mock_job),
            ),
            patch.object(scheduler, "_build_job_args", side_effect=_capture_build),
        ):
            await scheduler._enqueue_task("wf_1", past)

        assert captured["scheduled_at"] == past


@pytest.mark.regression
@pytest.mark.unit
class TestStaleScheduledFireRejected:
    async def test_stale_fire_is_not_claimed(self) -> None:
        """A job armed for 16:00 that fires after the workflow was rescheduled to
        21:00 must be rejected by the claim gate — trigger_config.next_run no
        longer matches the occurrence the job was armed for."""
        from app.db.repositories.workflows import workflow_repository

        old_fire = datetime.now(UTC).replace(microsecond=0)
        new_fire = old_fire + timedelta(hours=5)

        captured_filters: list[dict[str, Any]] = []

        async def _fake_apply_update(filter_: dict[str, Any], ops: dict[str, Any], **kwargs: Any):
            captured_filters.append(filter_)

        with patch.object(workflow_repository, "_apply_raw_update", side_effect=_fake_apply_update):
            claimed = await workflow_repository.claim_for_execution(
                "wf_1", expected_next_run=new_fire
            )

        assert claimed is False
        assert captured_filters[0]["trigger_config.next_run"] == new_fire

    async def test_fresh_fire_is_claimed(self) -> None:
        """A job whose stamp matches the current next_run still claims fine."""
        from app.db.repositories.workflows import workflow_repository

        fire = datetime.now(UTC).replace(microsecond=0)

        async def _fake_apply_update(filter_: dict[str, Any], ops: dict[str, Any], **kwargs: Any):
            assert filter_["trigger_config.next_run"] == fire
            return MagicMock()

        with patch.object(workflow_repository, "_apply_raw_update", side_effect=_fake_apply_update):
            claimed = await workflow_repository.claim_for_execution("wf_1", expected_next_run=fire)

        assert claimed is True

    async def test_legacy_job_without_stamp_claims_as_before(self) -> None:
        """In-flight jobs enqueued before the stamp existed carry no expected
        time and must keep claiming, so a deploy doesn't strand schedules."""
        from app.db.repositories.workflows import workflow_repository

        async def _fake_apply_update(filter_: dict[str, Any], ops: dict[str, Any], **kwargs: Any):
            assert "trigger_config.next_run" not in filter_
            return MagicMock()

        with patch.object(workflow_repository, "_apply_raw_update", side_effect=_fake_apply_update):
            claimed = await workflow_repository.claim_for_execution("wf_1")

        assert claimed is True


def _gate_claim(workflow: MagicMock, calls: list[datetime | None]):
    """A claim mock modeling the real gate semantics: it accepts only a fire
    whose expected time matches the workflow's current next_run — exactly what
    ``claim_for_execution(expected_next_run=...)`` enforces in Mongo."""

    async def _claim(workflow_id: str, expected_next_run: datetime | None = None) -> bool:
        calls.append(expected_next_run)
        next_run = workflow.trigger_config.next_run
        if expected_next_run is None:
            return True  # legacy unstamped fire: ungated
        return next_run is not None and int(next_run.timestamp()) == int(
            expected_next_run.timestamp()
        )

    return _claim


@pytest.mark.regression
@pytest.mark.unit
class TestWorkerRejectsStaleFire:
    async def test_execute_workflow_by_id_skips_stale_scheduled_fire(self) -> None:
        """A scheduled fire armed for 16:00 that fires after the workflow was
        rescheduled to 21:00 is rejected by the gate and skipped without
        executing or re-arming."""
        from app.workers.tasks.workflow_tasks import execute_workflow_by_id

        old_fire = datetime.now(UTC).replace(microsecond=0)
        new_fire = old_fire + timedelta(hours=5)

        workflow = MagicMock()
        workflow.id = f"wf_{uuid4().hex[:12]}"
        workflow.user_id = "user_abc"
        workflow.repeat = "0 16 * * *"
        workflow.activated = True
        workflow.trigger_config.next_run = new_fire

        scheduler = AsyncMock()
        scheduler.get_task = AsyncMock(return_value=workflow)
        claim_calls: list[datetime | None] = []
        scheduler.claim_scheduled_for_execution = AsyncMock(
            side_effect=_gate_claim(workflow, claim_calls)
        )

        context = {"trigger_type": "schedule", "scheduled_for": int(old_fire.timestamp())}

        with (
            patch("app.workers.tasks.workflow_tasks.workflow_scheduler", scheduler),
            patch("app.workers.tasks.workflow_tasks.create_execution", AsyncMock()) as mock_create,
        ):
            result = await execute_workflow_by_id({}, workflow.id, context)

        # The worker derived the expectation from the job's stamp...
        assert claim_calls == [old_fire]
        # ...the gate rejected it (armed 16:00 vs current next_run 21:00)...
        assert "skipped" in result.lower()
        # ...and nothing ran or re-armed.
        mock_create.assert_not_awaited()
        scheduler.handle_recurring_task.assert_not_awaited()

    async def test_execute_workflow_by_id_runs_fresh_scheduled_fire(self) -> None:
        """A scheduled fire whose stamp matches next_run passes the gate and
        executes normally."""
        from app.workers.tasks.workflow_tasks import execute_workflow_by_id

        fire = datetime.now(UTC).replace(microsecond=0)

        workflow = MagicMock()
        workflow.id = f"wf_{uuid4().hex[:12]}"
        workflow.user_id = "user_abc"
        workflow.repeat = "0 16 * * *"
        workflow.activated = True
        workflow.trigger_config.next_run = fire

        execution = MagicMock()
        execution.execution_id = "exec_1"

        scheduler = AsyncMock()
        scheduler.get_task = AsyncMock(return_value=workflow)
        claim_calls: list[datetime | None] = []
        scheduler.claim_scheduled_for_execution = AsyncMock(
            side_effect=_gate_claim(workflow, claim_calls)
        )

        context = {"trigger_type": "schedule", "scheduled_for": int(fire.timestamp())}

        with (
            patch("app.workers.tasks.workflow_tasks.workflow_scheduler", scheduler),
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(return_value=execution),
            ),
            patch("app.workers.tasks.workflow_tasks.complete_execution", AsyncMock()),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value="conv_1"),
            ),
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            result = await execute_workflow_by_id({}, workflow.id, context)

        assert claim_calls == [fire]
        assert "executed successfully" in result

    async def test_unstamped_scheduled_fire_still_executes(self) -> None:
        """Jobs enqueued before the stamp existed carry no scheduled_for key;
        the worker must not gate them, so a deploy never strands a schedule."""
        from app.workers.tasks.workflow_tasks import execute_workflow_by_id

        workflow = MagicMock()
        workflow.id = f"wf_{uuid4().hex[:12]}"
        workflow.user_id = "user_abc"
        workflow.repeat = "0 16 * * *"
        workflow.activated = True
        workflow.trigger_config.next_run = datetime.now(UTC)

        execution = MagicMock()
        execution.execution_id = "exec_1"

        scheduler = AsyncMock()
        scheduler.get_task = AsyncMock(return_value=workflow)
        claim_calls: list[datetime | None] = []
        scheduler.claim_scheduled_for_execution = AsyncMock(
            side_effect=_gate_claim(workflow, claim_calls)
        )

        context = {"trigger_type": "schedule"}

        with (
            patch("app.workers.tasks.workflow_tasks.workflow_scheduler", scheduler),
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(return_value=execution),
            ),
            patch("app.workers.tasks.workflow_tasks.complete_execution", AsyncMock()),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value="conv_1"),
            ),
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            result = await execute_workflow_by_id({}, workflow.id, context)

        assert claim_calls == [None]
        assert "executed successfully" in result
