"""The batched-trigger path in execute_workflow_by_id.

A coalesced run carries its events in Redis, not in the job payload — that is
what let concurrent enqueues dedup down to one job. The task must collect them
and hand the agent the whole batch, and must not run at all when another run
already took them. A gated workflow's batch never drains inside the user's
quiet hours: it waits for their end, and one run there takes every event.
"""

from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from arq.connections import ArqRedis
from arq.constants import default_queue_name, job_key_prefix
from arq.jobs import JobDef
import fakeredis.aioredis
import httpx
import pytest

from app.constants.trigger_gates import GateAuthor
from app.models.trigger_configs import GmailPollInboxConfig
from app.models.trigger_gate_models import AuthoredGate, TriggerGate
from app.models.user_models import AuthenticatedUser, UserDocument
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow, WorkflowStep
from app.services.triggers.handlers.gmail import GmailTriggerHandler
from app.utils.redis_utils import RedisPoolManager
from app.utils.timezone import Timezone
from app.workers.task_envelope import arq_task
from app.workers.tasks.workflow_tasks import execute_workflow_by_id
from tests.helpers import captured_wide_event, live_through, trigger_gate_seams

MODULE = "app.workers.tasks.workflow_tasks"


def _workflow() -> MagicMock:
    wf = MagicMock()
    wf.user_id = "6812f0b3c9a14e2b7d5a91cc"
    wf.steps = []
    wf.repeat = None
    wf.activated = True
    wf.gate = None
    return wf


def _onboarded_user() -> UserDocument:
    return UserDocument.model_validate({"onboarding": {"completed": True}})


async def _run_task(
    context: dict[str, Any] | None,
    drained: list[dict[str, Any]],
    budget_error: Exception | None = None,
) -> tuple[str, AsyncMock, AsyncMock, AsyncMock, Any, Any, Any]:
    with (
        patch(f"{MODULE}.workflow_scheduler") as scheduler,
        patch(
            f"{MODULE}.user_repository.get", new_callable=AsyncMock, return_value=_onboarded_user()
        ),
        patch(
            f"{MODULE}.drain_trigger_batch", new_callable=AsyncMock, return_value=drained
        ) as drain,
        # The paid-only gate is defaulted to active by the workers-dir conftest's
        # autouse _subscription_active_by_default fixture — these tests are
        # about batching, not that one.
        patch(f"{MODULE}.enforce_cost_budget", new_callable=AsyncMock, side_effect=budget_error),
        patch(f"{MODULE}.reschedule_if_refilled", new_callable=AsyncMock) as refill,
        patch(f"{MODULE}.coalesce_window_seconds", return_value=900) as coalesce,
        patch(f"{MODULE}.notification_service", MagicMock(send_notification=AsyncMock())),
        patch(f"{MODULE}.create_execution", new_callable=AsyncMock) as create,
        patch(
            f"{MODULE}.execute_workflow_as_chat",
            new_callable=AsyncMock,
            return_value=("conv-1", []),
        ) as run_chat,
        patch(f"{MODULE}.complete_execution", new_callable=AsyncMock),
        patch(f"{MODULE}.WorkflowService.increment_execution_count", new_callable=AsyncMock),
        patch(f"{MODULE}.capture"),
    ):
        workflow = _workflow()
        scheduler.get_task = AsyncMock(return_value=workflow)
        scheduler.claim_task_for_execution = AsyncMock(return_value=True)
        scheduler.handle_recurring_task = AsyncMock()
        create.return_value = MagicMock(execution_id="exec-1")
        with patch(f"{MODULE}.log") as log_mock:
            result = await execute_workflow_by_id({}, "wf-1", context)
        return result, drain, run_chat, refill, log_mock, coalesce, workflow


