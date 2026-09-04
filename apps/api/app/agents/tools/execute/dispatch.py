"""The dispatch core: resolve → validate → invoke, for both execute surfaces.

The LLM-facing ``execute`` tool and the sandbox code-mode route both call
``dispatch_tool`` — there is exactly one place a proxied tool is resolved,
validated and run, so classification, analytics and error shapes cannot drift
between the two surfaces.

Predictable failures (unknown tool, out-of-scope tool, args that fail the
schema, a tool that outruns the execution bound) return a structured error the
model can act on. Other infrastructure failures propagate to the caller's error
handling (the ToolNode's error formatting, the route's 500) — they are not the
model's mistake to correct.
"""

import asyncio
from collections.abc import Container
from enum import StrEnum
import json
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from prometheus_client import Counter
from pydantic import BaseModel, ValidationError

from app.agents.tools.execute.resolver import resolve_tool
from app.constants.llm import TOOL_EXECUTION_TIMEOUT_SECONDS, TOOL_TIMEOUT_EXEMPT_TOOLS
from app.constants.log_tags import LogTag
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.storage.metrics import _register_once
from app.services.tool_shape_service import record_observed_shape
from shared.py.wide_events import log, spawn_logged_task

# THE health metric of the proxy migration: bind_tools gave provider-constrained
# args (a malformed call was structurally impossible); execute moves that check
# to runtime, so invalid_args/ok is the retries-per-successful-action ratio that
# says whether the trade is paying. Charted in Grafana; labels are the closed
# outcome set below, never tool names (unbounded cardinality).
_EXECUTE_DISPATCH_TOTAL = _register_once(
    "gaia_execute_dispatch_total",
    lambda: Counter(
        "gaia_execute_dispatch_total",
        "Proxied tool dispatches by outcome",
        ["outcome"],
    ),
)


