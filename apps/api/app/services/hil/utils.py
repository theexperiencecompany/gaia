"""Pure readers and formatters the HIL services share. No I/O, no decisions.

Everything the gate and the judge need to *look at* — the tool call, the run's identity,
the graph state, the untrusted argument payload — is read through here, so the modules
that make decisions stay about decisions.

The graph-state readers deliberately expose tool *calls* and never message *content*: the
assistant's prose must never reach its own gate (see ``intent.py``).
"""

from dataclasses import dataclass
import json
import secrets
from typing import Any, cast

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.tools import BaseTool

from app.constants.execute import EXECUTE_TOOL_NAME
from app.constants.hil import (
    HIL_APPROVAL_TIMEOUT_SECONDS,
    HIL_JUDGE_MAX_ARGS_CHARS,
    HIL_JUDGE_MAX_PRIOR_ARGS_CHARS,
    HIL_JUDGE_MAX_PRIOR_CALLS,
    HIL_JUDGE_NONCE_BYTES,
)
from app.models.agent_models import AgentConfigurable, runtime_configurable
from app.utils.general_utils import clip_text


@dataclass(frozen=True)
class GatedCall:
    """The one tool call the gate is deciding about."""

    name: str
    id: str
    args: dict[str, Any]


@dataclass(frozen=True)
class PriorCall:
    """A tool call this run already made — an action, never a narration."""

    name: str
    args: dict[str, Any]


# --- reading the request ---------------------------------------------------------------


def unwrap_execute_call(name: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The REAL (name, args) of a call, seen through the execute proxy.

    An execute call carries its actual tool in ``args["tool_name"]``/``args["data"]``.
    Every gate decision keys off the name, so without this unwrap a destructive
    integration tool classifies as the (harmless) proxy and runs unapproved.
    """
    if name != EXECUTE_TOOL_NAME:
        return name, args
    real_name = args.get("tool_name")
    if not isinstance(real_name, str) or not real_name:
        # Malformed proxy call — gate it under its own name; dispatch will
        # reject it with a structured unknown_tool error anyway.
        return name, args
    data = args.get("data")
    return real_name, data if isinstance(data, dict) else {}


def unpack_tool_call(request: ToolCallRequest) -> GatedCall:
    """The pending call, whether the framework handed it over as a dict or an object.

    Execute-proxied calls are unwrapped to their real tool; ``id`` stays the
    proxy call's id, since that is the tool_call a refusal must answer.
    """
    # ToolCallRequest.tool_call is typed ToolCall (a dict), but dataclass fields
    # aren't runtime-validated — some framework versions/call paths have handed
    # this over as an object with .name/.id/.args instead. Widen to object so
    # that branch stays a real, reachable fallback rather than dead code.
    call = cast(object, request.tool_call)
    if isinstance(call, dict):
        name, args = unwrap_execute_call(call.get("name", ""), call.get("args", {}) or {})
        return GatedCall(name=name, id=call.get("id", ""), args=args)
    name, args = unwrap_execute_call(getattr(call, "name", ""), getattr(call, "args", None) or {})
    return GatedCall(name=name, id=getattr(call, "id", ""), args=args)


def tool_of(request: ToolCallRequest) -> BaseTool | None:
    return cast("BaseTool | None", getattr(request, "tool", None))


def tool_description(tool: BaseTool | None) -> str:
    return getattr(tool, "description", "") or ""


def configurable_of(request: ToolCallRequest) -> AgentConfigurable:
    """The run's ``configurable``, under this module's HIL-facing vocabulary."""
    return runtime_configurable(request)


# --- reading the graph state -----------------------------------------------------------


def current_tool_calls(state: object) -> list[dict[str, Any]]:
    """The tool calls of the AI message this node is executing (its last one).

    These are the pending call's *siblings* — what else the model asked for in the same
    turn. The gate needs them because a sibling that pauses re-runs this whole node.
    """
    for message in reversed(_messages_of(state)):
        calls = getattr(message, "tool_calls", None)
        if calls:
            return list(calls)
    return []


def prior_tool_calls(state: object, exclude_id: str) -> list[PriorCall]:
    """The tool calls this run already made, oldest first — names and args only.

    ``AIMessage.content`` (the assistant's prose) is deliberately never read: it is the
    one channel through which the agent could argue with its own gate. Tool calls carry
    the provenance the judge legitimately needs — "where did this recipient come from?" —
    without carrying an argument.

    ``exclude_id`` drops the pending call itself, which is already in state. Matched on
    tool_call id, not name: an earlier call of the *same* tool is real prior context.
    """
    calls = [
        PriorCall(name=call.get("name", ""), args=call.get("args", {}) or {})
        for message in _messages_of(state)
        for call in getattr(message, "tool_calls", None) or []
        if call.get("name") and call.get("id") != exclude_id
    ]
    return calls[-HIL_JUDGE_MAX_PRIOR_CALLS:]


def _messages_of(state: object) -> list[Any]:
    messages = _state_get(state, "messages")
    return messages if isinstance(messages, list) else []


def _state_get(state: object, key: str) -> object:
    """Read a key from graph state, which may be a dict or a State model."""
    if isinstance(state, dict):
        return state.get(key)
    getter = getattr(state, "get", None)
    return getter(key) if callable(getter) else getattr(state, key, None)


# --- rendering untrusted content for the judge -----------------------------------------


def args_preview(args: dict[str, Any]) -> str:
    """The pending call's arguments, JSON-encoded so a quote or newline inside a value
    cannot break out of the payload and read as prompt text."""
    return clip_text(json.dumps(args or {}, default=str), HIL_JUDGE_MAX_ARGS_CHARS)


def render_prior_calls(calls: list[PriorCall]) -> str:
    lines = [
        f"- {call.name}({clip_text(json.dumps(call.args, default=str), HIL_JUDGE_MAX_PRIOR_ARGS_CHARS)})"
        for call in calls
    ]
    return "\n".join(lines) or "(none)"


def approval_window_label() -> str:
    """How long the gate waited, in words, for the expiry message to the model.

    The configured window, not a measured elapsed time: the sweep resolves an
    approval within a tick of ``expires_at``, so the two agree to within a minute
    out of hours. Threading a real duration through the resume payload would buy
    nothing the user could notice.
    """
    hours, seconds = divmod(HIL_APPROVAL_TIMEOUT_SECONDS, 3600)
    if hours:
        return "1 hour" if hours == 1 else f"{hours} hours"
    minutes = max(1, seconds // 60)
    return "1 minute" if minutes == 1 else f"{minutes} minutes"


def untrusted_fence() -> str:
    """A per-call random marker around untrusted content in a judge prompt.

    Random rather than a fixed tag: an attacker who has seen the prompt can close a fixed
    tag and break out into instruction context, but cannot guess this.
    """
    return f"<<{secrets.token_hex(HIL_JUDGE_NONCE_BYTES)}>>"
