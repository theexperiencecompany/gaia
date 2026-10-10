"""Resume driver (app/services/hil/resume.py): background owners wake on verdicts.

Live runs resume through the executor inbox; background runs have no live run,
so approvals re-enqueue the owner and denials leave a trace where the owner
looks. Everything is best-effort and claim-guarded — a resume failure must
never fail the tap.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.constants.todos import TodoActivityEvent
from app.models.hil_models import LedgerState
from app.services.analytics_service import AnalyticsEvents
from app.services.hil import resume as resume_module
from app.services.hil.resume import (
    _resume_todo,
    _resume_workflow,
    record_owner_deny,
    resume_owner_after_approval,
)

MODULE = "app.services.hil.resume"


def _row(**overrides: Any) -> MagicMock:
    row = MagicMock()
    row.approval_id = "ap_bg1"
    row.conversation_id = "conv-bg"
    row.user_id = "u1"
    row.tool_name = "GMAIL_SEND_EMAIL"
    row.summary = "Send briefing"
    row.state = LedgerState.APPROVED
    row.owner_run_type = ""
    row.owner_id = ""
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


class TestResumeAfterApproval:
    async def test_no_owner_is_a_no_op(self) -> None:
        with patch(f"{MODULE}.approval_ledger_repository") as repo:
            await resume_owner_after_approval(_row())
        repo.claim_resume.assert_not_called()

    async def test_lost_claim_means_another_tap_already_resumed(self) -> None:
        with (
            patch(f"{MODULE}.approval_ledger_repository") as repo,
            patch(f"{MODULE}._resume_todo", new=AsyncMock()) as resume,
        ):
            repo.claim_resume = AsyncMock(return_value=False)
            await resume_owner_after_approval(_row(owner_run_type="todo", owner_id="todo-1"))
        resume.assert_not_awaited()

    async def test_todo_resume_logs_and_reenqueues(self) -> None:
        with (
            patch.object(resume_module, "approval_ledger_repository") as repo,
            patch(f"{MODULE}._resume_todo", new=AsyncMock()) as resume,
        ):
            repo.claim_resume = AsyncMock(return_value=True)
            await resume_owner_after_approval(_row(owner_run_type="todo", owner_id="todo-1"))
        resume.assert_awaited_once()

    async def test_unknown_owner_type_claims_but_runs_nothing(self) -> None:
        with patch(f"{MODULE}.approval_ledger_repository") as repo:
            repo.claim_resume = AsyncMock(return_value=True)
            with patch(f"{MODULE}.log"):
                await resume_owner_after_approval(_row(owner_run_type="cron", owner_id="x"))
        repo.claim_resume.assert_awaited_once()

    async def test_resume_failure_never_raises(self) -> None:
        with (
            patch(f"{MODULE}.approval_ledger_repository") as repo,
            patch(
                f"{MODULE}._resume_workflow",
                new=AsyncMock(side_effect=RuntimeError("redis down")),
            ),
        ):
            repo.claim_resume = AsyncMock(return_value=True)
            await resume_owner_after_approval(_row(owner_run_type="workflow", owner_id="wf-1"))


class TestResumeTodo:
    async def test_resume_enqueues_into_the_parked_conversation(self) -> None:
        pool = MagicMock()
        enqueued: dict[str, Any] = {}

        async def _fake_enqueue(pool_arg: Any, fn: str, *args: Any, **kwargs: Any) -> None:
            enqueued.update(fn=fn, args=args)

        with (
            patch(
                "app.utils.redis_utils.RedisPoolManager.get_pool",
                new=AsyncMock(return_value=pool),
            ),
            patch(
                f"{MODULE}.enqueue_worker_job",
                new=_fake_enqueue,
            ),
        ):
            await _resume_todo(_row(owner_run_type="todo", owner_id="todo-9"))
        # The parked conversation — never a fresh session. A fresh uuid would
        # orphan the parked run's thread, checkpoint, and partial results.
        assert enqueued["fn"] == "resume_tracked_todo"
        assert enqueued["args"] == ("todo-9", "conv-bg", "ap_bg1", "Send briefing")


class TestResumeWorkflow:
    async def test_requeued_with_receipt_context(self) -> None:
        queued: dict[str, Any] = {}

        async def _fake_queue(workflow_id: str, user_id: str, context: Any) -> bool:
            queued.update(workflow_id=workflow_id, user_id=user_id, context=context)
            return True

        with patch(
            "app.services.workflow.queue_service.WorkflowQueueService.queue_workflow_execution",
            new=_fake_queue,
        ):
            await _resume_workflow(_row(owner_run_type="workflow", owner_id="wf-7"))
        assert queued["workflow_id"] == "wf-7"
        assert queued["context"]["resume_from_approval"] == "ap_bg1"
        assert queued["context"]["approval_result"] == "granted"


class TestResumedEvent:
    async def test_todo_resume_emits_event_with_user_id(self) -> None:
        pool = MagicMock()
        with (
            patch(
                "app.utils.redis_utils.RedisPoolManager.get_pool",
                new=AsyncMock(return_value=pool),
            ),
            patch(
                f"{MODULE}.enqueue_worker_job",
                new=AsyncMock(),
            ),
            patch("app.services.hil.resume.capture_event") as capture,
        ):
            await _resume_todo(_row(owner_run_type="todo", owner_id="todo-9"))

        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.HIL_RESUMED,
            {"approval_id": "ap_bg1", "owner_run_type": "todo"},
        )

    async def test_workflow_resume_emits_event_with_user_id(self) -> None:
        async def _fake_queue(workflow_id: str, user_id: str, context: Any) -> bool:
            return True

        with (
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService.queue_workflow_execution",
                new=_fake_queue,
            ),
            patch("app.services.hil.resume.capture_event") as capture,
        ):
            await _resume_workflow(_row(owner_run_type="workflow", owner_id="wf-7"))

        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.HIL_RESUMED,
            {"approval_id": "ap_bg1", "owner_run_type": "workflow"},
        )


@dataclass
class ResumeSeams:
    """The resume driver's seams, each answering only for the parked row's own ids."""

    claim: AsyncMock
    log: MagicMock
    pool: MagicMock
    enqueue: AsyncMock
    brief: AsyncMock
    queue_workflow: AsyncMock
    append_activity: AsyncMock


@pytest.fixture
def seams() -> Iterator[ResumeSeams]:
    pool = MagicMock()

    async def _claim(approval_id: str) -> bool:
        return approval_id == "ap_bg1"

    async def _brief(workflow_id: str, user_id: str) -> str:
        return "last run drafted the briefing" if (workflow_id, user_id) == ("wf-7", "u1") else ""

    with (
        patch(f"{MODULE}.approval_ledger_repository") as repo,
        patch(f"{MODULE}.log") as log,
        patch(f"{MODULE}.RedisPoolManager.get_pool", new=AsyncMock(return_value=pool)),
        patch(f"{MODULE}.enqueue_worker_job", new=AsyncMock()) as enqueue,
        patch(f"{MODULE}.get_last_run_brief", new=AsyncMock(side_effect=_brief)) as brief,
        patch(
            f"{MODULE}.WorkflowQueueService.queue_workflow_execution", new=AsyncMock()
        ) as queue_workflow,
        patch(f"{MODULE}.record_activity", new=AsyncMock(return_value=True)) as activity,
        patch(f"{MODULE}.capture_event"),
    ):
        repo.claim_resume = AsyncMock(side_effect=_claim)
        yield ResumeSeams(
            claim=repo.claim_resume,
            log=log,
            pool=pool,
            enqueue=enqueue,
            brief=brief,
            queue_workflow=queue_workflow,
            append_activity=activity,
        )


class TestResumeRouting:
    @pytest.mark.parametrize(
        "owner", [{"owner_run_type": "todo"}, {"owner_id": "todo-1"}], ids=["no-id", "no-type"]
    )
    async def test_half_an_owner_resumes_nothing(
        self, seams: ResumeSeams, owner: dict[str, str]
    ) -> None:
        await resume_owner_after_approval(_row(**owner))

        seams.claim.assert_not_awaited()

    async def test_a_todo_owner_is_reenqueued_into_its_parked_conversation(
        self, seams: ResumeSeams
    ) -> None:
        await resume_owner_after_approval(_row(owner_run_type="todo", owner_id="todo-9"))

        seams.claim.assert_awaited_once_with("ap_bg1")
        seams.enqueue.assert_awaited_once_with(
            seams.pool, "resume_tracked_todo", "todo-9", "conv-bg", "ap_bg1", "Send briefing"
        )
        seams.queue_workflow.assert_not_awaited()

    async def test_a_workflow_owner_is_requeued_with_its_receipt_and_last_brief(
        self, seams: ResumeSeams
    ) -> None:
        await resume_owner_after_approval(_row(owner_run_type="workflow", owner_id="wf-7"))

        seams.queue_workflow.assert_awaited_once_with(
            "wf-7",
            "u1",
            {
                "resume_from_approval": "ap_bg1",
                "approval_summary": "Send briefing",
                "approval_result": "granted",
                "prior_run_brief": "last run drafted the briefing",
            },
        )
        seams.enqueue.assert_not_awaited()

    async def test_a_missing_brief_is_reported_and_the_resume_goes_on(
        self, seams: ResumeSeams
    ) -> None:
        seams.brief.side_effect = RuntimeError("mongo down")

        await resume_owner_after_approval(_row(owner_run_type="workflow", owner_id="wf-7"))

        assert seams.queue_workflow.await_args.args[2]["prior_run_brief"] == ""
        assert _warned(seams.log) == {
            f"{LogTag.HIL} last-run brief unavailable; resuming without it": {
                "approval_id": "ap_bg1",
                "error": "mongo down",
                "error_type": "RuntimeError",
            }
        }

    async def test_a_failed_claim_is_reported_and_resumes_nothing(self, seams: ResumeSeams) -> None:
        seams.claim.side_effect = ConnectionError("mongo down")

        await resume_owner_after_approval(_row(owner_run_type="todo", owner_id="todo-9"))

        seams.enqueue.assert_not_awaited()
        assert _warned(seams.log) == {
            f"{LogTag.HIL} resume claim failed; skipping resume": {
                "approval_id": "ap_bg1",
                "error": "mongo down",
                "error_type": "ConnectionError",
            }
        }

    async def test_an_unknown_owner_is_reported(self, seams: ResumeSeams) -> None:
        await resume_owner_after_approval(_row(owner_run_type="cron", owner_id="x"))

        assert _warned(seams.log) == {
            f"{LogTag.HIL} unknown resume owner; skipping": {
                "approval_id": "ap_bg1",
                "owner_run_type": "cron",
            }
        }

    async def test_a_failed_resume_is_reported_with_its_owner(self, seams: ResumeSeams) -> None:
        seams.enqueue.side_effect = RuntimeError("redis down")

        await resume_owner_after_approval(_row(owner_run_type="todo", owner_id="todo-9"))

        assert _warned(seams.log) == {
            f"{LogTag.HIL} owner resume failed; the approval itself stands": {
                "approval_id": "ap_bg1",
                "owner_run_type": "todo",
                "owner_id": "todo-9",
                "error": "redis down",
                "error_type": "RuntimeError",
            }
        }


class TestDenyTrace:
    @pytest.mark.parametrize(
        ("feedback", "detail"),
        [
            ("too pricey", "ap_bg1 ('too pricey'): skipped Send briefing"),
            (None, "ap_bg1: skipped Send briefing"),
        ],
        ids=["with-words", "bare"],
    )
    async def test_a_todo_deny_is_logged_on_that_todo(
        self, seams: ResumeSeams, feedback: str | None, detail: str
    ) -> None:
        await record_owner_deny(_row(owner_run_type="todo", owner_id="todo-3"), feedback)

        seams.append_activity.assert_awaited_once_with(
            "todo-3", "u1", TodoActivityEvent.APPROVAL_DENIED, detail
        )

    async def test_workflow_and_live_denies_record_nothing(self, seams: ResumeSeams) -> None:
        await record_owner_deny(_row(owner_run_type="workflow", owner_id="wf-1"), None)
        await record_owner_deny(_row(), None)

        seams.append_activity.assert_not_awaited()


def _warned(log: MagicMock) -> dict[str, dict[str, object]]:
    return {c.args[0]: c.kwargs for c in log.warning.call_args_list}