class DispatchErrorKind(StrEnum):
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_ARGS = "invalid_args"
    # An internal tool reached a surface (the sandbox route) that only runs
    # integration tools — internal tools need graph runtime and stay in-graph.
    INTERNAL_TOOL = "internal_tool"
    # A registered tool outside the calling agent's tool space (a subagent
    # reaching for another integration's tools).
    OUT_OF_SCOPE = "out_of_scope"
    # The tool did not return within the host's bound. Its own outcome is
    # unknown, so this is the one failure a retry can duplicate.
    TIMEOUT = "timeout"


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
    integration_only: bool = False,
    scoped_tool_names: Container[str] | None = None,
) -> ToolExecutionResult:
    """Run one proxied tool.

    ``integration_only`` is the sandbox route's scope: internal tools need graph
    runtime the route doesn't have, and excluding them narrows what a leaked
    token can reach.

    ``scoped_tool_names`` is a subagent's own tool set. Without it the caller's
    space is the whole registry (the executor). With it, a REGISTERED tool
    outside the set is refused — exactly the boundary ``retrieve_tools`` applies
    to binding, and both of the proxy's surfaces enforce it (the sandbox route
    reads the space from the run's token).

    Registered is the whole claim: MCP tools and unmaterialized catalog slugs
    belong to no space (``ResolvedTool.in_registry``), so no space excludes them
    — the same hole ``retrieve_tools`` has, and closing it means defining a
    subagent's space by toolkit rather than by name.
    """
    resolved = await resolve_tool(user_id, tool_name)
    if resolved is None:
        log.warning(f"{LogTag.TOOL} execute: unknown tool", tool_name=tool_name)
        return _failure(
            user_id,
            tool_name,
            DispatchError(
                kind=DispatchErrorKind.UNKNOWN_TOOL,
                detail=f"Unknown tool '{tool_name}'.",
                hint=(
                    "The name must be an exact tool name. Discover tools with "
                    "retrieve_tools(query=...) and use the name it returns verbatim."
                ),
            ),
        )
    resolved_name, tool = resolved.name, resolved.tool

    if integration_only and not resolved.is_integration:
        log.warning(
            f"{LogTag.TOOL} execute: internal tool refused on integration-only surface",
            tool_name=resolved_name,
        )
        return _failure(
            user_id,
            resolved_name,
            DispatchError(
                kind=DispatchErrorKind.INTERNAL_TOOL,
                detail=f"'{resolved_name}' is an internal tool, not an integration tool.",
                hint=(
                    "Sandbox scripts can only call integration tools (Gmail, GitHub, "
                    "Notion, MCP, ...). Use internal tools from the conversation instead."
                ),
            ),
        )

    if (
        scoped_tool_names is not None
        and resolved.in_registry
        and resolved_name not in scoped_tool_names
    ):
        log.warning(
            f"{LogTag.TOOL} execute: tool refused outside the calling agent's tool space",
            tool_name=resolved_name,
        )
        return _failure(
            user_id,
            resolved_name,
            DispatchError(
                kind=DispatchErrorKind.OUT_OF_SCOPE,
                detail=f"'{resolved_name}' is not available inside this subagent.",
                hint=(
                    "It belongs to the main executor, not this subagent. Do not retry it; "
                    "finish your task here and let the executor handle it."
                ),
            ),
        )

    validated = _validate_args(tool, data)
    if isinstance(validated, DispatchError):
        log.warning(
            f"{LogTag.TOOL} execute: args failed schema validation",
            tool_name=resolved_name,
        )
        return _failure(user_id, resolved_name, validated)

    # Named before the run so an infrastructure failure — which propagates from
    # here — still says WHICH tool it was. The outcome is stamped only once the
    # invoke has actually returned: stamping "ok" up front made this field, the
    # health metric of the migration, report success for every dispatch that
    # raised.
    log.set_ns("execute", tool=resolved_name)
    # Long-running orchestration tools manage their own lifecycles — the same
    # exemption the in-graph node applies, read from the same constant so a
    # proxied call is never bounded more tightly than a direct one.
    bound = None if resolved_name in TOOL_TIMEOUT_EXEMPT_TOOLS else TOOL_EXECUTION_TIMEOUT_SECONDS
    try:
        async with asyncio.timeout(bound):
            output = await tool.ainvoke(validated, config=config)
    except TimeoutError:
        # The only failure whose effect is unknown: the provider may have
        # applied it after we stopped waiting. Bounded HERE so both surfaces
        # inherit it and the model gets THIS structured error: the in-graph
        # node's own bound is a backstop set strictly above this one (see
        # TOOL_TIMEOUT_BACKSTOP_BUFFER_SECONDS), and the sandbox route has none
        # of its own — its client would otherwise give up first and retry a
        # mutation that was still in flight.
        return _failure(
            user_id,
            resolved_name,
            DispatchError(
                kind=DispatchErrorKind.TIMEOUT,
                detail=(
                    f"'{resolved_name}' did not return within {TOOL_EXECUTION_TIMEOUT_SECONDS}s."
                ),
                hint=(
                    "The operation may or may not have completed on the provider side. "
                    "Verify its effect before retrying — an identical retry can duplicate it."
                ),
            ),
        )
    log.set_ns("execute", outcome="ok")

    if resolved.is_integration:
        # Observed-shape learning rides every real response; fire-and-forget so
        # it can never slow or fail the dispatch it learns from.
        spawn_logged_task(
            "record_tool_output_shape",
            record_observed_shape(resolved_name, output, scope=resolved.shape_scope),
            tool_name=resolved_name,
        )

    _EXECUTE_DISPATCH_TOTAL.labels(outcome="ok").inc()
    if user_id:
        # The one TOOL_USED per proxied run, attributed to the REAL tool with
        # via="execute" so it can be ratioed against execute failures. The
        # middleware emitter skips calls named `execute` for exactly this reason
        # (root CLAUDE.md: one action, one event, one emitter).
        capture_event(
            user_id,
            AnalyticsEvents.TOOL_USED,
            {"tool_name": resolved_name, "via": "execute"},
        )

    return ToolExecutionResult(ok=True, resolved_name=resolved_name, output=output)


def _failure(user_id: str | None, tool_name: str, error: DispatchError) -> ToolExecutionResult:
    """A predictable dispatch failure — counted, captured, then returned.

    Failure is its own event, never a missing one: retries-per-success is only
    computable if the numerator is recorded as reliably as the denominator.
    """
    _EXECUTE_DISPATCH_TOTAL.labels(outcome=str(error.kind)).inc()
    log.set_ns("execute", tool=tool_name, outcome=str(error.kind))
    if user_id:
        capture_event(
            user_id,
            AnalyticsEvents.EXECUTE_TOOL_FAILED,
            {"tool_name": tool_name, "reason": str(error.kind)},
        )
    return ToolExecutionResult(ok=False, resolved_name=tool_name, error=error)


def _validate_args(tool: BaseTool, data: dict[str, Any]) -> dict[str, Any] | DispatchError:
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