class TestTriggerBatchDrain:
    async def test_whole_batch_reaches_the_agent_as_one_run(self) -> None:
        events = [{"id": index} for index in range(12)]
        result, drain, run_chat, refill, log_mock, coalesce, workflow = await _run_task(
            {"trigger_type": "integration", "trigger_batch_key": "trigger_batch:wf-1"}, events
        )

        assert result == "Workflow wf-1 executed successfully"
        drain.assert_awaited_once_with("trigger_batch:wf-1")
        run_chat.assert_awaited_once()
        context = run_chat.await_args.args[2]
        assert context["trigger_data"]["count"] == 12
        assert context["trigger_data"]["events"] == events
        # The wide event carries the batch size — how a burst is audited later.
        log_mock.set_ns.assert_any_call("workflow", trigger_batch_size=12)
        # Events that landed mid-run get their follow-up on the workflow's window.
        refill.assert_awaited_once()
        wf_id, batch_key, window_seconds, refill_context = refill.await_args.args
        assert (wf_id, batch_key, window_seconds) == ("wf-1", "trigger_batch:wf-1", 900)
        assert refill_context["trigger_type"] == "integration"
        # The refill window must be derived from THIS workflow's trigger config,
        # not a default the mock happens to return for anything.
        coalesce.assert_called_once_with(workflow.trigger_config)

    async def test_empty_batch_skips_the_run_entirely(self) -> None:
        """A drained batch must not spend the user's budget re-processing nothing."""
        result, _drain, run_chat, refill, log_mock, _coalesce, _wf = await _run_task(
            {"trigger_type": "integration", "trigger_batch_key": "trigger_batch:wf-1"}, []
        )

        assert result == "Workflow wf-1 skipped — trigger batch empty"
        log_mock.set_ns.assert_any_call("workflow", outcome="trigger_batch_empty")
        run_chat.assert_not_awaited()
        # Even a skipped run held the job id — mid-run arrivals still get
        # their follow-up.
        refill.assert_awaited_once()

    async def test_unbatched_run_never_touches_the_buffer(self) -> None:
        result, drain, run_chat, refill, _log, _coalesce, _wf = await _run_task(
            {"trigger_type": "manual"}, [{"id": 1}]
        )

        assert result == "Workflow wf-1 executed successfully"
        drain.assert_not_awaited()
        refill.assert_not_awaited()
        assert "trigger_data" not in run_chat.await_args.args[2]


class TestGatesRunBeforeTheDrain:
    async def test_budget_walled_run_leaves_the_buffer_intact(self) -> None:
        """A rejected run must not consume the batch; those events belong to a future run."""
        result, drain, run_chat, _refill, _log, _coalesce, _wf = await _run_task(
            {"trigger_type": "integration", "trigger_batch_key": "trigger_batch:wf-1"},
            [{"id": 1}],
            budget_error=RuntimeError("daily budget exhausted"),
        )

        drain.assert_not_awaited()
        run_chat.assert_not_awaited()


