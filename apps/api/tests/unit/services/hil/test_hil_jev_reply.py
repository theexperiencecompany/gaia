"""JEV reply classifier (app/services/hil/jev_reply.py).

The Decisions API is mocked at the HTTP boundary; the state and questions the
classifier builds, the answer parsing and the settle rules run for real.
"""

import httpx
import pytest

from app.constants.hil import (
    HIL_CLASSIFIER_MAX_ARG_CHARS,
    HIL_JEV_MODEL_NAME,
    HIL_JEV_REPLY_APPROVE_LINE,
    HIL_JEV_REPLY_DECIDE_FLOOR,
    HIL_JEV_URL,
    ReplyChoice,
)
from app.models.jev_models import JevReplyVerdict
from app.models.message_models import MessageDict
from app.services.hil.jev_reply import ask_jev_reply, settle_reply
from app.services.hil.prompts import JEV_REPLY_CRITERIA

from .conftest import jev_reply_body, serve_jev

ACTIONS = ["Send email — to: bob@example.com", "Post message — channel: #general"]


def _verdict(choice: ReplyChoice, confidence: float = 0.99) -> JevReplyVerdict:
    return JevReplyVerdict(choice=choice, confidence=confidence, probabilities={})


class TestTheDecisionsRequest:
    async def test_one_question_per_action_over_the_numbered_actions(self) -> None:
        body = jev_reply_body(("approve", 0.9), ("deny", 0.8))
        with serve_jev(body) as client:
            await ask_jev_reply("just the email", ACTIONS, None)

        post = client.post.await_args
        assert post.args == (HIL_JEV_URL,)
        assert post.kwargs["headers"] == {"Authorization": "Bearer or-key"}
        posted = post.kwargs["json"]
        assert posted["model"] == HIL_JEV_MODEL_NAME
        assert posted["state"] == {
            "reply": "just the email",
            "pending_actions": [
                {"number": 1, "action": ACTIONS[0]},
                {"number": 2, "action": ACTIONS[1]},
            ],
        }
        assert list(posted["questions"]) == ["action_1", "action_2"]

    async def test_each_question_is_about_its_own_action(self) -> None:
        # A question that did not name its action would ask JEV the same thing N times
        # and a selective reply ("just the email") could never split.
        with serve_jev(jev_reply_body(("approve", 0.9), ("deny", 0.8))) as client:
            await ask_jev_reply("just the email", ACTIONS, None)

        questions = client.post.await_args.kwargs["json"]["questions"]
        for number, name in ((1, "action_1"), (2, "action_2")):
            question = questions[name]
            assert question["type"] == "choice"
            assert f"number {number}" in question["instructions"]
            assert set(question["criteria"]) == {choice.value for choice in ReplyChoice}
            assert f"action {number}" in question["criteria"][ReplyChoice.APPROVE]
            assert "{number}" not in str(question)

    async def test_every_label_the_question_offers_has_criteria(self) -> None:
        assert set(JEV_REPLY_CRITERIA) == set(ReplyChoice)

    async def test_recent_turns_ride_along_clipped(self) -> None:
        history = [
            MessageDict(role="user", content="email bob the deck"),
            MessageDict(role="assistant", content="x" * (HIL_CLASSIFIER_MAX_ARG_CHARS + 50)),
        ]
        with serve_jev(jev_reply_body(("approve", 0.9))) as client:
            await ask_jev_reply("yes", ACTIONS[:1], history)

        turns = client.post.await_args.kwargs["json"]["state"]["recent_conversation"]
        assert turns[0] == {"role": "user", "content": "email bob the deck"}
        assert turns[1]["role"] == "assistant"
        assert turns[1]["content"] == "x" * HIL_CLASSIFIER_MAX_ARG_CHARS + "…"

    async def test_verdicts_come_back_in_action_order_with_usage(self) -> None:
        body = jev_reply_body(("deny", 0.7), ("approve", 0.95))
        with serve_jev(body):
            verdicts, tokens_in, tokens_out = await ask_jev_reply("only the second", ACTIONS, None)

        assert [(v.choice, v.confidence) for v in verdicts] == [
            (ReplyChoice.DENY, 0.7),
            (ReplyChoice.APPROVE, 0.95),
        ]
        assert (tokens_in, tokens_out) == (400, 40)
        assert [v.probabilities for v in verdicts] == [{"deny": 0.7}, {"approve": 0.95}]

    async def test_an_answer_without_confidence_reads_as_zero_and_never_runs(self) -> None:
        body = {"answers": {"action_1": {"type": "choice", "choice": "approve"}}}
        with serve_jev(body):
            verdicts, _, _ = await ask_jev_reply("yes", ACTIONS[:1], None)

        assert (verdicts[0].confidence, verdicts[0].probabilities) == (0.0, {})
        assert settle_reply(verdicts) == [ReplyChoice.LEAVE]


