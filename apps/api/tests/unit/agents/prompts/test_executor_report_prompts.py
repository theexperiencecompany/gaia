"""The executor is taught to file the report the review checks, in general terms."""

import pytest

from app.agents.prompts.executor_report_prompts import EXECUTOR_REPORT_RULES
from app.agents.templates.agent_template import get_executor_prompt
from app.constants.agents import OutcomeState
from app.constants.task_report import FactKind

pytestmark = pytest.mark.unit

#: Situations of the report eval suites. The rules teach by their own examples, so the
#: suite keeps measuring whether the model generalises instead of recalling a case.
EVAL_SUITE_SITUATIONS = (
    "marta",
    "ruth",
    "dental",
    "lease",
    "kofi",
    "sofa",
    "toit",
    "root canal",
    "school trip",
)


class TestExecutorReportRules:
    def test_the_executor_prompt_carries_the_rules(self) -> None:
        assert EXECUTOR_REPORT_RULES in get_executor_prompt()

    @pytest.mark.parametrize("outcome", list(OutcomeState))
    def test_every_outcome_is_taught(self, outcome: OutcomeState) -> None:
        assert outcome.value in EXECUTOR_REPORT_RULES

    @pytest.mark.parametrize("kind", list(FactKind))
    def test_every_fact_kind_is_taught(self, kind: FactKind) -> None:
        assert kind.value in EXECUTOR_REPORT_RULES

    def test_the_next_question_rule_asks_for_numbers_dates_and_times(self) -> None:
        assert "next question" in EXECUTOR_REPORT_RULES
        for specific in ("amount", "date", "time"):
            assert specific in EXECUTOR_REPORT_RULES

    def test_unprompted_findings_and_own_send_exposure_are_taught(self) -> None:
        assert "unprompted true" in EXECUTOR_REPORT_RULES
        assert "private detail" in EXECUTOR_REPORT_RULES

    def test_no_eval_suite_situation_is_reused(self) -> None:
        lowered = EXECUTOR_REPORT_RULES.lower()

        assert [name for name in EVAL_SUITE_SITUATIONS if name in lowered] == []

    def test_no_em_or_en_dash_is_written_into_the_prompt(self) -> None:
        assert "—" not in EXECUTOR_REPORT_RULES
        assert "–" not in EXECUTOR_REPORT_RULES

    def test_the_old_ask_outcome_is_not_taught(self) -> None:
        assert "outcome ask" not in get_executor_prompt()
