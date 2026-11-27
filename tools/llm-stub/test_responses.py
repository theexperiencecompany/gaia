"""The stub's OpenAI Responses API: create_artifact's model call, scripted from its input.

Pure stdlib + pytest, like test_directives.py:

    uv run --no-project --with pytest pytest tools/llm-stub -q
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from directives import (
    DEFAULT_REPLY,
    DirectiveError,
    SayResponse,
    parse_responses_request,
    resolve_text_response,
)
from responses_wire import build_response, response_sse_lines, stream_events
from wire import ScriptedFault

PROGRAM = 'root = Artifact("Launch", "Week one", [], [])'


def _artifact_body(brief: str, *, stream: bool = True) -> dict[str, object]:
    """Build the body generate_reply sends: the artifact prompt as instructions, the brief as input."""
    return {
        "model": "gpt-6-luna",
        "instructions": "Write an OpenUI program. [[say:never a script]]",
        "input": brief,
        "reasoning": {"effort": "none"},
        "max_output_tokens": 16000,
        "prompt_cache_key": "artifact-openui-dashboard",
        "stream": stream,
    }


def test_a_brief_scripts_the_program_and_the_instructions_never_do() -> None:
    parsed = parse_responses_request(_artifact_body(f"Sign-ups 1,840. [[say:{PROGRAM}]]"))

    assert parsed.stream is True
    assert resolve_text_response(parsed.messages, parsed.available_tools) == SayResponse(PROGRAM)


def test_an_unscripted_brief_gets_the_canned_reply() -> None:
    parsed = parse_responses_request(_artifact_body("Sign-ups 1,840."))

    assert resolve_text_response(parsed.messages) == SayResponse(DEFAULT_REPLY)


def test_message_items_are_read_as_their_text_parts() -> None:
    body = {
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "[[say:from parts]]"}]},
        ]
    }

    parsed = parse_responses_request(body)

    assert parsed.messages == [{"role": "user", "content": "[[say:from parts]]"}]
    assert parsed.stream is False


def test_a_scripted_tool_call_fails_loud() -> None:
    parsed = parse_responses_request(_artifact_body('[[tool:web_search {"q": "x"}]]'))

    with pytest.raises(DirectiveError, match="say/fail only"):
        resolve_text_response(parsed.messages)


def test_a_streamed_reply_is_text_deltas_then_completed_with_usage() -> None:
    events = list(stream_events("gpt-6-luna", SayResponse(PROGRAM), 40))

    assert [e["type"] for e in events] == [
        "response.created",
        *["response.output_text.delta"] * (len(events) - 2),
        "response.completed",
    ]
    deltas = [e for e in events if e["type"] == "response.output_text.delta"]
    assert "".join(e["delta"] for e in deltas) == PROGRAM
    assert [e["sequence_number"] for e in events] == list(range(len(events)))
    completed = events[-1]["response"]
    assert completed["status"] == "completed"
    assert completed["output"][0]["content"][0] == {
        "type": "output_text",
        "text": PROGRAM,
        "annotations": [],
        "logprobs": [],
    }
    assert completed["usage"]["input_tokens"] == 40
    assert completed["usage"]["output_tokens"] > 0
    assert completed["usage"]["input_tokens_details"] == {"cached_tokens": 0}
    assert completed["usage"]["output_tokens_details"] == {"reasoning_tokens": 0}


def test_each_sse_event_names_its_type() -> None:
    lines = list(response_sse_lines("m", SayResponse("hi"), 1))

    assert lines[0].startswith("event: response.created\ndata: {")
    assert lines[-1].startswith("event: response.completed\ndata: {")
    assert all(line.endswith("\n\n") for line in lines)


def test_a_failing_stream_sends_its_text_then_breaks() -> None:
    events = stream_events("m", SayResponse("half a program", fail="boom"), 1)
    sent = [next(events) for _ in range(4)]

    with pytest.raises(ScriptedFault, match="boom"):
        next(events)
    assert "".join(e.get("delta", "") for e in sent) == "half a program"


def test_a_non_streamed_reply_is_one_completed_message() -> None:
    payload = build_response("m", SayResponse("hi"), 5)

    assert payload["object"] == "response"
    assert payload["status"] == "completed"
    assert payload["output"][0]["content"][0]["text"] == "hi"
    assert payload["usage"]["total_tokens"] == 6
