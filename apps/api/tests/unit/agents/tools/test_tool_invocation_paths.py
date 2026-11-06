"""Every way a tool can run lands the call in the run record.

The static half enumerates every invoking call (ainvoke, invoke, arun, abatch, batch)
in app/ and requires each to be classified: a tool invocation is allowed only in
app/agents/tools/invocation.py, and anything else is named below with why it is not
a tool. A new path that runs tools on its own (as #1252's in-context execute did)
fails here until it routes through invoke_tool.

The runtime half drives each real execution path with a probe tool and reads the
record back.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Annotated, Any
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.runtime import Runtime
from langgraph.types import Command
import pytest

from app.agents.middleware.executor import MiddlewareExecutor
from app.agents.tools import run_record
from app.agents.tools.execute.execute_tool import execute
from app.agents.tools.execute.resolver import ResolvedTool
from app.agents.tools.run_record import read_run_record
from app.api.v1.endpoints.sandbox_execute import SandboxExecuteRequest, sandbox_execute
from app.config.settings import settings
from app.override.langgraph_bigtool.dynamic_tool_node import DynamicToolNode
from app.services.sandbox.execute_client import mint_execute_env

APP = Path(__file__).resolve().parents[4] / "app"
INVOKING = frozenset({"ainvoke", "invoke", "arun", "_arun", "abatch", "batch"})
#: The one module allowed to invoke a tool.
INVOCATION_MODULE = "agents/tools/invocation.py"

#: Every invoking call in app/ that is not a tool, as (file, receiver source): why.
NOT_A_TOOL: dict[tuple[str, str], str] = {
    ("agents/middleware/compaction.py", "summary_llm"): "an LLM summarising history",
    ("agents/middleware/summarization.py", "self.model"): "an LLM summarising history",
    ("agents/tools/flowchart_tool.py", "FLOWCHART_PROMPT_TEMPLATE"): "a prompt template",
    (
        "agents/llm/client.py",
        "with_llm_retry(primary, max_attempts=opts.max_attempts)",
    ): "the LLM client with retries",
    ("agents/llm/client.py", "fallback_runnable"): "the LLM client's fallback model",
    ("agents/memory/profile_crawler.py", "crawler"): "a web crawler",
    ("utils/crawl4ai_utils.py", "crawler"): "a web crawler",
    ("services/browser/llm.py", "self._inner"): "the browser agent's LLM",
    ("services/browser/jev/loop.py", "self._text_model"): "the browser agent's LLM",
    ("db/chroma/chroma_store.py", "self"): "the Chroma store's own batch of store ops",
    ("services/mcp/custom_mcp_index.py", "store"): "a LangGraph store batch write",
    ("db/chroma/index_warmup.py", "store"): "a LangGraph store batch write",
    ("utils/file_utils.py", "with_llm_retry(self.llm)"): "an LLM summarising file chunks",
    ("services/workflow/playbook/runner.py", "builder.compile()"): (
        "a playbook replay graph; its tools run in its DynamicToolNode, which records them"
    ),
}

STREAM_ID = "stream-paths"
WORKFLOW_ID = "wf-paths"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"


def _invoking_sites() -> list[tuple[str, str]]:
    sites: list[tuple[str, str]] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in INVOKING
            ):
                sites.append((str(path.relative_to(APP)), ast.unparse(node.func.value)))
    return sites


def test_every_invoking_call_is_a_recorded_tool_call_or_named_as_not_a_tool() -> None:
    unclassified = [
        site
        for site in _invoking_sites()
        if site[0] != INVOCATION_MODULE and site not in NOT_A_TOOL
    ]
    assert unclassified == [], (
        "Run a tool through app.agents.tools.invocation.invoke_tool so its call is "
        "recorded, or add the site to NOT_A_TOOL with why it is not a tool: "
        f"{unclassified}"
    )


def test_the_not_a_tool_table_has_no_stale_entries() -> None:
    assert set(NOT_A_TOOL) <= set(_invoking_sites())


# --- runtime: each path lands the call in the record ------------------------


@tool
async def probe(query: str) -> str:
    """Answer with the query."""
    return f"answered {query}"


@tool
def probe_sync(query: str) -> str:
    """Answer with the query, synchronously."""
    return f"answered {query}"


@tool
async def probe_with_state(query: str, state: Annotated[dict[str, Any], InjectedState]) -> str:
    """Answer with the query, reading graph state the way the playbook tools do."""
    del state
    return f"answered {query}"


@tool
async def probe_command(
    query: str,
    state: Annotated[dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Answer by updating graph state, the way a state-writing tool does."""
    del state
    return Command(
        update={"messages": [ToolMessage(f"answered {query}", tool_call_id=tool_call_id)]}
    )


