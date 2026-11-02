"""The exact words, keys and budgets behind GAIA's one LLM-written opening line.

tests/unit/services/test_first_question.py next door covers the shape of the
feature — a good draft comes back, a bad one falls back, the cache key changes
when the answers do. This module pins the *values*: the literal text handed to
the model, the literal hash the cache key is built from, the retry and timeout
budgets each caller gets, and the warning fields that are the only trace a
fallback leaves. Those are the things a reader of the code cannot check by
reading it, and the things a silent edit would otherwise change for free.

The rule throughout: assert the concrete string/number, never that a mock "was
called".
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
import pytest

from app.constants.log_tags import LogTag
from app.models.user_models import (
    OnboardingNeed,
    OnboardingPreferences,
    OnboardingSubdocument,
    StartingJobs,
    UserDocument,
)
from app.services.onboarding.first_question import (
    LIVE_QUESTION_TIMEOUT_SECONDS,
    QUESTION_PROMPT_TEMPLATE,
    QUESTION_TEMPERATURE,
    QUESTION_TIMEOUT_SECONDS,
    FirstQuestion,
    _answers_block,
    _QuestionDraft,
    answers_fingerprint,
    comms_voice_rules,
    compose_first_question,
    prewarm_first_question,
    resolve_first_question,
    seeded_chips,
)

MODULE = "app.services.onboarding.first_question"

GOOD_CHIPS = ["Find investors", "Fix my marketing", "Hire someone", "Write my pitch"]


def _prefs(
    profession: str | None = "founder",
    needs: list[OnboardingNeed] | None = None,
    other_need: str | None = None,
    language: str | None = None,
) -> OnboardingPreferences:
    return OnboardingPreferences(
        profession=profession,
        needs=needs if needs is not None else [OnboardingNeed.INBOX, OnboardingNeed.CALENDAR],
        other_need=other_need,
        language=language,
    )


#: The block ``_prefs()`` renders, spelled out. Every line of it is read by the
#: model, so the expected value is written by hand rather than derived.
DEFAULT_BLOCK = (
    "- Their job, as they answered it: founder\n"
    "- In their words: inbox out of control\n"
    "- In their words: meetings cold"
)


@pytest.mark.unit
class TestAnswersBlock:
    """The onboarding answers as the model literally reads them."""

    def test_every_answer_has_its_own_line_in_a_fixed_order(self) -> None:
        """Order is job, needs as picked, own words, then platform — the model is told this is everything it knows."""
        block = _answers_block(
            _prefs(
                profession="  Bakery owner  ",
                needs=[OnboardingNeed.CALENDAR, OnboardingNeed.INBOX],
                other_need="chasing invoices",
            ),
            "telegram",
        )

        assert block == (
            "- Their job, as they answered it: Bakery owner\n"
            "- In their words: meetings cold\n"
            "- In their words: inbox out of control\n"
            '- In their own words: "chasing invoices"\n'
            "- They already text you on telegram"
        )

    def test_the_default_answers_render_exactly(self) -> None:
        assert _answers_block(_prefs(), None) == DEFAULT_BLOCK

    @pytest.mark.parametrize("profession", ["other", "Other", "OTHER  "])
    def test_other_is_not_a_job_and_is_left_out(self, profession: str) -> None:
        """The wizard's escape hatch, not an answer — passing it on has the model write a question about being "other"."""
        block = _answers_block(_prefs(profession=profession, needs=[OnboardingNeed.INBOX]), None)

        assert block == "- In their words: inbox out of control"

    @pytest.mark.parametrize("profession", [None])
    def test_an_unanswered_job_is_left_out(self, profession: str | None) -> None:
        block = _answers_block(_prefs(profession=profession, needs=[OnboardingNeed.INBOX]), None)

        assert block == "- In their words: inbox out of control"

    def test_the_browser_language_closes_the_block_so_the_chips_are_written_in_it(self) -> None:
        block = _answers_block(_prefs(language="pt-BR"), None)

        assert block == (
            f"{DEFAULT_BLOCK}\n- Their browser language, the one the chips are written in: pt"
        )

    def test_a_platform_alone_still_renders_its_line(self) -> None:
        block = _answers_block(_prefs(profession=None, needs=[]), "whatsapp")

        assert block == "- They already text you on whatsapp"

    def test_an_empty_wizard_says_so_rather_than_sending_nothing(self) -> None:
        """An empty block leaves the prompt's "everything you know" sentence dangling, so the model invents a persona."""
        assert (
            _answers_block(_prefs(profession=None, needs=[], other_need=None), None)
            == "- Nothing. They answered nothing."
        )

    def test_their_own_words_are_quoted_verbatim(self) -> None:
        block = _answers_block(
            _prefs(profession=None, needs=[], other_need="Keep on TOP of my suppliers!"),
            None,
        )

        assert block == '- In their own words: "Keep on TOP of my suppliers!"'


