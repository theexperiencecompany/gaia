"""The instant reaction: one JEV call decides whether a user's message gets an emoji tap, and which."""

import asyncio
from collections.abc import Mapping
import json
from unittest.mock import AsyncMock, patch

import httpx
from pydantic import ValidationError
import pytest

from app.constants.reactions import (
    REACTION_CONTEXT_MAX_CHARS,
    REACTION_EMOJI_INSTRUCTIONS,
    REACTION_EMOJI_QUESTION_KEY,
    REACTION_KIND_CRITERIA,
    REACTION_KIND_INSTRUCTIONS,
    REACTION_KIND_QUESTION_KEY,
    REACTION_PALETTE,
    REACTION_UPSET_CRITERIA,
    REACTION_UPSET_INSTRUCTIONS,
    REACTION_UPSET_QUESTION_KEY,
    ReactionReason,
)
from app.models.jev_models import JevDecisionsResponse
from app.services.conversation import ack
from app.services.conversation.ack import (
    ReactionDecision,
    decide_reaction,
    reaction_request,
    read_reaction,
)
from app.services.hil.jev_client import JevUnconfiguredError
from tests.helpers import captured_wide_event, reaction_answers

_POST = "app.services.conversation.ack.post_decisions"
SEARCH = "🔎"


def _body(
    *,
    upset: float = 0.0,
    task: float = 1.0,
    sign_off: float = 0.0,
    emoji: str = SEARCH,
) -> JevDecisionsResponse:
    return JevDecisionsResponse.model_validate(
        reaction_answers(upset=upset, task=task, sign_off=sign_off, emoji=emoji)
    )


def _failures(event: Mapping[str, object]) -> list[dict[str, object]]:
    warnings = event.get("warnings", [])
    assert isinstance(warnings, list)
    return [w for w in warnings if w["msg"] == "reaction_ack.jev_failed"]


class TestReactionRequest:
    def test_the_request_is_byte_stable(self) -> None:
        state, questions = reaction_request("find my flight email", "Sure, what's next?")

        assert state == {
            "user_message": "find my flight email",
            "assistant_previous_message": "Sure, what's next?",
        }
        assert questions == {
            "upset": {
                "type": "noul",
                "instructions": REACTION_UPSET_INSTRUCTIONS,
                "criteria": dict(REACTION_UPSET_CRITERIA),
            },
            "kind": {
                "type": "choice",
                "instructions": REACTION_KIND_INSTRUCTIONS,
                "criteria": {str(k): v for k, v in REACTION_KIND_CRITERIA.items()},
            },
            "emoji": {
                "type": "choice",
                "instructions": REACTION_EMOJI_INSTRUCTIONS,
                "criteria": dict(REACTION_PALETTE),
            },
        }
        sent = json.dumps(questions, ensure_ascii=False)
        assert sent.index('"upset"') < sent.index('"kind"') < sent.index('"emoji"')
        assert sent.index('"task"') < sent.index('"sign_off"') < sent.index('"needs_words"')

    def test_the_previous_assistant_text_is_capped(self) -> None:
        state, _ = reaction_request("them too", "a" * 1000)

        assert state["assistant_previous_message"] == "a" * REACTION_CONTEXT_MAX_CHARS

    def test_an_empty_previous_assistant_text_is_sent_as_empty(self) -> None:
        state, _ = reaction_request("hi", "")

        assert state["assistant_previous_message"] == ""


class TestReadReaction:
    def test_exactly_at_the_threshold_reacts(self) -> None:
        decision = read_reaction(_body(upset=0.5, task=1.0))

        assert decision.reason is ReactionReason.REACTED
        assert decision.emoji == SEARCH

    def test_task_and_sign_off_add_up_to_the_threshold(self) -> None:
        decision = read_reaction(_body(task=0.25, sign_off=0.25, emoji="👍"))

        assert decision.emoji == "👍"
        assert (decision.p_task, decision.p_sign_off, decision.upset) == (0.25, 0.25, 0.0)

    def test_just_below_the_threshold_gives_no_reaction(self) -> None:
        decision = read_reaction(_body(upset=0.0, task=0.2499, sign_off=0.25))

        assert decision.emoji is None
        assert decision.reason is ReactionReason.NEEDS_WORDS

    def test_a_high_upset_blocks_a_clear_task(self) -> None:
        decision = read_reaction(_body(upset=0.9, task=1.0))

        assert decision.emoji is None
        assert decision.reason is ReactionReason.UPSET
        assert decision.upset == 0.9

    def test_needs_words_dominant_gives_no_reaction(self) -> None:
        decision = read_reaction(_body(task=0.1, sign_off=0.05))

        assert decision.emoji is None
        assert decision.reason is ReactionReason.NEEDS_WORDS

    def test_two_passing_factors_whose_product_misses_is_below_threshold(self) -> None:
        decision = read_reaction(_body(upset=0.4, task=0.6, sign_off=0.1))

        assert decision.emoji is None
        assert decision.reason is ReactionReason.BELOW_THRESHOLD

    def test_an_emoji_outside_the_palette_raises(self) -> None:
        with pytest.raises(ValueError, match="choice"):
            read_reaction(_body(emoji="🍕"))

    @pytest.mark.parametrize(
        "question",
        [REACTION_UPSET_QUESTION_KEY, REACTION_KIND_QUESTION_KEY, REACTION_EMOJI_QUESTION_KEY],
    )
    def test_a_missing_answer_raises(self, question: str) -> None:
        body = _body()
        del body.answers[question]

        with pytest.raises(ValueError):
            read_reaction(body)

    def test_a_kind_answer_without_probabilities_raises(self) -> None:
        body = _body()
        body.answers[REACTION_KIND_QUESTION_KEY] = JevDecisionsResponse.model_validate(
            {"answers": {"k": {"type": "choice", "choice": "task"}}}
        ).answers["k"]

        with pytest.raises(ValueError, match="probabilities"):
            read_reaction(body)


