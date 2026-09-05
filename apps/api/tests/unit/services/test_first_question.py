"""Rules for the one LLM-written line of the opening conversation.

The validator is the whole safety story: it is the only thing standing between
a model having an off day and the first sentence every new user reads. So every
rule gets a case that goes red when the rule is deleted, and the fallback path
gets one per failure shape (raised, timed out, unparseable, invalid).
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.onboarding.first_question import (
    LIVE_QUESTION_TIMEOUT_SECONDS,
    FirstQuestion,
    _QuestionDraft,
    answers_fingerprint,
    comms_voice_rules,
    compose_first_question,
    first_question_cache_key,
    prewarm_first_question,
    resolve_first_question,
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


@pytest.mark.unit
class TestVoiceRules:
    def test_the_rules_come_from_the_comms_prompt_itself(self) -> None:
        rules = comms_voice_rules()
        assert rules.startswith("## Voice")
        assert "TONE MIRRORING" in rules
        assert "## Length Modes" not in rules


@pytest.mark.unit
class TestComposeFirstQuestion:
    async def test_a_valid_draft_is_returned(self) -> None:
        draft = _QuestionDraft(chips=GOOD_CHIPS)
        with (
            patch(f"{MODULE}.background_structured_runnable"),
            patch(f"{MODULE}.ainvoke_llm", AsyncMock(return_value=draft)),
        ):
            result = await compose_first_question(_prefs(), None)

        assert result is not None
        assert result.chips == GOOD_CHIPS

    @pytest.mark.parametrize(
        "error",
        [TimeoutError(), RuntimeError("provider exploded"), ValueError("not valid json")],
    )
    async def test_every_failure_falls_back(self, error: Exception) -> None:
        with (
            patch(f"{MODULE}.background_structured_runnable"),
            patch(f"{MODULE}.ainvoke_llm", AsyncMock(side_effect=error)),
        ):
            assert await compose_first_question(_prefs(), None) is None


@pytest.mark.unit
class TestAnswersFingerprint:
    def test_the_same_answers_hash_the_same(self) -> None:
        assert answers_fingerprint(_prefs()) == answers_fingerprint(_prefs())

    def test_casing_and_padding_are_the_same_answers(self) -> None:
        assert answers_fingerprint(_prefs(profession="Founder ")) == answers_fingerprint(_prefs())

    @pytest.mark.parametrize(
        "changed",
        [
            {"profession": "student"},
            {"needs": [OnboardingNeed.INBOX]},
            {"other_need": "chasing invoices"},
        ],
    )
    def test_changing_any_answer_changes_the_key(self, changed: dict) -> None:
        """Re-answering Q2 must not read the question written for the old answers,
        and nothing anywhere calls an invalidate that could be forgotten."""
        assert first_question_cache_key("u1", _prefs(**changed)) != first_question_cache_key(
            "u1", _prefs()
        )

    def test_the_key_is_scoped_to_the_user(self) -> None:
        assert first_question_cache_key("u1", _prefs()) != first_question_cache_key("u2", _prefs())


@pytest.mark.unit
class TestResolveFirstQuestion:
    async def test_a_cache_hit_makes_no_model_call(self) -> None:
        cached = FirstQuestion(chips=GOOD_CHIPS)
        compose = AsyncMock()
        with (
            patch(f"{MODULE}.redis_cache.get", AsyncMock(return_value=cached)) as get,
            patch(f"{MODULE}.compose_first_question", compose),
        ):
            result = await resolve_first_question("u1", _prefs(), None)

        assert result == cached
        compose.assert_not_awaited()
        assert get.await_args.args[0] == first_question_cache_key("u1", _prefs())

    async def test_a_question_written_for_other_answers_is_not_read(self) -> None:
        """The hash is the invalidation: the changed answers read a key nobody
        wrote, so the miss path runs rather than the old question being served."""
        store = {first_question_cache_key("u1", _prefs()): "stale"}
        written = FirstQuestion(chips=GOOD_CHIPS)

        async def _get(key: str, model: object = None) -> object:
            return store.get(key)

        with (
            patch(f"{MODULE}.redis_cache.get", AsyncMock(side_effect=_get)),
            patch(f"{MODULE}.compose_first_question", AsyncMock(return_value=written)),
        ):
            result = await resolve_first_question("u1", _prefs(profession="student"), None)

        assert result == written

    async def test_a_miss_falls_through_to_one_short_live_call(self) -> None:
        written = FirstQuestion(chips=GOOD_CHIPS)
        compose = AsyncMock(return_value=written)
        with (
            patch(f"{MODULE}.redis_cache.get", AsyncMock(return_value=None)),
            patch(f"{MODULE}.compose_first_question", compose),
        ):
            result = await resolve_first_question("u1", _prefs(), "telegram")

        assert result == written
        assert compose.await_args.kwargs["timeout_seconds"] == LIVE_QUESTION_TIMEOUT_SECONDS

    async def test_a_miss_whose_live_call_misses_too_is_the_static_line(self) -> None:
        with (
            patch(f"{MODULE}.redis_cache.get", AsyncMock(return_value=None)),
            patch(f"{MODULE}.compose_first_question", AsyncMock(return_value=None)),
        ):
            assert await resolve_first_question("u1", _prefs(), None) is None


@pytest.mark.unit
class TestPrewarmFirstQuestion:
    async def test_a_written_question_is_cached_under_its_answers(self) -> None:
        written = FirstQuestion(chips=GOOD_CHIPS)
        setter = AsyncMock()
        with (
            patch(f"{MODULE}.compose_first_question", AsyncMock(return_value=written)),
            patch(f"{MODULE}.redis_cache.set", setter),
        ):
            await prewarm_first_question("u1", _prefs(), None)

        assert setter.await_args.args[0] == first_question_cache_key("u1", _prefs())
        assert setter.await_args.args[1] == written

    async def test_nothing_is_cached_when_nothing_was_written(self) -> None:
        setter = AsyncMock()
        with (
            patch(f"{MODULE}.compose_first_question", AsyncMock(return_value=None)),
            patch(f"{MODULE}.redis_cache.set", setter),
        ):
            await prewarm_first_question("u1", _prefs(), None)

        setter.assert_not_awaited()

    async def test_a_detached_failure_never_escapes(self) -> None:
        with patch(f"{MODULE}.compose_first_question", AsyncMock(side_effect=RuntimeError("nope"))):
            await prewarm_first_question("u1", _prefs(), None)
