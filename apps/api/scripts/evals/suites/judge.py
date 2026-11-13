"""The Judge's golden suite: 200 real-world attention scenarios, graded through the production Judge and Rails.

Each case is one update plus what GAIA knows of its user, with gold labels for urgency, deadline,
relevance, sensitivity, moment and authenticity. The Judge answers through its two passes (the
Decisions API, then the reasoning model when the first is unsure); the production verdict reader
and policy turn those answers into a disposition, which is graded for the failures that hurt:
a late or missed alert, a scam relayed, a moot item pushed, a sensitive item exposed.

The gate is zero critical misses on the critical rows. Cases ship with the answers of a recorded
run, regraded for free by tests/unit/evals/test_judge_sweep.py; the Decisions request each answer
belongs to is hashed, so an edit to the questions, the instructions or a case that is not
re-recorded fails that sweep.

Run:    uv run --group backend python -m scripts.evals run --suite judge --concurrency 6
Record: uv run --group backend python -m scripts.evals.record_judge <run-id>
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Final, NotRequired, TypedDict

import httpx

from app.constants.outbox_judge import (
    JUDGE_CONFIDENCE_GATE,
    JUDGE_FAST_MODEL,
    JudgeQuestion,
)
from app.models.ownership_models import DeliveryPolicy, DeliveryTiming
from app.models.quiet_hours_models import QuietHours
from app.services.outbox.judge_clients import (
    JudgeUnconfiguredError,
    ask_decisions,
    ask_reasoning,
    decisions_body,
)
from app.services.outbox.judge_models import JudgePass, JudgeVerdict, Sensitivity
from app.services.outbox.judge_verdict import (
    ChoiceAnswer,
    JudgeAnswerError,
    PassAnswers,
    UserClock,
    build_verdict,
)
from app.services.outbox.models import (
    Initiative,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    Subject,
    SubjectKind,
    UrgencyClass,
)
from app.services.outbox.policy import DecisionKind, decide
from app.utils.timezone import Timezone
from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.journal import RunJournal
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import register_suite
from scripts.evals.core.transport_suite import TransportSuite
from scripts.evals.core.types import Case, CaseRun, ProviderError

DATA_DIR: Final = Path(__file__).resolve().parent.parent / "data" / "judge"
RECORDED_DIR: Final = DATA_DIR / "recorded"
#: The attention profile every case is judged with: twelve answers one user gave, as measured.
PROFILE_PATH: Final = DATA_DIR / "profile.json"
JUDGE_GATE: Final = "judge_decision"
#: The user id the reasoning pass is metered under: no user.
EVAL_USER_ID: Final = "eval-judge"

#: Sensitivities the Judge must not read as none or personal.
SENSITIVE: Final = frozenset(
    {
        Sensitivity.HEALTH,
        Sensitivity.FINANCE,
        Sensitivity.CREDENTIALS,
        Sensitivity.SOCIAL_PRIVATE,
    }
)
#: How the corpus writes quiet hours: "22:00-08:00", sometimes followed by a do-not-disturb note.
QUIET_HOURS_PATTERN: Final = re.compile(r"(?P<start>\d\d):00-(?P<end>\d\d):00")
#: The corpus' recipient: no real user.
EVAL_RECIPIENT: Final = "6812f0b3c9a14e2b7d5a91cc"


class RecordedAnswer(TypedDict):
    """One question's answer as a pass gave it."""

    choice: str
    probabilities: NotRequired[dict[str, float]]
    confidence: NotRequired[float | None]


class RecordedPass(TypedDict):
    """What one pass answered, and the hash of the request it answered; None where it was never hashed."""

    request_sha: str | None
    answers: dict[str, RecordedAnswer]
    reason: NotRequired[str | None]


class RecordedCase(TypedDict):
    """What a recorded run answered for one case; reasoning is None where the Decisions pass was sure."""

    case_id: str
    decisions: RecordedPass
    reasoning: RecordedPass | None