class TestReactionDecision:
    def test_an_emoji_without_a_reaction_cannot_be_built(self) -> None:
        with pytest.raises(ValidationError):
            ReactionDecision(emoji=SEARCH, reason=ReactionReason.UPSET)

    def test_a_reaction_without_an_emoji_cannot_be_built(self) -> None:
        with pytest.raises(ValidationError):
            ReactionDecision(emoji=None, reason=ReactionReason.REACTED)


class TestDecideReaction:
    async def test_a_clear_task_reacts_and_records_the_decision(self) -> None:
        with patch(_POST, AsyncMock(return_value=_body(upset=0.1, task=0.9))) as post:
            async with captured_wide_event() as event:
                decision = await decide_reaction("find my flight email", "")

        assert decision.emoji == SEARCH
        assert post.await_args.args == reaction_request("find my flight email", "")
        recorded = event["reaction_ack"]
        assert recorded["outcome"] == "reacted"
        assert recorded["reason"] == "reacted"
        assert recorded["upset"] == 0.1
        assert recorded["p_task"] == 0.9
        assert recorded["p_sign_off"] == 0.0
        assert isinstance(recorded["latency_ms"], int)
        assert _failures(event) == []

    @pytest.mark.parametrize(
        ("error", "reason"),
        [
            (httpx.ConnectError("refused"), ReactionReason.ERROR),
            (
                httpx.HTTPStatusError(
                    "502", request=httpx.Request("POST", "http://j"), response=httpx.Response(502)
                ),
                ReactionReason.ERROR,
            ),
            (httpx.ReadTimeout("slow"), ReactionReason.TIMEOUT),
            (ValueError("not json"), ReactionReason.MALFORMED),
            (RuntimeError("boom"), ReactionReason.ERROR),
        ],
    )
    async def test_a_failure_gives_no_reaction_and_warns(
        self, error: Exception, reason: ReactionReason
    ) -> None:
        with patch(_POST, AsyncMock(side_effect=error)):
            async with captured_wide_event() as event:
                decision = await decide_reaction("send it", "Drafted.")

        assert decision.emoji is None
        assert decision.reason is reason
        assert event["reaction_ack"]["outcome"] == "none"
        assert event["reaction_ack"]["reason"] == reason.value
        (failure,) = _failures(event)
        assert failure["reason"] == reason.value
        assert failure["error_type"] == type(error).__name__

    async def test_an_out_of_palette_emoji_is_malformed(self) -> None:
        with patch(_POST, AsyncMock(return_value=_body(emoji="🍕"))):
            async with captured_wide_event() as event:
                decision = await decide_reaction("order pizza", "")

        assert decision.emoji is None
        assert decision.reason is ReactionReason.MALFORMED
        assert _failures(event)[0]["reason"] == "jev_malformed"

    async def test_an_answer_slower_than_the_budget_times_out(self) -> None:
        async def never_answers(*_: object) -> JevDecisionsResponse:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        with patch.object(ack, "REACTION_TIMEOUT_SECONDS", 0.01), patch(_POST, never_answers):
            async with captured_wide_event() as event:
                decision = await decide_reaction("find it", "")

        assert decision.reason is ReactionReason.TIMEOUT
        assert decision.emoji is None
        assert _failures(event)[0]["reason"] == "jev_timeout"

    async def test_no_openrouter_key_is_unconfigured_and_does_not_warn(self) -> None:
        with patch(_POST, AsyncMock(side_effect=JevUnconfiguredError("no key"))):
            async with captured_wide_event() as event:
                decision = await decide_reaction("find it", "")

        assert decision.reason is ReactionReason.UNCONFIGURED
        assert decision.emoji is None
        assert event["reaction_ack"]["reason"] == "jev_unconfigured"
        assert _failures(event) == []