class TestAMalformedAnswerRaises:
    """Every refusal raises, so the caller falls back instead of acting on a guess."""

    async def test_an_unknown_choice_is_refused_by_name(self) -> None:
        with serve_jev(jev_reply_body(("maybe", 0.9))), pytest.raises(ValueError) as caught:
            await ask_jev_reply("yes", ACTIONS[:1], None)

        assert str(caught.value) == "unknown JEV reply choice: 'maybe'"

    async def test_an_action_left_unanswered_is_refused(self) -> None:
        with (
            serve_jev(jev_reply_body(("approve", 0.9))),
            pytest.raises(ValueError, match="action_2"),
        ):
            await ask_jev_reply("yes", ACTIONS, None)

    async def test_a_non_choice_answer_is_refused(self) -> None:
        body = {"answers": {"action_1": {"type": "score", "choice": "approve"}}}
        with serve_jev(body), pytest.raises(ValueError, match="^non-choice JEV reply answer"):
            await ask_jev_reply("yes", ACTIONS[:1], None)

    async def test_a_transport_failure_propagates(self) -> None:
        with serve_jev(httpx.ConnectError("down")), pytest.raises(httpx.ConnectError):
            await ask_jev_reply("yes", ACTIONS[:1], None)


class TestSettle:
    def test_an_approve_under_the_line_is_a_leave(self) -> None:
        below = _verdict(ReplyChoice.APPROVE, HIL_JEV_REPLY_APPROVE_LINE - 0.01)
        assert settle_reply([below]) == [ReplyChoice.LEAVE]

    def test_an_approve_on_the_line_stands(self) -> None:
        on = _verdict(ReplyChoice.APPROVE, HIL_JEV_REPLY_APPROVE_LINE)
        assert settle_reply([on]) == [ReplyChoice.APPROVE]

    def test_a_deny_under_the_floor_is_a_leave(self) -> None:
        # A guessed deny would kill an action the user may well want; asking again is cheaper.
        below = _verdict(ReplyChoice.DENY, HIL_JEV_REPLY_DECIDE_FLOOR - 0.01)
        assert settle_reply([below]) == [ReplyChoice.LEAVE]

    def test_a_deny_on_the_floor_stands(self) -> None:
        on = _verdict(ReplyChoice.DENY, HIL_JEV_REPLY_DECIDE_FLOOR)
        assert settle_reply([on]) == [ReplyChoice.DENY]

    def test_an_unrelated_under_the_floor_never_abandons(self) -> None:
        below = _verdict(ReplyChoice.UNRELATED, HIL_JEV_REPLY_DECIDE_FLOOR - 0.01)
        assert settle_reply([below, _verdict(ReplyChoice.UNRELATED)]) == [
            ReplyChoice.LEAVE,
            ReplyChoice.LEAVE,
        ]

    def test_unrelated_survives_only_when_every_action_agrees(self) -> None:
        unanimous = [_verdict(ReplyChoice.UNRELATED), _verdict(ReplyChoice.UNRELATED)]
        assert settle_reply(unanimous) == [ReplyChoice.UNRELATED, ReplyChoice.UNRELATED]

    def test_a_split_unrelated_reads_as_leave(self) -> None:
        split = [_verdict(ReplyChoice.UNRELATED), _verdict(ReplyChoice.APPROVE)]
        assert settle_reply(split) == [ReplyChoice.LEAVE, ReplyChoice.APPROVE]

    def test_both_lines_are_parameters_for_the_offline_sweep(self) -> None:
        approve, deny = _verdict(ReplyChoice.APPROVE, 0.6), _verdict(ReplyChoice.DENY, 0.6)
        assert settle_reply([approve], approve_line=0.5) == [ReplyChoice.APPROVE]
        assert settle_reply([approve], approve_line=0.7) == [ReplyChoice.LEAVE]
        assert settle_reply([deny], decide_floor=0.5) == [ReplyChoice.DENY]
        assert settle_reply([deny], decide_floor=0.7) == [ReplyChoice.LEAVE]
