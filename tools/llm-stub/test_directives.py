"""Unit tests for the scripted LLM stub's directive protocol and wire shapes.

Pure stdlib + pytest — no repo project needed:

    uv run --no-project --with pytest pytest tools/llm-stub -q
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import time
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from directives import (
    CALL_EXECUTOR_TOOL,
    DEFAULT_REPLY,
    SCRIPTED_HAND_OFF_ARGS,
    VERBATIM_REQUEST_HEADER,
    DirectiveError,
    FailDirective,
    NarrateDirective,
    PaceDirective,
    SayDirective,
    SayResponse,
    ToolCallResponse,
    ToolDirective,
    WaitDirective,
    parse_directives,
    parse_request,
    resolve_response,
)
from wire import ScriptedFault, build_chat_completion, sse_lines, stream_chunks

#: One chat-completions message, as the stub reads it off the wire.
Message = dict[str, Any]

EXECUTOR_TOOLS = frozenset({"create_reminder", "web_search"})
COMMS_TOOLS = frozenset({CALL_EXECUTOR_TOOL, "add_memory", "search_memory"})


def _user(text: str) -> Message:
    return {"role": "user", "content": text}


def _assistant_tool_call(name: str, args: dict[str, Any] | None = None) -> Message:
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


def _tool_result(name: str) -> Message:
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


def test_a_quoted_script_is_text_to_the_end_of_its_string():
    """A recorded task quoting its own script back, escaped, is text — not a real directive."""
    quoted = (
        'earlier: "[[tool:create_todo {\\"title\\": \\"sim\\"}]] [[tool:list_todos]] '
        '[[say:old]]" then [[say:new]]'
    )
    assert parse_directives(quoted) == [SayDirective(text="new")]


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


def _tool_directive(name: str, args: dict[str, Any]) -> str:
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
    """Comms → executor → subagent: handoff carries the subagent's script."""
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
        args={"task": script, **SCRIPTED_HAND_OFF_ARGS},
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
    """The stub must script from the newest user message that carries directives."""
    messages = [
        _user("[[say:SCRIPTED]]"),
        _user("=== dynamic context ===\ncurrent todos: none"),
    ]
    assert resolve_response(messages, EXECUTOR_TOOLS) == SayResponse(text="SCRIPTED")


def test_bigtool_executor_retrieves_then_calls():
    """Bind first, call second; the retrieval turn never advances the script cursor."""
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
        args={"task": script, **SCRIPTED_HAND_OFF_ARGS},
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
        "m", ToolCallResponse(name="create_reminder", args={"title": "x"}), 50
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
    payload = build_chat_completion("m", SayResponse(text="hi"), 50)
    choice = payload["choices"][0]
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["content"] == "hi"


def test_stream_chunks_tool_call_assembly():
    chunks = list(
        stream_chunks("m", ToolCallResponse(name="create_reminder", args={"title": "x"}), 50)
    )
    assert all(c["object"] == "chat.completion.chunk" for c in chunks)
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
    # Reassemble tool call from the streamed deltas.
    name = None
    args = ""
    choice_chunks = [c for c in chunks if c["choices"]]
    for c in choice_chunks:
        for call in c["choices"][0]["delta"].get("tool_calls", []):
            fn = call.get("function", {})
            name = fn.get("name") or name
            args += fn.get("arguments", "")
    assert name == "create_reminder"
    assert json.loads(args) == {"title": "x"}
    assert choice_chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"


def test_stream_chunks_content_assembly():
    chunks = list(stream_chunks("m", SayResponse(text="Reminder set successfully!"), 50))
    choice_chunks = [c for c in chunks if c["choices"]]
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in choice_chunks)
    assert text == "Reminder set successfully!"
    assert choice_chunks[-1]["choices"][0]["finish_reason"] == "stop"
    # Every non-final choice carries an explicit null finish_reason.
    assert all("finish_reason" in c["choices"][0] for c in choice_chunks)


def test_a_streamed_reply_ends_with_the_usage_a_real_provider_reports():
    """GAIA refuses a success with no usage, so a zero-usage stub would make every sim call a metering error."""
    chunks = list(stream_chunks("m", SayResponse(text="Reminder set successfully!"), 50))
    assert chunks[-1]["choices"] == []
    assert chunks[-1]["usage"] == {"prompt_tokens": 50, "completion_tokens": 6, "total_tokens": 56}


