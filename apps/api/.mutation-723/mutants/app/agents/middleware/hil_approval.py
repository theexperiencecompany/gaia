"""HIL approval middleware: the middleware-chain adapter over ``decide_tool_call``.

DynamicToolNode has two execution paths; this covers the middleware chain
(regular tools). The parent ToolNode path is covered by ``hil_and_timeout_
guarded_tool_call`` in ``dynamic_tool_node.py``. Both ask the one canonical gate in
``app/services/hil/gate.py``, and both run the tool themselves — the gate decides and
never executes, so a blocked call is one the handler is simply not asked to run.
"""

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.services.hil.gate import Handler, decide_tool_call


class HILApprovalMiddleware(AgentMiddleware):
    """Middleware-chain adapter that puts regular tool calls to the HIL gate first."""

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Handler
    ) -> ToolMessage | Command[Any]:
        blocked = await decide_tool_call(request)
        return blocked if blocked is not None else await handler(request)
