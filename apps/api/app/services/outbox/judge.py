"""The Judge: what an item means for this user now, decided in two passes.

The Decisions API answers first, fast and cheap, with a confidence per question. When its least
confident decision question is at least JUDGE_CONFIDENCE_GATE its answer stands; otherwise the
reasoning model answers the same questions from the same context and its answer stands. Both
passes failing is degraded mode: the Rails decide from what the producer set, loudly.
"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from app.agents.llm.exceptions import LLM_FALLBACK_EXCEPTIONS
from app.constants.log_tags import LogTag
from app.constants.outbox_judge import (
    JUDGE_CONCURRENCY_KEY,
    JUDGE_CONFIDENCE_GATE,
    JUDGE_MAX_ATTEMPTS,
    JUDGE_MAX_CONCURRENT_CALLS,
)
from app.services.outbox.deliver import OutboxUserNotFoundError
from app.services.outbox.judge_clients import (
    JudgeUnconfiguredError,
    ask_decisions,
    ask_reasoning,
)
from app.services.outbox.judge_context import build_judge_context, user_clock
from app.services.outbox.judge_context_models import JudgeContext
from app.services.outbox.judge_models import JudgePass, JudgeUnavailableCause, JudgeVerdict
from app.services.outbox.judge_verdict import PassAnswers, UserClock, build_verdict
from app.services.outbox.metrics import OUTBOX_JUDGE_DECIDED, OUTBOX_JUDGE_UNAVAILABLE
from app.services.outbox.models import OutboxReport
from app.utils import clock
from app.utils.auth_utils import load_user_context
from app.utils.concurrency import loop_bound_semaphore
from shared.py.wide_events import log

_T = TypeVar("_T")

#: What a pass failing looks like: a transport or provider error, or an answer that cannot be read.
_PASS_FAILURES: tuple[type[BaseException], ...] = (
    httpx.HTTPError,
    ValueError,
    *LLM_FALLBACK_EXCEPTIONS,
)


async def _attempt(kind: JudgePass, produce: Callable[[], Awaitable[_T]]) -> _T | None:
    """Run one pass up to JUDGE_MAX_ATTEMPTS times; None when it never produced a readable answer."""
    for attempt in range(1, JUDGE_MAX_ATTEMPTS + 1):
        try:
            async with loop_bound_semaphore(JUDGE_CONCURRENCY_KEY, JUDGE_MAX_CONCURRENT_CALLS):
                return await produce()
        except JudgeUnconfiguredError:
            raise
        except _PASS_FAILURES as e:
            log.warning(
                f"{LogTag.NOTIFICATION} Judge pass failed",
                judge_pass=kind.value,
                attempt=attempt,
                error_type=type(e).__name__,
                error=str(e),
            )
    return None


def _unavailable(cause: JudgeUnavailableCause, report: OutboxReport) -> None:
    OUTBOX_JUDGE_UNAVAILABLE.labels(cause=cause.value).inc()
    message = f"{LogTag.NOTIFICATION} Judge unavailable; the Rails decide from the producer's hints"
    if cause is JudgeUnavailableCause.NOT_CONFIGURED:
        log.warning(message, cause=cause.value, report_id=report.report_id)
    else:
        log.error(message, cause=cause.value, report_id=report.report_id)


async def _decide(context: JudgeContext, user_id: str, clock_: UserClock) -> JudgeVerdict | None:
    state = context.as_state()
    runs = context.offered_runs

    def read(answers: PassAnswers, kind: JudgePass, confidence: float | None) -> JudgeVerdict:
        verdict = build_verdict(
            answers,
            decided_by=kind,
            decisions_confidence=confidence,
            now=context.now,
            clock=clock_,
            offered_runs=runs.keys(),
        )
        return context.with_wait_run(verdict)

    async def first_pass() -> tuple[JudgeVerdict, float]:
        answers = await ask_decisions(state, runs)
        confidence = answers.gate_confidence()
        return read(answers, JudgePass.DECISIONS, confidence), confidence

    first = await _attempt(JudgePass.DECISIONS, first_pass)
    if first is not None and first[1] >= JUDGE_CONFIDENCE_GATE:
        return first[0]

    async def second_pass() -> JudgeVerdict:
        answers = await ask_reasoning(state, runs, user_id=user_id)
        return read(answers, JudgePass.REASONING, first[1] if first else None)

    second = await _attempt(JudgePass.REASONING, second_pass)
    if second is not None:
        return second
    if first is not None:
        log.warning(
            f"{LogTag.NOTIFICATION} Judge could not escalate an unconfident answer; using it",
            confidence=first[1],
        )
        return first[0]
    return None


async def judge_report(report: OutboxReport) -> JudgeVerdict | None:
    """Return what one report means for its user now; None, loudly, when the Judge could not be asked.

    Raises when the context cannot be read from a source the user has: the intake job retries.
    """
    user = await load_user_context(report.recipient)
    if user is None:
        raise OutboxUserNotFoundError(report.recipient)
    context = await build_judge_context(report, user, now=clock.now())
    try:
        verdict = await _decide(context, user.user_id, user_clock(user))
    except JudgeUnconfiguredError:
        _unavailable(JudgeUnavailableCause.NOT_CONFIGURED, report)
        return None
    if verdict is None:
        _unavailable(JudgeUnavailableCause.FAILED, report)
        return None
    OUTBOX_JUDGE_DECIDED.labels(decided_by=verdict.decided_by.value).inc()
    log.info(
        f"{LogTag.NOTIFICATION} Judge decided",
        report_id=report.report_id,
        decided_by=verdict.decided_by.value,
        urgency=verdict.urgency.name.lower(),
        relevance=verdict.relevance.value,
        reason=verdict.reason,
    )
    return verdict
