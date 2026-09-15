"""The paid-only gate in execute_workflow_by_id — the single ARQ choke point.

Every workflow fire (manual "run now" via WorkflowService.execute_workflow,
a scheduler cron fire, and a batched Composio/email trigger via
app.services.triggers.batching) enqueues this same "execute_workflow_by_id"
ARQ job — see app/services/workflow/queue_service.py, scheduler.py, and
services/triggers/batching.py. So gating here, once, covers every trigger
type without sprinkling the check per call site.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.constants.log_tags import LogTag
from app.decorators import entitlements
from app.models.payment_models import PlanType
from app.models.user_models import UserDocument
from app.services.analytics_service import AnalyticsEvents
from app.workers.tasks.workflow_tasks import PAYWALL_FEATURE_WORKFLOW, execute_workflow_by_id

MODULE = "app.workers.tasks.workflow_tasks"


def _make_workflow(user_id: str = "user-free-1") -> MagicMock:
    wf = MagicMock()
    wf.id = str(uuid4())
    wf.user_id = user_id
    wf.title = "Daily Digest"
    wf.steps = [MagicMock(id="s1", title="Step 1", description="do it", category="general")]
    wf.repeat = None
    wf.activated = True
    return wf


def _patch_scheduler(workflow: MagicMock):
    scheduler = AsyncMock()
    scheduler.get_task = AsyncMock(return_value=workflow)
    return scheduler, patch(f"{MODULE}.workflow_scheduler", scheduler)


@pytest.fixture(autouse=True)
def _onboarded_user():
    """Keep the onboarding gate out of the way — this file is about the
    subscription gate, which runs before it."""
    user = UserDocument.model_validate({"onboarding": {"completed": True}})
    with patch(f"{MODULE}.user_repository.get", AsyncMock(return_value=user)):
        yield


@pytest.fixture(autouse=True)
def _no_real_analytics():
    with patch(f"{MODULE}.capture_event"):
        yield


class TestPaidOnlyGateBlocksFreeUsers:
    async def test_free_user_run_is_skipped_and_workflow_deactivated(self) -> None:
        workflow = _make_workflow(user_id="user-free-1")
        scheduler, p_scheduler = _patch_scheduler(workflow)

        mock_execute_chat = AsyncMock()
        mock_create_execution = AsyncMock()

        with (
            p_scheduler,
            patch(f"{MODULE}.is_paid", AsyncMock(return_value=False)),
            patch(f"{MODULE}.execute_workflow_as_chat", mock_execute_chat),
            patch(f"{MODULE}.create_execution", mock_create_execution),
            patch(f"{MODULE}.enforce_daily_cost_budget", new_callable=AsyncMock),
            patch(f"{MODULE}.log") as mock_log,
        ):
            result = await execute_workflow_by_id({}, workflow.id, {"trigger_type": "schedule"})

        assert result == f"Workflow {workflow.id} skipped — subscription required"
        # The run must never reach execution or record an execution — a skip
        # is not a failed run, and it must not touch billing-relevant state.
        mock_execute_chat.assert_not_called()
        mock_create_execution.assert_not_called()
        mock_log.warning.assert_called_once_with(
            f"{LogTag.WORKER} Workflow skipped — subscription required",
            workflow_id=workflow.id,
            user_id="user-free-1",
        )

    async def test_free_user_run_is_skipped_for_manual_trigger_too(self) -> None:
        """Not just scheduled fires — a manual "run now" from a lapsed user is
        gated at the exact same choke point."""
        workflow = _make_workflow(user_id="user-free-2")
        scheduler, p_scheduler = _patch_scheduler(workflow)

        mock_execute_chat = AsyncMock()

        with (
            p_scheduler,
            patch(f"{MODULE}.is_paid", AsyncMock(return_value=False)),
            patch(f"{MODULE}.execute_workflow_as_chat", mock_execute_chat),
        ):
            result = await execute_workflow_by_id({}, workflow.id, {"trigger_type": "manual"})

        assert result == f"Workflow {workflow.id} skipped — subscription required"
        mock_execute_chat.assert_not_called()

    async def test_free_user_run_is_skipped_for_integration_trigger_too(self) -> None:
        """Composio/email trigger fires drain their batch via the same
        function — the gate must sit before that drain, not after, so a
        lapsed user's buffered events are never spent on a run."""
        workflow = _make_workflow(user_id="user-free-3")
        scheduler, p_scheduler = _patch_scheduler(workflow)

        mock_drain = AsyncMock()

        with (
            p_scheduler,
            patch(f"{MODULE}.is_paid", AsyncMock(return_value=False)),
            patch(f"{MODULE}.drain_trigger_batch", mock_drain),
        ):
            result = await execute_workflow_by_id(
                {},
                workflow.id,
                {"trigger_type": "integration", "trigger_batch_key": "trigger_batch:wf-1"},
            )

        assert result == f"Workflow {workflow.id} skipped — subscription required"
        mock_drain.assert_not_called()

    async def test_gate_checks_the_workflow_owner_not_a_stale_context_user(self) -> None:
        """is_paid must be asked about the workflow's actual
        owner (workflow.user_id) — not any id that happens to be lying around
        in the trigger context."""
        workflow = _make_workflow(user_id="the-real-owner")
        scheduler, p_scheduler = _patch_scheduler(workflow)

        mock_is_active = AsyncMock(return_value=False)

        with (
            p_scheduler,
            patch(f"{MODULE}.is_paid", mock_is_active),
        ):
            await execute_workflow_by_id({}, workflow.id, {"trigger_type": "manual"})

        mock_is_active.assert_awaited_once_with("the-real-owner")


