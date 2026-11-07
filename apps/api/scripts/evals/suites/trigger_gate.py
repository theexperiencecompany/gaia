"""The trigger-gate corpus, 420 founder emails, anonymised, and 10 synthetic, asked two ways.

email-verdict: each email's verdict request by day (bucket) and inside quiet hours (bucket and
urgency), built by email_verdict.verdict_request as the desk gate and the desk's sweep send it.
tests/unit/evals/test_email_verdict_sweep.py regrades its buckets, and
tests/unit/evals/test_trigger_gate_sweep.py regrades the desk gate through decide_gate. Each
recorded pass joins a day pass of the unchanged bucket request (asked 2026-11-06) to a quiet
pass (asked 2026-11-07).

trigger-gate: the authored gate template with the desk's condition, by day and inside quiet
hours, built by gate_request; test_trigger_gate_sweep.py regrades it too.

Each request goes through the production client (post_decisions), and the journal keeps its
hash and JEV's answer, so an edit that is not re-recorded fails the sweep. Every address and
link is on a reserved .example domain.

Run:  uv run --group backend python -m scripts.evals run --suite email-verdict --concurrency 6
      uv run --group backend python -m scripts.evals run --suite trigger-gate --concurrency 6
Record: uv run --group backend python -m scripts.evals.record_trigger_gate <run-id> [...]
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import time
from typing import Final, TypedDict

import httpx

from app.constants.desk_buckets import DESK_AUTOMATION
from app.constants.hil import HIL_JEV_MODEL_NAME
from app.constants.trigger_gates import (
    SYSTEM_GATE_CONDITIONS,
    TRIGGER_GATE_QUESTION_KEY,
    TRIGGER_GATE_SKIP_PROBABILITY,
    TRIGGER_GATE_URGENT_PROBABILITY,
    TRIGGER_GATE_URGENT_QUESTION_KEY,
    GateAuthor,
    SystemGatePreset,
)
from app.models.jev_models import JevDecisionsResponse
from app.models.trigger_gate_models import AuthoredGate, SystemGate
from app.services.hil.jev_client import JevUnconfiguredError, post_decisions
from app.services.mail.email_verdict import read_verdict, verdict_request
from app.services.triggers.gmail_signals import gmail_gate_view
from app.services.triggers.trigger_gate import gate_request, skip_probability, urgency
from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.journal import RunJournal
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import register_suite
from scripts.evals.core.transport_suite import TransportSuite
from scripts.evals.core.types import Case, CaseRun, ProviderError

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "trigger-gate"
RECORDED_DIR = DATA_DIR / "recorded"
VERDICTS_RECORDED_DIR = DATA_DIR / "recorded-verdicts"
# Journaled where production leaves an email unbucketed: no verdict, or junk under the line.
UNBUCKETED: Final = "unbucketed"

DESK_GATE: Final = SystemGate(preset=SystemGatePreset.INBOX_DESK)
# The authored template with the desk's own intent as its condition, asked of the desk's job text.
AUTHORED_DESK_GATE: Final = AuthoredGate(
    condition=SYSTEM_GATE_CONDITIONS[SystemGatePreset.INBOX_DESK], author=GateAuthor.GAIA
)
# The setup key that says whether the user sent a message in a continued email's thread.
USER_WROTE_IN_THREAD: Final = "user_wrote_in_thread"


class GateMode(StrEnum):
    """The user's clock when the email arrives: by day, or inside their quiet hours."""

    DAY = "day"
    QUIET = "quiet"


class AskedRequest(TypedDict):
    """One request JEV answered: the hash of the body it read, and its answer."""

    request_sha: str
    response: dict[str, object]


class GateJournalFields(TypedDict):
    """What an authored-gate row is regraded from: each mode's request and answer."""

    outcome: str
    requests: dict[str, AskedRequest]


class VerdictJournalFields(TypedDict):
    """What a verdict row is regraded from: each mode's request and answer, and the day bucket."""

    bucket: str
    requests: dict[str, AskedRequest]