def test_a_non_streamed_reply_reports_non_zero_usage():
    payload = build_chat_completion("m", SayResponse(text="hi"), 50)
    assert payload["usage"] == {"prompt_tokens": 50, "completion_tokens": 1, "total_tokens": 51}


# --------------------------------------------------------------------------- #
# Multiple steers folded into one work run, and echoed-directive filtering.
# These pin the fix for the burst + cancel gaps: a run keeps its plan while
# folding every <user_interjection> steer, and never re-executes directives a
# cancel record (or any other internal-tag payload) quotes verbatim.
# --------------------------------------------------------------------------- #

WORK_TOOLS = frozenset({"create_todo"})


def _interjection(text: str) -> Message:
    return {"role": "user", "content": f"<user_interjection>\n{text}\n</user_interjection>"}


def _cancelled_record(quoted_task: str) -> Message:
    return {
        "role": "user",
        "content": (
            f"<executor_cancelled>\nThe background task 42 ('{quoted_task}') was "
            f"cancelled by the user before it completed.\n</executor_cancelled>"
        ),
    }


def test_steer_does_not_drop_the_original_plan():
    task = (
        "Plan: "
        + _tool_directive("create_todo", {"title": "A"})
        + " "
        + _tool_directive("create_todo", {"title": "B"})
        + " "
        + _tool_directive("create_todo", {"title": "C"})
        + " [[say:done]]"
    )
    messages = [
        _user(task),
        _assistant_tool_call("create_todo", {"title": "A"}),
        _tool_result("create_todo"),
        _interjection("also " + _tool_directive("create_todo", {"title": "STEER"})),
    ]
    # After A, with a steer folded in, the next step is the plan's B — not the steer.
    assert resolve_response(messages, WORK_TOOLS) == ToolCallResponse(
        name="create_todo", args={"title": "B"}
    )


def test_plan_and_all_steers_run_in_one_pass_then_say():
    task = (
        "Plan: "
        + _tool_directive("create_todo", {"title": "A"})
        + " "
        + _tool_directive("create_todo", {"title": "B"})
        + " [[say:done]]"
    )
    messages = [
        _user(task),
        _interjection(_tool_directive("create_todo", {"title": "X"})),
        _interjection(_tool_directive("create_todo", {"title": "Y"})),
    ]
    order: list[tuple[str, str]] = []
    for _ in range(10):
        got = resolve_response(messages, WORK_TOOLS)
        if isinstance(got, SayResponse):
            order.append(("say", got.text))
            break
        order.append(("tool", got.args["title"]))
        messages.append(_assistant_tool_call("create_todo", got.args))
        messages.append(_tool_result("create_todo"))
    assert order == [
        ("tool", "A"),
        ("tool", "B"),
        ("tool", "X"),
        ("tool", "Y"),
        ("say", "done"),
    ]


def test_interjection_directive_is_executed_after_plan():
    task = "task " + _tool_directive("create_todo", {"title": "A"}) + " [[say:done]]"
    messages = [
        _user(task),
        _assistant_tool_call("create_todo", {"title": "A"}),
        _tool_result("create_todo"),
        _interjection(_tool_directive("create_todo", {"title": "REAL"})),
    ]
    assert resolve_response(messages, WORK_TOOLS) == ToolCallResponse(
        name="create_todo", args={"title": "REAL"}
    )


def test_cancelled_record_not_re_executed_work_tier():
    ghost = _tool_directive("create_todo", {"title": "GHOST"})
    got = resolve_response([_cancelled_record(f"do {ghost}")], WORK_TOOLS)
    assert isinstance(got, SayResponse)  # the quoted GHOST directive is not run


def test_cancelled_record_not_forwarded_comms_tier():
    ghost = _tool_directive("create_todo", {"title": "GHOST"})
    got = resolve_response([_cancelled_record(f"do {ghost}")], COMMS_TOOLS)
    assert isinstance(got, SayResponse)  # comms does not forward a quoted cancel record


def test_interrupt_note_with_quoted_directive_is_ignored():
    ghost = _tool_directive("create_todo", {"title": "GHOST"})
    note = {
        "role": "user",
        "content": f"<executor_interrupted>\nStopped; it was doing {ghost}\n</executor_interrupted>",
    }
    assert isinstance(resolve_response([note], WORK_TOOLS), SayResponse)


