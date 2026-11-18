"""Tell an agent's own turn from every other call, and answer the others neutrally.

Only comms, the executor and subagents run the user's script. Everything else
(memory extraction, follow-up actions, titles, compaction) sees the same user
message, but replaying the script there makes each helper fail on an answer it
did not ask for and runs every scripted tool twice. Those calls get the emptiest
answer their request accepts instead.

The request's own shape says which it is: agent turns stream with tools bound
(the sim client streams), a structured one-shot binds exactly one tool and turns
streaming off, a forced tool_choice or a json_schema response_format asks for
that shape outright, and a call with no tools is never an agent turn. Pure stdlib.
"""

from __future__ import annotations

import json
from typing import Any, TypeAlias

from directives import (
    DEFAULT_REPLY,
    DirectiveError,
    Response,
    SayResponse,
    ToolCallResponse,
    parse_request,
    resolve_response,
)

#: Any value a JSON schema can describe.
JsonValue: TypeAlias = "None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]"
#: tool_choice values that force a call without naming the tool; forcing only when one is bound.
_FORCE_ANY = ("required", "any", True)


def answer_request(body: dict[str, Any]) -> Response:
    """Answer one chat-completions body: the script for an agent turn, a neutral reply otherwise."""
    tools: list[dict[str, Any]] = [t for t in body.get("tools") or [] if isinstance(t, dict)]
    tool = _answered_tool(tools, body.get("tool_choice"), stream=bool(body.get("stream")))
    if tool is not None:
        function = tool.get("function") or {}
        parameters = function.get("parameters") or {}
        args = emptiest(parameters, parameters.get("$defs") or {})
        if not isinstance(args, dict):
            raise DirectiveError(f"tool {function.get('name')!r} takes {args!r}, not an object")
        return ToolCallResponse(name=str(function.get("name")), args=args)
    if tools:
        parsed = parse_request(body)
        return resolve_response(parsed.messages, parsed.available_tools)
    schema = ((body.get("response_format") or {}).get("json_schema") or {}).get("schema")
    if schema is not None:
        return SayResponse(json.dumps(emptiest(schema, schema.get("$defs") or {})))
    return SayResponse(DEFAULT_REPLY)


def _answered_tool(
    tools: list[dict[str, Any]], tool_choice: object, *, stream: bool
) -> dict[str, Any] | None:
    """Pick the one tool a background call asks for; None for an agent turn or a tool-less call."""
    if isinstance(tool_choice, dict):
        name = (tool_choice.get("function") or {}).get("name")
        named = [t for t in tools if (t.get("function") or {}).get("name") == name]
        if not named:
            # Fail loud: a request forcing a tool it never offered is the caller's bug.
            raise DirectiveError(f"tool_choice forces {name!r}, which the request does not offer")
        return named[0]
    if len(tools) == 1 and (tool_choice in _FORCE_ANY or not stream):
        return tools[0]
    return None


def emptiest(schema: dict[str, Any], defs: dict[str, Any]) -> JsonValue:
    """Return the emptiest value schema accepts: null where allowed, else empty, zero, false or its first choice."""
    if "$ref" in schema:
        return emptiest(defs[schema["$ref"].rsplit("/", 1)[-1]], defs)
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    variants = schema.get("anyOf") or schema.get("oneOf")
    if variants:
        nullable = next((v for v in variants if v.get("type") == "null"), None)
        return None if nullable is not None else emptiest(variants[0], defs)
    kind = schema.get("type")
    if kind == "object":
        properties = schema.get("properties") or {}
        return {key: emptiest(properties[key], defs) for key in schema.get("required") or []}
    empty: dict[str, JsonValue] = {
        "array": [],
        "string": "",
        "integer": 0,
        "number": 0,
        "boolean": False,
    }
    return empty.get(str(kind))
