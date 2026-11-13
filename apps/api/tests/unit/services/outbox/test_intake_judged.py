"""Intake with the Judge: what it asks, what the item keeps, and what is recorded and not told."""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.constants.agents import OutcomeState
from app.constants.outbox import (
    OUTBOX_BATCHED_JOB_ID_SUFFIX,
    OUTBOX_INTAKE_TASK,
    OUTBOX_JOB_ID_PREFIX,
)
from app.constants.outbox_judge import (
    JUDGE_BATCH_WINDOW_SECONDS,
    JUDGE_INTERRUPT_CAP_WINDOW_SECONDS,
    JUDGE_INTERRUPT_DAILY_CAP,
)
from app.models.task_report_models import TaskReport
from app.services.outbox.holds import Tell
from app.services.outbox.intake import process_report
from app.services.outbox.judge_models import ItemJudgement, JudgeVerdict, Relevance, Sensitivity
from app.services.outbox.models import (
    DropReason,
    Initiative,
    ItemState,
    NoticeOutcome,
    ProducerKind,
    RunReport,
    Subject,
    SubjectKind,
    SubjectMerge,
    UrgencyClass,
)
from app.services.outbox.prerendered import PrerenderedKind, PrerenderedMessage
from tests._harness.judge import NOW, notice, verdict

MODULE = "app.services.outbox.intake"


class _Intake:
    def __init__(self, judged: JudgeVerdict | None, raised_today: int) -> None:
        self.judge = AsyncMock(return_value=judged)
        self.repo = MagicMock()
        self.repo.insert_if_new = AsyncMock(
            return_value=SimpleNamespace(
                item=SimpleNamespace(state=ItemState.RECEIVED), created=True
            )
        )
        self.repo.apply_replace = AsyncMock(return_value=True)
        self.repo.count_raised_interrupts_since = AsyncMock(return_value=raised_today)
        self.repo.drop = AsyncMock(return_value=SimpleNamespace())
        self.repo.queue = AsyncMock(return_value=SimpleNamespace())
        self.flush = AsyncMock()
        self.enqueue = AsyncMock()
        self.capped = MagicMock()
        self.log = MagicMock()

    def judgement(self, call: AsyncMock) -> ItemJudgement | None:
        return call.await_args.kwargs["judgement"]


NEUTRAL = verdict()


@contextmanager
def _intake(judged: JudgeVerdict | None = NEUTRAL, raised_today: int = 0) -> Iterator[_Intake]:
    world = _Intake(judged, raised_today)
    with ExitStack() as stack:
        enter = stack.enter_context
        enter(patch(f"{MODULE}.judge_report", world.judge))
        enter(patch(f"{MODULE}.outbox_items_repository", world.repo))
        enter(patch(f"{MODULE}.flush_subject", world.flush))
        enter(patch(f"{MODULE}.place_item", AsyncMock(return_value=Tell())))
        enter(patch(f"{MODULE}.enqueue_worker_job", world.enqueue))
        enter(patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock()))
        enter(patch(f"{MODULE}.OUTBOX_JUDGE_INTERRUPT_CAPPED", world.capped))
        enter(patch(f"{MODULE}.log", world.log))
        enter(patch(f"{MODULE}.clock.now", return_value=NOW))
        yield world


async def test_an_item_the_judge_finds_moot_is_recorded_with_that_reason_and_never_told() -> None:
    moot = verdict(relevance=Relevance.MOOT, not_worth_probability=0.8, reason="user did it")
    with _intake(moot) as world:
        await process_report(notice(), batched=True)

    reason = world.repo.drop.await_args.args[2]
    assert reason is DropReason.MOOT
    kept = world.judgement(world.repo.drop)
    assert kept is not None and kept.verdict == moot
    world.repo.queue.assert_not_awaited()
    world.flush.assert_not_awaited()


async def test_a_told_item_keeps_the_verdict_the_urgency_and_the_sensitivity() -> None:
    health = verdict(
        urgency=UrgencyClass.TIMELY, sensitivity=Sensitivity.HEALTH, reason="results are in"
    )
    with _intake(health) as world:
        await process_report(notice(), batched=True)

    kwargs = world.repo.queue.await_args.kwargs
    assert kwargs["urgency"] is UrgencyClass.TIMELY
    kept = world.judgement(world.repo.queue)
    assert kept == ItemJudgement(
        verdict=health,
        judge_unavailable=False,
        raised_interrupt=False,
        sensitivity=Sensitivity.HEALTH,
    )
    world.flush.assert_awaited_once()


async def test_the_judge_is_asked_about_the_report_it_was_given() -> None:
    report = notice(report_id="ask-me")
    with _intake() as world:
        await process_report(report, batched=True)

    world.judge.assert_awaited_once_with(report)