def test_an_unbound_internal_tool_is_retrieved_even_when_execute_is_exposed():
    """Internal tools bind through retrieve_tools; an execute call would skip the tool yet advance the script."""
    script = '[[tool:create_todo {"title": "x"}]] [[say:Done]]'
    executor = frozenset({"retrieve_tools", "execute"})

    assert resolve_response([_user(script)], executor) == ToolCallResponse(
        name="retrieve_tools", args={"query": "create_todo", "exact_tool_names": ["create_todo"]}
    )

    after_retrieval = [
        _user(script),
        _assistant_tool_call("retrieve_tools", {"exact_tool_names": ["create_todo"]}),
        _tool_result("retrieve_tools"),
    ]
    assert resolve_response(after_retrieval, executor | {"create_todo"}) == ToolCallResponse(
        name="create_todo", args={"title": "x"}
    )


def test_a_tool_retrieval_left_unbound_runs_through_execute_once():
    """Retrieval returns an integration tool's schema instead of binding it, so execute runs it."""
    script = '[[tool:GMAIL_SEND_EMAIL {"recipient_email": "a@b.c"}]] [[say:Done]]'
    executor = frozenset({"retrieve_tools", "execute"})

    assert resolve_response([_user(script)], executor) == ToolCallResponse(
        name="retrieve_tools",
        args={"query": "GMAIL_SEND_EMAIL", "exact_tool_names": ["GMAIL_SEND_EMAIL"]},
    )

    after_retrieval = [
        _user(script),
        _assistant_tool_call("retrieve_tools", {"exact_tool_names": ["GMAIL_SEND_EMAIL"]}),
        _tool_result("retrieve_tools"),
    ]
    execute_call = resolve_response(after_retrieval, executor)
    assert execute_call == ToolCallResponse(
        name="execute",
        args={
            "task_description": "Run GMAIL_SEND_EMAIL",
            "tool_name": "GMAIL_SEND_EMAIL",
            "data": {"recipient_email": "a@b.c"},
        },
    )

    after_execute = after_retrieval + [
        _assistant_tool_call("execute", execute_call.args),
        _tool_result("execute"),
    ]
    assert resolve_response(after_execute, executor) == SayResponse(text="Done")


def test_an_unbound_tool_runs_through_execute_when_nothing_can_bind_it():
    script = '[[tool:GMAIL_SEND_EMAIL {"recipient_email": "a@b.c"}]] [[say:Done]]'
    first = resolve_response([_user(script)], frozenset({"execute"}))
    assert isinstance(first, ToolCallResponse)
    assert first.name == "execute"


def test_a_quoted_copy_of_a_directive_in_the_same_message_is_plain_text():
    """A quoted, escaped copy of prior calls must neither run nor fail a message with a real script."""
    quoted = 'Last run: call_executor({"task": "[[tool:create_todo {\\"title\\": \\"sim\\"}]]"})'
    script = '[[tool:create_todo {"title": "sim"}]] [[say:done]]'
    directives = parse_directives(f"{quoted}\n\n{script}")
    assert directives == [
        ToolDirective(name="create_todo", args={"title": "sim"}),
        SayDirective(text="done"),
    ]


def test_a_malformed_directive_still_fails_loud():
    with pytest.raises(DirectiveError):
        parse_directives("[[tool:create_todo {bad}]]")


# --------------------------------------------------------------------------- #
# The executor brief quotes the user's request ahead of the task
# (compose_executor_brief). That quote is an echo of the script the task already
# carries, so its directives must not run a second time.
# --------------------------------------------------------------------------- #


def _executor_brief(request: str, task: str) -> str:
    """Lay the brief out as compose_executor_brief does: quote, task, intent, definition of done."""
    return (
        f"{VERBATIM_REQUEST_HEADER}\n{request}\n\n{task}\n\n"
        "Outcome the user actually wants: the scripted directives run\n"
        "Time horizon: one shot\n"
        "Nothing irreversible is approved.\n\n"
        "Definition of done (every item must be true before you finish):\n"
        "- scripted directives executed"
    )


def test_a_brief_quoting_the_request_runs_its_script_once() -> None:
    script = '[[tool:create_reminder {"title": "stretch"}]] [[say:Reminder set!]]'
    brief = _user(_executor_brief(script, script))

    assert resolve_response([brief], EXECUTOR_TOOLS) == ToolCallResponse(
        name="create_reminder", args={"title": "stretch"}
    )
    after_one = [brief, _assistant_tool_call("create_reminder"), _tool_result("create_reminder")]
    assert resolve_response(after_one, EXECUTOR_TOOLS) == SayResponse(text="Reminder set!")


