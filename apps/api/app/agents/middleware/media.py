"""Describes tool-result media for lanes that cannot see it.

A thin wrapper around ``describe_tool_media``; the spawned-subagent loop calls
that helper directly, because it runs outside the middleware stack. Same split as
``compact_tool_output``, and for the same reason.
"""

from collections.abc import Awaitable, Callable
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.agents.llm.vision import describe_tool_media


class MediaDescriptionMiddleware(AgentMiddleware):
    """Attaches a text description to any tool result whose images the model can't see."""

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        result = await handler(request)
        if not isinstance(result, ToolMessage):
            return result
        config = cast(RunnableConfig, getattr(request.runtime, "config", {}) or {})
        described = await describe_tool_media(result, config)
        return described if described is not None else result