@pytest.mark.unit
class TestCommsVoiceRules:
    """The voice section is sliced out of the comms prompt, never restated."""

    def test_the_slice_is_the_comms_prompts_own_voice_section_verbatim(self) -> None:
        from app.agents.prompts.comms_prompts import COMMS_AGENT_PROMPT

        start = COMMS_AGENT_PROMPT.index("## Voice")
        end = COMMS_AGENT_PROMPT.index("## Reply, react, or stay silent")

        assert comms_voice_rules() == COMMS_AGENT_PROMPT[start:end].strip()

    def test_it_starts_at_the_heading_and_stops_before_the_next_one(self) -> None:
        rules = comms_voice_rules()

        assert rules.startswith("## Voice\n")
        assert not rules.endswith("\n")
        assert "## Reply, react, or stay silent" not in rules
        assert "MATCH THEM." in rules

    def test_a_voice_section_at_the_very_start_is_still_read_whole(self) -> None:
        """The end marker is searched from just after the start marker, or the section is lost when it opens the prompt."""
        prompt = "## Voice\nbe brief\n\n## Reply, react, or stay silent\nshort"
        with patch(f"{MODULE}.COMMS_AGENT_PROMPT", prompt):
            assert comms_voice_rules() == "## Voice\nbe brief"

    def test_a_voice_section_one_character_in_is_still_read(self) -> None:
        """Guards a boundary the compiler cannot: index 1 is ordinary, not a sentinel meaning "missing"."""
        prompt = "\n## Voice\nbe brief\n\n## Reply, react, or stay silent\nshort"
        with patch(f"{MODULE}.COMMS_AGENT_PROMPT", prompt):
            assert comms_voice_rules() == "## Voice\nbe brief"

    def test_the_first_voice_heading_wins_over_a_later_mention(self) -> None:
        """Taking the last occurrence instead picks up a cross-reference further down and hands the model everything between."""
        prompt = (
            "## Voice\nbe brief\n\n## Reply, react, or stay silent\nshort\n\nsee ## Voice above"
        )
        with patch(f"{MODULE}.COMMS_AGENT_PROMPT", prompt):
            assert comms_voice_rules() == "## Voice\nbe brief"

    def test_the_closing_heading_is_looked_for_after_the_section_starts(self) -> None:
        """An earlier closing heading is not this section's end; searching from the top would return an empty slice."""
        prompt = "## Reply, react, or stay silent\nearly\n\n## Voice\nbe brief\n\n## Reply, react, or stay silent\nshort"
        with patch(f"{MODULE}.COMMS_AGENT_PROMPT", prompt):
            assert comms_voice_rules() == "## Voice\nbe brief"

    def test_the_section_stops_at_the_first_closing_heading_not_the_last(self) -> None:
        """Taking the last closing heading instead would swallow every section in between into the voice rules."""
        prompt = "## Voice\nbe brief\n\n## Reply, react, or stay silent\nshort\n\n## Reply, react, or stay silent\nagain"
        with patch(f"{MODULE}.COMMS_AGENT_PROMPT", prompt):
            assert comms_voice_rules() == "## Voice\nbe brief"

    def test_the_closing_search_starts_one_character_past_the_opening_marker(self) -> None:
        """The offset is exactly one: the end marker may begin at the very next character, so overlapping markers are used deliberately."""
        with (
            patch(f"{MODULE}._VOICE_SECTION_START", "AB"),
            patch(f"{MODULE}._VOICE_SECTION_END", "BC"),
            patch(f"{MODULE}.COMMS_AGENT_PROMPT", "ABC"),
        ):
            assert comms_voice_rules() == "A"

    def test_a_prompt_without_the_voice_heading_contributes_nothing(self) -> None:
        """A rename upstream must drop the section, not paste the whole comms prompt (or a stray tail) into the question prompt."""
        with patch(f"{MODULE}.COMMS_AGENT_PROMPT", "## Reply, react, or stay silent\nshort"):
            assert comms_voice_rules() == ""

    def test_a_prompt_without_the_following_heading_contributes_nothing(self) -> None:
        with patch(f"{MODULE}.COMMS_AGENT_PROMPT", "## Voice\nbe brief"):
            assert comms_voice_rules() == ""