class TestRefillOnEveryExit:
    async def test_a_budget_walled_run_still_reschedules_refill_arrivals(self) -> None:
        """A failed, gate-rejected run must not strand arrivals any more than a successful one."""
        result, _drain, _run_chat, refill, _log, _coalesce, _wf = await _run_task(
            {"trigger_type": "integration", "trigger_batch_key": "trigger_batch:wf-1"},
            [{"id": 1}],
            budget_error=RuntimeError("daily budget exhausted"),
        )

        refill.assert_awaited_once()
        wf_id, batch_key, window_seconds, _context = refill.await_args.args
        assert (wf_id, batch_key, window_seconds) == ("wf-1", "trigger_batch:wf-1", 900)

    async def test_a_refill_scheduling_error_never_masks_the_run_result(self) -> None:
        """The refill is best-effort: a Redis blip scheduling it must not fail a successful run."""
        events = [{"id": 1}]
        with patch(
            f"{MODULE}.reschedule_if_refilled",
            new_callable=AsyncMock,
            side_effect=RuntimeError("redis blip"),
        ) as broken_refill:
            with (
                patch(f"{MODULE}.workflow_scheduler") as scheduler,
                patch(
                    f"{MODULE}.user_repository.get",
                    new_callable=AsyncMock,
                    return_value=_onboarded_user(),
                ),
                patch(f"{MODULE}.drain_trigger_batch", new_callable=AsyncMock, return_value=events),
                patch(f"{MODULE}.enforce_cost_budget", new_callable=AsyncMock),
                patch(f"{MODULE}.coalesce_window_seconds", return_value=900),
                patch(f"{MODULE}.create_execution", new_callable=AsyncMock) as create,
                patch(
                    f"{MODULE}.execute_workflow_as_chat",
                    new_callable=AsyncMock,
                    return_value=("conv-1", []),
                ),
                patch(f"{MODULE}.complete_execution", new_callable=AsyncMock),
                patch(
                    f"{MODULE}.WorkflowService.increment_execution_count", new_callable=AsyncMock
                ),
                patch(f"{MODULE}.capture"),
                patch(f"{MODULE}.log") as log_mock,
            ):
                scheduler.get_task = AsyncMock(return_value=_workflow())
                scheduler.claim_task_for_execution = AsyncMock(return_value=True)
                scheduler.handle_recurring_task = AsyncMock()
                create.return_value = MagicMock(execution_id="exec-1")
                result = await execute_workflow_by_id(
                    {},
                    "wf-1",
                    {"trigger_type": "integration", "trigger_batch_key": "trigger_batch:wf-1"},
                )

        assert result == "Workflow wf-1 executed successfully"
        broken_refill.assert_awaited_once()
        log_mock.warning.assert_any_call(
            "[WORKER] Trigger batch refill check failed",
            workflow_id="wf-1",
            error="redis blip",
            error_type="RuntimeError",
        )

    async def test_a_run_with_no_context_never_touches_batching(self) -> None:
        """Scheduled fires pass no context, so no batch-shaped logic may run for them."""
        result, drain, _run_chat, refill, _log, coalesce, _wf = await _run_task(None, [])

        assert result == "Workflow wf-1 executed successfully"
        drain.assert_not_awaited()
        refill.assert_not_awaited()
        coalesce.assert_not_called()


class TestDrainUnavailable:
    async def test_redis_down_at_drain_never_claims_the_batch_was_empty(self) -> None:
        """None from the drain means "could not look"; the run must exit without consuming."""
        result, drain, run_chat, refill, log_mock, _coalesce, _wf = await _run_task(
            {"trigger_type": "integration", "trigger_batch_key": "trigger_batch:wf-1"},
            None,  # drain_trigger_batch returns None
        )

        assert result == "Workflow wf-1 skipped — trigger batch unavailable"
        log_mock.set_ns.assert_any_call("workflow", outcome="trigger_batch_unavailable")
        run_chat.assert_not_awaited()
        refill.assert_awaited_once()


KOLKATA = ZoneInfo("Asia/Kolkata")
_GATE_MODULE = "app.services.triggers.trigger_gate"
_GATED_ID = "wf_quiet000001"
_OWNER_ID = "6812f0b3c9a14e2b7d5a91cc"
_BILLING = AuthoredGate(condition="the email is about billing", author=GateAuthor.GAIA)
# Every gate question asks both; by day only "gate" is read: run. At night "urgent": it can wait.
_CAN_WAIT = {
    "answers": {
        "gate": {
            "type": "choice",
            "choice": "needed",
            "probabilities": {"needed": 0.9, "not_needed": 0.1},
        },
        "urgent": {
            "type": "choice",
            "choice": "can_wait",
            "probabilities": {
                "incident": 0.0,
                "service_down": 0.0,
                "meeting": 0.0,
                "can_wait": 1.0,
            },
        },
    }
}
_POLLED = TriggerConfig(
    type=TriggerType.INTEGRATION,
    trigger_name="gmail_poll_inbox",
    trigger_data=GmailPollInboxConfig(interval=15),
)
_PER_EMAIL = TriggerConfig(type=TriggerType.INTEGRATION, trigger_name="gmail_new_message")
# Never batches by day: each event runs at once.
_UNBATCHED = TriggerConfig(type=TriggerType.INTEGRATION, trigger_name="slack_new_message")


def _on_kolkata_clock(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=KOLKATA)


class _Inbox(GmailTriggerHandler):
    """The real Gmail dispatch, signals and gate included, for one workflow served in memory."""

    def __init__(self, workflow: Workflow) -> None:
        self._workflow = workflow

    def occurrence_key(self, event_type: str, data: Mapping[str, object]) -> str | None:
        return None

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: dict[str, object]
    ) -> list[Workflow]:
        return [self._workflow]


