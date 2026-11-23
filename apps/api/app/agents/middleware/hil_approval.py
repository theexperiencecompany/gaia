"""HIL approval middleware: the middleware-chain adapter over decide_tool_call.

Every tool call DynamicToolNode runs passes through the middleware chain, so this is
the gate's one adapter. The gate in app/services/hil/gate.py decides and never
executes, so a blocked call is one the handler is simply not asked to run.
"""

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.services.hil.gate import Handler, decide_tool_call


class HILApprovalMiddleware(AgentMiddleware):
    """Middleware-chain adapter that puts regular tool calls to the HIL gate first."""

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Handler
    ) -> ToolMessage | Command[str]:
        blocked = await decide_tool_call(request)
        return blocked if blocked is not None else await handler(request)
