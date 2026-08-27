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
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.constants.log_tags import LogTag
from app.models.scheduler_models import ScheduledTaskStatus
from app.services.workflow.scheduler import WorkflowScheduler
from app.workers.tasks.workflow_tasks import execute_workflow_by_id


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

    async def test_naive_scheduled_at_stamp_is_normalized_to_utc(
        self, scheduler: WorkflowScheduler, monkeypatch: pytest.MonkeyPatch
    ):
        """A naive scheduled_at is normalized to UTC BEFORE the stamp is built:
        the stamp must reflect the UTC instant, not the wall clock read in the
        process's local zone. Runs under a non-UTC zone so reading the naive
        value un-normalized drifts the stamp by the zone offset and fails."""
        monkeypatch.setenv("TZ", "America/New_York")
        time.tzset()
        try:
            # Winter date: EST is a fixed UTC-5, no DST ambiguity.
            naive = datetime(2099, 1, 15, 12, 0, 0)
            utc_armed = datetime(2099, 1, 15, 12, 0, tzinfo=UTC)
            mock_job = MagicMock(job_id="j")

            with patch(
                "app.services.scheduler_service.enqueue_worker_job",
                new=AsyncMock(return_value=mock_job),
            ) as mock_enqueue:
                await scheduler._enqueue_task("wf_1", naive)

            call = mock_enqueue.await_args
            context = call.args[3]
            assert context["scheduled_for"] == int(utc_armed.timestamp())
            defer_until = call.kwargs["_defer_until"]
            assert defer_until == utc_armed
            assert defer_until.tzinfo is not None
        finally:
            time.tzset()


@pytest.mark.unit
class TestStaleScheduledFireRejected:
    @pytest.mark.regression
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
        # The whole atomic filter: liveness, run-state, and the occurrence pin
        # must all hold together or the fire is not claimable.
        assert captured_filters[0] == {
            "_id": "wf_1",
            "activated": True,
            "status": ScheduledTaskStatus.SCHEDULED.value,
            "trigger_config.next_run": new_fire,
        }

    @pytest.mark.regression
    async def test_fresh_fire_is_claimed(self) -> None:
        """A job whose stamp matches the current next_run still claims fine."""
        from app.db.repositories.workflows import workflow_repository

        fire = datetime.now(UTC).replace(microsecond=0)

        async def _fake_apply_update(filter_: dict[str, Any], ops: dict[str, Any], **kwargs: Any):
            assert filter_ == {
                "_id": "wf_1",
                "activated": True,
                "status": ScheduledTaskStatus.SCHEDULED.value,
                "trigger_config.next_run": fire,
            }
            return MagicMock()

        with patch.object(workflow_repository, "_apply_raw_update", side_effect=_fake_apply_update):
            claimed = await workflow_repository.claim_for_execution("wf_1", expected_next_run=fire)

        assert claimed is True

    async def test_legacy_job_without_stamp_claims_as_before(self) -> None:
        """In-flight jobs enqueued before the stamp existed carry no expected
        time and must keep claiming, so a deploy doesn't strand schedules."""
        from app.db.repositories.workflows import workflow_repository

        async def _fake_apply_update(filter_: dict[str, Any], ops: dict[str, Any], **kwargs: Any):
            # No expected_next_run key: the legacy path must add nothing.
            assert filter_ == {
                "_id": "wf_1",
                "activated": True,
                "status": ScheduledTaskStatus.SCHEDULED.value,
            }
            return MagicMock()

        with patch.object(workflow_repository, "_apply_raw_update", side_effect=_fake_apply_update):
            claimed = await workflow_repository.claim_for_execution("wf_1")

        assert claimed is True


def _gate_claim(workflow: MagicMock, calls: list[tuple[str, datetime | None]]):
    """A claim mock modeling the real gate semantics: it accepts only a fire
    whose expected time matches the workflow's current next_run — exactly what
    ``claim_for_execution(expected_next_run=...)`` enforces in Mongo. Records
    (workflow_id, expected) pairs so tests assert the worker claimed the right
    workflow for the right occurrence."""

    async def _claim(workflow_id: str, expected_next_run: datetime | None = None) -> bool:
        calls.append((workflow_id, expected_next_run))
        next_run = workflow.trigger_config.next_run
        if expected_next_run is None:
            return True  # legacy unstamped fire: ungated
        return next_run is not None and int(next_run.timestamp()) == int(
            expected_next_run.timestamp()
        )

    return _claim


