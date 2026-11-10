"""A background subagent run is traced on its own stream, for the todo its dispatcher serves."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.subagents import delegation as delegation_module
from app.agents.core.subagents.delegation import Delegation, _run_background
from app.agents.core.subagents.subagent_runner import SubagentOutcome
from app.models.agent_models import RunningSubagent
from app.models.run_trace_models import RunState

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
STREAM_ID = "subagent-stream-1"


def _delegation(parent: dict[str, str]) -> Delegation:
    return cast(
        Delegation,
        SimpleNamespace(
            ctx=SimpleNamespace(agent_name="spawned", user_id=USER_ID, integration_id="spawn"),
            conversation_id="conv-1",
            subagent_id="row-1",
            display=SimpleNamespace(name="summarise"),
            parent_configurable=parent,
        ),
    )


@pytest.fixture
def traced() -> Iterator[SimpleNamespace]:
    """Patch every edge of a background run but its trace, which is what these tests read."""
    module = delegation_module
    with (
        patch.object(module, "begin_run", new_callable=AsyncMock) as begin,
        patch.object(module, "end_run", new_callable=AsyncMock) as end,
        patch.object(module, "RunningSubagents", return_value=MagicMock(deregister=AsyncMock())),
        patch.object(module, "close_folded_stream", new_callable=AsyncMock),
        patch.object(module, "_land", new_callable=AsyncMock),
        patch.object(module, "_park", new_callable=AsyncMock),
        patch.object(module, "_result_text", return_value="done"),
    ):
        yield SimpleNamespace(begin=begin, end=end)


async def _drive(
    outcome: SubagentOutcome | Exception, parent: dict[str, str] | None = None
) -> None:
    execute = AsyncMock(
        side_effect=outcome if isinstance(outcome, Exception) else None,
        return_value=None if isinstance(outcome, Exception) else outcome,
    )
    record = cast(RunningSubagent, MagicMock(dispatched_by="parent-stream"))
    with patch.object(delegation_module, "_execute_on_own_stream", execute):
        await _run_background(_delegation(parent or {}), record, STREAM_ID, resume=None)


async def test_a_run_is_traced_on_its_own_stream_for_the_todo_its_dispatcher_serves(
    traced: SimpleNamespace,
) -> None:
    await _drive(SubagentOutcome(text="done"), {"active_todo_id": "todo-9"})

    (opened,) = traced.begin.await_args.args
    ended_owner, ended_state = traced.end.await_args.args
    assert opened == ended_owner
    assert (
        opened.user_id,
        opened.conversation_id,
        opened.run_id,
        opened.todo_id,
        opened.parent_run_id,
    ) == (USER_ID, "conv-1", STREAM_ID, "todo-9", "parent-stream")
    assert ended_state is RunState.FINISHED


async def test_a_run_with_no_todo_behind_it_is_a_hidden_record(traced: SimpleNamespace) -> None:
    await _drive(SubagentOutcome(text="done"))

    (opened,) = traced.begin.await_args.args
    assert opened.todo_id is None


@pytest.mark.parametrize(
    ("outcome", "state"),
    [
        (SubagentOutcome(text="", interrupt={"approval_id": "appr-1"}), RunState.PAUSED),
        (SubagentOutcome(text="", stopped=True), RunState.CANCELLED),
        (RuntimeError("boom"), RunState.FAILED),
    ],
    ids=["parked", "stopped", "raised"],
)
async def test_a_run_ends_its_trace_in_the_state_its_outcome_names(
    traced: SimpleNamespace, outcome: SubagentOutcome | Exception, state: RunState
) -> None:
    await _drive(outcome)

    assert traced.end.await_args.args[1] is state
