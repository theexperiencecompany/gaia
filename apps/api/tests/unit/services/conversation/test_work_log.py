"""record_work_started: work is logged only under the step claim that dispatches it."""

import pytest

from app.models.agent_config import StepTurnRef
from app.services.conversation.runtime import install_runtime_ports
from app.services.conversation.work_log import record_work_started
from tests.unit.services.conversation.log_helpers import user
from tests.unit.services.conversation.runtime_doubles import Runtime

pytestmark = pytest.mark.unit

CONVERSATION = "conv-work"
STALE_STEP: StepTurnRef = {"epoch": 99, "batch_start": 1, "cause_through": 1, "answers": ["u1"]}


async def test_work_under_a_claim_the_step_no_longer_holds_is_refused() -> None:
    runtime = Runtime()
    install_runtime_ports(runtime.ports)
    await runtime.log.append(CONVERSATION, "user-1", user("u1"))

    logged = await record_work_started(STALE_STEP, CONVERSATION, "user-1", "task-1")

    assert logged is False
    assert [
        entry.entry.id for entry in await runtime.log.read_after(CONVERSATION, "user-1", 0)
    ] == ["u1"]
