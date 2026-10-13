"""The workflow assistant's reply, parsed into a draft, a question, or a parse error."""

import json

from app.constants.workflows import WorkflowDelivery
from app.services.workflow.subagent_output import FinalizedOutput, parse_subagent_response

FINALIZED = {
    "type": "finalized",
    "title": "Morning digest",
    "description": "Summarise my inbox",
    "prompt": "Summarise my unread mail",
    "trigger_type": "manual",
}


def _fenced(payload: object) -> str:
    return f"Here it is:\n```json\n{json.dumps(payload)}\n```"


def test_a_finalized_payload_becomes_a_draft() -> None:
    result = parse_subagent_response(_fenced(FINALIZED))

    assert result.mode == "finalized"
    assert result.draft is not None
    assert (result.draft.title, result.draft.prompt) == (
        "Morning digest",
        "Summarise my unread mail",
    )


def test_an_invalid_finalized_payload_is_a_parse_error() -> None:
    result = parse_subagent_response(_fenced({"type": "finalized", "title": "No prompt"}))

    assert result.mode == "parse_error"
    assert result.parse_error is not None
    assert result.parse_error.startswith("Invalid finalized output:")


def test_a_clarifying_payload_carries_its_question() -> None:
    reply = _fenced({"type": "clarifying", "message": "Which inbox?"})

    result = parse_subagent_response(reply)

    assert (result.mode, result.message, result.raw_response) == (
        "clarifying",
        "Which inbox?",
        reply,
    )


def test_a_clarifying_payload_without_a_question_asks_with_the_whole_reply() -> None:
    reply = _fenced({"type": "clarifying", "message": 42})

    result = parse_subagent_response(reply)

    assert (result.mode, result.message, result.raw_response) == ("clarifying", reply, reply)


def test_a_payload_of_another_type_is_not_ours() -> None:
    reply = _fenced({"type": "something_else"})

    result = parse_subagent_response(reply)

    assert (result.mode, result.message) == ("clarifying", reply)


def test_the_stream_payload_carries_the_agents_delivery() -> None:
    draft = FinalizedOutput.model_validate(FINALIZED)

    frame = draft.to_stream_payload(WorkflowDelivery.BRIEF)

    assert frame["workflow_draft"]["delivery"] == "brief"
    assert frame["workflow_draft"]["suggested_title"] == "Morning digest"
