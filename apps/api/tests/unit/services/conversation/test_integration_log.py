"""The integration a step's work waits on, and the connect that wakes that work, as log entries."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
import time_machine

from app.constants.conversation import INTEGRATION_NEED_WINDOW
from app.models.agent_config import StepTurnRef
from app.models.conversation_log_models import IntegrationConnected, IntegrationNeeded
from app.services.conversation.integration_log import (
    continue_after_connect,
    record_integration_needed,
)
from app.services.conversation.runtime import install_runtime_ports
from tests.unit.services.conversation.log_helpers import T0, logged
from tests.unit.services.conversation.runtime_doubles import USER, Runtime

MODULE = "app.services.conversation.integration_log"

STEP: StepTurnRef = {
    "epoch": 3,
    "batch_start": 2,
    "cause_through": 7,
    "answers": ["u1"],
    "asked": True,
}


def _need(need_id: str, integration_id: str = "gmail") -> IntegrationNeeded:
    return IntegrationNeeded(id=need_id, integration_id=integration_id, integration_name="Gmail")


@pytest.fixture
def runtime() -> Runtime:
    runtime = Runtime()
    install_runtime_ports(runtime.ports)
    return runtime


@pytest.fixture
def found() -> Iterator[AsyncMock]:
    with patch(f"{MODULE}.integration_entry_repository") as repo:
        repo.list_integration_entries = AsyncMock(return_value=[])
        yield repo.list_integration_entries


async def _entries(runtime: Runtime, conversation_id: str) -> list[object]:
    return [item.entry for item in await runtime.log.read_after(conversation_id, USER, 0)]


async def test_a_need_is_logged_once_per_step_attempt(runtime: Runtime) -> None:
    await record_integration_needed(STEP, "c1", USER, "gmail", "Gmail")
    await record_integration_needed(STEP, "c1", USER, "gmail", "Gmail")

    assert await _entries(runtime, "c1") == [
        IntegrationNeeded(
            id="integration:gmail:3:7", integration_id="gmail", integration_name="Gmail"
        )
    ]


@time_machine.travel(T0, tick=False)
async def test_a_connect_answers_each_open_need_once(runtime: Runtime, found: AsyncMock) -> None:
    open_need = _need("integration:gmail:1:4")
    answered_need = _need("integration:gmail:1:2")
    found.return_value = [
        ("c1", logged(2, answered_need)),
        (
            "c1",
            logged(
                3,
                IntegrationConnected(
                    id="integration:gmail:1:2:connected",
                    integration_id="gmail",
                    integration_name="Gmail",
                    needed_id=answered_need.id,
                ),
            ),
        ),
        ("c2", logged(4, open_need)),
    ]

    woken = await continue_after_connect(USER, "gmail")

    assert woken == 1
    found.assert_awaited_once_with(
        user_id=USER, integration_id="gmail", since=T0 - INTEGRATION_NEED_WINDOW
    )
    assert await _entries(runtime, "c2") == [
        IntegrationConnected(
            id="integration:gmail:1:4:connected",
            integration_id="gmail",
            integration_name="Gmail",
            needed_id=open_need.id,
        )
    ]
    assert await _entries(runtime, "c1") == []


async def test_a_connect_with_nothing_waiting_wakes_nothing(
    runtime: Runtime, found: AsyncMock
) -> None:
    assert await continue_after_connect(USER, "gmail") == 0
    assert await _entries(runtime, "c1") == []
