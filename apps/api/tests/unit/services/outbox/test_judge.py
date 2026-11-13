"""The Judge's two passes: the confidence gate, retries, degraded mode, and who waits for a batch."""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.constants.outbox_judge import (
    JUDGE_CONCURRENCY_KEY,
    JUDGE_CONFIDENCE_GATE,
    JUDGE_MAX_ATTEMPTS,
    JUDGE_MAX_CONCURRENT_CALLS,
    JudgeQuestion,
)
from app.models.user_models import AuthenticatedUser
from app.services.outbox.deliver import OutboxUserNotFoundError
from app.services.outbox.judge import judge_report
from app.services.outbox.judge_clients import JudgeUnconfiguredError
from app.services.outbox.judge_context_models import (
    AskView,
    ItemView,
    JudgeContext,
    PresenceView,
    RunView,
    SettingsView,
    UserView,
)
from app.services.outbox.judge_models import JudgePass, ReasoningAnswer
from app.services.outbox.judge_verdict import PassAnswers, answers_from_reasoning
from app.services.outbox.models import UrgencyClass
from tests._harness.judge import NOW, answers, choice, notice

MODULE = "app.services.outbox.judge"
USER = AuthenticatedUser(user_id="6812f0b3c9a14e2b7d5a91cc", timezone="Asia/Kolkata")


def _context(runs: list[RunView] | None = None) -> JudgeContext:
    return JudgeContext(
        now=NOW,
        user=UserView(
            timezone="Asia/Kolkata", usual_wake="08:00", usual_sleep="22:00", attention_profile=[]
        ),
        item=ItemView(
            producer="todo", outcome="info", subject="s", facts=["f"], producer_suggested={}
        ),
        other_items_in_batch=[],
        ask=AskView(initiative="self_initiated", delivery_timing="when_done", may_wake=False),
        recent_user_messages=[],
        recent_gaia_replies=[],
        open_subjects=[],
        pending_asks=[],
        recent_deliveries=[],
        memory=[],
        calendar=None,
        attention_settings=SettingsView(quiet_hours="22:00-08:00"),
        presence=PresenceView(last_active_surface=None, last_active_at=None, active_surfaces={}),
        upcoming_runs=runs or [],
        held_items=[],
        past_waits=[],
    )


def _confident(confidence: float) -> PassAnswers:
    return answers(
        worth_telling=choice("yes", {"yes": 0.9, "no": 0.1}, confidence=confidence),
        within_minutes=choice("no", {"yes": 0.1, "no": 0.9}, confidence=confidence),
        before_checkin=choice("yes", {"yes": 0.9, "no": 0.1}, confidence=confidence),
        authenticity=choice("genuine", {"genuine": 0.9}, confidence=confidence),
    )


def _reasoned(**overrides: Any) -> PassAnswers:
    fields: dict[str, Any] = {
        "urgency": "interrupt",
        "deadline": "within_1h",
        "relevance": "new",
        "sensitivity": "none",
        "moment": "ok",
        "authenticity": "genuine",
        "worth_telling": "yes",
        "within_minutes": "yes",
        "before_checkin": "yes",
        "wait_for_run": None,
        "reason": "A person is waiting.",
        "relevance_ref": None,
        "same_fact_key": None,
        "corrects": None,
        "valid_until": None,
        "topics": [],
        "rules_applied": [],
    }
    return answers_from_reasoning(ReasoningAnswer.model_validate({**fields, **overrides}))


class _Judge:
    """The patched world of one judge_report call."""

    def __init__(
        self, decisions: list[object], reasoning: list[object], context: JudgeContext
    ) -> None:
        self.decisions = AsyncMock(side_effect=decisions)
        self.reasoning = AsyncMock(side_effect=reasoning)
        self.context = context
        self.log = MagicMock()
        self.unavailable = MagicMock()
        self.decided = MagicMock()


@contextmanager
def _judged(
    decisions: list[object] | None = None,
    reasoning: list[object] | None = None,
    context: JudgeContext | None = None,
    user: AuthenticatedUser | None = USER,
) -> Iterator[_Judge]:
    world = _Judge(decisions or [], reasoning or [], context or _context())
    with ExitStack() as stack:
        enter = stack.enter_context
        enter(patch(f"{MODULE}.load_user_context", AsyncMock(return_value=user)))
        enter(patch(f"{MODULE}.build_judge_context", AsyncMock(return_value=world.context)))
        enter(patch(f"{MODULE}.ask_decisions", world.decisions))
        enter(patch(f"{MODULE}.ask_reasoning", world.reasoning))
        enter(patch(f"{MODULE}.log", world.log))
        enter(patch(f"{MODULE}.OUTBOX_JUDGE_UNAVAILABLE", world.unavailable))
        enter(patch(f"{MODULE}.OUTBOX_JUDGE_DECIDED", world.decided))
        yield world


async def test_a_confident_decisions_answer_decides_alone() -> None:
    with _judged(decisions=[_confident(0.9)]) as world:
        verdict = await judge_report(notice())

    assert verdict is not None
    assert (verdict.decided_by, verdict.confidence) == (JudgePass.DECISIONS, 0.9)
    assert verdict.urgency is UrgencyClass.TIMELY
    world.reasoning.assert_not_awaited()
    world.decided.labels.assert_called_once_with(decided_by="decisions")


@pytest.mark.parametrize(
    ("confidence", "reasoning_asked"),
    [(JUDGE_CONFIDENCE_GATE, False), (JUDGE_CONFIDENCE_GATE - 0.01, True)],
)
async def test_the_gate_is_a_least_confidence_of_the_measured_value(
    confidence: float, reasoning_asked: bool
) -> None:
    with _judged(decisions=[_confident(confidence)], reasoning=[_reasoned()]) as world:
        await judge_report(notice())

    assert (world.reasoning.await_count == 1) is reasoning_asked