def test_a_multi_paragraph_request_quote_is_skipped_whole() -> None:
    script = '[[tool:web_search {"q": "x"}]]\n\n[[tool:create_reminder {"title": "y"}]] [[say:ok]]'
    brief = _user(_executor_brief(script, script))
    emitted = [
        brief,
        _assistant_tool_call("web_search"),
        _tool_result("web_search"),
        _assistant_tool_call("create_reminder"),
        _tool_result("create_reminder"),
    ]

    assert resolve_response(emitted, EXECUTOR_TOOLS) == SayResponse(text="ok")


def _after(brief: Message, *names: str) -> list[Message]:
    turns: list[Message] = [brief]
    for name in names:
        turns += [_assistant_tool_call(name), _tool_result(name)]
    return turns


_TWICE = '[[tool:create_reminder {"title": "a"}]]\n\n[[tool:create_reminder {"title": "a"}]]'


def test_a_request_repeating_a_paragraph_under_a_different_task_keeps_both() -> None:
    """A repeated paragraph inside the request is not the task restating it."""
    task = '[[tool:web_search {"q": "x"}]] [[say:done]]'
    brief = _user(_executor_brief(_TWICE, task))

    assert resolve_response(_after(brief, "create_reminder"), EXECUTOR_TOOLS) == ToolCallResponse(
        name="create_reminder", args={"title": "a"}
    )
    assert resolve_response(
        _after(brief, "create_reminder", "create_reminder"), EXECUTOR_TOOLS
    ) == ToolCallResponse(name="web_search", args={"q": "x"})


def test_a_restated_request_repeating_a_paragraph_runs_each_once() -> None:
    script = _TWICE + " [[say:done]]"
    brief = _user(_executor_brief(script, script))

    assert resolve_response(_after(brief, "create_reminder"), EXECUTOR_TOOLS) == ToolCallResponse(
        name="create_reminder", args={"title": "a"}
    )
    assert resolve_response(
        _after(brief, "create_reminder", "create_reminder"), EXECUTOR_TOOLS
    ) == SayResponse(text="done")


# --------------------------------------------------------------------------- #
# A result handed back to a tier is re-voiced, not answered with the script again
# --------------------------------------------------------------------------- #


def _result(tag: str, body: str) -> Message:
    return _user(f"<{tag}>\n{body}\n</{tag}>\n")


def test_the_front_door_re_voices_the_executor_result_handed_to_it():
    script = '[[tool:create_reminder {"title": "x"}]] [[say:On it.]]'
    messages = [
        _user(script),
        _assistant_tool_call(CALL_EXECUTOR_TOOL, {"task": script}),
        _tool_result(CALL_EXECUTOR_TOOL),
        {"role": "assistant", "content": "On it."},
        _user("[[say:Side answer.]]"),
        {"role": "assistant", "content": "Side answer."},
        _result("executor_result", "Reminder set for 9am."),
    ]
    assert resolve_response(messages, COMMS_TOOLS) == SayResponse(text="Reminder set for 9am.")


@pytest.mark.parametrize(
    "note",
    [
        "[Background work finished. The user has not seen this result yet, so report it in "
        "your reply: Pantry stocked.]",
        "[Background work ended failed. The user has not seen this yet, so tell them in your "
        "reply: Pantry stocked.]",
    ],
)
def test_the_front_door_re_voices_the_conversation_steps_finished_work_note(note: str):
    """Regression (live test): the result was re-voiced as the newest script's say instead."""
    script = '[[tool:create_todo {"title": "x"}]] [[say:On it.]]'
    messages = [
        _user(script),
        _assistant_tool_call(CALL_EXECUTOR_TOOL, {"task": script}),
        _tool_result(CALL_EXECUTOR_TOOL),
        {"role": "assistant", "content": "On it."},
        _user("three [[say:Got all three.]]"),
        {"role": "assistant", "content": "Got all three."},
        _user(note),
    ]
    assert resolve_response(messages, COMMS_TOOLS) == SayResponse(text="Pantry stocked.")


def test_the_working_tier_re_voices_a_browser_result():
    messages = [
        _user('[[tool:web_search {"q": "x"}]] [[say:ok]]'),
        _assistant_tool_call("web_search"),
        _tool_result("web_search"),
        _result("browser_task_result", "Booked the 6pm table."),
    ]
    assert resolve_response(messages, EXECUTOR_TOOLS) == SayResponse(text="Booked the 6pm table.")