def record(run_dir: Path, out_dir: Path = RECORDED_DIR) -> Path:
    """Write a finished run's regrade inputs to <out_dir>/<run-id>.jsonl, one email per line.

    A run with an unanswered email is refused: a pass missing emails reads as fewer skips.
    """
    rows = RunJournal(run_dir.parent, run_dir.name).latest_per_case()
    unanswered = sorted(case_id for case_id, row in rows.items() if not row.get("end_state"))
    if unanswered:
        raise SystemExit(f"{run_dir.name}: no answer for {unanswered}; --resume the run first")
    out = out_dir / f"{run_dir.name}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = (
        json.dumps({"case_id": case_id, **rows[case_id]["end_state"]}, ensure_ascii=False)
        for case_id in sorted(rows)
    )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def request_sha(body: Mapping[str, object]) -> str:
    """Hash a Decisions request body as JEV reads it, key order included."""
    canonical = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def jev_body(state: Mapping[str, object], questions: Mapping[str, object]) -> dict[str, object]:
    """Return the body post_decisions sends for this state and these questions."""
    return {"model": HIL_JEV_MODEL_NAME, "state": state, "questions": questions}


def _event(message: Mapping[str, object]) -> dict[str, object]:
    view = gmail_gate_view(message)
    if view is None:
        raise ValueError("corpus message is not a readable Gmail payload")
    return view.as_event()


def gate_requests(
    message: Mapping[str, object],
) -> dict[GateMode, tuple[dict[str, object], dict[str, dict[str, object]]]]:
    """Build both modes' authored-gate requests for one email with the production builder."""
    event = _event(message)
    return {
        mode: gate_request(AUTHORED_DESK_GATE, event, DESK_AUTOMATION, quiet=mode is GateMode.QUIET)
        for mode in GateMode
    }


def verdict_requests(
    message: Mapping[str, object],
) -> dict[GateMode, tuple[dict[str, object], dict[str, dict[str, object]]]]:
    """Build both modes' verdict requests for one email with the production builder."""
    event = _event(message)
    return {mode: verdict_request(event, quiet=mode is GateMode.QUIET) for mode in GateMode}


def graded_bucket(body: JevDecisionsResponse, mode: GateMode = GateMode.DAY) -> str:
    """Return the bucket production reads from an answer, or UNBUCKETED where it reads none."""
    try:
        bucket = read_verdict(body, quiet=mode is GateMode.QUIET).bucket
    except ValueError:
        return UNBUCKETED
    return bucket.value if bucket else UNBUCKETED


def day_outcome(setup: Mapping[str, object], body: JevDecisionsResponse) -> str:
    """Return the authored gate's "skip" or "run" by day; a conversation always runs.

    A continuation is a conversation when setup says the user wrote in its thread.
    """
    message = setup["message"]
    if not isinstance(message, Mapping):
        raise ValueError("corpus case has no message")
    view = gmail_gate_view(message)
    if view is None or view.continues_thread is None:
        return "run"
    if view.continues_thread and setup.get(USER_WROTE_IN_THREAD) is not False:
        return "run"
    answer = body.answers[TRIGGER_GATE_QUESTION_KEY]
    p_skip = skip_probability(AUTHORED_DESK_GATE, answer)
    return "skip" if p_skip >= TRIGGER_GATE_SKIP_PROBABILITY else "run"


def quiet_wakes(body: JevDecisionsResponse) -> bool:
    """Return whether an answer's urgency wakes the user. The sweep checks decide_gate agrees."""
    answer = body.answers[TRIGGER_GATE_URGENT_QUESTION_KEY]
    return urgency(answer).probability >= TRIGGER_GATE_URGENT_PROBABILITY


def quiet_wake(case: Case, run: CaseRun) -> float:
    """Fail a run whose quiet-hours answer wakes the user for mail that can wait, or that has none."""
    asked = (run.end_state or {}).get("requests", {}).get(GateMode.QUIET)
    if asked is None:
        return 0.0
    woke = quiet_wakes(JevDecisionsResponse.model_validate(asked["response"]))
    return 0.0 if woke and not case.expected["urgent"] else 1.0


EXTRA = {
    "gate_outcome": lambda case, run: (
        1.0 if (run.end_state or {}).get("outcome") == case.expected.get("outcome") else 0.0
    ),
    "quiet_wake": quiet_wake,
}


