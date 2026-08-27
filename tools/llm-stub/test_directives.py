"""Unit tests for the scripted LLM stub's directive protocol and wire shapes.

Pure stdlib + pytest — no repo project needed:

    uv run --no-project --with pytest pytest tools/llm-stub -q
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from directives import (
    CALL_EXECUTOR_TOOL,
    DEFAULT_REPLY,
    SCRIPTED_CRITERIA,
    DirectiveError,
    SayDirective,
    SayResponse,
    ToolCallResponse,
    ToolDirective,
    parse_directives,
    parse_request,
    resolve_response,
)
from wire import build_chat_completion, stream_chunks

EXECUTOR_TOOLS = frozenset({"create_reminder", "web_search"})
COMMS_TOOLS = frozenset({CALL_EXECUTOR_TOOL, "add_memory", "search_memory"})


def _user(text: str) -> dict:
    return {"role": "user", "content": text}


def _assistant_tool_call(name: str, args: dict | None = None) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": f"call_{name}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args or {})},
            }
        ],
    }


def _tool_result(name: str) -> dict:
    return {"role": "tool", "tool_call_id": f"call_{name}", "content": "ok"}


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def test_parse_say_only():
    assert parse_directives("[[say:Hello there]]") == [SayDirective(text="Hello there")]


def test_parse_plain_text_has_no_directives():
    assert parse_directives("just chatting, no directives") == []


def test_parse_tool_with_json_args():
    got = parse_directives('[[tool:create_reminder {"when": "tomorrow", "title": "Dentist"}]]')
    assert got == [
        ToolDirective(name="create_reminder", args={"when": "tomorrow", "title": "Dentist"})
    ]


def test_parse_tool_without_args_defaults_to_empty_object():
    assert parse_directives("[[tool:list_todos]]") == [ToolDirective(name="list_todos", args={})]


def test_parse_ordered_multi_directive():
    text = (
        'noise [[tool:web_search {"q": "weather"}]] more '
        '[[tool:create_reminder {"title": "x"}]] tail [[say:All done]]'
    )
    assert parse_directives(text) == [
        ToolDirective(name="web_search", args={"q": "weather"}),
        ToolDirective(name="create_reminder", args={"title": "x"}),
        SayDirective(text="All done"),
    ]


def test_parse_malformed_json_raises():
    with pytest.raises(DirectiveError) as exc:
        parse_directives('[[tool:create_reminder {"when": tomorrow}]]')
    assert "create_reminder" in str(exc.value)


def test_parse_non_object_args_raises():
    with pytest.raises(DirectiveError):
        parse_directives("[[tool:create_reminder [1, 2, 3]]]")


def test_parse_tool_missing_name_raises():
    with pytest.raises(DirectiveError):
        parse_directives('[[tool: {"a": 1}]]')


# --------------------------------------------------------------------------- #
# Parser — nesting and delimiter boundaries
#
# A hand-off directive carries the next tier's script inside its JSON args, so
# the args routinely contain a whole ``[[tool:…]]`` directive — and therefore a
# literal ``]]``. The closing delimiter is only the ``]]`` that follows the
# directive's own JSON value; everything inside that value belongs to the value.
# --------------------------------------------------------------------------- #


def _tool_directive(name: str, args: dict) -> str:
    """Render a directive the way a test author would: JSON-encoded args."""
    return f"[[tool:{name} {json.dumps(args)}]]"


def test_parse_tool_with_empty_json_object_args():
    assert parse_directives("[[tool:noop {}]]") == [ToolDirective(name="noop", args={})]


def test_parse_empty_say_yields_empty_text():
    assert parse_directives("[[say:]]") == [SayDirective(text="")]


def test_parse_json_string_may_contain_literal_close_delimiter():
    script = _tool_directive("web_search", {"q": "how do wiki links ]] close"})
    assert parse_directives(script) == [
        ToolDirective(name="web_search", args={"q": "how do wiki links ]] close"})
    ]


def test_parse_nested_directive_one_level():
    """comms → executor → subagent: handoff carries the subagent's script."""
    inner = _tool_directive("fetch_emails", {"max_results": 5})
    script = _tool_directive("handoff", {"subagent_id": "gmail", "task": inner})
    assert parse_directives(script) == [
        ToolDirective(name="handoff", args={"subagent_id": "gmail", "task": inner})
    ]


