"""The workflow assistant's finalized draft, as the parser reads it and the draft card receives it."""

import json

import pytest

from app.constants.trigger_gates import TRIGGER_GATE_CONDITION_MAX_CHARS
from app.services.workflow.subagent_output import parse_subagent_response

pytestmark = pytest.mark.unit

BILLING = "The email is from a customer and is about billing, an invoice or a refund."


def _reply(**fields: object) -> str:
    draft: dict[str, object] = {
        "type": "finalized",
        "title": "Billing replies",
        "description": "Drafts a reply to customer billing emails",
        "prompt": "1. Read the email\n2. Draft a reply in Gmail",
        "trigger_type": "integration",
        "trigger_slug": "GMAIL_NEW_GMAIL_MESSAGE",
        "integration_ids": ["gmail"],
        **fields,
    }
    return f"Here it is.\n```json\n{json.dumps(draft)}\n```"


class TestRunsOnlyWhen:
    def test_an_integration_draft_carries_its_condition_to_the_draft_card(self) -> None:
        result = parse_subagent_response(_reply(runs_only_when=BILLING))

        assert result.mode == "finalized"
        assert result.draft is not None
        assert result.draft.to_stream_payload()["workflow_draft"]["runs_only_when"] == BILLING

    @pytest.mark.parametrize("fields", [{}, {"runs_only_when": None}], ids=["omitted", "null"])
    def test_a_draft_that_wants_every_event_carries_none(self, fields: dict[str, object]) -> None:
        result = parse_subagent_response(_reply(**fields))

        assert result.mode == "finalized"
        assert result.draft is not None
        assert result.draft.to_stream_payload()["workflow_draft"]["runs_only_when"] is None

    def test_a_condition_on_a_scheduled_draft_is_sent_back_for_correction(self) -> None:
        result = parse_subagent_response(
            _reply(trigger_type="scheduled", cron_expression="0 9 * * *", runs_only_when=BILLING)
        )

        assert result.mode == "parse_error"
        assert result.parse_error is not None
        assert "runs_only_when" in result.parse_error

    def test_a_condition_longer_than_a_gate_holds_is_sent_back_for_correction(self) -> None:
        result = parse_subagent_response(
            _reply(runs_only_when="x" * (TRIGGER_GATE_CONDITION_MAX_CHARS + 1))
        )

        assert result.mode == "parse_error"
