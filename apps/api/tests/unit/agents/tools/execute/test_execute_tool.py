"""The execute proxy tool — and the tool space it is confined to.

`execute` sits in EVERY subagent's tool set and resolves names globally, so it
is the one tool that can reach outside its agent's space. The factory is what
stops that: the unscoped instance is the executor's (its space IS the registry),
and a subagent builds one bound to its own dict.
"""

import json
from unittest.mock import AsyncMock, patch

from langchain_core.tools import StructuredTool
import pytest

from app.agents.tools.execute.dispatch import (
    DispatchError,
    DispatchErrorKind,
    ToolExecutionResult,
)
from app.agents.tools.execute.execute_tool import build_execute_tool, execute
from app.constants.execute import EXECUTE_TOOL_NAME

MODULE = "app.agents.tools.execute.execute_tool"
CONFIG = {"configurable": {"user_id": "u1"}}


def _ok() -> ToolExecutionResult:
    return ToolExecutionResult(ok=True, resolved_name="GMAIL_SEND_EMAIL", output={"status": "sent"})


async def _invoke(tool, tool_name: str = "GMAIL_SEND_EMAIL") -> str:
    return await tool.ainvoke(
        {"task_description": "d", "tool_name": tool_name, "data": {}}, config=CONFIG
    )


@pytest.mark.unit
class TestExecuteToolScope:
    async def test_the_registry_instance_is_unscoped(self) -> None:
        """The executor's space is the whole registry — scoping it would refuse
        every tool it is supposed to run."""
        with patch(f"{MODULE}.dispatch_tool", new=AsyncMock(return_value=_ok())) as dispatch:
            await _invoke(execute)
        assert dispatch.await_args.kwargs["scoped_tool_names"] is None

    async def test_a_scoped_instance_passes_its_live_tool_set(self) -> None:
        """Read at CALL time, not build time: a subagent keeps adding to its dict
        (todo tools, finish_task) after `execute` is put in it, and a snapshot
        taken then would refuse every tool added afterwards."""
        scoped_tools: dict[str, StructuredTool] = {}
        proxy = build_execute_tool(scoped_tools)
        scoped_tools["GMAIL_SEND_EMAIL"] = StructuredTool.from_function(
            func=lambda: None, name="GMAIL_SEND_EMAIL", description="Send."
        )
        with patch(f"{MODULE}.dispatch_tool", new=AsyncMock(return_value=_ok())) as dispatch:
            await _invoke(proxy)
        assert dispatch.await_args.kwargs["scoped_tool_names"] == {"GMAIL_SEND_EMAIL"}

    async def test_a_scoped_instance_keeps_the_proxy_name(self) -> None:
        """The name is a constant five other seams key on (HIL unwrap, the stream
        formatter, the analytics dedupe) — a per-agent instance must not rename it."""
        assert build_execute_tool({}).name == EXECUTE_TOOL_NAME == execute.name

    async def test_a_refusal_comes_back_as_a_structured_error(self) -> None:
        refusal = ToolExecutionResult(
            ok=False,
            resolved_name="SLACK_SEND_MESSAGE",
            error=DispatchError(
                kind=DispatchErrorKind.OUT_OF_SCOPE, detail="not here", hint="ask the executor"
            ),
        )
        with patch(f"{MODULE}.dispatch_tool", new=AsyncMock(return_value=refusal)):
            body = json.loads(await _invoke(build_execute_tool({}), "SLACK_SEND_MESSAGE"))
        assert body == {
            "ok": False,
            "error": "out_of_scope",
            "detail": "not here",
            "next": "ask the executor",
        }
