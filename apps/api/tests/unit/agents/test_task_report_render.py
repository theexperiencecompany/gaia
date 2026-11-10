"""The structured report reaches comms as text: facts with their kinds, gaps, asks and failures."""

from typing import Any

import pytest

from app.agents.core.task_report import finish_task_content, render_task_report
from app.models.task_report_models import FinishTaskArgs

pytestmark = pytest.mark.unit


def _render(**fields: Any) -> str:
    return render_task_report(FinishTaskArgs.model_validate({"result": "the answer", **fields}))


class TestRenderTaskReport:
    def test_a_bare_result_is_returned_verbatim(self) -> None:
        assert _render() == "the answer"

    def test_an_empty_result_stays_empty(self) -> None:
        assert render_task_report(FinishTaskArgs.model_validate({"result": ""})) == ""

    def test_facts_are_listed_with_their_kind(self) -> None:
        text = _render(
            facts=[
                {"text": "Sent the draft.", "kind": "did", "source_call_ids": ["c1"]},
                {"text": "The vendor will confirm.", "kind": "pending_confirmation"},
                {"text": "The second invoice was not paid.", "kind": "not_done"},
            ]
        )

        assert text.startswith("the answer\n")
        assert "- did: Sent the draft." in text
        assert "- pending_confirmation: The vendor will confirm." in text
        assert "- not_done: The second invoice was not paid." in text

    def test_call_ids_stay_out_of_the_text(self) -> None:
        text = _render(facts=[{"text": "Sent it.", "kind": "did", "source_call_ids": ["call_9f"]}])

        assert "call_9f" not in text

    def test_a_fact_carries_its_time_counterparty_quote_and_unprompted_flag(self) -> None:
        text = _render(
            facts=[
                {
                    "text": "The subscription renews.",
                    "kind": "observed",
                    "time": {"at": "2026-11-20", "meaning": "due_by", "if_missed": "it lapses"},
                    "counterparty": "the publisher",
                    "quote": "renews on 20 Nov",
                    "unprompted": True,
                }
            ]
        )

        assert "due_by 2026-11-20" in text
        assert "if missed: it lapses" in text
        assert "the publisher" in text
        assert '"renews on 20 Nov"' in text
        assert "not asked for" in text

    def test_scope_gaps_are_disclosed(self) -> None:
        text = _render(scope={"covered": "the inbox", "complete": False, "gaps": ["spam folder"]})

        assert "the inbox" in text
        assert "not complete" in text
        assert "spam folder" in text

    def test_a_complete_scope_says_so(self) -> None:
        text = _render(scope={"covered": "the inbox", "complete": True, "gaps": []})

        assert "complete" in text
        assert "not complete" not in text

    def test_the_answer_recommendation_and_verdict_are_stated(self) -> None:
        text = _render(answer={"recommendation": "take the cheaper plan", "verdict": "mixed"})

        assert "take the cheaper plan" in text
        assert "mixed" in text

    def test_what_only_the_user_can_unblock_is_stated_with_its_options(self) -> None:
        text = _render(
            needs_you={
                "kind": "choose",
                "ask": "Which flight?",
                "options": [{"label": "Early", "consequence": "costs 40 more"}],
                "expires_at": "2026-11-12",
            }
        )

        assert "choose" in text
        assert "Which flight?" in text
        assert "Early: costs 40 more" in text
        assert "2026-11-12" in text

    def test_a_failure_names_its_reason_and_recovery(self) -> None:
        text = _render(
            failure={"reason": "integration_disconnected", "recovery": "needs_reconnect"}
        )

        assert "integration_disconnected" in text
        assert "needs_reconnect" in text

    def test_no_em_dashes_reach_comms(self) -> None:
        text = _render(
            facts=[{"text": "x", "kind": "did"}],
            scope={"covered": "y", "complete": False, "gaps": ["z"]},
            failure={"reason": "not_found", "recovery": "none"},
        )

        assert "—" not in text


class TestFinishTaskContent:
    def test_a_valid_report_is_rendered(self) -> None:
        text = finish_task_content(
            {"result": "ok", "outcome": "done", "facts": [{"text": "Booked.", "kind": "did"}]}
        )

        assert "- did: Booked." in text

    def test_a_malformed_report_still_delivers_the_result_text(self) -> None:
        text = finish_task_content(
            {"result": "partial notes", "facts": [{"text": "x", "kind": "guessed"}]}
        )

        assert text == "partial notes"

    def test_a_missing_result_is_no_answer(self) -> None:
        assert finish_task_content({"outcome": "done"}) == ""