async def _ask(
    provider: ProviderConfig,
    state: dict[str, object],
    questions: dict[str, dict[str, object]],
    what: str,
) -> tuple[JevDecisionsResponse, AskedRequest]:
    try:
        body = await post_decisions(state, questions)
    except (JevUnconfiguredError, httpx.HTTPError, ValueError) as e:
        raise ProviderError(provider.name, f"decisions API failed ({what}): {e}") from e
    asked = AskedRequest(
        request_sha=request_sha(jev_body(state, questions)),
        response=body.model_dump(mode="json", exclude_none=True),
    )
    return body, asked


def _case_run(
    case: Case,
    provider: ProviderConfig,
    graded: str,
    end_state: Mapping[str, object],
    bodies: list[JevDecisionsResponse],
    started: float,
) -> CaseRun:
    tokens = [body.tokens() for body in bodies]
    return CaseRun(
        case_id=case.id,
        provider=provider.name,
        model=HIL_JEV_MODEL_NAME,
        messages=[
            {"role": "user", "content": str(case.setup["message"].get("subject") or "")},
            {"role": "assistant", "content": graded},
        ],
        end_state=dict(end_state),
        text=graded,
        tokens_in=sum(t[0] for t in tokens),
        tokens_out=sum(t[1] for t in tokens),
        duration_s=time.monotonic() - started,
    )


class GateTransport:
    """One email: both modes' authored-gate requests through the production client, journaled whole."""

    async def run(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        del cfg, tracker
        started = time.monotonic()
        asked: dict[str, AskedRequest] = {}
        answers: dict[GateMode, JevDecisionsResponse] = {}
        for mode, (state, questions) in gate_requests(case.setup["message"]).items():
            answers[mode], asked[mode] = await _ask(provider, state, questions, mode)
        outcome = day_outcome(case.setup, answers[GateMode.DAY])
        want = str(case.expected.get("outcome"))
        print(f"[{'ok' if outcome == want else 'MISS'}] {case.id}: want={want} got={outcome}")
        fields = GateJournalFields(outcome=outcome, requests=asked)
        return _case_run(case, provider, outcome, fields, list(answers.values()), started)


@register_suite("trigger-gate")
class TriggerGateSuite(TransportSuite):
    name = "trigger-gate"
    project = "gaia-trigger-gate"
    label = "Trigger gate (authored template)"
    data_dir = DATA_DIR
    extra = EXTRA
    transport_type = GateTransport


class VerdictTransport:
    """One email: both modes' verdict requests through the production client, journaled whole."""

    async def run(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        del cfg, tracker
        started = time.monotonic()
        asked: dict[str, AskedRequest] = {}
        answers: dict[GateMode, JevDecisionsResponse] = {}
        for mode, (state, questions) in verdict_requests(case.setup["message"]).items():
            answers[mode], asked[mode] = await _ask(provider, state, questions, mode)
        bucket = graded_bucket(answers[GateMode.DAY])
        want = str(case.expected.get("bucket"))
        print(f"[{'ok' if bucket == want else 'MISS'}] {case.id}: want={want} got={bucket}")
        fields = VerdictJournalFields(bucket=bucket, requests=asked)
        return _case_run(case, provider, bucket, fields, list(answers.values()), started)


BUCKET_GATE: Final = "email_bucket"
# The corpus declares the gate's scorers, so the verdict suite still implements them.
VERDICT_EXTRA = {
    **EXTRA,
    BUCKET_GATE: lambda case, run: (
        1.0 if (run.end_state or {}).get("bucket") == case.expected["bucket"] else 0.0
    ),
}


@register_suite("email-verdict")
class EmailVerdictSuite(TransportSuite):
    """The trigger-gate corpus asked the one email verdict, graded by its bucket alone."""

    name = "email-verdict"
    project = "gaia-email-verdict"
    label = "Email verdict (desk bucket and urgency)"
    data_dir = DATA_DIR
    extra = VERDICT_EXTRA
    transport_type = VerdictTransport

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        """Return the corpus with each case gated on its bucket instead of the gate's outcome."""
        return [
            replace(case, expected={**case.expected, "score": {"gates": [BUCKET_GATE]}})
            for case in super().load_cases(cfg)
        ]
