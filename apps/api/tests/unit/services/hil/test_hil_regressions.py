"""Regressions for bugs found reviewing the HIL branch. Each test names the bug it pins.

An orchestration tool that fell through to the destructive classifier, which fails closed.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage
import pytest

from app.constants.comms import REACT_TOOL_NAME, STAY_SILENT_TOOL_NAME
from app.constants.hil import HIL_EXEMPT_TOOLS

from .conftest import make_request, run_through_gate

GATE = "app.services.hil.gate"


class TestExemptToolsAreNeverGated:
    """HIL_EXEMPT_TOOLS must keep covering every bound orchestration tool, or the gate sends one to the LLM destructive classifier, which fails CLOSED."""

    def test_the_spawn_tool_is_exempt(self) -> None:
        assert "spawn_subagent" in HIL_EXEMPT_TOOLS

    async def test_the_gate_runs_it_without_resolving_any_policy(self) -> None:
        ran = False

        async def handler(_request: Any) -> ToolMessage:
            nonlocal ran
            ran = True
            return ToolMessage(content="collected", tool_call_id="call-1")

        with patch(f"{GATE}.resolve_policy", new=AsyncMock()) as policy:
            result = await run_through_gate(make_request(name="spawn_subagent"), handler)

        assert ran is True
        assert result.content == "collected"
        policy.assert_not_awaited()


@pytest.mark.parametrize("name", [REACT_TOOL_NAME, STAY_SILENT_TOOL_NAME])
async def test_a_turn_ending_call_runs_without_resolving_any_policy(name: str) -> None:
    """Regression (live e2e): a failed classification gated stay_silent and left the chat waiting on an approval."""

    async def handler(_request: Any) -> ToolMessage:
        return ToolMessage(content="ended", tool_call_id="call-1")

    with patch(f"{GATE}.resolve_policy", new=AsyncMock()) as policy:
        result = await run_through_gate(make_request(name=name), handler)

    assert result.content == "ended"
    policy.assert_not_awaited()