@pytest.fixture
async def arq_queue() -> AsyncIterator[ArqRedis]:
    """Serve a real ArqRedis on fakeredis, so job-id dedupe and each job's time are as in production."""
    server = fakeredis.aioredis.FakeRedis()
    pool = ArqRedis(pool_or_conn=server.connection_pool)
    with patch.object(RedisPoolManager, "get_pool", AsyncMock(return_value=pool)):
        yield pool
    await server.aclose()


@contextmanager
def _live_stack(workflow: Workflow, runs: list[tuple[datetime, int]]) -> Iterator[None]:
    """Run the dispatcher and the worker for real around the JEV call and the agent run."""

    async def run_chat(
        _workflow: Workflow, _user: AuthenticatedUser, context: dict[str, Any], **_: object
    ) -> tuple[str, list[object]]:
        runs.append((datetime.now(KOLKATA), context["trigger_data"]["count"]))
        return "conv-1", []

    with (
        trigger_gate_seams(Timezone.parse("Asia/Kolkata")) as gate,
        patch(
            "app.services.triggers.base.TriggerHandler._queue_todo_dispatch",
            AsyncMock(return_value=True),
        ),
        patch("app.services.triggers.base.get_signal_matching_context", AsyncMock(return_value="")),
        patch(f"{MODULE}.workflow_scheduler") as scheduler,
        patch(f"{MODULE}.user_repository.get", AsyncMock(return_value=_onboarded_user())),
        patch(f"{MODULE}.pause_workflow_before_fire", AsyncMock(return_value=[])),
        patch(f"{MODULE}.enforce_cost_budget", AsyncMock()),
        patch(
            f"{MODULE}.create_execution", AsyncMock(return_value=MagicMock(execution_id="exec-1"))
        ),
        patch(f"{MODULE}.execute_workflow_as_chat", AsyncMock(side_effect=run_chat)),
        patch(f"{MODULE}.complete_execution", AsyncMock()),
        patch(f"{MODULE}.distrust_fresh_playbook", AsyncMock()),
        patch(f"{MODULE}.WorkflowService.increment_execution_count", AsyncMock()),
        patch(f"{MODULE}.capture"),
    ):
        gate.jev.mock(return_value=httpx.Response(200, json=_CAN_WAIT))
        scheduler.get_task = AsyncMock(return_value=workflow)
        scheduler.handle_recurring_task = AsyncMock()
        yield


async def _live_through(
    queue: ArqRedis, workflow: Workflow, emails: list[datetime]
) -> list[tuple[datetime, int]]:
    """Deliver each new email at its moment and fire every job when due; return each run's start and size.

    Two drains due at one instant would race for the workflow's conversation, so none may.
    """
    runs: list[tuple[datetime, int]] = []
    fired_at: list[datetime] = []

    async def deliver(moment: datetime) -> None:
        email: dict[str, object] = {
            "thread_id": f"t{moment:%d%H%M}",
            "message_id": f"t{moment:%d%H%M}",
        }
        await _Inbox(workflow).process_event("GMAIL_NEW_GMAIL_MESSAGE", None, _OWNER_ID, email)

    async def fire(job: JobDef) -> None:
        fired_at.append(datetime.now(UTC))
        await arq_task(execute_workflow_by_id)({}, *job.args, **job.kwargs)
        await queue.delete(job_key_prefix + job.job_id)
        await queue.zrem(default_queue_name, job.job_id)

    with _live_stack(workflow, runs):
        await live_through(queue, emails, deliver, fire)
    assert len(set(fired_at)) == len(fired_at), f"drains due at once: {fired_at}"
    return runs


def _workflow_gated_by(gate: TriggerGate | None, trigger_config: TriggerConfig) -> Workflow:
    return Workflow(
        id=_GATED_ID,
        user_id=_OWNER_ID,
        title="Draft replies",
        steps=[WorkflowStep(title="Draft", description="Draft the reply")],
        trigger_config=trigger_config,
        gate=gate,
    )


