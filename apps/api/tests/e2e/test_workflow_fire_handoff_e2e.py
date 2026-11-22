"""E2E: a workflow fire reaches the executor and its result lands in the workflow's chat, on live infra.

Real: execute_workflow_by_id as the ARQ job runs it (gates, admission, execution record),
the fire appended to the conversation log, the step and the comms graph with its real
call_executor and comms ledger, the executor graph and its run, all on real Mongo, Redis
and the Postgres checkpointer. Substituted: both graphs' model (scripted), the paid gate,
the tool store, the memory engine and the WebSocket fan-out (the e2e step stack).

Not exercised: a real LLM choosing for_messages, and ARQ picking the job up (the test calls it).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.db.repositories.workflows import workflow_repository
from app.models.conversation_log_models import Reply
from app.models.scheduler_models import ScheduledTaskStatus
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import (
    TriggerConfig,
    TriggerType,
    WorkflowDocument,
    WorkflowStep,
)
from app.workers.tasks import workflow_tasks
from app.workers.tasks.workflow_tasks import execute_workflow_by_id
from tests.e2e._harness.background import drain_background_runs
from tests.e2e._harness.graph_run import call
from tests.e2e._harness.step_stack import OpenStack, entries_of, replayed

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("conversation_indexes")]

REPORT = "Overnight: 2 invoices due, 1 meeting moved to 3pm."
NARRATED = "Your morning digest: 2 invoices are due and a meeting moved to 3pm."
HANDED_OFF = "On it."


def _comms() -> list[Any]:
    """Script the fire's turn: hand the workflow off naming no message, then narrate the work's result."""
    return [
        call(
            "call_executor",
            {"task": "Run the morning digest workflow", "for_messages": []},
            call_id="tc_exec",
        ),
        HANDED_OFF,
        NARRATED,
    ]


@pytest.fixture
async def workflow(
    owner: AuthenticatedUser, mongo_db: AsyncIOMotorDatabase
) -> AsyncIterator[WorkflowDocument]:
    """Yield a scheduled workflow of an onboarded owner, idle and due."""
    await mongo_db["users"].update_one(
        {"_id": ObjectId(owner.user_id)}, {"$set": {"onboarding.completed": True}}
    )
    created = await workflow_repository.create(
        WorkflowDocument(
            user_id=owner.user_id,
            title="Morning digest",
            description="Summarize overnight mail.",
            prompt="Summarize overnight mail.",
            trigger_config=TriggerConfig(
                type=TriggerType.SCHEDULE, cron_expression="0 9 * * *", timezone="UTC"
            ),
            steps=[WorkflowStep(id="s1", title="Summarize", category="general", description="a")],
            activated=True,
            status=ScheduledTaskStatus.SCHEDULED,
        )
    )
    yield created
    await mongo_db["workflows"].delete_many({"_id": created.id})
    await mongo_db["workflow_executions"].delete_many({"workflow_id": created.id})


@pytest.mark.regression
@pytest.mark.parametrize("trigger_type", [TriggerType.SCHEDULE, TriggerType.MANUAL])
async def test_a_workflow_fire_runs_its_work_and_delivers_the_result(
    open_stack: OpenStack,
    owner: AuthenticatedUser,
    workflow: WorkflowDocument,
    mongo_db: AsyncIOMotorDatabase,
    trigger_type: TriggerType,
) -> None:
    delivered = AsyncMock()
    with (
        patch.object(workflow_tasks, "is_paid", AsyncMock(return_value=True)),
        patch.object(workflow_tasks, "notify_workflow_result", delivered),
    ):
        async with open_stack(executor=[REPORT], comms=_comms()) as stack:
            result = await execute_workflow_by_id(
                {}, workflow.id, {"trigger_type": trigger_type.value}
            )
            await drain_background_runs()

    assert result == f"Workflow {workflow.id} executed successfully"
    execution = await mongo_db["workflow_executions"].find_one({"workflow_id": workflow.id})
    assert execution is not None
    assert execution["status"] == "success", execution.get("error_message")
    assert stack.executor_model.prompts, "the fire never reached the executor"
    # What the user is sent is the work's result, never the hand-off's acknowledgement.
    [notified] = delivered.await_args_list
    assert notified.kwargs["result_text"] == NARRATED
    shown = await replayed(execution["conversation_id"], owner.user_id)
    assert NARRATED in [reply.text for reply in entries_of(shown, Reply)]
