"""What a workflow run did, recorded once and replayed into the next run.

A workflow reuses one conversation forever, so its LangGraph checkpoints used to
be what carried "what happened last time" — at the cost of re-sending every
previous run as a full transcript. The threads are reset before each run
(:mod:`app.services.workflow.thread_reset`); these helpers are what replaces
them: the run's own tool events become a compact :class:`RecordedCall` list, and
the previous run's list is rendered into the next run's executor brief.

Pure by design — no I/O, so the mapping and the rendering stay unit-testable
against plain dicts. The reads live in ``execution_service``.
"""

import json

from app.constants.agents import AgentTag, wrap_agent_payload
from app.models.chat_models import ToolDataEntry
from app.models.workflow_execution_models import (
    RESULT_DIGEST_MAX_CHARS,
    RecordedCall,
    WorkflowExecution,
)

#: The two ``tool_data`` kinds that carry tool calls. Everything else in the list
#: (per-tool card payloads like ``email_fetch_data``) is render material, not a call.
TOOL_CALLS_ENTRY = "tool_calls_data"
SUBAGENT_GROUP_ENTRY = "subagent_group"

#: Bounds on the rendered block. The trace itself is stored whole — this caps only
#: what a single run pays to read the previous one, so a 300-call run can't
#: reintroduce the context bloat the reset exists to remove.
LAST_RUN_MAX_CALLS = 40
LAST_RUN_MAX_ARGS_CHARS = 300
LAST_RUN_MAX_SUMMARY_CHARS = 800


def build_trace(tool_data: list[ToolDataEntry]) -> list[RecordedCall]:
    """The run's tool calls, in the order they were emitted.

    Descends into ``subagent_group`` entries because
    ``reconstruct_subagent_groups`` folds a delegated subagent's calls out of the
    flat list and into its group — a trace read only at the top level would be
    one ``handoff`` call and nothing else.
    """
    trace: list[RecordedCall] = []
    for entry in tool_data:
        name = entry.get("tool_name")
        if name == TOOL_CALLS_ENTRY:
            call = _recorded_call(entry.get("data"), entry.get("subagent_id"))
            if call is not None:
                trace.append(call)
        elif name == SUBAGENT_GROUP_ENTRY:
            trace.extend(_group_calls(entry.get("data")))
    return trace


def render_last_run(execution: WorkflowExecution) -> str:
    """The previous run as the ``<last_run>`` block folded into the next run's brief."""
    when = (execution.completed_at or execution.started_at).isoformat()
    lines = [f"at: {when}", f"status: {execution.status}"]
    for call in execution.trace[:LAST_RUN_MAX_CALLS]:
        args = json.dumps(call.args, default=str)[:LAST_RUN_MAX_ARGS_CHARS]
        lines.append(f"{call.tool_name}({args})")
        if call.result_digest:
            lines.append(f"  -> {call.result_digest}")
    omitted = len(execution.trace) - LAST_RUN_MAX_CALLS
    if omitted > 0:
        lines.append(f"... and {omitted} more calls")
    if execution.summary:
        lines.append(f"summary: {execution.summary[:LAST_RUN_MAX_SUMMARY_CHARS]}")
    return wrap_agent_payload(AgentTag.LAST_RUN, "\n".join(lines))


def _group_calls(group: object) -> list[RecordedCall]:
    """One subagent group's calls, then its nested subagents', depth-first."""
    if not isinstance(group, dict):
        return []
    subagent_id = group.get("subagent_id")
    calls: list[RecordedCall] = []
    tool_calls = group.get("tool_calls")
    if isinstance(tool_calls, list):
        for data in tool_calls:
            call = _recorded_call(data, subagent_id)
            if call is not None:
                calls.append(call)
    nested = group.get("nested_subagents")
    if isinstance(nested, list):
        for child in nested:
            calls.extend(_group_calls(child))
    return calls


def _recorded_call(data: object, subagent_id: object) -> RecordedCall | None:
    """One ``tool_calls_data`` payload as a recorded call, or ``None`` if it isn't one.

    ``data`` is deliberately open on ``ToolDataEntry`` (each tool owns its shape),
    so this is the boundary that validates it into a real model.
    """
    if not isinstance(data, dict):
        return None
    tool_name = data.get("tool_name")
    if not tool_name:
        return None
    inputs = data.get("inputs")
    output = data.get("output")
    return RecordedCall(
        tool_name=str(tool_name),
        tool_category=str(data.get("tool_category") or ""),
        subagent_id=str(subagent_id) if subagent_id else None,
        args=dict(inputs) if isinstance(inputs, dict) else {},
        result_digest="" if output is None else str(output)[:RESULT_DIGEST_MAX_CHARS],
    )