class TestAGatedBatchWaitsOutQuietHours:
    """Founder's rule: a gated job starts no run inside quiet hours unless it is urgent.

    What it held runs when they end, once, with everything that arrived; an
    ungated job batches exactly as it always has.
    """

    @pytest.mark.usefixtures("fake_redis")
    @pytest.mark.parametrize(
        ("gate", "trigger_config", "emails", "runs"),
        [
            pytest.param(
                _BILLING,
                _POLLED,
                [_on_kolkata_clock(1, 21, 50), _on_kolkata_clock(1, 23, 0)],
                [(_on_kolkata_clock(2, 8, 0), 2)],
                id="batch-due-inside-quiet-hours",
            ),
            pytest.param(
                _BILLING,
                _POLLED,
                [_on_kolkata_clock(1, 21, 50)],
                [(_on_kolkata_clock(2, 8, 0), 1)],
                id="batch-of-day-email-due-inside-quiet-hours",
            ),
            pytest.param(
                _BILLING,
                _PER_EMAIL,
                [_on_kolkata_clock(1, 14, 30), _on_kolkata_clock(2, 2, 30)],
                [(_on_kolkata_clock(2, 8, 0), 2)],
                id="batch-due-after-quiet-hours",
            ),
            pytest.param(
                _BILLING,
                _UNBATCHED,
                [_on_kolkata_clock(1, 23, 0), _on_kolkata_clock(2, 2, 30)],
                [(_on_kolkata_clock(2, 8, 0), 2)],
                id="unbatched-trigger-held-overnight",
            ),
            pytest.param(
                None,
                _POLLED,
                [_on_kolkata_clock(1, 21, 50), _on_kolkata_clock(1, 23, 0)],
                [(_on_kolkata_clock(1, 22, 5), 1), (_on_kolkata_clock(1, 23, 15), 1)],
                id="ungated-polled",
            ),
            pytest.param(
                None,
                _PER_EMAIL,
                [_on_kolkata_clock(1, 14, 30), _on_kolkata_clock(2, 2, 30)],
                [(_on_kolkata_clock(2, 14, 30), 2)],
                id="ungated-per-email",
            ),
        ],
    )
    async def test_a_night_of_email_runs_when_quiet_hours_end_and_only_then(
        self,
        arq_queue: ArqRedis,
        gate: TriggerGate | None,
        trigger_config: TriggerConfig,
        emails: list[datetime],
        runs: list[tuple[datetime, int]],
    ) -> None:
        assert (
            await _live_through(arq_queue, _workflow_gated_by(gate, trigger_config), emails) == runs
        )


class TestADrainDueInsideQuietHours:
    """A gated batch's drain that comes due at night moves to the morning, before any run starts."""

    @pytest.mark.usefixtures("fake_redis")
    async def test_it_moves_to_the_morning_with_its_context_and_says_so(
        self, arq_queue: ArqRedis
    ) -> None:
        workflow = _workflow_gated_by(_BILLING, _POLLED)
        context: dict[str, object] = {
            "trigger_type": "integration",
            "trigger_batch_key": f"trigger_batch:{_GATED_ID}",
        }
        night = _on_kolkata_clock(1, 23, 0)

        with (
            patch(f"{MODULE}.workflow_scheduler") as scheduler,
            trigger_gate_seams(Timezone.parse("Asia/Kolkata"), now=night) as gate,
        ):
            scheduler.get_task = AsyncMock(return_value=workflow)
            async with captured_wide_event() as event:
                result = await execute_workflow_by_id({}, _GATED_ID, context)
            (job,) = await arq_queue.queued_jobs()

        assert result == f"Workflow {_GATED_ID} held until the user's quiet hours end"
        scheduler.get_task.assert_awaited_once_with(_GATED_ID)
        gate.tz.assert_awaited_once_with(_OWNER_ID)
        assert job.args == (_GATED_ID, {**context, "quiet_hours": {"kind": "hold"}})
        assert job.score == int(_on_kolkata_clock(2, 8, 0).timestamp() * 1000)
        assert event["workflow_id"] == _GATED_ID
        assert event["workflow"] == {
            "outcome": "held_for_quiet_hours",
            "held_until": "2026-10-02T08:00:00+05:30",
        }