def test_a_result_older_than_the_newest_script_is_not_re_voiced():
    messages = [_result("executor_error", "it broke"), _user("[[say:fresh]]")]
    assert resolve_response(messages, COMMS_TOOLS) == SayResponse(text="fresh")


# --------------------------------------------------------------------------- #
# Fault injection
# --------------------------------------------------------------------------- #


def test_parse_fail_directive():
    assert parse_directives("[[say:part]] [[fail:boom]]") == [
        SayDirective(text="part"),
        FailDirective(message="boom"),
    ]


def test_fail_fires_only_after_every_tool_directive_ran():
    script = _user('[[tool:create_reminder {"title": "x"}]] [[say:half]] [[fail:boom]]')
    assert resolve_response([script], EXECUTOR_TOOLS) == ToolCallResponse(
        name="create_reminder", args={"title": "x"}
    )
    done = [script, _assistant_tool_call("create_reminder"), _tool_result("create_reminder")]
    assert resolve_response(done, EXECUTOR_TOOLS) == SayResponse(text="half", fail="boom")


def test_comms_fail_breaks_its_final_reply():
    script = _user("[[say:half]] [[fail:boom]]")
    assert resolve_response([script], COMMS_TOOLS) == SayResponse(text="half", fail="boom")


def test_a_failing_stream_sends_its_text_then_breaks():
    chunks = stream_chunks("m", SayResponse(text="half an answer", fail="boom"), 50)
    sent = [next(chunks) for _ in range(4)]
    with pytest.raises(ScriptedFault, match="boom"):
        next(chunks)
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in sent)
    assert text == "half an answer"


# --------------------------------------------------------------------------- #
# Timing: wait and pace
# --------------------------------------------------------------------------- #


def test_parse_wait_and_pace_directives():
    assert parse_directives("[[wait:250]] [[pace:40]] [[say:hi]]") == [
        WaitDirective(ms=250),
        PaceDirective(ms=40),
        SayDirective(text="hi"),
    ]


@pytest.mark.parametrize("bad", ["[[wait:soon]]", "[[wait:-5]]", "[[pace:]]", "[[wait:1.5]]"])
def test_a_wait_or_pace_that_is_not_a_whole_millisecond_count_raises(bad: str):
    with pytest.raises(DirectiveError):
        parse_directives(bad)


def test_a_wait_delays_only_the_tool_call_it_precedes():
    script = '[[tool:web_search {"q": "x"}]] [[wait:3000]] [[tool:create_reminder {"title": "y"}]] [[say:ok]]'
    first = [_user(script)]
    assert resolve_response(first, EXECUTOR_TOOLS) == ToolCallResponse(
        name="web_search", args={"q": "x"}
    )
    second = first + [_assistant_tool_call("web_search"), _tool_result("web_search")]
    assert resolve_response(second, EXECUTOR_TOOLS) == ToolCallResponse(
        name="create_reminder", args={"title": "y"}, delay_ms=3000
    )
    done = second + [_assistant_tool_call("create_reminder"), _tool_result("create_reminder")]
    assert resolve_response(done, EXECUTOR_TOOLS) == SayResponse(text="ok")


def test_consecutive_waits_add_up_and_a_trailing_wait_delays_the_reply():
    script = _user("[[wait:1000]] [[say:hi]] [[wait:500]]")
    assert resolve_response([script], COMMS_TOOLS) == SayResponse(text="hi", delay_ms=1500)


def test_the_front_door_forwards_at_once_and_the_executor_waits():
    script = '[[wait:2000]] [[tool:create_reminder {"title": "x"}]] [[say:Set]]'
    assert resolve_response([_user(script)], COMMS_TOOLS) == ToolCallResponse(
        name=CALL_EXECUTOR_TOOL, args={"task": script, **SCRIPTED_HAND_OFF_ARGS}
    )
    assert resolve_response([_user(script)], EXECUTOR_TOOLS) == ToolCallResponse(
        name="create_reminder", args={"title": "x"}, delay_ms=2000
    )


def test_a_tool_retrieval_never_carries_the_wait_the_tool_does():
    script = _user('[[wait:700]] [[tool:create_todo {"title": "x"}]] [[say:Done]]')
    bigtool = frozenset({"retrieve_tools"})
    retrieve = resolve_response([script], bigtool)
    assert isinstance(retrieve, ToolCallResponse)
    assert retrieve.name == "retrieve_tools"
    assert retrieve.delay_ms == 0
    retrieved = [
        script,
        _assistant_tool_call("retrieve_tools", {"exact_tool_names": ["create_todo"]}),
        _tool_result("retrieve_tools"),
    ]
    assert resolve_response(retrieved, bigtool | {"create_todo"}) == ToolCallResponse(
        name="create_todo", args={"title": "x"}, delay_ms=700
    )


