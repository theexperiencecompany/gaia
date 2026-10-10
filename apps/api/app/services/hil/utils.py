"""Pure readers and formatters the HIL services share. No I/O, no decisions.

Everything the gate and the judge need to *look at* — the tool call, the run's identity,
the graph state, the untrusted argument payload — is read through here, so the modules
that make decisions stay about decisions.

The graph-state readers expose tool *calls* (with their outputs, which carry
minted ids) and the assistant's recent *words* as labeled provenance — never as
authorization. The authority line stays where it was: only the user's turns
authorize (see intent.py).
"""

from dataclasses import dataclass
import json
import secrets
from typing import TypedDict, cast

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolCall
from langchain_core.tools import BaseTool

from app.agents.tools.execute.unwrap import unwrap_execute_call
from app.constants.hil import (
    HIL_APPROVAL_TIMEOUT_SECONDS,
    HIL_JUDGE_MAX_ARGS_CHARS,
    HIL_JUDGE_MAX_ASSISTANT_CHARS,
    HIL_JUDGE_MAX_ASSISTANT_TURNS,
    HIL_JUDGE_MAX_PRIOR_ARGS_CHARS,
    HIL_JUDGE_MAX_PRIOR_CALLS,
    HIL_JUDGE_MAX_PRIOR_OUTPUT_CHARS,
    HIL_JUDGE_MAX_SCHEMA_CHARS,
    HIL_JUDGE_NONCE_BYTES,
)
from app.models.agent_models import AgentConfigurable, runtime_configurable
from app.utils.general_utils import clip_text


@dataclass(frozen=True)
class GatedCall:
    """The one tool call the gate is deciding about."""

    name: str
    id: str
    args: dict[str, object]


@dataclass(frozen=True)
class PriorCall:
    """A tool call this run already made — an action, never a narration.

    output is the call's truncated result: ids minted mid-run (a draft id, a
    created event id) live in outputs, never in args, so without it an id the run
    itself created reads as "from nowhere".
    """

    name: str
    args: dict[str, object]
    output: str = ""


class _DictMessage(TypedDict, total=False):
    """A graph-state message given as a plain dict; values are unchecked, so read as object."""

    type: object
    role: object
    content: object
    tool_call_id: object


class _TextBlock(TypedDict, total=False):
    """One dict block of a list-shaped message content."""

    text: str


# --- reading the request ---------------------------------------------------------------


def raw_tool_call(request: ToolCallRequest) -> GatedCall:
    """Read the pending call as handed over, dict- or object-shaped, before any unwrapping."""
    tool_call: ToolCall = request.tool_call
    # tool_call is typed ToolCall (a dict), but dataclass fields aren't runtime-
    # validated and some call paths hand over an object with .name/.id/.args.
    # Widen to object so that branch stays a reachable fallback, not dead code.
    if isinstance(cast(object, tool_call), dict):
        return GatedCall(
            name=tool_call.get("name", ""),
            id=tool_call.get("id", ""),
            args=tool_call.get("args", {}) or {},
        )
    return GatedCall(
        name=getattr(tool_call, "name", ""),
        id=getattr(tool_call, "id", ""),
        args=getattr(tool_call, "args", None) or {},
    )


def unpack_tool_call(request: ToolCallRequest) -> GatedCall:
    """Read the pending call, with an execute-proxied call unwrapped to its real tool.

    The id stays the proxy call's id, since that is the tool_call a refusal must answer.
    """
    raw = raw_tool_call(request)
    name, args = unwrap_execute_call(raw.name, raw.args)
    return GatedCall(name=name, id=raw.id, args=args)


def tool_of(request: ToolCallRequest) -> BaseTool | None:
    return cast("BaseTool | None", getattr(request, "tool", None))


def tool_description(tool: BaseTool | None) -> str:
    return getattr(tool, "description", "") or ""