@dataclass(frozen=True, slots=True)
class Graded:
    """What the production Judge and Rails made of recorded answers, and how it fared against the gold."""

    disposition: str
    failures: tuple[str, ...]
    decided_by: JudgePass
    verdict: JudgeVerdict


def request_sha(body: Mapping[str, object]) -> str:
    """Hash a Decisions request body as the Decisions API reads it, key order included."""
    canonical = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_profile() -> dict[str, object]:
    """Return the attention profile the corpus is judged with."""
    profile: dict[str, object] = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    return profile


def state_of(case: Case) -> dict[str, object]:
    """Return a case's state with the attention profile on its user, as the Judge is shown it."""
    state: dict[str, object] = json.loads(json.dumps(case.setup["state"]))
    user = state.setdefault("user", {})
    assert isinstance(user, dict)
    user["attention_profile"] = load_profile()
    return state


def decisions_request_sha(state: Mapping[str, object]) -> str:
    """Hash the Decisions request production would send for this state."""
    return request_sha(decisions_body(state, {}, anonymised_state=True))


def recorded_pass(answers: PassAnswers, sha: str | None, reason: str | None = None) -> RecordedPass:
    """Return a pass's answers in the form a recorded run keeps them."""
    recorded: dict[str, RecordedAnswer] = {}
    for question, answer in answers.answers.items():
        entry = RecordedAnswer(choice=answer.choice)
        if answer.probabilities:
            entry["probabilities"] = dict(answer.probabilities)
        if answer.confidence is not None:
            entry["confidence"] = answer.confidence
        recorded[question.value] = entry
    result = RecordedPass(request_sha=sha, answers=recorded)
    if reason is not None:
        result["reason"] = reason
    return result


def pass_answers(recorded: RecordedPass) -> PassAnswers:
    """Read a recorded pass back as the answers production reads."""
    return PassAnswers(
        answers={
            JudgeQuestion(question): ChoiceAnswer(
                answer["choice"],
                answer.get("probabilities", {}),
                answer.get("confidence"),
            )
            for question, answer in recorded["answers"].items()
        }
    )


def _timezone_of(state: Mapping[str, object]) -> Timezone:
    user = state["user"]
    assert isinstance(user, dict)
    return Timezone.parse(str(user["timezone"]))


def _local_now(state: Mapping[str, object]) -> datetime:
    return datetime.fromisoformat(str(state["now"])).replace(tzinfo=_timezone_of(state).tzinfo)


def _quiet_hours(state: Mapping[str, object]) -> QuietHours:
    settings = state.get("attention_settings") or {}
    assert isinstance(settings, dict)
    hours = QUIET_HOURS_PATTERN.match(str(settings["quiet_hours"]))
    if hours is None:
        raise ValueError(f"unreadable quiet hours: {settings['quiet_hours']!r}")
    return QuietHours(enabled=True, start_hour=int(hours["start"]), end_hour=int(hours["end"]))


def is_quiet(state: Mapping[str, object]) -> bool:
    """Whether the case's now falls in the user's quiet hours, where a timely item is held to morning."""
    return _quiet_hours(state).contains(_local_now(state))


def report_of(state: Mapping[str, object]) -> NoticeReport:
    """Return the report the outbox would hold for a case: what its producer and the user's ask say."""
    item = state["item"]
    assert isinstance(item, dict)
    producer = item["producer"]
    asked = state.get("ask") is not None
    reminder = producer == "reminder"
    interrupt_hint = item.get("producer_suggested", {}).get("urgency") == "interrupt"
    kind = {
        "reminder": ProducerKind.REMINDER,
        "workflow": ProducerKind.WORKFLOW,
        "tracked_todo": ProducerKind.TODO,
    }.get(str(producer), ProducerKind.EXECUTOR)
    outcome = {"needs_you": NoticeOutcome.NEEDS_YOU, "failed": NoticeOutcome.FAILED}.get(
        str(item["outcome"]), NoticeOutcome.INFO
    )
    if reminder:
        initiative = Initiative.USER_SCHEDULED
    else:
        initiative = Initiative.ASKED if asked else Initiative.SELF_INITIATED
    return NoticeReport(
        report_id="eval",
        recipient=EVAL_RECIPIENT,
        producer=kind,
        subject=Subject(kind=SubjectKind.ASK, id="eval", label="eval"),
        occurred_at=_local_now(state),
        initiative=initiative,
        delivery_policy=DeliveryPolicy(
            timing=DeliveryTiming.AT_TIME
            if reminder and interrupt_hint
            else DeliveryTiming.WHEN_DONE,
            may_wake=reminder and interrupt_hint,
        ),
        outcome=outcome,
        facts=[str(fact) for fact in item["facts"]],
    )


