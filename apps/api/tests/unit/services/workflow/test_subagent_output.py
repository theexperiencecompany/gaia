"""The workflow authoring parser: one decoded JSON object into a ParseResult."""

from app.services.workflow.subagent_output import (
    FinalizedOutput,
    _result_from_payload,
)


def _finalized() -> dict[str, object]:
    return {
        "type": "finalized",
        "title": "Inbox digest",
        "description": "Summarise new mail",
        "prompt": "Read the inbox and summarise it",
        "trigger_type": "manual",
    }


def test_a_finalized_payload_becomes_a_draft() -> None:
    result = _result_from_payload(_finalized(), raw := "{}")

    assert result is not None
    assert result.mode == "finalized"
    assert result.draft is not None
    assert result.draft.title == "Inbox digest"
    assert result.raw_response == raw


def test_a_clarifying_payload_keeps_its_question() -> None:
    result = _result_from_payload({"type": "clarifying", "message": "Which inbox?"}, "{}")

    assert result is not None
    assert result.mode == "clarifying"
    assert result.message == "Which inbox?"


def test_an_unknown_payload_is_not_ours() -> None:
    assert _result_from_payload({"type": "something-else"}, "{}") is None
    assert _result_from_payload({}, "{}") is None


def test_a_broken_finalized_payload_reports_parse_error() -> None:
    result = _result_from_payload({"type": "finalized", "title": "only a title"}, "{}")

    assert result is not None
    assert result.mode == "parse_error"
    assert result.parse_error is not None


def test_a_scheduled_draft_without_cron_is_refused() -> None:
    payload = _finalized() | {"trigger_type": "scheduled"}

    result = _result_from_payload(payload, "{}")

    assert result is not None
    assert result.mode == "parse_error"
    assert "cron_expression" in (result.parse_error or "")


def test_stream_payload_names_the_draft_fields() -> None:
    draft = FinalizedOutput(
        type="finalized",
        title="Inbox digest",
        description="Summarise new mail",
        prompt="Read the inbox and summarise it",
        trigger_type="manual",
    )

    payload = draft.to_stream_payload()
    body = payload["workflow_draft"]

    assert isinstance(body, dict)
    assert body["suggested_title"] == "Inbox digest"