def configurable_of(request: ToolCallRequest) -> AgentConfigurable:
    """Return the run's configurable, under this module's HIL-facing vocabulary."""
    return runtime_configurable(request)


# --- reading the graph state -----------------------------------------------------------


def current_tool_calls(state: object) -> list[ToolCall]:
    """Return the tool calls of the AI message this node is executing (its last one).

    These are the pending call's *siblings* — what else the model asked for in the same
    turn. The gate needs them because a sibling that pauses re-runs this whole node.
    """
    for message in reversed(_messages_of(state)):
        calls = getattr(message, "tool_calls", None)
        if calls:
            return list(calls)
    return []


def prior_tool_calls(state: object, exclude_id: str) -> list[PriorCall]:
    """Return the tool calls this run already made, oldest first — names, args, outputs.

    AIMessage.content (assistant prose) is never read: it is the one channel the
    agent could use to argue with its own gate. exclude_id drops the pending call,
    matched on id not name since an earlier call of the same tool is real context.
    Outputs are matched by tool_call_id and clipped: minted ids, not authority.
    """
    outputs = _tool_outputs_by_call_id(state)
    made: list[ToolCall] = [
        call
        for message in _messages_of(state)
        for call in getattr(message, "tool_calls", None) or []
    ]
    calls = [
        PriorCall(
            name=call["name"],
            args=call.get("args", {}) or {},
            output=outputs.get(call_id, "") if (call_id := call.get("id")) else "",
        )
        for call in made
        if call.get("name") and call.get("id") != exclude_id
    ]
    return calls[-HIL_JUDGE_MAX_PRIOR_CALLS:]


def _tool_outputs_by_call_id(state: object) -> dict[str, str]:
    """Map tool_call_id to its truncated result, for calls already answered.

    Reads ToolMessages (dict or object shaped); anything without an id match is
    ignored by the caller. Untrusted tool-result text, so clipped like args.
    """
    outputs: dict[str, str] = {}
    for message in _messages_of(state):
        if isinstance(message, dict):
            as_dict: _DictMessage = cast(_DictMessage, message)
            call_id = as_dict.get("tool_call_id")
            content = as_dict.get("content")
        else:
            call_id = getattr(message, "tool_call_id", None)
            content = getattr(message, "content", None)
        if not call_id or not isinstance(content, str) or not content.strip():
            continue
        outputs[str(call_id)] = clip_text(content, HIL_JUDGE_MAX_PRIOR_OUTPUT_CHARS)
    return outputs


def recent_assistant_turns(state: object) -> list[str]:
    """Return the run's latest assistant messages, oldest first; provenance, not authority.

    What the agent already told the user ("your draft to X is ready") is the
    context a bare user shorthand ("send it") refers to. Bounded and clipped;
    callers must label it as the assistant's words, never as authorization.
    """
    turns = [
        clip_text(content, HIL_JUDGE_MAX_ASSISTANT_CHARS)
        for message in _messages_of(state)
        if _is_ai_message(message)
        for content in [_message_text(message)]
        if content.strip()
    ]
    return turns[-HIL_JUDGE_MAX_ASSISTANT_TURNS:]


def _is_ai_message(message: object) -> bool:
    """Whether a state message is the assistant's own (not human, tool, or system).

    LangChain shapes vary (objects with type, dicts with type/role), so accept the
    assistant spellings and reject everything else — a human turn duplicating
    user_messages is waste, a tool result at this budget is laundering.
    """
    if isinstance(message, dict):
        as_dict: _DictMessage = cast(_DictMessage, message)
        role = as_dict.get("type") or as_dict.get("role")
        return isinstance(role, str) and role.lower() in ("ai", "assistant")
    kind = getattr(message, "type", None)
    if kind:
        return str(kind).lower() == "ai"
    return type(message).__name__ == "AIMessage"


