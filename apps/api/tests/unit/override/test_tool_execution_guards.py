"""The guards wrapped around every tool call.

Three things sit between the agent deciding to call a tool and the result coming
back, and each one exists because of a specific way a turn used to break:

* a **timeout**, because a hung integration call hung the entire chat forever;
* a **``GraphBubbleUp`` re-raise**, because a HIL approval is raised as control
  flow through the same path an error takes — convert it and the approval card
  never reaches the user and the gated action is silently dropped;
* a **``Command`` passthrough**, because a state-mutating tool's whole effect is
  its graph update, and stringifying it loses the update while looking like
  success.

None of the three had a test. All three are user-visible the moment they break.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt
from langgraph.types import Command
import pytest

from app.agents.tools.execute.execute_tool import execute
from app.agents.tools.execute.resolver import ResolvedTool
from app.constants.llm import TOOL_EXECUTION_TIMEOUT_SECONDS, TOOL_TIMEOUT_EXEMPT_TOOLS
from app.override.langgraph_bigtool.dynamic_tool_node import (
    format_tool_error,
    timeout_guarded_tool_call,
)

NODE = "app.override.langgraph_bigtool.dynamic_tool_node"
DISPATCH = "app.agents.tools.execute.dispatch"


def _request(name: str = "GMAIL_FETCH_MESSAGES", call_id: str = "c1") -> MagicMock:
    request = MagicMock()
    request.tool_call = {"name": name, "id": call_id, "args": {}}
    return request


class TestTimeoutGuard:
    async def test_a_hung_tool_is_cut_short_with_an_actionable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Before this guard a hung provider call hung the whole chat: no reply,
        no error, the turn simply never ended."""
        monkeypatch.setattr(
            "app.override.langgraph_bigtool.dynamic_tool_node.TOOL_EXECUTION_TIMEOUT_SECONDS",
            0.01,
        )

        async def never_returns(_request: Any) -> ToolMessage:
            await asyncio.sleep(30)
            raise AssertionError("the guard let a hung call run to completion")

        result = await timeout_guarded_tool_call(_request(), never_returns)

        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert result.tool_call_id == "c1"
        assert "timed out" in result.content

    async def test_the_timeout_message_warns_the_side_effect_may_have_landed(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A timed-out send may still have sent. The model must be told to verify
        rather than blindly retry, or a timeout becomes a duplicate email."""
        monkeypatch.setattr(
            "app.override.langgraph_bigtool.dynamic_tool_node.TOOL_EXECUTION_TIMEOUT_SECONDS",
            0.01,
        )

        async def never_returns(_request: Any) -> ToolMessage:
            await asyncio.sleep(30)
            raise AssertionError("unreachable")

        result = await timeout_guarded_tool_call(_request("GMAIL_SEND_EMAIL"), never_returns)

        assert "may or may not have" in result.content
        assert "verify" in result.content

    async def test_a_tool_that_finishes_in_time_is_untouched(self):
        """Control: the guard must be invisible on the happy path."""
        expected = ToolMessage(content="3 unread", tool_call_id="c1")

        async def quick(_request: Any) -> ToolMessage:
            return expected

        assert await timeout_guarded_tool_call(_request(), quick) is expected

    async def test_an_exempt_tool_is_allowed_to_outlive_the_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Orchestration tools manage their own lifecycle — a handoff waits on a
        whole subagent run. Timing those out would kill work in progress."""
        monkeypatch.setattr(
            "app.override.langgraph_bigtool.dynamic_tool_node.TOOL_EXECUTION_TIMEOUT_SECONDS",
            0.01,
        )
        exempt = next(iter(TOOL_TIMEOUT_EXEMPT_TOOLS))
        expected = ToolMessage(content="subagent finished", tool_call_id="c1")

        async def slow(_request: Any) -> ToolMessage:
            await asyncio.sleep(0.05)
            return expected

        assert await timeout_guarded_tool_call(_request(exempt), slow) is expected

    async def test_bash_is_allowed_to_outlive_the_generic_bound(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """bash carries its own deadline all the way down to e2b's server-side
        command timeout, and advertises up to 300s to the model. Cutting it at the
        generic 120 killed long commands the tool said it would run — and in code
        mode it killed the bash call before the host could answer an in-flight
        execute() with its own structured error."""
        monkeypatch.setattr(
            "app.override.langgraph_bigtool.dynamic_tool_node.TOOL_EXECUTION_TIMEOUT_SECONDS",
            0.01,
        )
        expected = ToolMessage(content="exit_code: 0", tool_call_id="c1")

        async def slow(_request: Any) -> ToolMessage:
            await asyncio.sleep(0.05)
            return expected

        assert await timeout_guarded_tool_call(_request("bash"), slow) is expected

    async def test_a_proxied_call_comes_back_with_dispatchs_structured_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """dispatch_tool's timeout error names the REAL tool and tells the model a
        retry can duplicate the action; this node's text is generic. Both bounds
        were the same 120s and this one is armed first, so it always won the race:
        the structured error — and the analytics event and metric that ride with
        it — could not fire for any in-graph call."""
        monkeypatch.setattr(f"{DISPATCH}.TOOL_EXECUTION_TIMEOUT_SECONDS", 0.02)
        monkeypatch.setattr(f"{NODE}.TOOL_EXECUTION_TIMEOUT_SECONDS", 0.02)
        monkeypatch.setattr(f"{NODE}.TOOL_TIMEOUT_BACKSTOP_BUFFER_SECONDS", 0.3)

        hung = MagicMock()
        hung.name = "GMAIL_SEND_EMAIL"
        hung.args_schema = None

        async def never_returns(*_args: Any, **_kwargs: Any) -> None:
            await asyncio.sleep(5)

        hung.ainvoke = never_returns

        request = _request("execute")
        request.tool_call["args"] = {"tool_name": "GMAIL_SEND_EMAIL", "data": {}}

        async def run_the_proxy(_request: Any) -> ToolMessage:
            content = await execute.ainvoke(
                {
                    "task_description": "Sending the email",
                    "tool_name": "GMAIL_SEND_EMAIL",
                    "data": {},
                },
                config={"configurable": {"user_id": "u1"}},
            )
            return ToolMessage(content=content, tool_call_id="c1")

        resolved = ResolvedTool("GMAIL_SEND_EMAIL", hung, is_integration=True, in_registry=True)
        with (
            patch(f"{DISPATCH}.resolve_tool", new=AsyncMock(return_value=resolved)),
            patch(f"{DISPATCH}.capture_event"),
        ):
            result = await timeout_guarded_tool_call(request, run_the_proxy)

        body = json.loads(result.content)
        assert body["error"] == "timeout"
        assert "GMAIL_SEND_EMAIL" in body["detail"]
        assert "verify" in body["next"].lower()

    def test_the_configured_timeout_is_long_enough_for_a_real_call(self):
        """A guard set to a few seconds would abort legitimate provider calls;
        this pins the value as a deliberate choice rather than a default."""
        assert TOOL_EXECUTION_TIMEOUT_SECONDS >= 60


class TestControlFlowPassesThrough:
    async def test_an_approval_interrupt_is_not_converted_into_an_error(self):
        """A HIL approval is raised, not returned. If the guard caught it like a
        failure the run would never checkpoint, the approval card would never
        reach the user, and the gated action would be dropped while the model
        was told the tool errored."""

        async def gated(_request: Any) -> ToolMessage:
            raise GraphInterrupt(())

        with pytest.raises(GraphInterrupt):
            await timeout_guarded_tool_call(_request(), gated)

    async def test_a_state_mutating_tools_command_comes_back_intact(self):
        """The tool's entire effect is this object. Anything that turns it into
        a message loses the state change while still looking like a result."""
        command = Command(update={"todos": [{"id": "a", "content": "one"}]})

        async def mutating(_request: Any) -> Command:
            return command

        assert await timeout_guarded_tool_call(_request("plan_tasks"), mutating) is command


class TestErrorText:
    def test_the_error_names_the_exception_type(self):
        """The model uses the type to tell a transient network failure from a
        permanently invalid request — one is worth retrying, the other is not."""
        assert format_tool_error(TimeoutError("upstream slow")) == (
            "Error: TimeoutError: upstream slow"
        )

    def test_an_exception_with_no_message_still_reads_as_an_error(self):
        assert format_tool_error(ValueError()).startswith("Error: ValueError:")