async def test_when_the_judge_cannot_answer_the_producers_hints_decide_and_the_item_says_so() -> (
    None
):
    needs_you = notice(outcome="needs_you")
    with _intake(None) as world:
        await process_report(needs_you, batched=True)

    assert world.repo.queue.await_args.kwargs["urgency"] is UrgencyClass.TIMELY
    kept = world.judgement(world.repo.queue)
    assert kept is not None
    assert (kept.verdict, kept.judge_unavailable) == (None, True)
    world.flush.assert_awaited_once()


async def test_a_report_the_policy_decides_alone_is_never_shown_to_the_judge() -> None:
    quiet_check = RunReport(
        report_id="check",
        recipient="u",
        producer=ProducerKind.TODO,
        subject=Subject(
            kind=SubjectKind.TODO_RUN, id="t", label="Watch", merge=SubjectMerge.REPLACE
        ),
        occurred_at=NOW,
        initiative=Initiative.SELF_INITIATED,
        report=TaskReport(outcome=OutcomeState.NOTHING_NEW),
    )
    with _intake() as world:
        await process_report(quiet_check)

    world.judge.assert_not_awaited()
    world.enqueue.assert_not_awaited()
    assert world.repo.drop.await_args.args[2] is DropReason.NOTHING_NEW
    assert world.judgement(world.repo.drop) is None


async def test_an_interrupt_the_judge_raised_is_flagged_so_it_counts_against_the_cap() -> None:
    with _intake(verdict(urgency=UrgencyClass.INTERRUPT), raised_today=0) as world:
        await process_report(notice(), batched=True)

    assert world.repo.queue.await_args.kwargs["urgency"] is UrgencyClass.INTERRUPT
    kept = world.judgement(world.repo.queue)
    assert kept is not None and kept.raised_interrupt is True


async def test_past_the_cap_the_interrupt_is_timely_and_the_refusal_is_loud() -> None:
    with _intake(
        verdict(urgency=UrgencyClass.INTERRUPT), raised_today=JUDGE_INTERRUPT_DAILY_CAP
    ) as world:
        await process_report(notice(), batched=True)

    assert world.repo.queue.await_args.kwargs["urgency"] is UrgencyClass.TIMELY
    kept = world.judgement(world.repo.queue)
    assert kept is not None and kept.raised_interrupt is False
    world.capped.inc.assert_called_once()
    world.log.error.assert_called_once()


async def test_the_cap_counts_a_rolling_day_of_this_users_interrupts() -> None:
    with _intake() as world:
        await process_report(notice(), batched=True)

    user, since = world.repo.count_raised_interrupts_since.await_args.args
    assert user == notice().recipient
    assert since == NOW - timedelta(seconds=JUDGE_INTERRUPT_CAP_WINDOW_SECONDS)


async def test_a_report_a_newer_one_replaced_is_neither_judged_nor_queued() -> None:
    with _intake() as world:
        world.repo.apply_replace.return_value = False
        await process_report(notice(), batched=True)

    world.judge.assert_not_awaited()
    world.repo.queue.assert_not_awaited()


async def test_a_report_that_waits_for_its_users_others_is_handed_back_deferred_not_slept_on() -> (
    None
):
    report = notice(report_id="wait")
    with _intake() as world:
        await process_report(report)

    kwargs = world.enqueue.await_args.kwargs
    assert world.enqueue.await_args.args[1:] == (
        OUTBOX_INTAKE_TASK,
        report.model_dump(mode="json"),
        True,
    )
    assert kwargs["_job_id"] == f"{OUTBOX_JOB_ID_PREFIX}wait{OUTBOX_BATCHED_JOB_ID_SUFFIX}"
    assert kwargs["_defer_by"] == JUDGE_BATCH_WINDOW_SECONDS
    world.judge.assert_not_awaited()
    world.repo.queue.assert_not_awaited()
    world.flush.assert_not_awaited()


async def test_a_report_that_does_not_wait_is_judged_at_once() -> None:
    with _intake() as world:
        await process_report(notice(initiative=Initiative.ASKED))

    world.enqueue.assert_not_awaited()
    world.judge.assert_awaited_once()
    world.flush.assert_awaited_once()


async def test_progress_someone_is_watching_is_told_at_once_without_the_judge_or_the_batch() -> (
    None
):
    progress = notice(outcome=NoticeOutcome.PROGRESS, facts=["Reading the second file."])
    with _intake() as world, patch(f"{MODULE}.is_watched_live", AsyncMock(return_value=True)):
        await process_report(progress)

    world.judge.assert_not_awaited()
    world.enqueue.assert_not_awaited()
    world.repo.queue.assert_awaited_once()
    world.flush.assert_awaited_once()


async def test_a_prerendered_message_is_told_at_once_without_the_judge_or_the_batch() -> None:
    hello = notice(
        facts=[],
        prerendered=PrerenderedMessage(
            kind=PrerenderedKind.FIRST_CONTACT, bubbles=["Hi, I am GAIA."]
        ),
    )
    with _intake() as world:
        await process_report(hello)

    world.judge.assert_not_awaited()
    world.enqueue.assert_not_awaited()
    world.repo.queue.assert_awaited_once()
    world.flush.assert_awaited_once()
