"""invoke_tool: what a finished, failed or paused call leaves in the run record."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.errors import GraphInterrupt
import pytest

from app.agents.tools.invocation import invoke_tool
from app.agents.tools.run_record import read_run_record
from app.constants.cache import RUN_RECORD_PREFIX, RUN_RECORD_TTL

STREAM_ID = "stream-invocation"
CONFIG: RunnableConfig = {"configurable": {"stream_id": STREAM_ID, "subagent_id": "todos_agent"}}


@tool
async def answers(query: str) -> dict[str, Any]:
    """Answer with a structured result."""
    return {"items": [query]}


@tool
async def raises(query: str) -> str:
    """Fail."""
    raise RuntimeError(f"no {query}")


@tool
async def pauses(query: str) -> str:
    """Stop for an approval."""
    raise GraphInterrupt(())


@tool("execute")
async def execute_proxy(query: str) -> str:
    """Stand in for the execute proxy, whose dispatch records the real call."""
    return query


async def test_a_finished_call_is_recorded_with_its_args_and_result(fake_redis: Any) -> None:
    await invoke_tool(answers, {"query": "q"}, CONFIG)

    (call,) = await read_run_record(STREAM_ID)
    assert (call.tool_name, call.args, call.subagent_id, call.failed) == (
        "answers",
        {"query": "q"},
        "todos_agent",
        False,
    )
    assert json.loads(call.result_digest) == {"items": ["q"]}
    assert await fake_redis.ttl(f"{RUN_RECORD_PREFIX}{STREAM_ID}") == RUN_RECORD_TTL


async def test_a_failed_call_is_recorded_as_failed_and_still_raises(fake_redis: Any) -> None:
    with pytest.raises(RuntimeError, match="no q"):
        await invoke_tool(raises, {"query": "q"}, CONFIG)

    (call,) = await read_run_record(STREAM_ID)
    assert (call.tool_name, call.failed, call.result_digest) == (
        "raises",
        True,
        "Error: RuntimeError: no q",
    )


async def test_a_call_paused_for_approval_is_not_recorded_yet(fake_redis: Any) -> None:
    with pytest.raises(GraphInterrupt):
        await invoke_tool(pauses, {"query": "q"}, CONFIG)

    assert await read_run_record(STREAM_ID) == []


async def test_the_execute_proxy_itself_is_not_recorded(fake_redis: Any) -> None:
    await invoke_tool(execute_proxy, {"query": "q"}, CONFIG)

    assert await read_run_record(STREAM_ID) == []


async def test_a_call_outside_any_run_records_nothing(fake_redis: Any) -> None:
    await invoke_tool(answers, {"query": "q"}, {"configurable": {}})
    await invoke_tool(answers, {"query": "q"})

    assert await fake_redis.keys(f"{RUN_RECORD_PREFIX}*") == []


async def test_injected_values_are_not_recorded_when_the_model_args_are_given(
    fake_redis: Any,
) -> None:
    await invoke_tool(answers, {"query": "q"}, CONFIG, call_args={"query": "model asked"})

    (call,) = await read_run_record(STREAM_ID)
    assert call.args == {"query": "model asked"}
