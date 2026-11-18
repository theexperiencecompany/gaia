"""Unit tests for which calls run the user's script and what every other call gets.

Pure stdlib + pytest, like test_directives.py.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from background import answer_request
from directives import CALL_EXECUTOR_TOOL, DEFAULT_REPLY, SayResponse, ToolCallResponse

SCRIPT = '[[tool:create_todo {"title": "buy milk"}]] [[say:done]]'

#: FollowUpActions as bind_tools offers it.
FOLLOW_UP_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "FollowUpActions",
        "parameters": {
            "type": "object",
            "properties": {"actions": {"type": "array", "items": {"type": "string"}}},
            "required": ["actions"],
        },
    },
}

#: A nested schema: a $ref, an enum, a nullable field, scalars, and an optional field.
NESTED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"$ref": "#/$defs/Verdict"},
        "score": {"type": "number"},
        "count": {"type": "integer"},
        "flagged": {"type": "boolean"},
        "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "detail": {
            "type": "object",
            "properties": {"why": {"type": "string"}},
            "required": ["why"],
        },
        "optional": {"type": "string"},
    },
    "required": ["verdict", "score", "count", "flagged", "note", "detail"],
    "$defs": {"Verdict": {"type": "string", "enum": ["safe", "unsafe"]}},
}

NESTED_VALUE = {
    "verdict": "safe",
    "score": 0,
    "count": 0,
    "flagged": False,
    "note": None,
    "detail": {"why": ""},
}


def _tool(name: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "parameters": parameters or {}}}


def _body(**fields: object) -> dict[str, Any]:
    return {"model": "gaia-sim-stub", "messages": [{"role": "user", "content": SCRIPT}], **fields}


def test_a_structured_one_shot_gets_its_own_tool_not_the_users_script() -> None:
    """The sim client offers the one-shot's tool unforced and unstreamed (tool_choice auto)."""
    body = _body(tools=[FOLLOW_UP_TOOL], tool_choice="auto", stream=False)

    assert answer_request(body) == ToolCallResponse(name="FollowUpActions", args={"actions": []})


def test_a_tool_forced_by_name_gets_schema_valid_minimal_args() -> None:
    body = _body(
        tools=[_tool("Moderation", NESTED_SCHEMA), _tool("create_todo")],
        tool_choice={"type": "function", "function": {"name": "Moderation"}},
        stream=True,
    )

    assert answer_request(body) == ToolCallResponse(name="Moderation", args=NESTED_VALUE)


def test_required_tool_choice_with_one_tool_is_forced_even_when_streamed() -> None:
    body = _body(tools=[FOLLOW_UP_TOOL], tool_choice="required", stream=True)

    assert answer_request(body) == ToolCallResponse(name="FollowUpActions", args={"actions": []})


def test_a_json_schema_response_format_gets_minimal_valid_json() -> None:
    body = _body(
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "X", "schema": NESTED_SCHEMA},
        },
        stream=False,
    )

    response = answer_request(body)

    assert isinstance(response, SayResponse)
    assert json.loads(response.text) == NESTED_VALUE


def test_a_call_with_no_tools_gets_neutral_text() -> None:
    """A title, summary or compaction call carries the user's message but binds no tools."""
    assert answer_request(_body(stream=True)) == SayResponse(DEFAULT_REPLY)


def test_an_executor_turn_still_runs_the_script() -> None:
    body = _body(tools=[_tool("create_todo"), _tool("web_search")], stream=True)

    assert answer_request(body) == ToolCallResponse(name="create_todo", args={"title": "buy milk"})


def test_a_comms_turn_with_one_tool_bound_still_forwards_the_script() -> None:
    """Streaming marks an agent turn, so a single bound tool does not make it a one-shot."""
    body = _body(tools=[_tool(CALL_EXECUTOR_TOOL)], stream=True)

    response = answer_request(body)

    assert isinstance(response, ToolCallResponse)
    assert response.name == CALL_EXECUTOR_TOOL
