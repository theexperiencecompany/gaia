"""invoke_tool: every executor run's calls reach the run trace, whatever the run is for."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from prometheus_client import REGISTRY
from pymongo.errors import PyMongoError
import pytest

from app.agents.tools.invocation import invoke_tool
from app.agents.tools.run_record import read_run_record
from app.services.executor_trace.recorder import RunOwner, TracedCall


def _failures(write: str) -> float:
    return (
        REGISTRY.get_sample_value("gaia_executor_trace_write_failed_total", {"write": write}) or 0.0
    )


RUN_ID = "run-trace-1"


def _config(**overrides: object) -> RunnableConfig:
    configurable: dict[str, object] = {
        "stream_id": RUN_ID,
        "user_id": "user-1",
        "conversation_id": "conv-1",
        "agent_name": "executor_agent",
    }
    configurable.update(overrides)
    return {"configurable": configurable}


@tool
async def search(query: str) -> str:
    """Answer with a result."""
    return f"found {query}"


@tool
async def breaks(query: str) -> str:
    """Fail."""
    raise RuntimeError(f"no {query}")


@pytest.fixture
def traced() -> Iterator[AsyncMock]:
    with patch("app.agents.tools.invocation.record_call", new_callable=AsyncMock) as record:
        yield record


def _recorded(record: AsyncMock) -> tuple[RunOwner, TracedCall]:
    record.assert_awaited_once()
    owner, call = record.await_args.args
    return owner, call


async def test_an_executor_call_is_traced_under_its_run_with_what_it_was_given_and_returned(
    traced: AsyncMock,
) -> None:
    await invoke_tool(search, {"query": "lease"}, _config())

    owner, call = _recorded(traced)
    assert owner == RunOwner(user_id="user-1", conversation_id="conv-1", run_id=RUN_ID)
    assert (call.tool_name, call.args, call.output_text, call.failed) == (
        "search",
        {"query": "lease"},
        "found lease",
        False,
    )
    assert call.started_at <= call.finished_at


async def test_a_run_of_a_tracked_todo_is_traced_against_that_todo(traced: AsyncMock) -> None:
    await invoke_tool(search, {"query": "q"}, _config(active_todo_id="todo-1"))

    owner, _ = _recorded(traced)
    assert owner.todo_id == "todo-1"


async def test_a_graph_tool_call_carries_the_models_call_id_and_its_own_args(
    traced: AsyncMock,
) -> None:
    graph_call: dict[str, Any] = {
        "type": "tool_call",
        "id": "toolu_42",
        "name": "search",
        "args": {"query": "lease"},
    }

    await invoke_tool(search, graph_call, _config())

    _, call = _recorded(traced)
    assert (call.tool_call_id, call.args) == ("toolu_42", {"query": "lease"})


async def test_a_failed_call_is_traced_as_failed_with_its_error_and_still_raises(
    traced: AsyncMock,
) -> None:
    with pytest.raises(RuntimeError, match="no q"):
        await invoke_tool(breaks, {"query": "q"}, _config())

    _, call = _recorded(traced)
    assert (call.failed, call.output_text) == (True, "Error: RuntimeError: no q")


@pytest.mark.parametrize(
    "config",
    [
        _config(agent_name="comms_agent"),
        _config(stream_id=None),
        _config(user_id=None),
        _config(conversation_id=None),
        {"configurable": {}},
    ],
    ids=["comms-tier", "no-stream", "no-user", "no-conversation", "bare-config"],
)
async def test_a_call_that_belongs_to_no_executor_run_is_not_traced(
    traced: AsyncMock, config: RunnableConfig
) -> None:
    await invoke_tool(search, {"query": "q"}, config)

    traced.assert_not_awaited()


async def test_a_call_the_trace_could_not_take_keeps_its_own_outcome_and_is_logged(
    traced: AsyncMock,
) -> None:
    traced.side_effect = PyMongoError("down")
    before = _failures("call")

    with patch("app.agents.tools.invocation.log") as log:
        assert await invoke_tool(search, {"query": "q"}, _config()) == "found q"

    assert _failures("call") == before + 1
    assert log.error.call_args.args == ("[TOOL] run trace: a finished call was not recorded",)
    assert log.error.call_args.kwargs["error_type"] == "PyMongoError"


async def test_a_workflow_call_is_written_to_the_run_record_and_the_trace_both(
    traced: AsyncMock, fake_redis: Any
) -> None:
    config = _config(workflow_id="wf_1")

    await invoke_tool(search, {"query": "q"}, config)

    (replayable,) = await read_run_record(RUN_ID)
    assert replayable.tool_name == "search"
    _recorded(traced)


async def test_a_failing_trace_does_not_stop_the_workflow_run_record(
    traced: AsyncMock, fake_redis: Any
) -> None:
    traced.side_effect = PyMongoError("down")

    await invoke_tool(search, {"query": "q"}, _config(workflow_id="wf_1"))

    (replayable,) = await read_run_record(RUN_ID)
    assert replayable.tool_name == "search"
