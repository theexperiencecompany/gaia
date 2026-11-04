"""invoke_tool: what a finished, failed or paused call leaves in the run record."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.errors import GraphInterrupt
from langgraph.types import Command
import pytest

from app.agents.tools import run_record
from app.agents.tools.invocation import ViaExecute, invoke_tool, invoke_tool_sync
from app.agents.tools.run_record import read_run_record
from app.constants.cache import RUN_RECORD_PREFIX, RUN_RECORD_TTL
from app.models.workflow_execution_models import RecordedCall

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


@tool
async def reports_failure(query: str) -> dict[str, Any]:
    """Answer normally with a body that says the call failed."""
    return {"success": False, "error": f"no {query}"}


async def test_a_tool_that_reports_its_own_failure_is_recorded_as_failed(fake_redis: Any) -> None:
    await invoke_tool(reports_failure, {"query": "q"}, CONFIG)
    await invoke_tool(answers, {"query": "q"}, CONFIG)

    failed, answered = await read_run_record(STREAM_ID)
    assert (failed.failed, answered.failed) == (True, False)


@pytest.mark.parametrize("tool_under_test", [answers, raises], ids=["returned", "raised"])
async def test_a_call_the_record_could_not_take_keeps_its_own_outcome(
    fake_redis: Any, tool_under_test: BaseTool
) -> None:
    """The tool already ran: a record that fails to write must not report it failed, or succeeded."""
    with (
        patch("app.agents.tools.invocation.append_call", AsyncMock(side_effect=OSError("down"))),
        patch("app.agents.tools.invocation.log") as log,
    ):
        if tool_under_test is raises:
            with pytest.raises(RuntimeError, match="no q"):
                await invoke_tool(tool_under_test, {"query": "q"}, CONFIG)
        else:
            assert await invoke_tool(tool_under_test, {"query": "q"}, CONFIG) == {"items": ["q"]}

    assert log.error.call_args.kwargs == {
        "tool_name": tool_under_test.name,
        "error_type": "OSError",
        "exc_info": True,
    }


@tool
async def answers_unencodable(query: str) -> dict[tuple[int, int], str]:
    """Answer with a result JSON cannot encode (a tuple key)."""
    return {(1, 2): query}


@tool
def answers_unencodable_sync(query: str) -> dict[tuple[int, int], str]:
    """Answer synchronously with a result JSON cannot encode."""
    return {(1, 2): query}


async def test_a_result_the_record_cannot_encode_still_returns(fake_redis: Any) -> None:
    """Review of #1618: building the record raised TypeError after the tool had already run."""
    with patch("app.agents.tools.invocation.log") as log:
        assert await invoke_tool(answers_unencodable, {"query": "q"}, CONFIG) == {(1, 2): "q"}

    assert await read_run_record(STREAM_ID) == []
    assert log.error.call_args.kwargs == {
        "tool_name": "answers_unencodable",
        "error_type": "TypeError",
        "exc_info": True,
    }


def test_a_sync_result_the_record_cannot_encode_still_returns() -> None:
    with patch("app.agents.tools.invocation.log") as log:
        assert invoke_tool_sync(answers_unencodable_sync, {"query": "q"}, CONFIG) == {(1, 2): "q"}

    assert log.error.call_args.kwargs["error_type"] == "TypeError"


def test_a_sync_call_the_record_could_not_take_still_returns() -> None:
    with (
        patch("app.agents.tools.invocation.append_call_sync", MagicMock(side_effect=OSError("x"))),
        patch("app.agents.tools.invocation.log") as log,
    ):
        assert invoke_tool_sync(answers_sync, {"query": "q"}, CONFIG) == "q"

    assert log.error.call_args.args == ("[TOOL] run record: a finished call was not recorded",)
    assert log.error.call_args.kwargs == {
        "tool_name": "answers_sync",
        "error_type": "OSError",
        "exc_info": True,
    }


@tool
def answers_sync(query: str) -> str:
    """Answer synchronously."""
    return query


@tool
def reads_config_sync(query: str, config: RunnableConfig) -> str:
    """Answer synchronously with the stream the call ran in."""
    return f"{query} in {config['configurable']['stream_id']}"


@tool
def raises_sync(query: str) -> str:
    """Fail synchronously."""
    raise RuntimeError(f"no {query}")


@pytest.fixture
def sync_redis(monkeypatch: pytest.MonkeyPatch) -> fakeredis.FakeRedis:
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(run_record, "_sync_client", lambda: client)
    return client


def _sync_record(client: fakeredis.FakeRedis) -> list[RecordedCall]:
    recorded = client.lrange(f"{RUN_RECORD_PREFIX}{STREAM_ID}", 0, -1)
    assert isinstance(recorded, list)
    return [RecordedCall.model_validate_json(raw) for raw in recorded]


def test_a_sync_call_is_recorded_with_the_models_args_and_kept_for_the_ttl(
    sync_redis: fakeredis.FakeRedis,
) -> None:
    output = invoke_tool_sync(
        reads_config_sync, {"query": "q"}, CONFIG, call_args={"query": "asked"}
    )

    assert output == f"q in {STREAM_ID}"
    (call,) = _sync_record(sync_redis)
    assert (call.tool_name, call.args, call.failed) == (
        "reads_config_sync",
        {"query": "asked"},
        False,
    )
    assert call.result_digest == f"q in {STREAM_ID}"
    assert sync_redis.ttl(f"{RUN_RECORD_PREFIX}{STREAM_ID}") == RUN_RECORD_TTL


def test_a_sync_call_that_raises_is_recorded_as_failed_and_still_raises(
    sync_redis: fakeredis.FakeRedis,
) -> None:
    with pytest.raises(RuntimeError, match="no q"):
        invoke_tool_sync(raises_sync, {"query": "q"}, CONFIG)

    (call,) = _sync_record(sync_redis)
    assert (call.tool_name, call.args, call.failed, call.result_digest) == (
        "raises_sync",
        {"query": "q"},
        True,
        "Error: RuntimeError: no q",
    )