@tool
def probe_command_sync(
    query: str,
    state: Annotated[dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Answer by updating graph state, synchronously."""
    del state
    return Command(
        update={"messages": [ToolMessage(f"answered {query}", tool_call_id=tool_call_id)]}
    )


class _Passthrough(AgentMiddleware):
    async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        return await handler(request)


def _run_config() -> RunnableConfig:
    return {
        "configurable": {"stream_id": STREAM_ID, "workflow_id": WORKFLOW_ID, "user_id": USER_ID}
    }


def _one_call(name: str) -> dict[str, Any]:
    call = {"name": name, "args": {"query": "q"}, "id": "call_1", "type": "tool_call"}
    return {"messages": [AIMessage(content="", tool_calls=[call])]}


async def _recorded() -> list[tuple[str, dict[str, object], str]]:
    return [(c.tool_name, c.args, c.result_digest) for c in await read_run_record(STREAM_ID)]


@pytest.mark.parametrize(
    ("tool_name", "middleware"),
    [
        ("probe", MiddlewareExecutor([_Passthrough()])),
        ("probe", None),
        ("probe_with_state", MiddlewareExecutor([_Passthrough()])),
        ("probe_with_state", None),
    ],
    ids=["middleware", "parent", "injected-state-with-middleware", "injected-state"],
)
async def test_the_graph_tool_node_records_the_call(
    fake_redis: Any, tool_name: str, middleware: MiddlewareExecutor | None
) -> None:
    node = DynamicToolNode(
        {"probe": probe, "probe_with_state": probe_with_state}, middleware_executor=middleware
    )

    await node._afunc(_one_call(tool_name), _run_config(), Runtime())

    assert await _recorded() == [(tool_name, {"query": "q"}, "answered q")]


def test_the_sync_graph_tool_node_records_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(run_record, "_sync_client", lambda: client)
    node = DynamicToolNode({"probe_sync": probe_sync})

    node._func(_one_call("probe_sync"), _run_config(), Runtime())

    recorded = client.lrange(f"run_record:{STREAM_ID}", 0, -1)
    assert isinstance(recorded, list)
    (raw,) = recorded
    assert '"tool_name":"probe_sync"' in raw


async def test_the_execute_proxy_records_the_real_tool_and_not_itself(fake_redis: Any) -> None:
    resolved = ResolvedTool(name="probe", tool=probe, is_integration=False)
    with (
        patch("app.agents.tools.execute.dispatch.resolve_tool", AsyncMock(return_value=resolved)),
        patch("app.agents.tools.execute.dispatch.choose_account", AsyncMock(return_value=None)),
        patch("app.agents.tools.execute.dispatch.capture"),
    ):
        await execute.ainvoke(
            {"task_description": "probing", "tool_name": "probe", "data": {"query": "q"}},
            config=_run_config(),
        )

    assert await _recorded() == [("probe", {"query": "q"}, "answered q")]


async def test_a_sandbox_script_calling_back_records_into_its_run(
    fake_redis: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The token minted for the bash run carries the run its calls land in."""
    monkeypatch.setattr(settings, "SANDBOX_EXECUTE_TOKEN_SECRET", "s" * 32)
    monkeypatch.setattr(
        settings, "SANDBOX_EXECUTE_CALLBACK_URL", "https://api.test/sandbox/execute"
    )
    configurable = {"stream_id": STREAM_ID, "workflow_id": WORKFLOW_ID, "user_id": USER_ID}
    token = mint_execute_env(
        user_id=USER_ID,
        run_id="bash-run-1",
        config={"configurable": configurable},
        sandbox_id=None,
        command_timeout_seconds=60,
        scoped_tool_names=None,
    )["GAIA_EXECUTE_TOKEN"]
    resolved = ResolvedTool(name="probe", tool=probe, is_integration=True)
    with (
        patch("app.agents.tools.execute.dispatch.resolve_tool", AsyncMock(return_value=resolved)),
        patch("app.agents.tools.execute.dispatch.choose_account", AsyncMock(return_value=None)),
        patch("app.agents.tools.execute.dispatch.capture"),
        patch("app.agents.tools.execute.dispatch.spawn_logged_task", MagicMock()),
        patch("app.api.v1.endpoints.sandbox_execute.enforce_token_budget", AsyncMock()),
    ):
        response = await sandbox_execute(
            SandboxExecuteRequest(tool_name="probe", data={"query": "q"}),
            authorization=f"Bearer {token}",
        )

    assert response.ok
    assert await _recorded() == [("probe", {"query": "q"}, "answered q")]


async def test_a_state_updating_tool_still_updates_state_and_is_recorded(fake_redis: Any) -> None:
    """The node hands LangGraph its own input shape, which decides whether a Command's update is accepted."""
    node = DynamicToolNode({"probe_command": probe_command})

    output = await node._afunc(_one_call("probe_command"), _run_config(), Runtime())

    assert [type(item) for item in output] == [Command]
    assert await _recorded() == [("probe_command", {"query": "q"}, "answered q")]


def test_a_sync_state_updating_tool_still_updates_state(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(run_record, "_sync_client", lambda: client)
    node = DynamicToolNode({"probe_command_sync": probe_command_sync})

    output = node._func(_one_call("probe_command_sync"), _run_config(), Runtime())

    assert [type(item) for item in output] == [Command]