@pytest.mark.unit
class TestAnswersFingerprintValue:
    """The hash IS the invalidation, so its inputs are pinned to a literal."""

    def test_the_digest_is_a_fixed_16_char_hash_of_the_three_answers(self) -> None:
        """Pinned rather than recomputed: the digest is a production cache key, and a change to it orphans every question already written."""
        fingerprint = answers_fingerprint(
            _prefs(
                profession=" Founder ",
                needs=[OnboardingNeed.INBOX, OnboardingNeed.CALENDAR],
                other_need="Chasing Invoices",
            )
        )

        assert fingerprint == "db8ff3619a26d6f8"
        assert len(fingerprint) == 16

    def test_the_browser_language_is_part_of_the_pinned_digest(self) -> None:
        """Chips are written in it, so a German and an English user must not share one."""
        assert answers_fingerprint(_prefs(language="de-DE")) == "f7002d53b1c2eaaa"

    def test_an_empty_wizard_has_its_own_stable_digest(self) -> None:
        assert answers_fingerprint(_prefs(profession=None, needs=[], other_need=None)) == (
            "68b6d7c07ea25558"
        )

    def test_casing_and_padding_are_the_same_answers_in_every_field(self) -> None:
        """The wizard round-trips free text; a stray space must not throw away a question already paid for."""
        assert answers_fingerprint(
            _prefs(profession="  FOUNDER", other_need="  CHASING invoices  ")
        ) == answers_fingerprint(_prefs(profession="founder", other_need="chasing invoices"))

    def test_the_order_the_needs_were_picked_in_is_part_of_the_answers(self) -> None:
        """The block renders needs in pick order, so two orders are different prompts and must not share one cached question."""
        assert answers_fingerprint(
            _prefs(needs=[OnboardingNeed.CALENDAR, OnboardingNeed.INBOX])
        ) != answers_fingerprint(_prefs(needs=[OnboardingNeed.INBOX, OnboardingNeed.CALENDAR]))

    @pytest.mark.parametrize(
        "changed",
        [
            {"profession": "student"},
            {"needs": [OnboardingNeed.INBOX]},
            {"needs": []},
            {"other_need": "chasing invoices"},
            {"language": "de"},
        ],
    )
    def test_changing_any_answer_changes_the_digest(self, changed: dict[str, Any]) -> None:
        assert answers_fingerprint(_prefs(**changed)) != answers_fingerprint(_prefs())


def _llm_patch(draft: Any = None, error: Exception | None = None) -> AsyncMock:
    return AsyncMock(return_value=draft, side_effect=error)


