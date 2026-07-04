"""HIL approval gate: pause destructive tool calls until the user decides.

One canonical ``gate_tool_call`` wraps every tool execution. It is used by both
of DynamicToolNode's execution paths (the middleware chain and the parent
ToolNode) via thin adapters — the middleware class in
``app/agents/middleware/hil_approval.py`` and the composed ToolNode wrapper in
``dynamic_tool_node.py``. Living in the service layer keeps it importable from
the override package without a middleware↔override cycle.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.agents.tools.core.registry import get_tool_registry
from app.constants.hil import HIL_EXEMPT_TOOLS
from app.constants.log_tags import LogTag
from app.services.hil.bridge import build_summary, request_approval
from app.services.hil.classification import is_tool_destructive
from app.services.hil.preferences import add_always_allowed_tool, get_hil_preferences
from shared.py.wide_events import log

Handler = Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]

DENIED_TEMPLATE = (
    "The user declined to run `{tool}`. The action was NOT performed.{feedback} "
    "Adjust your approach based on this, or ask the user what they'd like "
    "instead. Do not retry the same call unchanged."
)
TIMEOUT_TEMPLATE = (
    "The approval request for `{tool}` expired without a response. The action "
    "was NOT performed. Tell the user you were waiting for their approval and "
    "that they can ask again when ready."
)


def _config_from(request: ToolCallRequest) -> dict[str, Any]:
    runtime = getattr(request, "runtime", None)
    config = getattr(runtime, "config", {}) or {}
    if not isinstance(config, dict):
        return {}
    configurable = config.get("configurable", {})
    return configurable if isinstance(configurable, dict) else {}


def _unpack_tool_call(request: ToolCallRequest) -> tuple[str, str, dict[str, Any]]:
    tool_call = request.tool_call
    if isinstance(tool_call, dict):
        return (
            tool_call.get("name", ""),
            tool_call.get("id", ""),
            tool_call.get("args", {}) or {},
        )
    return tool_call.name, tool_call.id, (tool_call.args or {})


async def _integration_name_for(tool_name: str) -> str | None:
    registry = await get_tool_registry()
    category = registry.get_category(registry.get_category_of_tool(tool_name))
    return category.integration_name if category else None


async def gate_tool_call(request: ToolCallRequest, handler: Handler) -> ToolMessage | Command[Any]:
    """Run ``handler`` unless HIL must first get the user's approval."""
    tool_name, tool_call_id, args = _unpack_tool_call(request)
    if tool_name in HIL_EXEMPT_TOOLS:
        return await handler(request)

    configurable = _config_from(request)
    stream_id = configurable.get("stream_id")
    user_id = configurable.get("user_id")
    conversation_id = configurable.get("thread_id")
    # Interactive runs only: no stream/user means nobody can answer, and a
    # background run (scheduled workflow, queued task) has no live client to
    # approve — gating it would just stall until timeout. Background approvals
    # are a later phase.
    if not stream_id or not user_id or not conversation_id:
        return await handler(request)
    if configurable.get("execution_mode") == "background":
        return await handler(request)

    prefs = await get_hil_preferences(user_id)
    if not prefs.enabled or tool_name in prefs.always_allowed_tools:
        return await handler(request)

    description = getattr(getattr(request, "tool", None), "description", "") or ""
    if not await is_tool_destructive(tool_name, description):
        return await handler(request)

    integration_name = await _integration_name_for(tool_name)
    outcome = await request_approval(
        stream_id=stream_id,
        user_id=user_id,
        conversation_id=conversation_id,
        tool_call={"id": tool_call_id, "name": tool_name, "args": args},
        summary=build_summary(tool_name, args, integration_name),
        integration_name=integration_name,
    )
    log.info(f"{LogTag.HIL} HIL decision for {tool_name}: {outcome.status}")

    if outcome.status == "approved":
        if outcome.scope == "always_tool":
            await add_always_allowed_tool(user_id, tool_name)
        return await handler(request)

    template = TIMEOUT_TEMPLATE if outcome.status == "timeout" else DENIED_TEMPLATE
    feedback = f" The user said: {outcome.feedback!r}." if outcome.feedback else ""
    return ToolMessage(
        content=template.format(tool=tool_name, feedback=feedback),
        tool_call_id=tool_call_id,
        name=tool_name,
        additional_kwargs={"hil_status": outcome.status},
    )
