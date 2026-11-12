"""The composition prompt: every placeholder filled from the pool, the constants and the day."""

from datetime import date

from app.agents.prompts.brief_composition_prompts import COMPOSITION_EXAMPLES
from app.constants.briefing import BriefAction, BriefOutcome
from app.services.briefing.composition.prompt import composition_prompt
from app.services.briefing.fact_pool.pool import FactPool, PoolContext
from app.services.briefing.fact_pool.render import context_block

_CONTEXT = PoolContext(
    reader="Ada",
    timezone="Asia/Kolkata",
    today=date(2026, 11, 11),
    calendar_events=0,
    calendar_connected=True,
    calendar_span="today",
    recent_openings=[],
)


def _pool(criteria: dict[str, str]) -> FactPool:
    return FactPool(items={}, series=[], quotes=[], goals=[], context=_CONTEXT, criteria=criteria)


class TestCompositionPrompt:
    def test_every_placeholder_is_filled_with_a_value(self) -> None:
        prompt = composition_prompt(_pool({"Gmail": "a person waiting"}), "daily", "FACTS")

        assert "None" not in prompt

    def test_the_reader_is_named_in_the_frame_and_the_brief(self) -> None:
        prompt = composition_prompt(_pool({}), "daily", "FACTS")

        assert "composing Ada's morning brief for 2026-11-11" in prompt
        assert "two minutes of Ada's attention" in prompt
        assert "Compose Ada's brief now" in prompt

    def test_each_apps_criteria_is_one_line_and_none_written_says_so(self) -> None:
        written = composition_prompt(
            _pool({"Gmail": "a person waiting", "Linear": "a blocked issue"}), "daily", "FACTS"
        )
        none_written = composition_prompt(_pool({}), "daily", "FACTS")

        assert "- Gmail: a person waiting\n- Linear: a blocked issue" in written
        assert "(no app wrote criteria)" not in written
        assert "\n- (no app wrote criteria)\n" in none_written

    def test_the_day_the_facts_and_the_examples_are_laid_in(self) -> None:
        prompt = composition_prompt(_pool({}), "daily", "THE FACTS")

        assert context_block(_CONTEXT) in prompt
        assert "THE FACTS" in prompt
        assert COMPOSITION_EXAMPLES in prompt

    def test_the_allowed_actions_and_outcomes_are_listed_in_order(self) -> None:
        prompt = composition_prompt(_pool({}), "daily", "FACTS")

        assert ", ".join(BriefAction) in prompt
        assert ", ".join(BriefOutcome) in prompt

    def test_a_weekly_brief_is_framed_as_the_week(self) -> None:
        prompt = composition_prompt(_pool({}), "weekly", "FACTS")

        assert "composing Ada's weekly digest for the week ending 2026-11-11" in prompt