def gold_disposition(gold: Mapping[str, str]) -> str:
    """Return what the gold labels say should happen to the item."""
    if gold.get("authenticity") == "suspicious":
        return "warn"
    if gold["relevance"] != "new":
        return "record"
    return {"interrupt": "now", "timely": "soon", "routine": "later", "background": "fyi"}[
        gold["urgency"]
    ]


_BY_URGENCY: Final = {
    UrgencyClass.INTERRUPT: "now",
    UrgencyClass.TIMELY: "soon",
    UrgencyClass.ROUTINE: "later",
    UrgencyClass.BACKGROUND: "fyi",
}
_PUSH: Final = frozenset({"now", "soon"})


def disposition_of(report: NoticeReport, verdict: JudgeVerdict) -> str:
    """Return what production does with the item: warn, record, or tell it at its urgency."""
    if verdict.suspicious:
        return "warn"
    decision = decide(report, verdict)
    if decision.kind is DecisionKind.RECORD_ONLY:
        return "record"
    return _BY_URGENCY[decision.urgency]


def failures_of(
    gold: Mapping[str, str], disposition: str, verdict: JudgeVerdict, *, quiet: bool
) -> tuple[str, ...]:
    """Return how a disposition hurts the user against the gold: late, missed, relayed, pushed, exposed."""
    wanted = gold_disposition(gold)
    found: list[str] = []
    if wanted == "now" and disposition == "soon" and quiet:
        found.append("late now->soon (held overnight)")
    elif wanted == "now" and disposition not in _PUSH:
        found.append(f"late now->{disposition}")
    elif wanted == "soon" and disposition not in _PUSH:
        found.append(f"missed soon->{disposition}")
    if wanted == "warn" and disposition != "warn":
        found.append("scam relayed")
    if wanted == "record" and gold["urgency"] in ("interrupt", "timely") and disposition in _PUSH:
        found.append(f"moot pushed ->{disposition}")
    if Sensitivity(gold["sensitivity"]) in SENSITIVE and verdict.sensitivity not in SENSITIVE:
        found.append("exposed")
    return tuple(found)


def regrade(case: Case, decisions: RecordedPass, reasoning: RecordedPass | None) -> Graded:
    """Read a case's recorded answers through the production confidence gate, verdict reader and policy.

    The reasoning pass is read only where the Decisions pass was unsure, as in production.
    """
    state = state_of(case)
    first = pass_answers(decisions)
    confidence = first.gate_confidence()
    if confidence >= JUDGE_CONFIDENCE_GATE:
        answers, decided_by = first, JudgePass.DECISIONS
    elif reasoning is None:
        raise JudgeAnswerError(
            f"{case.id}: the Decisions pass was unsure and no reasoning pass was recorded"
        )
    else:
        answers, decided_by = pass_answers(reasoning), JudgePass.REASONING
    now = _local_now(state)
    verdict = build_verdict(
        answers,
        decided_by=decided_by,
        decisions_confidence=confidence,
        now=now,
        clock=UserClock(_timezone_of(state), _quiet_hours(state)),
        offered_runs=frozenset(),
    )
    disposition = disposition_of(report_of(state), verdict)
    gold = case.expected["gold"]
    return Graded(
        disposition=disposition,
        failures=failures_of(gold, disposition, verdict, quiet=is_quiet(state)),
        decided_by=decided_by,
        verdict=verdict,
    )


