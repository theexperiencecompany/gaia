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

A tool directive's args are terminated by the JSON value itself, not by the
first ``]]``, so args may contain a literal ``]]`` — including a whole nested
directive, at any depth. That is what a hand-off script needs: the outer
directive carries the next tier's script inside its ``task`` argument.

Limitations (documented, not silently handled):
- A ``[[say:…]]`` body is plain text and ends at the first ``]]``, so say text
  cannot itself contain that sequence. Put nested scripts in tool args.
- A directive opened but never closed raises ``DirectiveError`` rather than
  being ignored — a truncated script must not degrade into the canned reply.
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
# call_executor requires acceptance_criteria, so a scripted hand-off has to send
# something. Exported rather than inlined so the stub's tests pin the real value
# instead of a copy that can drift.
SCRIPTED_CRITERIA = ["scripted directives executed"]
# The bigtool executor binds tools at inference: when a scripted tool is not yet
# bound, the stub first emits retrieve_tools(exact_tool_names=[name]) so the
# graph binds it, then emits the tool itself on the next invocation.
RETRIEVE_TOOLS_TOOL = "retrieve_tools"

_DIRECTIVE_OPEN_RE = re.compile(r"\[\[(tool|say):")
_CLOSE = "]]"
# Consumes exactly one JSON value and reports where it ended, so a ``]]`` inside
# the value (a nested directive) cannot be mistaken for the closing delimiter.
_JSON_DECODER = json.JSONDecoder()

# Agent tiers frame internal payloads in XML-ish tags (see app/constants/agents.py
# ``wrap_agent_payload``). A real model reads those as quoted context, never as new
# commands — but a cancelled run's record and other notices echo the ORIGINAL
# request verbatim, ``[[tool:...]]`` directives and all. Only ``<user_interjection>``
# is the user genuinely speaking new work into a live run; every other tag is an
# echo whose directives must NOT be re-executed. Strip those blocks before parsing
# so the stub stops re-firing quoted work (phantom todos, a re-dispatched cancel).
USER_INTERJECTION_TAG = "user_interjection"
_ECHO_BLOCK_RE = re.compile(r"<([a-z][a-z0-9_]*)(?:\s[^>]*)?>.*?</\1>", re.DOTALL)


def _strip_echoed_payloads(text: str) -> str:
    """Remove every internal-tag block except ``<user_interjection>``."""
    return _ECHO_BLOCK_RE.sub(
        lambda m: m.group(0) if m.group(1) == USER_INTERJECTION_TAG else "", text
    )


def _is_interjection(text: str) -> bool:
    return text.lstrip().startswith(f"<{USER_INTERJECTION_TAG}")


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
    """Parse ordered directives out of a single message's text.

    Scans opener-first: each directive is consumed whole before the search for
    the next one resumes, so an opener nested inside a directive's args is part
    of those args and never starts a directive of its own.
    """
    directives: list[Directive] = []
    directive: Directive
    pos = 0
    while (opener := _DIRECTIVE_OPEN_RE.search(text, pos)) is not None:
        if opener.group(1) == "say":
            directive, pos = _scan_say(text, opener.end())
        else:
            directive, pos = _scan_tool(text, opener.end())
        directives.append(directive)
    return directives


def _skip_space(text: str, pos: int) -> int:
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _scan_say(text: str, start: int) -> tuple[SayDirective, int]:
    """Say bodies are plain text: they end at the first ``]]``."""
    end = text.find(_CLOSE, start)
    if end < 0:
        raise DirectiveError(f"unterminated say directive: [[say:{text[start : start + 60]}")
    return SayDirective(text=text[start:end].strip()), end + len(_CLOSE)


def _scan_tool(text: str, start: int) -> tuple[ToolDirective, int]:
    """Tool args end where their JSON value ends, not at the first ``]]``."""
    cursor = start
    while cursor < len(text) and not text[cursor].isspace() and not text.startswith(_CLOSE, cursor):
        cursor += 1
    name = text[start:cursor]
    if not name:
        raise DirectiveError(f"tool directive missing a name: [[tool:{text[start : start + 60]}")

    cursor = _skip_space(text, cursor)
    if text.startswith(_CLOSE, cursor):
        return ToolDirective(name=name, args={}), cursor + len(_CLOSE)

    try:
        args, cursor = _JSON_DECODER.raw_decode(text, cursor)
    except json.JSONDecodeError as exc:
        raise DirectiveError(
            f"tool directive '{name}' has invalid JSON args: {text[cursor : cursor + 120]!r} ({exc})"
        ) from exc
    if not isinstance(args, dict):
        raise DirectiveError(f"tool directive '{name}' args must be a JSON object, got {args!r}")

    cursor = _skip_space(text, cursor)
    if not text.startswith(_CLOSE, cursor):
        raise DirectiveError(
            f"unterminated tool directive '{name}': expected ']]' after its JSON args, "
            f"found {text[cursor : cursor + 60]!r}"
        )
    return ToolDirective(name=name, args=args), cursor + len(_CLOSE)


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
        if message.get("role") == "user" and parse_directives(
            _strip_echoed_payloads(message_text(message))
        ):
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