def test_parse_nested_directive_two_levels():
    """Scenario 5, fully composed: call_executor wraps handoff wraps a tool."""
    inner = _tool_directive("fetch_emails", {"max_results": 5})
    mid = _tool_directive("handoff", {"subagent_id": "gmail", "task": inner})
    top = _tool_directive("call_executor", {"task": mid})

    assert parse_directives(top) == [ToolDirective(name="call_executor", args={"task": mid})]
    # Each layer peels off cleanly and is itself a valid script.
    assert parse_directives(mid) == [
        ToolDirective(name="handoff", args={"subagent_id": "gmail", "task": inner})
    ]
    assert parse_directives(inner) == [ToolDirective(name="fetch_emails", args={"max_results": 5})]


def test_parse_directive_following_a_nested_one_is_not_swallowed():
    inner = _tool_directive("fetch_emails", {"max_results": 5})
    script = _tool_directive("handoff", {"subagent_id": "gmail", "task": inner}) + " [[say:outer]]"
    assert parse_directives(script) == [
        ToolDirective(name="handoff", args={"subagent_id": "gmail", "task": inner}),
        SayDirective(text="outer"),
    ]


def test_parse_unterminated_tool_directive_raises():
    """A truncated script must fail loud, not degrade into the canned reply."""
    with pytest.raises(DirectiveError) as exc:
        parse_directives('[[tool:handoff {"subagent_id": "gmail"}')
    assert "handoff" in str(exc.value)


def test_parse_unterminated_say_directive_raises():
    with pytest.raises(DirectiveError) as exc:
        parse_directives("[[say:never closed")
    assert "say" in str(exc.value)


def test_nested_handoff_script_resolves_through_all_three_tiers():
    inner = _tool_directive("fetch_emails", {"max_results": 5})
    script = _tool_directive("handoff", {"subagent_id": "gmail", "task": inner}) + " [[say:done]]"

    # comms: handoff is unbound, call_executor is -> forward the script verbatim.
    assert resolve_response([_user(script)], COMMS_TOOLS) == ToolCallResponse(
        name=CALL_EXECUTOR_TOOL,
        args={"task": script, "acceptance_criteria": SCRIPTED_CRITERIA},
    )
    # executor: handoff is bound -> emit it, carrying the subagent's script intact.
    assert resolve_response([_user(script)], frozenset({"handoff"})) == ToolCallResponse(
        name="handoff", args={"subagent_id": "gmail", "task": inner}
    )
    # subagent: that task text is itself a script the stub can drive.
    assert resolve_response([_user(inner)], frozenset({"fetch_emails"})) == ToolCallResponse(
        name="fetch_emails", args={"max_results": 5}
    )


# --------------------------------------------------------------------------- #
# Turn counting — executor mode (directive tools are bound in this request)
# --------------------------------------------------------------------------- #


def test_trailing_context_user_message_does_not_hide_script():
    """The graph injects context slots as trailing user-role messages; the stub
    must script from the newest user message that carries directives."""
    messages = [
        _user("[[say:SCRIPTED]]"),
        _user("=== dynamic context ===\ncurrent todos: none"),
    ]
    assert resolve_response(messages, EXECUTOR_TOOLS) == SayResponse(text="SCRIPTED")


