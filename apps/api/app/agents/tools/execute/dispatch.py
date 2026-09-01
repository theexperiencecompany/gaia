"""The dispatch core: resolve → validate → invoke, for both execute surfaces.

The LLM-facing ``execute`` tool and the sandbox code-mode route both call
``dispatch_tool`` — there is exactly one place a proxied tool is resolved,
validated and run, so classification, analytics and error shapes cannot drift
between the two surfaces.

Predictable failures (unknown tool, args that fail the schema) return a
structured error the model can act on. Infrastructure failures propagate to the
caller's error handling (the ToolNode's error formatting, the route's 500) —
they are not the model's mistake to correct.
"""

from enum import StrEnum
import json
from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ValidationError

from app.agents.tools.execute.resolver import resolve_tool
from app.constants.log_tags import LogTag
from app.services.analytics_service import AnalyticsEvents, capture_event
from shared.py.wide_events import log


class DispatchErrorKind(StrEnum):
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_ARGS = "invalid_args"


class DispatchError(BaseModel):
    kind: DispatchErrorKind
    detail: str
    hint: str


class ToolExecutionResult(BaseModel):
    """Outcome of one proxied tool run; ``output`` is the tool's own payload."""

    ok: bool
    resolved_name: str
    # Tool outputs are genuinely schemaless here — each integration returns its
    # own shape and the proxy must pass it through unaltered (boundary, item 8).
    output: Any = None
    error: DispatchError | None = None


async def dispatch_tool(
    *,
    user_id: str | None,
    tool_name: str,
    data: dict[str, Any],
    config: RunnableConfig,
) -> ToolExecutionResult:
    resolved = await resolve_tool(user_id, tool_name)
    if resolved is None:
        log.warning(f"{LogTag.TOOL} execute: unknown tool", tool_name=tool_name)
        return ToolExecutionResult(
            ok=False,
            resolved_name=tool_name,
            error=DispatchError(
                kind=DispatchErrorKind.UNKNOWN_TOOL,
                detail=f"Unknown tool '{tool_name}'.",
                hint=(
                    "The name must be an exact tool name. Discover tools with "
                    "retrieve_tools(query=...) and use the name it returns verbatim."
                ),
            ),
        )
    resolved_name, tool = resolved

    validated = _validate_args(tool, data)
    if isinstance(validated, DispatchError):
        log.warning(
            f"{LogTag.TOOL} execute: args failed schema validation",
            tool_name=resolved_name,
        )
        return ToolExecutionResult(ok=False, resolved_name=resolved_name, error=validated)

    log.set_ns("execute", tool=resolved_name)
    output = await tool.ainvoke(validated, config=config)

    if user_id:
        # The one TOOL_USED per proxied run, attributed to the REAL tool. The
        # middleware emitter skips calls named `execute` for exactly this reason
        # (root CLAUDE.md: one action, one event, one emitter).
        capture_event(user_id, AnalyticsEvents.TOOL_USED, {"tool_name": resolved_name})

    return ToolExecutionResult(ok=True, resolved_name=resolved_name, output=output)


def _validate_args(tool: Any, data: dict[str, Any]) -> dict[str, Any] | DispatchError:
    """``data`` coerced through the tool's schema, or the correction to return.

    Provider-side constrained decoding is gone under the proxy — this check is
    what stands in for it, so it fails loud with the exact Pydantic errors.
    """
    schema = getattr(tool, "args_schema", None)
    if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
        # Dict-style JSON schemas (some MCP adapters) have no Pydantic model to
        # coerce through; the tool's own run performs its validation.
        return data
    try:
        model = schema.model_validate(data)
    except ValidationError as e:
        return DispatchError(
            kind=DispatchErrorKind.INVALID_ARGS,
            detail=json.dumps(e.errors(include_url=False), default=str),
            hint=f"Fix `data` to match the {tool.name} schema shown by retrieve_tools, then retry.",
        )
    # exclude_unset so tool-side defaults stay the tool's own — mirrors the
    # bind path, which forwards only the args the model actually supplied.
    return model.model_dump(exclude_unset=True)