def _work_primary_index(messages: Sequence[dict[str, Any]]) -> int | None:
    """Newest non-interjection user message carrying directives — the current task.

    Newest, not first: an executor thread persists per conversation, so a later
    run's context still holds earlier runs' tasks. The task in flight is the most
    recent genuine (non-interjection, echo-stripped) instruction; steers for it
    arrive after it."""
    for idx in range(len(messages) - 1, -1, -1):
        message = messages[idx]
        if message.get("role") != "user":
            continue
        text = message_text(message)
        if _is_interjection(text):
            continue
        if parse_directives(_strip_echoed_payloads(text)):
            return idx
    return None


def _collect_work_directives(
    messages: Sequence[dict[str, Any]],
) -> tuple[list[ToolDirective], SayDirective | None, int | None]:
    """The current task's directives PLUS every steer folded into its run.

    A run works through the whole plan — the original tool directives and each
    ``<user_interjection>`` the drain hook injected, in order, each once — then
    the final say. This is what lets a burst of steers all land in one run and
    the plan survive a mid-run steer (a real model keeps its plan; the old
    "newest scripted message wins" made the stub drop it)."""
    primary_idx = _work_primary_index(messages)
    if primary_idx is None:
        return [], None, None
    genuine: list[Directive] = list(
        parse_directives(_strip_echoed_payloads(message_text(messages[primary_idx])))
    )
    for message in messages[primary_idx + 1 :]:
        if message.get("role") != "user":
            continue
        text = message_text(message)
        if _is_interjection(text):
            genuine.extend(parse_directives(_strip_echoed_payloads(text)))
    tool_dirs = [d for d in genuine if isinstance(d, ToolDirective)]
    say = next((d for d in reversed(genuine) if isinstance(d, SayDirective)), None)
    return tool_dirs, say, primary_idx


def _resolve_work(messages: Sequence[dict[str, Any]], available_tools: frozenset[str]) -> Response:
    """Executor/subagent tier: aggregate the task + its steers, emit the next step."""
    tool_dirs, say, primary_idx = _collect_work_directives(messages)
    if not tool_dirs and say is None:
        return SayResponse(DEFAULT_REPLY)

    tail = messages[primary_idx + 1 :] if primary_idx is not None else messages
    di = _cursor(tool_dirs, _emitted_tool_names(tail), available_tools)
    if di < len(tool_dirs):
        nxt = tool_dirs[di]
        if nxt.name not in available_tools and RETRIEVE_TOOLS_TOOL in available_tools:
            return ToolCallResponse(
                name=RETRIEVE_TOOLS_TOOL,
                args={"query": nxt.name, "exact_tool_names": [nxt.name]},
            )
        return ToolCallResponse(name=nxt.name, args=nxt.args)
    return SayResponse(say.text if say is not None else DEFAULT_REPLY)


def _resolve_comms(messages: Sequence[dict[str, Any]], available_tools: frozenset[str]) -> Response:
    """Front-door tier: forward / cancel the newest genuine instruction this turn.

    One user message per comms turn (each steer is its own request), so newest —
    not aggregated. Echo-stripping keeps comms from forwarding a quoted
    ``<executor_cancelled>`` record as if it were fresh work."""
    latest = _script_message_index(messages)
    if latest is None:
        return SayResponse(DEFAULT_REPLY)

    task_text = _strip_echoed_payloads(message_text(messages[latest]))
    directives = parse_directives(task_text)
    tool_dirs = [d for d in directives if isinstance(d, ToolDirective)]
    say = next((d for d in directives if isinstance(d, SayDirective)), None)
    if not tool_dirs and say is None:
        return SayResponse(DEFAULT_REPLY)

    di = _cursor(tool_dirs, _emitted_tool_names(messages[latest + 1 :]), available_tools)
    if di < len(tool_dirs):
        nxt = tool_dirs[di]
        if nxt.name not in available_tools and CALL_EXECUTOR_TOOL in available_tools:
            # acceptance_criteria became required with the structured handoff.
            return ToolCallResponse(
                name=CALL_EXECUTOR_TOOL,
                args={"task": task_text, "acceptance_criteria": SCRIPTED_CRITERIA},
            )
        return ToolCallResponse(name=nxt.name, args=nxt.args)
    return SayResponse(say.text if say is not None else DEFAULT_REPLY)


def resolve_response(
    messages: Sequence[dict[str, Any]],
    available_tools: frozenset[str] = frozenset(),
) -> Response:
    """Pick the next scripted action for this invocation (stateless).

    The front door (``call_executor`` bound) forwards/cancels the newest
    instruction; the tier that runs work aggregates the task and every steer
    folded into its run."""
    if CALL_EXECUTOR_TOOL in available_tools:
        return _resolve_comms(messages, available_tools)
    return _resolve_work(messages, available_tools)


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