@pytest.mark.unit
class TestWorkerRejectsStaleFire:
    @staticmethod
    @staticmethod
    def _scheduled_workflow(next_run: datetime) -> MagicMock:
        workflow = MagicMock()
        workflow.id = f"wf_{uuid4().hex[:12]}"
        workflow.user_id = "user_abc"
        workflow.repeat = "0 16 * * *"
        workflow.activated = True
        workflow.trigger_config.next_run = next_run
        return workflow

    @staticmethod
    async def _run_fire(
        context: dict[str, Any], *, next_run: datetime | None = None
    ) -> tuple[
        MagicMock,
        MagicMock,
        list[tuple[str, datetime | None]],
        str,
        MagicMock,
    ]:
        """Drive one fire through execute_workflow_by_id with every seam
        mocked; returns (workflow, scheduler, claim_calls, result)."""
        workflow = TestWorkerRejectsStaleFire._scheduled_workflow(next_run or datetime.now(UTC))
        scheduler = AsyncMock()
        scheduler.get_task = AsyncMock(return_value=workflow)
        claim_calls: list[tuple[str, datetime | None]] = []
        scheduler.claim_scheduled_for_execution = AsyncMock(
            side_effect=_gate_claim(workflow, claim_calls)
        )

        with (
            patch("app.workers.tasks.workflow_tasks.workflow_scheduler", scheduler),
            patch(
                "app.workers.tasks.workflow_tasks.create_execution",
                AsyncMock(return_value=MagicMock(execution_id="exec_1")),
            ) as mock_create,
            patch("app.workers.tasks.workflow_tasks.complete_execution", AsyncMock()),
            patch("app.workers.tasks.workflow_tasks.WorkflowService") as mock_wf_svc,
            patch("app.workers.tasks.workflow_tasks.log") as mock_log,
            patch(
                "app.workers.tasks.workflow_tasks.enforce_daily_cost_budget",
                AsyncMock(),
            ),
            patch(
                "app.workers.tasks.workflow_tasks.execute_workflow_as_chat",
                AsyncMock(return_value="conv_1"),
            ),
        ):
            mock_wf_svc.increment_execution_count = AsyncMock()
            result = await execute_workflow_by_id({}, workflow.id, context)
            mocks = MagicMock()
            mocks.create_execution = mock_create
            mocks.log_warning = mock_log.warning
            mocks.increment_execution_count = mock_wf_svc.increment_execution_count

        return workflow, scheduler, claim_calls, result, mocks

    @pytest.mark.regression
    async def test_execute_workflow_by_id_skips_stale_scheduled_fire(self) -> None:
        """A scheduled fire armed for 16:00 that fires after the workflow was
        rescheduled to 21:00 is rejected by the gate and skipped without
        executing or re-arming."""
        old_fire = datetime.now(UTC).replace(microsecond=0)
        new_fire = old_fire + timedelta(hours=5)

        workflow = self._scheduled_workflow(new_fire)
        # The gate accepts only the CURRENT occurrence (21:00).
        scheduler = AsyncMock()
        scheduler.get_task = AsyncMock(return_value=workflow)
        claim_calls: list[tuple[str, datetime | None]] = []
        scheduler.claim_scheduled_for_execution = AsyncMock(
            side_effect=_gate_claim(workflow, claim_calls)
        )
        context = {"trigger_type": "schedule", "scheduled_for": int(old_fire.timestamp())}

        with (
            patch("app.workers.tasks.workflow_tasks.workflow_scheduler", scheduler),
            patch("app.workers.tasks.workflow_tasks.create_execution", AsyncMock()) as mock_create,
            patch("app.workers.tasks.workflow_tasks.log") as mock_log,
        ):
            await execute_workflow_by_id({}, workflow.id, context)

        # The worker derived the expectation from the job's stamp and asked
        # for THIS workflow...
        assert claim_calls == [(workflow.id, old_fire)]
        # ...the gate rejected it (armed 16:00 vs current next_run 21:00),
        # and the skip is logged with the context to find it in Loki...
        mock_log.warning.assert_called_once_with(
            f"{LogTag.WORKER} Workflow not in scheduled state "
            "(already claimed, running, deactivated, or rescheduled away); "
            "skipping stale scheduled fire",
            workflow_id=workflow.id,
            scheduled_for=int(old_fire.timestamp()),
        )
        # ...nothing ran or re-armed.
        mock_create.assert_not_awaited()
        scheduler.handle_recurring_task.assert_not_awaited()

    @pytest.mark.regression
    async def test_execute_workflow_by_id_runs_fresh_scheduled_fire(self) -> None:
        """A scheduled fire whose stamp matches next_run passes the gate and
        executes normally."""
        fire = datetime.now(UTC).replace(microsecond=0)
        context = {"trigger_type": "schedule", "scheduled_for": int(fire.timestamp())}

        workflow, _, claim_calls, result, _ = await self._run_fire(context, next_run=fire)

        assert claim_calls == [(workflow.id, fire)]
        assert "executed successfully" in result

    async def test_unstamped_scheduled_fire_still_executes(self) -> None:
        """Jobs enqueued before the stamp existed carry no scheduled_for key;
        the worker must not gate them, so a deploy never strands a schedule."""
        context = {"trigger_type": "schedule"}

        workflow, _, claim_calls, result, _ = await self._run_fire(context)

        assert claim_calls == [(workflow.id, None)]
        assert "executed successfully" in result

    async def test_garbage_scheduled_for_is_ignored_not_crashed(self) -> None:
        """A manual caller typing its own context (trigger_type=schedule with a
        non-numeric stamp) must not crash fromtimestamp: the fire is treated as
        unstamped, logged, and runs ungated — pre-change behavior."""
        garbage = "not-a-timestamp-" + "x" * 40  # >33 chars: pins log truncation
        context = {"trigger_type": "schedule", "scheduled_for": garbage}

        workflow, _, claim_calls, result, mocks = await self._run_fire(context)

        assert claim_calls == [(workflow.id, None)]
        assert "executed successfully" in result
        mocks.log_warning.assert_called_once_with(
            f"{LogTag.WORKER} Unparseable scheduled_for on scheduled fire; treating as unstamped",
            workflow_id=workflow.id,
            scheduled_for=garbage[:32],
        )

    async def test_overflowing_numeric_scheduled_for_is_ignored_not_crashed(self) -> None:
        """A numeric stamp fromtimestamp cannot represent (year out of range)
        takes the same discard path: ungated, logged with the truncated value."""
        stamp = 10**40
        context = {"trigger_type": "schedule", "scheduled_for": stamp}

        workflow, _, claim_calls, result, mocks = await self._run_fire(context)

        assert claim_calls == [(workflow.id, None)]
        assert "executed successfully" in result
        mocks.log_warning.assert_called_once_with(
            f"{LogTag.WORKER} Unparseable scheduled_for on scheduled fire; treating as unstamped",
            workflow_id=workflow.id,
            scheduled_for=str(stamp)[:32],
        )
