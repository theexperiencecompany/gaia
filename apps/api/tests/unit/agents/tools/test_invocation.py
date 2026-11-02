"""invoke_tool: what a finished, failed or paused call leaves in the run record."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.errors import GraphInterrupt
from langgraph.types import Command
import pytest

from app.agents.tools.invocation import ViaExecute, invoke_tool
from app.agents.tools.run_record import read_run_record
from app.constants.cache import RUN_RECORD_PREFIX, RUN_RECORD_TTL

STREAM_ID = "stream-invocation"
CONFIG: RunnableConfig = {
    "configurable": {"stream_id": STREAM_ID, "subagent_id": "todos_agent", "run_scope": "todos"}
}


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


@tool
async def reads_config(query: str, config: RunnableConfig) -> str:
    """Answer with the stream the call ran in."""
    return f"{query} in {config['configurable']['stream_id']}"


@tool
async def structured(query: str) -> dict[str, Any]:
    """Answer with text a JSON encoder would escape and a value it cannot encode."""
    return {"name": "Zoë", "at": datetime(2026, 11, 3, 9, 0, tzinfo=UTC), "query": query}


def _command_tool(update: object) -> BaseTool:
    @tool("updates_state")
    async def updates_state(query: str) -> Command:
        """Answer by updating graph state."""
        return Command(update=update)

    return updates_state


@tool("execute")
async def execute_proxy(query: str) -> str:
    """Stand in for the execute proxy, whose dispatch records the real call."""
    return query


async def test_a_finished_call_is_recorded_with_its_args_and_result(fake_redis: Any) -> None:
    await invoke_tool(answers, {"query": "q"}, CONFIG)

    (call,) = await read_run_record(STREAM_ID)
    assert (call.tool_name, call.args, call.subagent_id, call.subagent, call.failed) == (
        "answers",
        {"query": "q"},
        "todos_agent",
        "todos",
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


async def test_the_tool_runs_with_the_callers_config(fake_redis: Any) -> None:
    output = await invoke_tool(reads_config, {"query": "q"}, CONFIG)

    assert output == f"q in {STREAM_ID}"


async def test_a_structured_result_is_recorded_as_readable_json(fake_redis: Any) -> None:
    await invoke_tool(structured, {"query": "q"}, CONFIG)

    (call,) = await read_run_record(STREAM_ID)
    assert '"Zoë"' in call.result_digest
    assert json.loads(call.result_digest) == {
        "name": "Zoë",
        "at": "2026-11-03 09:00:00+00:00",
        "query": "q",
    }


@pytest.mark.parametrize(
    ("update", "digest"),
    [
        (
            {
                "messages": [
                    ToolMessage("first answer", tool_call_id="c1"),
                    ToolMessage("second answer", tool_call_id="c2"),
                ]
            },
            "first answer",
        ),
        ({"messages": [], "todos": ["x"]}, ""),
        ([("messages", [ToolMessage("as a list", tool_call_id="c1")])], ""),
    ],
    ids=["its-tool-message", "no-tool-message", "not-a-mapping"],
)
async def test_a_state_update_is_recorded_as_the_answer_it_carries(
    fake_redis: Any, update: object, digest: str
) -> None:
    await invoke_tool(_command_tool(update), {"query": "q"}, CONFIG)

    (call,) = await read_run_record(STREAM_ID)
    assert call.result_digest == digest


async def test_every_call_of_a_run_reads_back_in_order(fake_redis: Any) -> None:
    for query in ("one", "two", "three"):
        await invoke_tool(answers, {"query": query}, CONFIG)

    assert [call.args for call in await read_run_record(STREAM_ID)] == [
        {"query": "one"},
        {"query": "two"},
        {"query": "three"},
    ]


async def test_a_call_the_execute_proxy_made_is_recorded_as_proxied_with_its_account(
    fake_redis: Any,
) -> None:
    await invoke_tool(answers, {"query": "q"}, CONFIG, via=ViaExecute("work@acme.com"))
    await invoke_tool(answers, {"query": "direct"}, CONFIG)

    proxied, direct = await read_run_record(STREAM_ID)
    assert (proxied.proxied, proxied.account) == (True, "work@acme.com")
    assert (direct.proxied, direct.account) == (False, None)