def test_bigtool_executor_retrieves_then_calls():
    """Unbound scripted tool + retrieve_tools available → bind first, call second,
    and the retrieval turn never advances the script cursor."""
    script = '[[tool:create_todo {"title": "x"}]] [[say:Done]]'
    bigtool = frozenset({"retrieve_tools"})

    first = resolve_response([_user(script)], bigtool)
    assert first == ToolCallResponse(
        name="retrieve_tools", args={"query": "create_todo", "exact_tool_names": ["create_todo"]}
    )

    after_retrieval = [
        _user(script),
        _assistant_tool_call("retrieve_tools", {"exact_tool_names": ["create_todo"]}),
        _tool_result("retrieve_tools"),
    ]
    bound = frozenset({"retrieve_tools", "create_todo"})
    assert resolve_response(after_retrieval, bound) == ToolCallResponse(
        name="create_todo", args={"title": "x"}
    )

    after_call = after_retrieval + [
        _assistant_tool_call("create_todo", {"title": "x"}),
        _tool_result("create_todo"),
    ]
    assert resolve_response(after_call, bound) == SayResponse(text="Done")


def test_executor_first_turn_emits_first_tool():
    messages = [_user('[[tool:create_reminder {"title": "x"}]] [[say:Done]]')]
    got = resolve_response(messages, EXECUTOR_TOOLS)
    assert got == ToolCallResponse(name="create_reminder", args={"title": "x"})


def test_executor_after_one_tool_emits_say():
    messages = [
        _user('[[tool:create_reminder {"title": "x"}]] [[say:Reminder set!]]'),
        _assistant_tool_call("create_reminder", {"title": "x"}),
        _tool_result("create_reminder"),
    ]
    assert resolve_response(messages, EXECUTOR_TOOLS) == SayResponse(text="Reminder set!")


def test_executor_multi_tool_ordering():
    script = '[[tool:web_search {"q": "x"}]] [[tool:create_reminder {"title": "y"}]] [[say:ok]]'
    # No tools called yet -> first directive.
    assert resolve_response([_user(script)], EXECUTOR_TOOLS) == ToolCallResponse(
        name="web_search", args={"q": "x"}
    )
    # First tool done -> second directive.
    after_first = [_user(script), _assistant_tool_call("web_search"), _tool_result("web_search")]
    assert resolve_response(after_first, EXECUTOR_TOOLS) == ToolCallResponse(
        name="create_reminder", args={"title": "y"}
    )
    # Both tools done -> say.
    after_both = after_first + [
        _assistant_tool_call("create_reminder"),
        _tool_result("create_reminder"),
    ]
    assert resolve_response(after_both, EXECUTOR_TOOLS) == SayResponse(text="ok")


def test_no_directives_yields_canned_reply():
    assert resolve_response([_user("hi")], EXECUTOR_TOOLS) == SayResponse(text=DEFAULT_REPLY)


def test_tools_only_no_say_falls_back_to_default_after_completion():
    messages = [
        _user("[[tool:create_reminder]]"),
        _assistant_tool_call("create_reminder"),
        _tool_result("create_reminder"),
    ]
    assert resolve_response(messages, EXECUTOR_TOOLS) == SayResponse(text=DEFAULT_REPLY)


def test_latest_user_message_wins():
    # A prior turn's directives must not leak into a fresh user message.
    messages = [
        _user('[[tool:create_reminder {"title": "old"}]] [[say:old]]'),
        _assistant_tool_call("create_reminder", {"title": "old"}),
        _tool_result("create_reminder"),
        {"role": "assistant", "content": "old"},
        _user("[[say:fresh reply]]"),
    ]
    assert resolve_response(messages, EXECUTOR_TOOLS) == SayResponse(text="fresh reply")


# --------------------------------------------------------------------------- #
# Turn counting — front-door (comms) mode: forward executor tools via call_executor
# --------------------------------------------------------------------------- #


def test_comms_forwards_executor_tool_via_call_executor():
    script = '[[tool:create_reminder {"title": "x"}]] [[say:Reminder set!]]'
    got = resolve_response([_user(script)], COMMS_TOOLS)
    assert got == ToolCallResponse(
        name=CALL_EXECUTOR_TOOL,
        args={"task": script, "acceptance_criteria": SCRIPTED_CRITERIA},
    )