@pytest.mark.unit
class TestComposeFirstQuestionPrompt:
    """What the model is actually sent."""

    async def test_the_prompt_is_the_template_filled_with_the_voice_and_the_answers(
        self,
    ) -> None:
        """The two slots are not interchangeable: swapped, the model is told the user's answers are its voice rules."""
        invoke = _llm_patch(_QuestionDraft(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.ainvoke_structured", invoke),
        ):
            await compose_first_question(_prefs(), None)

        assert invoke.await_args.args[1] == QUESTION_PROMPT_TEMPLATE.format(
            voice=comms_voice_rules(), answers=DEFAULT_BLOCK
        )

    async def test_the_connected_platform_reaches_the_prompt(self) -> None:
        invoke = _llm_patch(_QuestionDraft(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.ainvoke_structured", invoke),
        ):
            await compose_first_question(_prefs(), "telegram")

        assert invoke.await_args.args[1] == QUESTION_PROMPT_TEMPLATE.format(
            voice=comms_voice_rules(),
            answers=DEFAULT_BLOCK + "\n- They already text you on telegram",
        )

    async def test_the_call_runs_the_draft_schema_on_the_cheap_lane(self) -> None:
        """The schema IS the validation: the call must ask for _QuestionDraft."""
        invoke = _llm_patch(_QuestionDraft(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.ainvoke_structured", invoke),
        ):
            await compose_first_question(_prefs(), None, user_id="u1")

        assert invoke.await_args.args[0] is _QuestionDraft
        assert invoke.await_args.kwargs["options"].temperature == QUESTION_TEMPERATURE
        assert QUESTION_TEMPERATURE == 0.4
        assert invoke.await_args.kwargs["label"] == "onboarding_first_question"

    async def test_a_user_id_attributes_the_spend_to_that_user(self) -> None:
        """The call is auxiliary COGS: unattributed, it lands on nobody."""
        invoke = _llm_patch(_QuestionDraft(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.ainvoke_structured", invoke),
        ):
            await compose_first_question(_prefs(), None, user_id="u1")

        expected = {"configurable": {"user_id": "u1"}}
        assert invoke.await_args.kwargs["config"] == expected

    @pytest.mark.parametrize("user_id", [None, ""])
    async def test_without_a_user_id_no_config_is_invented(self, user_id: str | None) -> None:
        invoke = _llm_patch(_QuestionDraft(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.ainvoke_structured", invoke),
        ):
            await compose_first_question(_prefs(), None, user_id=user_id)

        assert invoke.await_args.kwargs["config"] is None


@pytest.mark.unit
class TestComposeFirstQuestionBudget:
    """Nobody waits on the prewarm; the user waits on the live call."""

    @pytest.mark.parametrize(
        ("timeout_seconds", "expected_attempts"),
        [
            (QUESTION_TIMEOUT_SECONDS, 2),
            (20.0, 2),
            (LIVE_QUESTION_TIMEOUT_SECONDS, 1),
            (QUESTION_TIMEOUT_SECONDS - 0.1, 1),
        ],
    )
    async def test_only_a_call_nobody_waits_on_may_retry(
        self, timeout_seconds: float, expected_attempts: int
    ) -> None:
        """At the prewarm's ceiling a second attempt fits; under it a retry would cost the user the same wait twice."""
        invoke = _llm_patch(_QuestionDraft(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.ainvoke_structured", invoke),
        ):
            await compose_first_question(_prefs(), None, timeout_seconds=timeout_seconds)

        options = invoke.await_args.kwargs["options"]
        assert options.max_attempts == expected_attempts
        assert options.timeout == timeout_seconds

    async def test_the_default_ceiling_is_the_prewarms_twenty_seconds(self) -> None:
        invoke = _llm_patch(_QuestionDraft(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.ainvoke_structured", invoke),
        ):
            await compose_first_question(_prefs(), None)

        assert QUESTION_TIMEOUT_SECONDS == 20.0
        assert LIVE_QUESTION_TIMEOUT_SECONDS == 6.0
        assert invoke.await_args.kwargs["options"].timeout == 20.0


@pytest.mark.unit
class TestComposeFirstQuestionDraft:
    """What comes back out."""

    async def test_the_drafts_words_are_returned_trimmed(self) -> None:
        """Model output routinely carries leading newlines, which render as blank lines and padded chip labels."""
        invoke = _llm_patch(_QuestionDraft(chips=[f" {c} \n" for c in GOOD_CHIPS]))
        with (
            patch(f"{MODULE}.ainvoke_structured", invoke),
        ):
            result = await compose_first_question(_prefs(), None)

        assert result == FirstQuestion(chips=GOOD_CHIPS)

    def test_anything_but_four_chips_is_rejected_by_the_schema(self) -> None:
        """Four jobs is the contract with the thread; the schema is the check."""
        with pytest.raises(ValidationError):
            _QuestionDraft(chips=["Find investors", "Fix my marketing", "Hire someone"])
        with pytest.raises(ValidationError):
            _QuestionDraft(chips=GOOD_CHIPS + ["Ship it"])

    @pytest.mark.parametrize(
        "error",
        [TimeoutError(), RuntimeError("provider exploded"), ValueError("not valid json")],
    )
    async def test_a_failed_call_yields_no_question_at_all(self, error: Exception) -> None:
        """Not a fallback question: the caller composes the static line; a placeholder here would ship as the user's first sentence."""
        invoke = _llm_patch(error=error)
        with (
            patch(f"{MODULE}.ainvoke_structured", invoke),
        ):
            assert await compose_first_question(_prefs(), None) is None

    async def test_the_fallback_records_why_and_how_long_it_waited(self) -> None:
        """A fallback is silent in the product; log.warning writes message and kwargs into warnings[] (wide_events.py) as the only trace."""
        invoke = _llm_patch(error=TimeoutError())
        clock = MagicMock()
        clock.monotonic.side_effect = [1.0, 1.0005678]
        with (
            patch(f"{MODULE}.ainvoke_structured", invoke),
            patch(f"{MODULE}.time", clock),
            patch(f"{MODULE}.log") as mock_log,
        ):
            assert await compose_first_question(_prefs(), None) is None

        mock_log.warning.assert_called_once_with(
            f"{LogTag.ONBOARDING} first question fell back",
            outcome="fallback",
            reason="TimeoutError",
            duration_s=0.001,
        )


def _repository(stored: StartingJobs | None = None) -> MagicMock:
    """Build a users repository whose user holds stored as their drafted jobs."""
    repository = MagicMock()
    repository.get = AsyncMock(
        return_value=UserDocument(id="u1", onboarding=OnboardingSubdocument(starting_jobs=stored))
    )
    repository.set_starting_jobs = AsyncMock()
    return repository


def _stored(preferences: OnboardingPreferences | None = None) -> StartingJobs:
    return StartingJobs(
        answers_fingerprint=answers_fingerprint(preferences or _prefs()), chips=GOOD_CHIPS
    )


@pytest.mark.unit
class TestSeededChips:
    """The one reader of the drafted jobs: paywall preview, welcome thread and first-chat guidance."""

    async def test_the_jobs_drafted_from_these_answers_are_returned(self) -> None:
        repository = _repository(_stored())
        with patch(f"{MODULE}.user_repository", repository):
            assert await seeded_chips("u1", _prefs()) == GOOD_CHIPS

        repository.get.assert_awaited_once_with("u1")

    async def test_jobs_drafted_from_other_answers_are_not_served(self) -> None:
        """A user who went back and re-answered must not see the old answers' jobs."""
        with patch(f"{MODULE}.user_repository", _repository(_stored(_prefs(profession="student")))):
            assert await seeded_chips("u1", _prefs()) == []

    async def test_no_drafted_jobs_yet_is_an_empty_list(self) -> None:
        with patch(f"{MODULE}.user_repository", _repository(None)):
            assert await seeded_chips("u1", _prefs()) == []

    async def test_a_user_that_is_gone_has_no_jobs(self) -> None:
        repository = _repository()
        repository.get = AsyncMock(return_value=None)
        with patch(f"{MODULE}.user_repository", repository):
            assert await seeded_chips("u1", _prefs()) == []


@pytest.mark.unit
class TestPrewarmWrites:
    """The jobs drafted while the user is still clicking, stored on their record."""

    async def test_the_jobs_are_stored_under_the_answers_they_were_written_from(self) -> None:
        repository = _repository()
        compose = AsyncMock(return_value=FirstQuestion(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.compose_first_question", compose),
            patch(f"{MODULE}.user_repository", repository),
        ):
            await prewarm_first_question("u1", _prefs(), "telegram")

        repository.set_starting_jobs.assert_awaited_once_with("u1", _stored())
        assert compose.await_args.args == (_prefs(), "telegram")
        assert compose.await_args.kwargs == {"user_id": "u1"}

    async def test_a_miss_stores_nothing(self) -> None:
        """An empty entry would read as drafted jobs and suppress the one live attempt."""
        repository = _repository()
        with (
            patch(f"{MODULE}.compose_first_question", AsyncMock(return_value=None)),
            patch(f"{MODULE}.user_repository", repository),
        ):
            await prewarm_first_question("u1", _prefs(), None)

        repository.set_starting_jobs.assert_not_awaited()

    async def test_a_detached_failure_is_recorded_and_never_raised(self) -> None:
        """Runs off the request that saved the answers, so it can't raise; the message is truncated so a traceback can't leak a connection string."""
        with (
            patch(
                f"{MODULE}.compose_first_question",
                AsyncMock(side_effect=RuntimeError("x" * 300)),
            ),
            patch(f"{MODULE}.log") as mock_log,
        ):
            await prewarm_first_question("u1", _prefs(), None)

        mock_log.warning.assert_called_once_with(
            f"{LogTag.ONBOARDING} first question prewarm failed",
            user_id="u1",
            error="x" * 200,
            error_type="RuntimeError",
        )

    async def test_a_failed_store_does_not_escape_either(self) -> None:
        repository = _repository()
        repository.set_starting_jobs = AsyncMock(side_effect=ConnectionError("down"))
        with (
            patch(
                f"{MODULE}.compose_first_question",
                AsyncMock(return_value=FirstQuestion(chips=GOOD_CHIPS)),
            ),
            patch(f"{MODULE}.user_repository", repository),
            patch(f"{MODULE}.log") as mock_log,
        ):
            await prewarm_first_question("u1", _prefs(), None)

        assert mock_log.warning.call_args.kwargs["error_type"] == "ConnectionError"


@pytest.mark.unit
class TestResolveBranches:
    """Stored, else one short live attempt that is stored too, else no chips."""

    async def test_stored_jobs_cost_no_model_call(self) -> None:
        compose = AsyncMock()
        with (
            patch(f"{MODULE}.user_repository", _repository(_stored())),
            patch(f"{MODULE}.compose_first_question", compose),
        ):
            result = await resolve_first_question("u1", _prefs(), "telegram")

        assert result == FirstQuestion(chips=GOOD_CHIPS)
        compose.assert_not_awaited()

    async def test_a_miss_gets_one_live_attempt_on_the_six_second_ceiling_and_stores_it(
        self,
    ) -> None:
        """The user is watching a spinner, so this is a last chance; stored so the guidance and paywall see the same jobs."""
        written = FirstQuestion(chips=GOOD_CHIPS)
        compose = AsyncMock(return_value=written)
        repository = _repository(None)
        with (
            patch(f"{MODULE}.user_repository", repository),
            patch(f"{MODULE}.compose_first_question", compose),
        ):
            result = await resolve_first_question("u1", _prefs(), "telegram")

        assert result is written
        assert compose.await_args.args == (_prefs(), "telegram")
        assert compose.await_args.kwargs == {
            "user_id": "u1",
            "timeout_seconds": LIVE_QUESTION_TIMEOUT_SECONDS,
        }
        assert LIVE_QUESTION_TIMEOUT_SECONDS == 6.0
        repository.set_starting_jobs.assert_awaited_once_with("u1", _stored())

    async def test_a_miss_whose_live_call_misses_too_is_no_chips_and_a_warning(self) -> None:
        repository = _repository(None)
        with (
            patch(f"{MODULE}.user_repository", repository),
            patch(f"{MODULE}.compose_first_question", AsyncMock(return_value=None)),
            patch(f"{MODULE}.log") as log,
        ):
            assert await resolve_first_question("u1", _prefs(), None) is None

        repository.set_starting_jobs.assert_not_awaited()
        log.warning.assert_called_once()
        assert "first question missed" in log.warning.call_args.args[0]
        assert log.warning.call_args.kwargs == {"user_id": "u1", "outcome": "fallback"}