def test_a_steer_s_wait_delays_the_tool_it_brings():
    messages = [
        _user('[[tool:web_search {"q": "x"}]] [[say:ok]]'),
        _assistant_tool_call("web_search"),
        _tool_result("web_search"),
        _user(
            '<user_interjection>[[wait:900]] [[tool:create_reminder {"title": "y"}]]</user_interjection>'
        ),
    ]
    assert resolve_response(messages, EXECUTOR_TOOLS) == ToolCallResponse(
        name="create_reminder", args={"title": "y"}, delay_ms=900
    )


def test_pace_sets_the_reply_s_streaming_cadence():
    assert resolve_response(
        [_user("[[pace:20]] [[say:one two three]]")], COMMS_TOOLS
    ) == SayResponse(text="one two three", pace_ms=20)


def _content_pieces(lines: list[str]) -> list[str]:
    chunks = [json.loads(line[len("data: ") :]) for line in lines if line != "data: [DONE]\n\n"]
    return [
        c["choices"][0]["delta"]["content"]
        for c in chunks
        if c["choices"] and "content" in c["choices"][0]["delta"]
    ]


def test_a_paced_reply_streams_one_word_per_chunk_spaced_by_the_pace():
    async def collect() -> tuple[list[str], float]:
        started = time.perf_counter()
        response = SayResponse(text="one two three", pace_ms=30)
        lines = [line async for line in sse_lines("m", response, 5)]
        return lines, time.perf_counter() - started

    lines, elapsed = asyncio.run(collect())
    assert _content_pieces(lines) == ["one ", "two ", "three"]
    assert elapsed >= 0.06


def test_an_unpaced_reply_streams_its_usual_pieces_without_sleeping():
    async def collect() -> tuple[list[str], float]:
        started = time.perf_counter()
        lines = [line async for line in sse_lines("m", SayResponse(text="one two three"), 5)]
        return lines, time.perf_counter() - started

    lines, elapsed = asyncio.run(collect())
    assert "".join(_content_pieces(lines)) == "one two three"
    assert elapsed < 0.05


# --------------------------------------------------------------------------- #
# Narration: text the front door streams with its hand-off, then retracts
# --------------------------------------------------------------------------- #


def test_parse_narrate_directive():
    assert parse_directives("[[narrate:On it.]] [[say:done]]") == [
        NarrateDirective(text="On it."),
        SayDirective(text="done"),
    ]


def test_the_front_door_streams_narration_with_its_hand_off():
    script = '[[pace:20]] [[narrate:On it, checking.]] [[tool:create_reminder {"title": "x"}]] [[say:Done.]]'
    assert resolve_response([_user(script)], COMMS_TOOLS) == ToolCallResponse(
        name=CALL_EXECUTOR_TOOL,
        args={"task": script, **SCRIPTED_HAND_OFF_ARGS},
        text="On it, checking.",
        pace_ms=20,
    )


def test_the_executor_never_narrates():
    script = '[[narrate:On it.]] [[tool:create_reminder {"title": "x"}]] [[say:Done.]]'
    assert resolve_response([_user(script)], EXECUTOR_TOOLS) == ToolCallResponse(
        name="create_reminder", args={"title": "x"}
    )


def test_narration_streams_word_by_word_before_the_tool_call():
    async def collect() -> list[str]:
        response = ToolCallResponse(
            name=CALL_EXECUTOR_TOOL, args={"task": "t"}, text="Let me look.", pace_ms=5
        )
        return [line async for line in sse_lines("m", response, 5)]

    lines = asyncio.run(collect())
    chunks = [json.loads(line[len("data: ") :]) for line in lines if line != "data: [DONE]\n\n"]
    deltas = [c["choices"][0]["delta"] for c in chunks if c["choices"]]
    first_call = next(i for i, d in enumerate(deltas) if d.get("tool_calls"))
    assert _content_pieces(lines) == ["Let ", "me ", "look."]
    assert all("tool_calls" not in d for d in deltas[:first_call] if "content" in d)
    assert max(i for i, d in enumerate(deltas) if "content" in d) < first_call
