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
from app.models.workflow_execution_models import largest_list_len

#: Longest serialized form a single recorded arg value may take; anything past
#: it is cut with the marker so the record's token cost stays bounded.
MAX_RECORDED_ARG_CHARS = 200
ARG_TRUNCATION_MARKER = "…[truncated]"
#: Appended to a recorded call whose result carried no items, so the executor
#: can see the empty step before it freezes the call.
EMPTY_RESULT_SUFFIX = " -> returned no items"

CALL_RECORD_LEAD_IN = (
    "Calls this subagent ran (successful only, in order). When writing a "
    "playbook, this handoff step's nested steps are the calls below that did "
    "the work, with these exact tool names and args. Leave out discovery "
    "(reading a skill file, a search that found nothing) the same way you "
    "leave out your own."
)


def _compact_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def _truncated_arg(value: object) -> object:
    """The value itself when small, else its serialized form cut to the cap."""
    rendered = value if isinstance(value, str) else _compact_json(value)
    if len(rendered) <= MAX_RECORDED_ARG_CHARS:
        return value
    return rendered[:MAX_RECORDED_ARG_CHARS] + ARG_TRUNCATION_MARKER


def parsed_result(message: ToolMessage) -> object | None:
    """The tool result as JSON when its content is a JSON document, else ``None``."""
    content = message.content
    if not isinstance(content, str):
        return None
    try:
        parsed: object = json.loads(content)
    except ValueError:
        return None
    return parsed


def is_error_envelope(result: object) -> bool:
    """A "successful" tool message whose body says the call failed.

    Many tools answer with ``{"success": false, ...}`` or ``{"error": "..."}``
    under a normal status, so status alone does not say the call worked.
    """
    if not isinstance(result, dict):
        return False
    if result.get("success") is False:
        return True
    error = result.get("error")
    return bool(error)


def successful_call_lines(messages: Sequence[AnyMessage]) -> list[str]:
    """One ``TOOL_NAME({"arg":value})`` line per successful call, in call order.

    A call counts as successful only when a non-error ``ToolMessage`` answers its
    id and its body is not an error envelope. ``finish_task`` is infrastructure,
    never a playbook step, so it is dropped even when it succeeded. A call whose
    result carried no items is kept but marked, so the executor sees an empty
    step before freezing it.
    """
    results: dict[str, object | None] = {}
    for message in messages:
        if isinstance(message, ToolMessage) and message.status != "error" and message.tool_call_id:
            result = parsed_result(message)
            if not is_error_envelope(result):
                results[message.tool_call_id] = result
    lines: list[str] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            name = str(call.get("name") or "")
            call_id = call.get("id")
            # Read once: past the guard, call_id is a key of results, and every
            # key there is a non-empty tool_call_id, so the second read never
            # needed a fallback for a missing id.
            if not name or name == FINISH_TASK_NAME or call_id not in results:
                continue
            args = {key: _truncated_arg(value) for key, value in (call.get("args") or {}).items()}
            line = f"{name}({_compact_json(args)})"
            if largest_list_len(results[call_id]) == 0:
                line += EMPTY_RESULT_SUFFIX
            lines.append(line)
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
