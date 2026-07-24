"""Directive protocol for the scripted LLM stub.

Pure stdlib — no third-party imports — so the parser and turn-counter can be
unit-tested without booting the HTTP server or resolving the stub's runtime deps.

A test authors its script inline, in the message it sends GAIA. The stub reads
the LATEST user message in each chat-completions request and parses ordered
directives out of it:

    [[tool:<name> <json-args>]]   one scripted tool call (repeatable, ordered)
    [[say:<text>]]                the final assistant reply (at most one, terminal)

The stub is stateless. On every invocation it re-derives where in the script it
is by counting the tool-call turns already present in the request's message list
after that user message, then emits the next pending tool call — or the say-text
once every tool directive has been consumed. A message with no directives yields
a fixed canned reply.

Two-agent awareness: GAIA's front-door ``comms_agent`` only has the
``call_executor`` hand-off tool; the real work runs in ``executor_agent`` with
the full tool registry. So a directive naming a tool that is NOT bound in the
current request, while ``call_executor`` IS bound, is a signal that this
invocation is the front door: the stub emits a single ``call_executor`` call
that forwards the whole script as the task. ``call_executor`` re-injects that
text as the executor's task message, where the same directives are parsed again
and executed directly. One ``call_executor`` turn therefore stands in for every
consecutive executor-tool directive.

Limitations (documented, not silently handled):
- Directive JSON args must not contain a literal ``]]`` sequence (e.g. nested
  ``[[...]]`` arrays); the closing delimiter would truncate the args and the
  resulting invalid JSON fails loud as a ``DirectiveError``.
- A single script should target one agent level. Mixing comms-only tools
  (``add_memory``/``search_memory``) with executor tools in one script is not
  supported, because forwarding replays the full script to the executor.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import json
import re
from typing import Any

DEFAULT_REPLY = "ok (llm-stub)"
CALL_EXECUTOR_TOOL = "call_executor"
# The bigtool executor binds tools at inference: when a scripted tool is not yet
# bound, the stub first emits retrieve_tools(exact_tool_names=[name]) so the
# graph binds it, then emits the tool itself on the next invocation.
RETRIEVE_TOOLS_TOOL = "retrieve_tools"

# Non-greedy body capture up to the closing ``]]``. See the module limitation
# note: a literal ``]]`` inside the body terminates the match early.
_DIRECTIVE_RE = re.compile(r"\[\[(tool|say):(.*?)\]\]", re.DOTALL)


class DirectiveError(ValueError):
    """A directive is present but malformed. Surfaced as HTTP 500 (fail loud)."""


@dataclass(frozen=True)
class ToolDirective:
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class SayDirective:
    text: str


Directive = ToolDirective | SayDirective


@dataclass(frozen=True)
class ToolCallResponse:
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class SayResponse:
    text: str


Response = ToolCallResponse | SayResponse


def parse_directives(text: str) -> list[Directive]:
    """Parse ordered directives out of a single message's text."""
    directives: list[Directive] = []
    for kind, raw_body in _DIRECTIVE_RE.findall(text):
        body = raw_body.strip()
        if kind == "say":
            directives.append(SayDirective(text=body))
            continue
        directives.append(_parse_tool_directive(body))
    return directives


def _parse_tool_directive(body: str) -> ToolDirective:
    name, _, raw_args = body.partition(" ")
    name = name.strip()
    if not name:
        raise DirectiveError(f"tool directive missing a name: [[tool:{body}]]")
    raw_args = raw_args.strip() or "{}"
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        raise DirectiveError(
            f"tool directive '{name}' has invalid JSON args: {raw_args!r} ({exc})"
        ) from exc
    if not isinstance(args, dict):
        raise DirectiveError(
            f"tool directive '{name}' args must be a JSON object, got {raw_args!r}"
        )
    return ToolDirective(name=name, args=args)


def message_text(message: dict[str, Any]) -> str:
    """Flatten a chat message's content to text.

    Content is usually a plain string but the OpenAI wire format also allows a
    list of typed content blocks; concatenate their text parts.
    """
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(parts)
    return ""


