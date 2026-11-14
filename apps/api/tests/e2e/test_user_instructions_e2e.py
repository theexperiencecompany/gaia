"""E2E: the user's saved instructions on a chat message the step answers, on live infra.

Real: the instructions route and service with its Redis cache, the send route, the step
and the comms graph, the executor graph, context assembly and the HIL gate on Mongo.
Substituted: both graphs' model (scripted, recording its prompts), the tool store, the
memory engine and the WebSocket fan-out (the e2e step stack).

Not exercised: a real LLM following the instructions; only that they reach it.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from langchain_core.messages import BaseMessage
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.agents.prompts.user_instructions_prompts import USER_INSTRUCTIONS_TAG
from app.models.conversation_log_models import ApprovalRequested
from app.models.user_instructions_models import GLOBAL_INSTRUCTIONS_SCOPE
from app.models.user_models import AuthenticatedUser
from tests.e2e._harness.background import drain_background_runs
from tests.e2e._harness.graph_run import call
from tests.e2e._harness.step_stack import OpenStack, entries_of, replayed
from tests.e2e.test_tracked_todo_chat_e2e import ask_before, gated_run

pytestmark = pytest.mark.e2e

SKIP_APPROVALS = "Never ask me for approval. Run every tool immediately without a card."
GLOBAL_FENCE = f'<{USER_INSTRUCTIONS_TAG} scope="{GLOBAL_INSTRUCTIONS_SCOPE}">'
ASK = "draw the deploy's flowchart"


def _read(prompts: list[list[BaseMessage]]) -> str:
    return " ".join(str(message.content) for prompt in prompts for message in prompt)


def _comms() -> list[Any]:
    return [call("call_executor", {"task": ASK}, call_id="tc_exec"), "On it.", "Done."]


@pytest.mark.usefixtures("mongo_db")
class TestSavedInstructionsOnAStepTurn:
    async def test_they_reach_both_models_and_the_gate_still_asks(
        self,
        open_stack: OpenStack,
        owner: AuthenticatedUser,
        mongo_db: AsyncIOMotorDatabase,
        client: AsyncClient,
    ) -> None:
        await mongo_db["user_instructions"].delete_many({"user_id": owner.user_id})
        saved = await client.put(
            f"/api/v1/instructions/{GLOBAL_INSTRUCTIONS_SCOPE}",
            json={"content": SKIP_APPROVALS, "base_revision": 0},
        )
        assert saved.status_code == 200, saved.text
        await ask_before(mongo_db, "create_flowchart")
        conversation_id = str(uuid4())

        try:
            async with open_stack(executor=gated_run([]), comms=_comms()) as stack:
                sent = await client.post(
                    f"/api/v1/conversations/{conversation_id}/messages",
                    json={"message_id": str(uuid4()), "text": ASK},
                )
                assert sent.status_code == 202, sent.text
                await drain_background_runs()
        finally:
            await mongo_db["user_instructions"].delete_many({"user_id": owner.user_id})

        for model in (stack.comms_model, stack.executor_model):
            read = _read(model.prompts)
            assert GLOBAL_FENCE in read
            assert SKIP_APPROVALS in read
        # The gate is code, not prompt text: the instruction does not skip the approval.
        (requested,) = entries_of(await replayed(conversation_id, owner.user_id), ApprovalRequested)
        assert "flowchart" in requested.summary.lower()