async def test_one_unconfident_question_sends_the_item_to_the_reasoning_model() -> None:
    unsure = answers(
        worth_telling=choice("yes", {"yes": 0.9}, confidence=0.95),
        within_minutes=choice("no", {"no": 0.9}, confidence=0.2),
        before_checkin=choice("no", {"no": 0.9}, confidence=0.95),
        authenticity=choice("genuine", {"genuine": 0.9}, confidence=0.95),
    )
    with _judged(decisions=[unsure], reasoning=[_reasoned()]) as world:
        verdict = await judge_report(notice())

    assert verdict is not None
    assert verdict.decided_by is JudgePass.REASONING
    assert verdict.urgency is UrgencyClass.INTERRUPT
    assert verdict.confidence == pytest.approx(0.2)
    assert world.reasoning.await_args.args[0] == world.decisions.await_args.args[0]
    world.decided.labels.assert_called_once_with(decided_by="reasoning")


async def test_a_failed_decisions_call_is_asked_again_and_then_the_reasoning_model_decides() -> (
    None
):
    boom = httpx.ConnectError("down")
    with _judged(decisions=[boom] * JUDGE_MAX_ATTEMPTS, reasoning=[_reasoned()]) as world:
        verdict = await judge_report(notice())

    assert world.decisions.await_count == JUDGE_MAX_ATTEMPTS
    assert verdict is not None and verdict.decided_by is JudgePass.REASONING
    assert verdict.confidence is None


async def test_a_pass_that_fails_once_is_retried() -> None:
    with _judged(decisions=[ValueError("garbled"), _confident(0.9)]) as world:
        verdict = await judge_report(notice())

    assert verdict is not None and verdict.decided_by is JudgePass.DECISIONS
    assert world.decisions.await_count == 2
    world.log.warning.assert_called_once()


async def test_both_passes_failing_is_degraded_mode_loudly() -> None:
    with _judged(
        decisions=[httpx.ReadTimeout("slow")] * JUDGE_MAX_ATTEMPTS,
        reasoning=[ValueError("garbled")] * JUDGE_MAX_ATTEMPTS,
    ) as world:
        verdict = await judge_report(notice())

    assert verdict is None
    world.unavailable.labels.assert_called_once_with(cause="failed")
    world.log.error.assert_called_once()
    world.decided.labels.assert_not_called()


async def test_an_unconfident_answer_is_used_when_the_reasoning_model_cannot_be_reached() -> None:
    with _judged(
        decisions=[_confident(0.3)], reasoning=[httpx.ConnectError("down")] * JUDGE_MAX_ATTEMPTS
    ) as world:
        verdict = await judge_report(notice())

    assert verdict is not None and verdict.decided_by is JudgePass.DECISIONS
    world.log.warning.assert_called()
    world.unavailable.labels.assert_not_called()


async def test_a_reasoning_answer_that_waits_for_a_run_nobody_offered_fails_the_pass() -> None:
    with _judged(
        decisions=[_confident(0.1)],
        reasoning=[_reasoned(wait_for_run="workflow:ghost")] * JUDGE_MAX_ATTEMPTS,
    ) as world:
        verdict = await judge_report(notice())

    assert verdict is not None and verdict.decided_by is JudgePass.DECISIONS
    assert world.reasoning.await_count == JUDGE_MAX_ATTEMPTS


async def test_without_an_openai_key_the_item_is_decided_without_the_judge_and_never_retried() -> (
    None
):
    with _judged(decisions=[JudgeUnconfiguredError("none")]) as world:
        verdict = await judge_report(notice())

    assert verdict is None
    assert world.decisions.await_count == 1
    world.reasoning.assert_not_awaited()
    world.unavailable.labels.assert_called_once_with(cause="not_configured")
    world.log.error.assert_not_called()


async def test_a_report_for_nobody_raises() -> None:
    with _judged(user=None), pytest.raises(OutboxUserNotFoundError):
        await judge_report(notice())


async def test_a_bug_in_a_pass_is_not_swallowed() -> None:
    with _judged(decisions=[KeyError("bug")]), pytest.raises(KeyError):
        await judge_report(notice())


async def test_judge_calls_share_a_bounded_pool() -> None:
    sem = MagicMock()
    sem.__aenter__ = AsyncMock()
    sem.__aexit__ = AsyncMock(return_value=None)
    with (
        _judged(decisions=[_confident(0.9)]),
        patch(f"{MODULE}.loop_bound_semaphore", return_value=sem) as pool,
    ):
        await judge_report(notice())

    pool.assert_called_once_with(JUDGE_CONCURRENCY_KEY, JUDGE_MAX_CONCURRENT_CALLS)
    sem.__aenter__.assert_awaited_once()


async def test_the_runs_in_the_context_are_offered_and_a_wait_for_one_is_kept() -> None:
    run = RunView(
        run_id="workflow:wf_1",
        kind="workflow_run",
        label="Morning briefing",
        starts_at=NOW + timedelta(minutes=30),
        hit_rate=1.0,
    )
    waiting = PassAnswers(
        answers={**_confident(0.9).answers, JudgeQuestion.WAIT_FOR_RUN: choice("workflow:wf_1")}
    )
    with _judged(decisions=[waiting], context=_context([run])) as world:
        verdict = await judge_report(notice())

    assert verdict is not None and verdict.wait_for_run == "workflow:wf_1"
    assert world.decisions.await_args.args[1] == {"workflow:wf_1": "Morning briefing"}