class TestTheBlockReachesTheFunnel:
    """A skipped run is a paywall block like any other, and must be countable.

    This gate cannot go through ``require_active_subscription`` — that raises,
    and a worker must skip and re-arm — so the event it would have fired has to
    be fired here. Without it, "how many users lost a workflow run to the wall"
    is unanswerable while every HTTP and bot surface answers it.
    """

    async def test_a_skipped_run_is_captured_against_the_owners_own_profile(self) -> None:
        """A worker has no request context: an implicit distinct_id would strand
        the block on an anonymous profile that never joins the user's funnel."""
        workflow = _make_workflow(user_id="user-free-7")
        scheduler, p_scheduler = _patch_scheduler(workflow)

        with (
            p_scheduler,
            patch(f"{MODULE}.is_paid", AsyncMock(return_value=False)),
            patch(f"{MODULE}.capture_event") as capture,
        ):
            await execute_workflow_by_id({}, workflow.id, {"trigger_type": "schedule"})

        capture.assert_called_once_with(
            "user-free-7",
            AnalyticsEvents.PAYWALL_BLOCKED,
            {"feature": PAYWALL_FEATURE_WORKFLOW},
        )

    async def test_a_run_that_clears_the_gate_is_never_captured_as_blocked(self) -> None:
        """A stale cached FREE that the fresh read overturns is not a block."""
        workflow = _make_workflow(user_id="user-paid-stale-2")
        scheduler, p_scheduler = _patch_scheduler(workflow)

        with (
            p_scheduler,
            patch(f"{MODULE}.is_paid", AsyncMock(return_value=True)),
            patch(f"{MODULE}._admit_fire", AsyncMock(return_value=None)),
            patch(f"{MODULE}.enforce_daily_cost_budget", new_callable=AsyncMock),
            patch(
                f"{MODULE}._drain_trigger_events",
                AsyncMock(return_value=({"trigger_type": "schedule"}, "drained-for-test")),
            ),
            patch(f"{MODULE}.capture_event") as capture,
        ):
            await execute_workflow_by_id({}, workflow.id, {"trigger_type": "schedule"})

        captured = [call.args[1] for call in capture.call_args_list]
        assert AnalyticsEvents.PAYWALL_BLOCKED not in captured


