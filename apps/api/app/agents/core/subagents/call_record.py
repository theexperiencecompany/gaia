"""Compact record of the tool calls a subagent actually ran.

A workflow run's executor writes playbooks from what it can see, but a handoff
only ever shows it the subagent's final text — so it guessed tool names and
argument shapes and burned write_playbook attempts on inventions. Workflow
handoffs append this record to the result so the executor transcribes the
subagent's real calls instead.
"""

from collections.abc import Sequence
import json

from langchain_core.messages import AnyMessage, ToolMessage

from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.general import FINISH_TASK_NAME

#: Longest serialized form a single recorded arg value may take; anything past
#: it is cut with the marker so the record's token cost stays bounded.
MAX_RECORDED_ARG_CHARS = 200
ARG_TRUNCATION_MARKER = "…[truncated]"

CALL_RECORD_LEAD_IN = (
    "Calls this subagent ran (successful only, in order). When writing a "
    "playbook, copy these exact tool names and args as this handoff step's "
    "nested steps."
)


def _compact_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def _truncated_arg(value: object) -> object:
    """The value itself when small, else its serialized form cut to the cap."""
    rendered = value if isinstance(value, str) else _compact_json(value)
    if len(rendered) <= MAX_RECORDED_ARG_CHARS:
        return value
    return rendered[:MAX_RECORDED_ARG_CHARS] + ARG_TRUNCATION_MARKER


def successful_call_lines(messages: Sequence[AnyMessage]) -> list[str]:
    """One ``TOOL_NAME({"arg":value})`` line per successful call, in call order.

    A call counts as successful only when a non-error ``ToolMessage`` answers its
    id. ``finish_task`` is infrastructure, never a playbook step, so it is
    dropped even when it succeeded.
    """
    succeeded = {
        message.tool_call_id
        for message in messages
        if isinstance(message, ToolMessage) and message.status != "error" and message.tool_call_id
    }
    lines: list[str] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            name = str(call.get("name") or "")
            if not name or name == FINISH_TASK_NAME or call.get("id") not in succeeded:
                continue
            args = {key: _truncated_arg(value) for key, value in (call.get("args") or {}).items()}
            lines.append(f"{name}({_compact_json(args)})")
    return lines


def append_call_record(text: str, messages: Sequence[AnyMessage]) -> str:
    """``text`` with the run's call record appended, unchanged when there is
    nothing to record."""
    lines = successful_call_lines(messages)
    if not lines:
        return text
    record = wrap_agent_payload(
        AgentTag.SUBAGENT_CALL_RECORD, "\n".join([CALL_RECORD_LEAD_IN, *lines])
    )
    return f"{text}\n\n{record}"