def _last_user_index(messages: Sequence[dict[str, Any]]) -> int | None:
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].get("role") == "user":
            return idx
    return None


def _script_message_index(messages: Sequence[dict[str, Any]]) -> int | None:
    """Index of the newest user message carrying directives.

    The agent graph injects context slots (dynamic context, todos, time) as
    trailing user-role messages, so the LAST user message is often not the one
    a test scripted. A malformed directive raises here — fail loud."""
    for idx in range(len(messages) - 1, -1, -1):
        message = messages[idx]
        if message.get("role") == "user" and parse_directives(message_text(message)):
            return idx
    return None


def _emitted_tool_names(messages: Sequence[dict[str, Any]]) -> list[str]:
    """Ordered tool-call names from assistant messages, flattened."""
    names: list[str] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            name = (call.get("function") or {}).get("name")
            if name:
                names.append(name)
    return names


def _cursor(
    tool_dirs: Sequence[ToolDirective],
    emitted: Sequence[str],
    available_tools: frozenset[str],
) -> int:
    """How many tool directives are already satisfied by the emitted turns."""
    di = 0
    for name in emitted:
        if di >= len(tool_dirs):
            break
        cur = tool_dirs[di]
        forwarding = cur.name not in available_tools and CALL_EXECUTOR_TOOL in available_tools
        if name == CALL_EXECUTOR_TOOL and forwarding:
            # One forwarding hand-off covers every consecutive executor-tool directive.
            while (
                di < len(tool_dirs)
                and tool_dirs[di].name not in available_tools
                and CALL_EXECUTOR_TOOL in available_tools
            ):
                di += 1
        elif name == RETRIEVE_TOOLS_TOOL:
            # Binding plumbing, not a scripted action — never advances the script.
            continue
        else:
            di += 1
    return di


def resolve_response(
    messages: Sequence[dict[str, Any]],
    available_tools: frozenset[str] = frozenset(),
) -> Response:
    """Pick the next scripted action for this invocation (stateless)."""
    latest = _script_message_index(messages)
    if latest is None:
        return SayResponse(DEFAULT_REPLY)

    user_text = message_text(messages[latest])
    directives = parse_directives(user_text)
    tool_dirs = [d for d in directives if isinstance(d, ToolDirective)]
    say = next((d for d in directives if isinstance(d, SayDirective)), None)
    if not tool_dirs and say is None:
        return SayResponse(DEFAULT_REPLY)

    emitted = _emitted_tool_names(messages[latest + 1 :])
    di = _cursor(tool_dirs, emitted, available_tools)

    if di < len(tool_dirs):
        nxt = tool_dirs[di]
        if nxt.name not in available_tools:
            if CALL_EXECUTOR_TOOL in available_tools:
                return ToolCallResponse(name=CALL_EXECUTOR_TOOL, args={"task": user_text})
            if RETRIEVE_TOOLS_TOOL in available_tools:
                return ToolCallResponse(
                    name=RETRIEVE_TOOLS_TOOL,
                    args={"query": nxt.name, "exact_tool_names": [nxt.name]},
                )
        return ToolCallResponse(name=nxt.name, args=nxt.args)

    return SayResponse(say.text if say is not None else DEFAULT_REPLY)


@dataclass(frozen=True)
class ChatRequest:
    """The fields of an OpenAI-compatible chat-completions request the stub needs."""

    model: str
    messages: list[dict[str, Any]]
    stream: bool
    available_tools: frozenset[str] = field(default_factory=frozenset)


def parse_request(body: dict[str, Any]) -> ChatRequest:
    tool_names = {
        (tool.get("function") or {}).get("name")
        for tool in body.get("tools") or []
        if isinstance(tool, dict)
    }
    return ChatRequest(
        model=body.get("model") or "llm-stub",
        messages=list(body.get("messages") or []),
        stream=bool(body.get("stream")),
        available_tools=frozenset(name for name in tool_names if name),
    )
