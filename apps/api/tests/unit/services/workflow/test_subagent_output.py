"""Unit tests for ``app.services.workflow.subagent_output`` — the workflow
subagent's structured-output parser."""

from app.services.workflow.subagent_output import parse_subagent_response


def test_finalized_draft_inside_a_fence_parses() -> None:
    result = parse_subagent_response(
        'Sure! ```json\n{"type": "finalized", "title": "Morning brief", '
        '"description": "sends the brief", "prompt": "send it", '
        '"trigger_type": "manual", "direct_create": true}\n```'
    )
    assert result.mode == "finalized"
    assert result.draft is not None
    assert result.draft.title == "Morning brief"
    assert result.draft.direct_create is True


def test_scheduled_without_cron_is_a_parse_error() -> None:
    result = parse_subagent_response(
        '{"type": "finalized", "title": "T", "description": "D", "prompt": "do it", '
        '"trigger_type": "scheduled"}'
    )
    assert result.mode == "parse_error"
    assert "cron_expression" in result.parse_error


def test_integration_without_trigger_slug_is_a_parse_error() -> None:
    result = parse_subagent_response(
        '{"type": "finalized", "title": "T", "description": "D", "prompt": "do it", '
        '"trigger_type": "integration"}'
    )
    assert result.mode == "parse_error"
    assert "trigger_slug" in result.parse_error


def test_clarifying_payload_parses() -> None:
    result = parse_subagent_response('{"type": "clarifying", "message": "Which day?"}')
    assert result.mode == "clarifying"
    assert result.message == "Which day?"


def test_clarifying_without_message_falls_back_to_the_raw_reply() -> None:
    """An unvalidatable clarifying payload still asks the user the raw reply."""
    response = '{"type": "clarifying"}'
    result = parse_subagent_response(response)

    assert result.mode == "clarifying"
    assert result.message == response


def test_invalid_finalized_payload_reports_parse_error() -> None:
    result = parse_subagent_response('{"type": "finalized", "title": 5}')
    assert result.mode == "parse_error"
    assert "Invalid finalized output" in result.parse_error


def test_unrecognized_type_is_treated_as_a_message() -> None:
    result = parse_subagent_response('{"type": "something-else", "x": 1}')
    assert result.mode == "clarifying"
    assert "something-else" in result.message


def test_no_json_is_treated_as_a_message() -> None:
    result = parse_subagent_response("just a plain question")
    assert result.mode == "clarifying"
    assert result.message == "just a plain question"
    assert result.raw_response == "just a plain question"