def _message_text(message: object) -> str:
    """Best-effort text of one state message (AI messages only carry content here)."""
    if isinstance(message, dict):
        as_dict: _DictMessage = cast(_DictMessage, message)
        if as_dict.get("tool_call_id"):
            return ""
        content = as_dict.get("content")
        return content if isinstance(content, str) else ""
    if getattr(message, "tool_call_id", None):
        return ""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        blocks: list[_TextBlock] = [
            cast(_TextBlock, part) for part in content if isinstance(part, dict)
        ]
        return " ".join(block.get("text", "") for block in blocks)
    return ""


def _messages_of(state: object) -> list[object]:
    messages = _state_get(state, "messages")
    return messages if isinstance(messages, list) else []


def _state_get(state: object, key: str) -> object:
    """Read a key from graph state, which may be a dict or a State model."""
    if isinstance(state, dict):
        return state.get(key)
    getter = getattr(state, "get", None)
    return getter(key) if callable(getter) else getattr(state, key, None)


# --- rendering untrusted content for the judge -----------------------------------------


def args_preview(args: dict[str, object]) -> str:
    """JSON-encode the pending call's arguments.

    JSON-encoding means a quote or newline inside a value cannot break out of the
    payload and read as prompt text.
    """
    return clip_text(json.dumps(args or {}, default=str), HIL_JUDGE_MAX_ARGS_CHARS)


def render_prior_calls(calls: list[PriorCall]) -> str:
    lines = []
    for call in calls:
        line = f"- {call.name}({clip_text(json.dumps(call.args, default=str), HIL_JUDGE_MAX_PRIOR_ARGS_CHARS)})"
        if call.output.strip():
            # JSON-encoded like args: a result containing a quote or newline
            # must not break out of its line and read as prompt structure.
            line += (
                f" => {clip_text(json.dumps(call.output), HIL_JUDGE_MAX_PRIOR_OUTPUT_CHARS + 2)}"
            )
        lines.append(line)
    return "\n".join(lines) or "(none)"


def render_assistant_turns(turns: list[str]) -> str:
    """Numbered recent assistant messages for a prompt — labeled, never quoted as authority."""
    lines = [f"{index + 1}. {turn}" for index, turn in enumerate(turns) if turn.strip()]
    return "\n".join(lines) or "(none)"


def tool_schema(tool: BaseTool | None) -> dict[str, object] | None:
    """Read the pending tool's argument contract, or None when it cannot be read.

    An opaque id stops being opaque once the judge sees what it is for (draft_id:
    "ID of a previously created draft"). Best-effort: a missing schema degrades to
    today's description-only view.
    """
    if tool is None:
        return None
    schema = getattr(tool, "args", None)
    if not isinstance(schema, dict) or not schema:
        return None
    return cast(dict[str, object], schema)


def render_tool_schema(schema: dict[str, object] | None) -> str:
    """Clip the arg contract for a prompt — schemas bloat, and JEV is cheap but not free."""
    if not schema:
        return "(no schema)"
    return clip_text(json.dumps(schema, default=str), HIL_JUDGE_MAX_SCHEMA_CHARS)


def approval_window_label() -> str:
    """How long the gate waited, in words, for the expiry message to the model.

    The configured window, not a measured elapsed time: the sweep resolves an
    approval within a tick of expires_at, so the two agree to within a minute
    out of hours. Threading a real duration through the resume payload would buy
    nothing the user could notice.
    """
    hours, seconds = divmod(HIL_APPROVAL_TIMEOUT_SECONDS, 3600)
    if hours:
        return "1 hour" if hours == 1 else f"{hours} hours"
    minutes = max(1, seconds // 60)
    return "1 minute" if minutes == 1 else f"{minutes} minutes"


def untrusted_fence() -> str:
    """Build a per-call random marker around untrusted content in a judge prompt.

    Random rather than a fixed tag: an attacker who has seen the prompt can close a fixed
    tag and break out into instruction context, but cannot guess this.
    """
    return f"<<{secrets.token_hex(HIL_JUDGE_NONCE_BYTES)}>>"