class TestTheGateReadsTheRowWhenTheCacheSaysFree:
    async def test_a_user_who_just_paid_runs_off_the_row_not_the_stale_cache(self) -> None:
        """The real gate, not a stub of it: the cache says FREE, the row says
        PRO, and the run goes ahead."""
        workflow = _make_workflow(user_id="user-paid-stale-3")
        scheduler, p_scheduler = _patch_scheduler(workflow)

        with (
            p_scheduler,
            patch(f"{MODULE}.is_paid", entitlements.is_paid),
            patch(
                "app.decorators.entitlements.payment_service.get_cached_plan_type",
                AsyncMock(return_value=PlanType.FREE),
            ),
            patch(
                "app.decorators.entitlements.payment_service.get_user_subscription_status",
                AsyncMock(return_value=MagicMock(plan_type=PlanType.PRO)),
            ),
            patch("app.decorators.entitlements.invalidate_plan_cache", new_callable=AsyncMock),
            patch(f"{MODULE}._admit_fire", AsyncMock(return_value=None)),
            patch(f"{MODULE}.enforce_daily_cost_budget", new_callable=AsyncMock),
            patch(
                f"{MODULE}._drain_trigger_events",
                AsyncMock(return_value=({"trigger_type": "schedule"}, "drained-for-test")),
            ),
        ):
            result = await execute_workflow_by_id({}, workflow.id, {"trigger_type": "schedule"})

        assert result == "drained-for-test"


class TestPaidOnlyGateLetsProUsersThrough:
    async def test_pro_user_run_proceeds_to_execution(self) -> None:
        workflow = _make_workflow(user_id="user-pro-1")
        scheduler, p_scheduler = _patch_scheduler(workflow)

        mock_execution = MagicMock()
        mock_execution.execution_id = "exec-pro-1"

        with (
            p_scheduler,
            patch(f"{MODULE}.is_paid", AsyncMock(return_value=True)),
            patch(f"{MODULE}.enforce_daily_cost_budget", new_callable=AsyncMock),
            patch(
                f"{MODULE}.create_execution",
                new_callable=AsyncMock,
                return_value=mock_execution,
            ),
            patch(f"{MODULE}.complete_execution", new_callable=AsyncMock),
            patch(
                f"{MODULE}.execute_workflow_as_chat",
                new_callable=AsyncMock,
                return_value=("conv-pro-1", MagicMock()),
            ) as mock_execute_chat,
            patch(f"{MODULE}.WorkflowService.increment_execution_count", new_callable=AsyncMock),
        ):
            result = await execute_workflow_by_id({}, workflow.id, {"trigger_type": "schedule"})

        assert "executed successfully" in result
        mock_execute_chat.assert_awaited_once()


class TestTheGateNeverDestroys:
    """Found in review: the gate deactivated every workflow the user owned off a
    five-minute-stale cache read. Deactivation belongs to the billing webhook;
    the gate only skips (``is_paid`` asks the database before it does — see
    ``TestTheGateReadsTheRowWhenTheCacheSaysFree``)."""

    async def test_a_skipped_scheduled_run_is_re_armed_not_deactivated(self) -> None:
        workflow = _make_workflow(user_id="user-free-4")
        workflow.repeat = "daily"
        scheduler, p_scheduler = _patch_scheduler(workflow)
        with (
            p_scheduler,
            patch(f"{MODULE}.is_paid", AsyncMock(return_value=False)),
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            await execute_workflow_by_id({}, workflow.id, {"trigger_type": "schedule"})

        scheduler.handle_recurring_task.assert_awaited_once()
        service.deactivate_workflow.assert_not_called()

    async def test_the_re_arm_names_the_workflow_it_could_not_arm(self) -> None:
        """A re-arm failure is logged against the workflow id; a lost id is an
        unattributable error in the worker log."""
        workflow = _make_workflow(user_id="user-free-6")
        workflow.repeat = "daily"
        scheduler, p_scheduler = _patch_scheduler(workflow)
        with (
            p_scheduler,
            patch(f"{MODULE}.is_paid", AsyncMock(return_value=False)),
            patch(f"{MODULE}._rearm_quietly", new_callable=AsyncMock) as rearm,
        ):
            context = {"trigger_type": "schedule"}
            await execute_workflow_by_id({}, workflow.id, context)

        rearm.assert_awaited_once_with(scheduler, workflow, context, workflow.id)

    async def test_a_skipped_manual_run_does_not_shift_the_schedule(self) -> None:
        workflow = _make_workflow(user_id="user-free-5")
        workflow.repeat = "daily"
        scheduler, p_scheduler = _patch_scheduler(workflow)
        with (
            p_scheduler,
            patch(f"{MODULE}.is_paid", AsyncMock(return_value=False)),
        ):
            await execute_workflow_by_id({}, workflow.id, {"trigger_type": "manual"})

        scheduler.handle_recurring_task.assert_not_called()
