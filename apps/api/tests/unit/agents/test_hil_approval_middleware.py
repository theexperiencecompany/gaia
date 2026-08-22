"""Behavior tests for app.agents.middleware.hil_approval.

The middleware is the chain adapter over the HIL gate: a gate verdict
(ToolMessage) is returned without running the handler; a ``None`` verdict
(cleared to run) falls through to the handler. Locks both paths and that the
request is handed through unchanged.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage
import pytest

from app.agents.middleware.hil_approval import HILApprovalMiddleware

MODULE = "app.agents.middleware.hil_approval"

REQUEST: dict[str, Any] = {
    "tool_call": {"name": "send_email", "args": {"to": "bob@x.com"}, "id": "call_1"},
    "tool": None,
    "state": {},
    "runtime": None,
}


def _handler(return_value: object) -> AsyncMock:
    return AsyncMock(return_value=return_value)


class TestHILApprovalMiddleware:
    async def test_blocked_call_skips_the_handler(self) -> None:
        denied = ToolMessage(content="denied", tool_call_id="call_1")
        with patch(f"{MODULE}.decide_tool_call", AsyncMock(return_value=denied)) as decide:
            handler = _handler(ToolMessage(content="ran", tool_call_id="call_1"))
            result = await HILApprovalMiddleware().awrap_tool_call(REQUEST, handler)

        decide.assert_awaited_once_with(REQUEST)
        handler.assert_not_called()
        assert result is denied

    async def test_cleared_call_runs_the_handler(self) -> None:
        ran = ToolMessage(content="ran", tool_call_id="call_1")
        with patch(f"{MODULE}.decide_tool_call", AsyncMock(return_value=None)):
            handler = _handler(ran)
            result = await HILApprovalMiddleware().awrap_tool_call(REQUEST, handler)

        handler.assert_awaited_once_with(REQUEST)
        assert result is ran

    async def test_handler_exception_propagates(self) -> None:
        with patch(f"{MODULE}.decide_tool_call", AsyncMock(return_value=None)):
            handler = AsyncMock(side_effect=RuntimeError("tool crashed"))
            with pytest.raises(RuntimeError, match="tool crashed"):
                await HILApprovalMiddleware().awrap_tool_call(REQUEST, handler)
