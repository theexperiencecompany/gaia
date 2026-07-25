"""HIL approval middleware: the middleware-chain adapter over ``gate_tool_call``.

DynamicToolNode has two execution paths; this covers the middleware chain
(regular tools). The parent ToolNode path is covered by ``hil_and_timeout_
guarded_tool_call`` in ``dynamic_tool_node.py``. Both delegate to the one
canonical gate in ``app/services/hil/gate.py``.
"""

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.services.hil.gate import Handler, gate_tool_call


class HILApprovalMiddleware(AgentMiddleware):
    """Middleware-chain adapter that routes regular tool calls through the HIL gate."""

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Handler
    ) -> ToolMessage | Command[Any]:
        return await gate_tool_call(request, handler)