def is_graded(case: Case) -> bool:
    """Whether the gold labels judge this case: the Judge's answers matter, and two labellers agree."""
    return bool(case.expected["judge_applicable"]) and not case.expected["ambiguous"]


def judge_decision(case: Case, run: CaseRun) -> float:
    """Pass a run whose regraded disposition hurt no one; fail a run with no recorded disposition at all."""
    end_state = run.end_state or {}
    if "disposition" not in end_state:
        return 0.0
    if not is_graded(case):
        return 1.0
    return 0.0 if end_state["failures"] else 1.0


EXTRA: Final = {JUDGE_GATE: judge_decision}


class JudgeTransport:
    """One case: both passes through the production Judge clients, journaled whole for the recorder."""

    async def run(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        del cfg, tracker
        started = time.monotonic()
        state = state_of(case)
        sha = decisions_request_sha(state)
        try:
            first = await ask_decisions(state, {}, anonymised_state=True)
            decisions = recorded_pass(first, sha)
            reasoning: RecordedPass | None = None
            if first.gate_confidence() < JUDGE_CONFIDENCE_GATE:
                second = await ask_reasoning(state, {}, user_id=EVAL_USER_ID, anonymised_state=True)
                reason = second.free_form.reason if second.free_form else None
                reasoning = recorded_pass(second, None, reason)
            graded = regrade(case, decisions, reasoning)
        except (JudgeUnconfiguredError, httpx.HTTPError, ValueError) as e:
            raise ProviderError(provider.name, f"the Judge could not be asked: {e}") from e
        want = gold_disposition(case.expected["gold"])
        print(
            f"[{'ok' if not graded.failures else 'MISS'}] {case.id}: want={want} got={graded.disposition}"
        )
        end_state = {
            "disposition": graded.disposition,
            "failures": list(graded.failures),
            "decided_by": graded.decided_by.value,
            "decisions": decisions,
            "reasoning": reasoning,
        }
        return CaseRun(
            case_id=case.id,
            provider=provider.name,
            model=JUDGE_FAST_MODEL,
            messages=[
                {"role": "user", "content": str(case.setup["state"]["item"]["facts"][0])},
                {"role": "assistant", "content": graded.disposition},
            ],
            end_state=end_state,
            text=graded.disposition,
            duration_s=time.monotonic() - started,
        )


@register_suite("judge")
class JudgeSuite(TransportSuite):
    name = "judge"
    project = "gaia-judge"
    label = "Judge (attention scenarios)"
    data_dir = DATA_DIR
    extra = EXTRA
    transport_type = JudgeTransport


def recorded_cases(directory: Path = RECORDED_DIR) -> dict[str, RecordedCase]:
    """Return every recorded case under a directory by id; a case recorded twice is refused."""
    recorded: dict[str, RecordedCase] = {}
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row: RecordedCase = json.loads(line)
                if row["case_id"] in recorded:
                    raise ValueError(f"{row['case_id']} is recorded twice")
                recorded[row["case_id"]] = row
    return recorded


def record(run_dir: Path, out_dir: Path = RECORDED_DIR) -> Path:
    """Write a finished run's answers to <out_dir>/<run-id>.jsonl, one case per line.

    A run with an unanswered case is refused: a corpus missing cases reads as fewer misses.
    """
    rows = RunJournal(run_dir.parent, run_dir.name).latest_per_case()
    unanswered = sorted(case_id for case_id, row in rows.items() if not row.get("end_state"))
    if unanswered:
        raise SystemExit(f"{run_dir.name}: no answer for {unanswered}; --resume the run first")
    lines = (
        json.dumps(
            RecordedCase(
                case_id=case_id,
                decisions=rows[case_id]["end_state"]["decisions"],
                reasoning=rows[case_id]["end_state"]["reasoning"],
            ),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for case_id in sorted(rows)
    )
    out = out_dir / f"{run_dir.name}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