def test_comms_after_forwarding_emits_say():
    script = '[[tool:create_reminder {"title": "x"}]] [[say:Reminder set!]]'
    messages = [
        _user(script),
        _assistant_tool_call(CALL_EXECUTOR_TOOL, {"task": script}),
        _tool_result(CALL_EXECUTOR_TOOL),
    ]
    assert resolve_response(messages, COMMS_TOOLS) == SayResponse(text="Reminder set!")


def test_comms_single_forward_covers_multiple_executor_tools():
    script = '[[tool:web_search {"q": "x"}]] [[tool:create_reminder {"title": "y"}]] [[say:ok]]'
    # One call_executor turn stands in for BOTH executor-tool directives.
    messages = [
        _user(script),
        _assistant_tool_call(CALL_EXECUTOR_TOOL, {"task": script}),
        _tool_result(CALL_EXECUTOR_TOOL),
    ]
    assert resolve_response(messages, COMMS_TOOLS) == SayResponse(text="ok")


def test_comms_direct_tool_when_bound():
    # add_memory is bound to comms -> emit it directly, no forwarding.
    script = '[[tool:add_memory {"text": "likes tea"}]] [[say:noted]]'
    assert resolve_response([_user(script)], COMMS_TOOLS) == ToolCallResponse(
        name="add_memory", args={"text": "likes tea"}
    )


# --------------------------------------------------------------------------- #
# Request parsing
# --------------------------------------------------------------------------- #


def test_parse_request_extracts_tool_names_and_stream():
    body = {
        "model": "x-ai/grok",
        "stream": True,
        "messages": [_user("hi")],
        "tools": [
            {"type": "function", "function": {"name": "create_reminder"}},
            {"type": "function", "function": {"name": "web_search"}},
        ],
    }
    req = parse_request(body)
    assert req.model == "x-ai/grok"
    assert req.stream is True
    assert req.available_tools == frozenset({"create_reminder", "web_search"})


def test_parse_request_defaults():
    req = parse_request({"messages": [_user("hi")]})
    assert req.model == "llm-stub"
    assert req.stream is False
    assert req.available_tools == frozenset()


def test_message_text_flattens_content_blocks():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "[[say:block reply]]"}]},
    ]
    assert resolve_response(messages, EXECUTOR_TOOLS) == SayResponse(text="block reply")


# --------------------------------------------------------------------------- #
# Wire shapes
# --------------------------------------------------------------------------- #


def test_build_chat_completion_tool_call_shape():
    payload = build_chat_completion(
        "m", ToolCallResponse(name="create_reminder", args={"title": "x"})
    )
    assert payload["object"] == "chat.completion"
    assert "system_fingerprint" in payload
    choice = payload["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    call = choice["message"]["tool_calls"][0]
    assert call["type"] == "function"
    assert call["function"]["name"] == "create_reminder"
    assert json.loads(call["function"]["arguments"]) == {"title": "x"}


def test_build_chat_completion_say_shape():
    payload = build_chat_completion("m", SayResponse(text="hi"))
    choice = payload["choices"][0]
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["content"] == "hi"


def test_stream_chunks_tool_call_assembly():
    chunks = list(stream_chunks("m", ToolCallResponse(name="create_reminder", args={"title": "x"})))
    assert all(c["object"] == "chat.completion.chunk" for c in chunks)
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
    # Reassemble tool call from the streamed deltas.
    name = None
    args = ""
    for c in chunks:
        for call in c["choices"][0]["delta"].get("tool_calls", []):
            fn = call.get("function", {})
            name = fn.get("name") or name
            args += fn.get("arguments", "")
    assert name == "create_reminder"
    assert json.loads(args) == {"title": "x"}
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"


def test_stream_chunks_content_assembly():
    chunks = list(stream_chunks("m", SayResponse(text="Reminder set successfully!")))
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert text == "Reminder set successfully!"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    # Every non-final choice carries an explicit null finish_reason.
    assert all("finish_reason" in c["choices"][0] for c in chunks)
