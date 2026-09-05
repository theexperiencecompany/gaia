"""The exact words, keys and budgets behind GAIA's one LLM-written opening line.

``tests/unit/services/test_first_question.py`` next door covers the shape of the
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

from app.constants.cache import FIRST_QUESTION_CACHE_TTL
from app.constants.log_tags import LogTag
from app.models.user_models import OnboardingNeed, OnboardingPreferences
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
    first_question_cache_key,
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
) -> OnboardingPreferences:
    return OnboardingPreferences(
        profession=profession,
        needs=needs if needs is not None else [OnboardingNeed.INBOX, OnboardingNeed.CALENDAR],
        other_need=other_need,
    )


#: The block ``_prefs()`` renders, spelled out. Every line of it is read by the
#: model, so the expected value is written by hand rather than derived.
DEFAULT_BLOCK = (
    "- Their job, as they answered it: founder\n"
    "- I'm drowning in email\n"
    "- my week is back-to-back meetings"
)


@pytest.mark.unit
class TestAnswersBlock:
    """The onboarding answers as the model literally reads them."""

    def test_every_answer_has_its_own_line_in_a_fixed_order(self) -> None:
        """Job, then needs in the order they were picked, then their own words,
        then the platform. The model is told this is everything it knows, so a
        dropped or reordered line changes what it writes."""
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
            "- my week is back-to-back meetings\n"
            "- I'm drowning in email\n"
            '- In their own words: "chasing invoices"\n'
            "- They already text you on telegram"
        )

    def test_the_default_answers_render_exactly(self) -> None:
        assert _answers_block(_prefs(), None) == DEFAULT_BLOCK

    @pytest.mark.parametrize("profession", ["other", "Other", "OTHER  "])
    def test_other_is_not_a_job_and_is_left_out(self, profession: str) -> None:
        """The wizard's escape hatch, not an answer. Passing it on would have
        the model write a question about being an "other"."""
        block = _answers_block(_prefs(profession=profession, needs=[OnboardingNeed.INBOX]), None)

        assert block == "- I'm drowning in email"

    @pytest.mark.parametrize("profession", [None])
    def test_an_unanswered_job_is_left_out(self, profession: str | None) -> None:
        block = _answers_block(_prefs(profession=profession, needs=[OnboardingNeed.INBOX]), None)

        assert block == "- I'm drowning in email"

    def test_a_platform_alone_still_renders_its_line(self) -> None:
        block = _answers_block(_prefs(profession=None, needs=[]), "whatsapp")

        assert block == "- They already text you on whatsapp"

    def test_an_empty_wizard_says_so_rather_than_sending_nothing(self) -> None:
        """An empty block would leave the prompt's "this is everything you know"
        sentence dangling, and the model invents a persona to fill it."""
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
        end = COMMS_AGENT_PROMPT.index("## Length Modes")

        assert comms_voice_rules() == COMMS_AGENT_PROMPT[start:end].strip()

    def test_it_starts_at_the_heading_and_stops_before_the_next_one(self) -> None:
        rules = comms_voice_rules()

        assert rules.startswith("## Voice\n")
        assert not rules.endswith("\n")
        assert "## Length Modes" not in rules
        assert "TONE MIRRORING" in rules

    def test_a_voice_section_at_the_very_start_is_still_read_whole(self) -> None:
        """The end marker is searched from just after the start marker. Searching
        from anywhere earlier or later loses the section when it opens the
        prompt, which is exactly where a rewrite would put it."""
        prompt = "## Voice\nbe brief\n\n## Length Modes\nshort"
        with patch(f"{MODULE}.COMMS_AGENT_PROMPT", prompt):
            assert comms_voice_rules() == "## Voice\nbe brief"

    def test_a_voice_section_one_character_in_is_still_read(self) -> None:
        """Guards a boundary the compiler cannot: index 1 is an ordinary
        position, not a sentinel meaning "missing"."""
        prompt = "\n## Voice\nbe brief\n\n## Length Modes\nshort"
        with patch(f"{MODULE}.COMMS_AGENT_PROMPT", prompt):
            assert comms_voice_rules() == "## Voice\nbe brief"

    def test_the_first_voice_heading_wins_over_a_later_mention(self) -> None:
        """The section is the one that opens the voice rules. Taking the last
        occurrence instead picks up a cross-reference further down the prompt
        and hands the model everything between them — or nothing."""
        prompt = "## Voice\nbe brief\n\n## Length Modes\nshort\n\nsee ## Voice above"
        with patch(f"{MODULE}.COMMS_AGENT_PROMPT", prompt):
            assert comms_voice_rules() == "## Voice\nbe brief"

    def test_the_closing_heading_is_looked_for_after_the_section_starts(self) -> None:
        """A "## Length Modes" earlier in the prompt is not this section's end;
        searching from the top would find it and return an empty slice."""
        prompt = "## Length Modes\nearly\n\n## Voice\nbe brief\n\n## Length Modes\nshort"
        with patch(f"{MODULE}.COMMS_AGENT_PROMPT", prompt):
            assert comms_voice_rules() == "## Voice\nbe brief"

    def test_the_section_stops_at_the_first_closing_heading_not_the_last(self) -> None:
        """Taking the last one swallows every section in between into the voice
        rules."""
        prompt = "## Voice\nbe brief\n\n## Length Modes\nshort\n\n## Length Modes\nagain"
        with patch(f"{MODULE}.COMMS_AGENT_PROMPT", prompt):
            assert comms_voice_rules() == "## Voice\nbe brief"

    def test_the_closing_search_starts_one_character_past_the_opening_marker(self) -> None:
        """The offset is exactly one: the end marker may begin at the very next
        character. Markers that overlap by a character are the only way to see
        this, so they are used deliberately rather than the real headings."""
        with (
            patch(f"{MODULE}._VOICE_SECTION_START", "AB"),
            patch(f"{MODULE}._VOICE_SECTION_END", "BC"),
            patch(f"{MODULE}.COMMS_AGENT_PROMPT", "ABC"),
        ):
            assert comms_voice_rules() == "A"

    def test_a_prompt_without_the_voice_heading_contributes_nothing(self) -> None:
        """A rename upstream must drop the section, not paste the whole comms
        prompt (or a stray tail of it) into the question prompt."""
        with patch(f"{MODULE}.COMMS_AGENT_PROMPT", "## Length Modes\nshort"):
            assert comms_voice_rules() == ""

    def test_a_prompt_without_the_following_heading_contributes_nothing(self) -> None:
        with patch(f"{MODULE}.COMMS_AGENT_PROMPT", "## Voice\nbe brief"):
            assert comms_voice_rules() == ""


@pytest.mark.unit
class TestAnswersFingerprintValue:
    """The hash IS the invalidation, so its inputs are pinned to a literal."""

    def test_the_digest_is_a_fixed_16_char_hash_of_the_three_answers(self) -> None:
        """Pinned rather than recomputed: the digest is a cache key in
        production, and a change to what goes into it (or how much of it is
        kept) silently orphans every question already written."""
        fingerprint = answers_fingerprint(
            _prefs(
                profession=" Founder ",
                needs=[OnboardingNeed.INBOX, OnboardingNeed.CALENDAR],
                other_need="Chasing Invoices",
            )
        )

        assert fingerprint == "db8ff3619a26d6f8"
        assert len(fingerprint) == 16

    def test_an_empty_wizard_has_its_own_stable_digest(self) -> None:
        assert answers_fingerprint(_prefs(profession=None, needs=[], other_need=None)) == (
            "68b6d7c07ea25558"
        )

    def test_casing_and_padding_are_the_same_answers_in_every_field(self) -> None:
        """The wizard round-trips free text; a stray space must not throw away a
        question that was already paid for."""
        assert answers_fingerprint(
            _prefs(profession="  FOUNDER", other_need="  CHASING invoices  ")
        ) == answers_fingerprint(_prefs(profession="founder", other_need="chasing invoices"))

    def test_the_order_the_needs_were_picked_in_is_part_of_the_answers(self) -> None:
        """The block renders needs in pick order, so two orders are two different
        prompts and must not share one cached question."""
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
        ],
    )
    def test_changing_any_answer_changes_the_digest(self, changed: dict[str, Any]) -> None:
        assert answers_fingerprint(_prefs(**changed)) != answers_fingerprint(_prefs())

    def test_the_cache_key_is_the_prefix_the_user_and_the_digest(self) -> None:
        assert first_question_cache_key("u1", _prefs()) == (
            "onboarding:first_question:u1:4e49aea28b02740d"
        )


def _llm_patches(draft: Any = None, error: Exception | None = None) -> tuple[Any, Any]:
    runnable = MagicMock(name="structured_runnable")
    invoke = AsyncMock(return_value=draft, side_effect=error)
    return runnable, invoke


@pytest.mark.unit
class TestComposeFirstQuestionPrompt:
    """What the model is actually sent."""

    async def test_the_prompt_is_the_template_filled_with_the_voice_and_the_answers(
        self,
    ) -> None:
        """The two slots are not interchangeable: swapped, the model is told the
        user's answers are its voice rules."""
        runnable, invoke = _llm_patches(_QuestionDraft(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.background_structured_runnable", return_value=runnable),
            patch(f"{MODULE}.ainvoke_llm", invoke),
        ):
            await compose_first_question(_prefs(), None)

        assert invoke.await_args.args[1] == QUESTION_PROMPT_TEMPLATE.format(
            voice=comms_voice_rules(), answers=DEFAULT_BLOCK
        )

    async def test_the_connected_platform_reaches_the_prompt(self) -> None:
        runnable, invoke = _llm_patches(_QuestionDraft(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.background_structured_runnable", return_value=runnable),
            patch(f"{MODULE}.ainvoke_llm", invoke),
        ):
            await compose_first_question(_prefs(), "telegram")

        assert invoke.await_args.args[1] == QUESTION_PROMPT_TEMPLATE.format(
            voice=comms_voice_rules(),
            answers=DEFAULT_BLOCK + "\n- They already text you on telegram",
        )

    async def test_the_call_runs_the_draft_schema_on_the_cheap_lane(self) -> None:
        """The schema IS the validation, so the runnable must be built from
        ``_QuestionDraft`` — and it is that runnable, not another, that is
        invoked."""
        runnable, invoke = _llm_patches(_QuestionDraft(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.background_structured_runnable", return_value=runnable) as build,
            patch(f"{MODULE}.ainvoke_llm", invoke),
        ):
            await compose_first_question(_prefs(), None, user_id="u1")

        assert build.call_args.args == (_QuestionDraft,)
        assert build.call_args.kwargs["temperature"] == QUESTION_TEMPERATURE
        assert QUESTION_TEMPERATURE == 0.4
        assert invoke.await_args.args[0] is runnable
        assert invoke.await_args.kwargs["label"] == "onboarding_first_question"

    async def test_a_user_id_attributes_the_spend_to_that_user(self) -> None:
        """The call is auxiliary COGS: unattributed, it lands on nobody."""
        runnable, invoke = _llm_patches(_QuestionDraft(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.background_structured_runnable", return_value=runnable) as build,
            patch(f"{MODULE}.ainvoke_llm", invoke),
        ):
            await compose_first_question(_prefs(), None, user_id="u1")

        expected = {"configurable": {"user_id": "u1"}}
        assert build.call_args.kwargs["config"] == expected
        assert invoke.await_args.kwargs["config"] == expected

    @pytest.mark.parametrize("user_id", [None, ""])
    async def test_without_a_user_id_no_config_is_invented(self, user_id: str | None) -> None:
        runnable, invoke = _llm_patches(_QuestionDraft(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.background_structured_runnable", return_value=runnable) as build,
            patch(f"{MODULE}.ainvoke_llm", invoke),
        ):
            await compose_first_question(_prefs(), None, user_id=user_id)

        assert build.call_args.kwargs["config"] is None
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
        """At the prewarm's ceiling a second attempt fits; under it a retry plus
        backoff cannot, and a second timeout costs the user the same wait
        twice."""
        runnable, invoke = _llm_patches(_QuestionDraft(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.background_structured_runnable", return_value=runnable),
            patch(f"{MODULE}.ainvoke_llm", invoke),
        ):
            await compose_first_question(_prefs(), None, timeout_seconds=timeout_seconds)

        options = invoke.await_args.kwargs["options"]
        assert options.max_attempts == expected_attempts
        assert options.timeout == timeout_seconds

    async def test_the_default_ceiling_is_the_prewarms_twenty_seconds(self) -> None:
        runnable, invoke = _llm_patches(_QuestionDraft(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.background_structured_runnable", return_value=runnable),
            patch(f"{MODULE}.ainvoke_llm", invoke),
        ):
            await compose_first_question(_prefs(), None)

        assert QUESTION_TIMEOUT_SECONDS == 20.0
        assert LIVE_QUESTION_TIMEOUT_SECONDS == 2.0
        assert invoke.await_args.kwargs["options"].timeout == 20.0


@pytest.mark.unit
class TestComposeFirstQuestionDraft:
    """What comes back out."""

    async def test_the_drafts_words_are_returned_trimmed(self) -> None:
        """Model output routinely carries leading newlines; those render as blank
        lines in the chat bubble and as padded chip labels."""
        runnable, invoke = _llm_patches(_QuestionDraft(chips=[f" {c} \n" for c in GOOD_CHIPS]))
        with (
            patch(f"{MODULE}.background_structured_runnable", return_value=runnable),
            patch(f"{MODULE}.ainvoke_llm", invoke),
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
        """Not a fallback question: the caller composes the static line, and a
        placeholder here would ship as the first sentence a user ever reads."""
        runnable, invoke = _llm_patches(error=error)
        with (
            patch(f"{MODULE}.background_structured_runnable", return_value=runnable),
            patch(f"{MODULE}.ainvoke_llm", invoke),
        ):
            assert await compose_first_question(_prefs(), None) is None

    async def test_the_fallback_records_why_and_how_long_it_waited(self) -> None:
        """A fallback is silent in the product, so the wide event is the only
        trace. ``log.warning`` writes message and kwargs into ``warnings[]``
        (libs/shared/py/wide_events.py), which makes both a queryable surface:
        without ``reason`` a timeout is indistinguishable from a bad key."""
        runnable, invoke = _llm_patches(error=TimeoutError())
        clock = MagicMock()
        clock.monotonic.side_effect = [1.0, 1.0005678]
        with (
            patch(f"{MODULE}.background_structured_runnable", return_value=runnable),
            patch(f"{MODULE}.ainvoke_llm", invoke),
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


@pytest.mark.unit
class TestPrewarmWrites:
    """The question written while the user is still clicking."""

    async def test_the_question_is_written_under_this_users_answers_with_a_ttl(self) -> None:
        """Two hours: long enough to survive a wizard someone walks away from,
        short enough that a stale question is never served after a re-answer."""
        written = FirstQuestion(chips=GOOD_CHIPS)
        setter = AsyncMock()
        compose = AsyncMock(return_value=written)
        with (
            patch(f"{MODULE}.compose_first_question", compose),
            patch(f"{MODULE}.redis_cache.set", setter),
        ):
            await prewarm_first_question("u1", _prefs(), "telegram")

        assert setter.await_args.args == (first_question_cache_key("u1", _prefs()), written)
        assert setter.await_args.kwargs == {
            "ttl": FIRST_QUESTION_CACHE_TTL,
            "model": FirstQuestion,
        }
        assert FIRST_QUESTION_CACHE_TTL == 7200

    async def test_the_prewarm_composes_for_this_user_on_the_generous_ceiling(self) -> None:
        """Nobody is waiting, so it takes the default 8s budget — and it passes
        the user id, or the prewarm's spend lands on nobody."""
        setter = AsyncMock()
        compose = AsyncMock(return_value=FirstQuestion(chips=GOOD_CHIPS))
        with (
            patch(f"{MODULE}.compose_first_question", compose),
            patch(f"{MODULE}.redis_cache.set", setter),
        ):
            await prewarm_first_question("u1", _prefs(), "telegram")

        assert compose.await_args.args == (_prefs(), "telegram")
        assert compose.await_args.kwargs == {"user_id": "u1"}

    async def test_a_miss_writes_nothing(self) -> None:
        """An empty entry would be read as a hit at completion and suppress the
        one live attempt."""
        setter = AsyncMock()
        with (
            patch(f"{MODULE}.compose_first_question", AsyncMock(return_value=None)),
            patch(f"{MODULE}.redis_cache.set", setter),
        ):
            await prewarm_first_question("u1", _prefs(), None)

        setter.assert_not_awaited()

    async def test_a_detached_failure_is_recorded_and_never_raised(self) -> None:
        """This runs off the request that saved the answers, so a raise has
        nowhere to go — but a silent swallow makes a dead prewarm invisible.
        The message is truncated: a provider traceback in a log line is how a
        connection string ends up in Loki."""
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

    async def test_a_redis_outage_does_not_escape_either(self) -> None:
        with (
            patch(
                f"{MODULE}.compose_first_question",
                AsyncMock(return_value=FirstQuestion(chips=GOOD_CHIPS)),
            ),
            patch(f"{MODULE}.redis_cache.set", AsyncMock(side_effect=ConnectionError("down"))),
            patch(f"{MODULE}.log") as mock_log,
        ):
            await prewarm_first_question("u1", _prefs(), None)

        assert mock_log.warning.call_args.kwargs["error_type"] == "ConnectionError"


@pytest.mark.unit
class TestResolveBranches:
    """Cached, else one short live attempt, else the static line."""

    async def test_a_hit_is_returned_as_is_and_costs_no_model_call(self) -> None:
        cached = FirstQuestion(chips=GOOD_CHIPS)
        compose = AsyncMock()
        getter = AsyncMock(return_value=cached)
        with (
            patch(f"{MODULE}.redis_cache.get", getter),
            patch(f"{MODULE}.compose_first_question", compose),
        ):
            result = await resolve_first_question("u1", _prefs(), "telegram")

        assert result is cached
        compose.assert_not_awaited()
        assert getter.await_args.args == (first_question_cache_key("u1", _prefs()), FirstQuestion)

    async def test_a_miss_gets_one_live_attempt_on_the_two_second_ceiling(self) -> None:
        """The user is watching a spinner: past two seconds the static line is
        the better product, so this is a last chance rather than a real
        attempt."""
        written = FirstQuestion(chips=GOOD_CHIPS)
        compose = AsyncMock(return_value=written)
        with (
            patch(f"{MODULE}.redis_cache.get", AsyncMock(return_value=None)),
            patch(f"{MODULE}.compose_first_question", compose),
        ):
            result = await resolve_first_question("u1", _prefs(), "telegram")

        assert result is written
        assert compose.await_args.args == (_prefs(), "telegram")
        assert compose.await_args.kwargs == {
            "user_id": "u1",
            "timeout_seconds": LIVE_QUESTION_TIMEOUT_SECONDS,
        }
        assert LIVE_QUESTION_TIMEOUT_SECONDS == 2.0

    async def test_a_miss_whose_live_call_misses_too_is_the_static_line(self) -> None:
        compose = AsyncMock(return_value=None)
        with (
            patch(f"{MODULE}.redis_cache.get", AsyncMock(return_value=None)),
            patch(f"{MODULE}.compose_first_question", compose),
        ):
            assert await resolve_first_question("u1", _prefs(), None) is None

        compose.assert_awaited_once()


class TestSeededChips:
    """The agent's prompt reads back the chips the seeded turn actually offered,
    from the same cache key the seed was built from. Nothing is guessed."""

    async def test_reads_the_seed_key_and_returns_its_chips_as_a_list(self) -> None:
        cached = FirstQuestion(chips=GOOD_CHIPS)
        getter = AsyncMock(return_value=cached)
        with patch(f"{MODULE}.redis_cache.get", getter):
            chips = await seeded_chips("u1", _prefs())

        assert chips == list(GOOD_CHIPS)
        assert chips is not cached.chips
        assert getter.await_args.args == (first_question_cache_key("u1", _prefs()), FirstQuestion)
        assert getter.await_args.kwargs == {}

    async def test_a_different_user_or_answer_set_reads_a_different_key(self) -> None:
        getter = AsyncMock(return_value=None)
        with patch(f"{MODULE}.redis_cache.get", getter):
            await seeded_chips("u2", _prefs(profession="Dentist"))

        assert getter.await_args.args[0] == first_question_cache_key(
            "u2", _prefs(profession="Dentist")
        )
        assert getter.await_args.args[0] != first_question_cache_key("u1", _prefs())

    async def test_an_expired_key_yields_no_chips_rather_than_a_guess(self) -> None:
        with patch(f"{MODULE}.redis_cache.get", AsyncMock(return_value=None)):
            assert await seeded_chips("u1", _prefs()) == []

    async def test_a_cache_outage_is_logged_with_its_cause_and_yields_no_chips(self) -> None:
        boom = ConnectionError("redis down")
        warning = MagicMock()
        with (
            patch(f"{MODULE}.redis_cache.get", AsyncMock(side_effect=boom)),
            patch(f"{MODULE}.log.warning", warning),
        ):
            assert await seeded_chips("u1", _prefs()) == []

        warning.assert_called_once_with(
            f"{LogTag.ONBOARDING} seeded chips unreadable — prompt goes without them",
            user_id="u1",
            error="redis down",
            error_type="ConnectionError",
        )
