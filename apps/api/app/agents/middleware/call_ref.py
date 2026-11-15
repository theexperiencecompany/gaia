"""Shows the executor model the ref each of its tool results is cited by.

The ref is a view of the request: the thread keeps the tool results as the tools
returned them, and the review resolves citations through the same call_ref.
"""

from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse

from app.agents.core.call_ref import with_call_refs

ModelCallHandler = Callable[[ModelRequest], Awaitable[ModelResponse]]


class CallRefMiddleware(AgentMiddleware):
    """Prefixes every tool result in the model's request with its call ref."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: ModelCallHandler,
    ) -> ModelResponse:
        """Call the model with each tool result carrying its ref."""
        return await handler(request.override(messages=with_call_refs(list(request.messages))))
