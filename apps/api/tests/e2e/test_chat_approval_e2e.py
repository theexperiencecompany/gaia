"""E2E: an approval a chat message's work asks for, from the send to the user's decision, on live infra.

Real: the send route, the step and the comms graph, the executor graph on the Postgres
checkpointer, the HIL gate and ledger, the decision route and the conversation log on
Mongo, the events route's replay. Substituted: both graphs' model (scripted), the tool
store, the memory engine and the WebSocket fan-out (the e2e step stack).

Not exercised: a real LLM, and a device holding the events stream open (the log replay
is what the events route sends a device that connects).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.models.conversation_log_models import (
    ApprovalDecided,
    ApprovalRequested,
    Entry,
    UserMessage,
    WorkFinished,
    WorkStarted,
)
from app.models.user_models import AuthenticatedUser
from tests.e2e._harness.background import drain_background_runs
from tests.e2e._harness.graph_run import call
from tests.e2e._harness.step_stack import OpenStack, entries_of, replayed
from tests.e2e.test_tracked_todo_chat_e2e import (
    DRAWN,
    SKIPPED,
    WAITING,
    ask_before,
    gated_run,
    redeem,
)

pytestmark = pytest.mark.e2e

ASK = "draw the deploy's flowchart"
NARRATED = "Your flowchart is ready."
FEEDBACK = "not this week"


async def _send(client: AsyncClient, conversation_id: str, text: str) -> None:
    sent = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message_id": str(uuid4()), "text": text},
    )
    assert sent.status_code == 202, sent.text
    await drain_background_runs()


def _comms() -> list[Any]:
    return [call("call_executor", {"task": ASK}, call_id="tc_exec"), "On it.", NARRATED, NARRATED]


async def _ledger(mongo_db: AsyncIOMotorDatabase, approval_id: str) -> str:
    row = await mongo_db["approval_ledger"].find_one({"approval_id": approval_id})
    assert row is not None
    return str(row["state"])


async def _ask_and_park(
    client: AsyncClient, owner: AuthenticatedUser, conversation_id: str
) -> tuple[list[Entry], ApprovalRequested]:
    await _send(client, conversation_id, ASK)
    parked = await replayed(conversation_id, owner.user_id)
    (requested,) = entries_of(parked, ApprovalRequested)
    return parked, requested


@pytest.mark.usefixtures("mongo_db")
class TestAnApprovalAChatMessagesWorkAsksFor:
    async def test_the_request_is_logged_on_the_messages_work_and_the_call_waits(
        self,
        open_stack: OpenStack,
        owner: AuthenticatedUser,
        mongo_db: AsyncIOMotorDatabase,
        client: AsyncClient,
    ) -> None:
        """Regression: a chat turn on the step carried no run identity, so the gate let every call through."""
        await ask_before(mongo_db, "create_flowchart")
        conversation_id = str(uuid4())

        async with open_stack(executor=gated_run([]), comms=_comms()):
            parked, requested = await _ask_and_park(client, owner, conversation_id)

        (message,) = entries_of(parked, UserMessage)
        (work,) = entries_of(parked, WorkStarted)
        (finished,) = entries_of(parked, WorkFinished)
        assert work.answers == (message.id,)
        assert requested.task_id == work.task_id
        assert "flowchart" in requested.summary.lower()
        # The gated call did not run: the work ended on the proposal, and the ledger waits.
        assert finished.report == WAITING
        assert await _ledger(mongo_db, requested.approval_id) == "pending"
        assert entries_of(parked, ApprovalDecided) == []

    async def test_approving_logs_the_decision_and_resumes_the_work(
        self,
        open_stack: OpenStack,
        owner: AuthenticatedUser,
        mongo_db: AsyncIOMotorDatabase,
        client: AsyncClient,
    ) -> None:
        await ask_before(mongo_db, "create_flowchart")
        conversation_id = str(uuid4())

        async with open_stack(executor=gated_run([redeem(), DRAWN]), comms=_comms()):
            _, requested = await _ask_and_park(client, owner, conversation_id)
            decided = await client.post(
                f"/api/v1/approvals/{requested.approval_id}/decision", json={"decision": "approve"}
            )
            await drain_background_runs()

        assert decided.json()["status"] == "approved"
        shown = await replayed(conversation_id, owner.user_id)
        (decision,) = entries_of(shown, ApprovalDecided)
        assert (decision.approval_id, decision.decision) == (requested.approval_id, "approve")
        assert [finished.report for finished in entries_of(shown, WorkFinished)] == [WAITING, DRAWN]
        assert await _ledger(mongo_db, requested.approval_id) == "executed"

    async def test_denying_logs_the_decision_and_tells_the_model(
        self,
        open_stack: OpenStack,
        owner: AuthenticatedUser,
        mongo_db: AsyncIOMotorDatabase,
        client: AsyncClient,
    ) -> None:
        await ask_before(mongo_db, "create_flowchart")
        conversation_id = str(uuid4())
        executor = gated_run([SKIPPED])

        async with open_stack(executor=executor, comms=_comms()):
            _, requested = await _ask_and_park(client, owner, conversation_id)
            before = len(executor.prompts)
            decided = await client.post(
                f"/api/v1/approvals/{requested.approval_id}/decision",
                json={"decision": "deny", "feedback": FEEDBACK},
            )
            await drain_background_runs()

        assert decided.json()["status"] == "denied"
        shown = await replayed(conversation_id, owner.user_id)
        (decision,) = entries_of(shown, ApprovalDecided)
        assert decision.decision == "deny"
        assert await _ledger(mongo_db, requested.approval_id) == "denied"
        told = " ".join(str(m.content) for prompt in executor.prompts[before:] for m in prompt)
        assert FEEDBACK in told
        assert entries_of(shown, WorkFinished)[-1].report.startswith(SKIPPED)
