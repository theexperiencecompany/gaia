"""trigger-gate suite: the Inbox desk gate's JEV answers on 420 founder-labelled emails, anonymised.

Each email's request is built by the production builder (gmail_gate_view, gate_request) and
sent through the production client (post_decisions), once by day and once inside quiet
hours. The journal keeps every request's hash and JEV's answers, so the CI sweep
(tests/unit/evals/test_trigger_gate_sweep.py) regrades it through decide_gate itself, and a
prompt edit that is not re-recorded fails there. Every address and link is on a reserved
.example domain; the recorded answers were given on an earlier pseudonymisation of the same
emails and re-keyed to this one, so a re-record is what refreshes them.

Run:  uv run --group backend python -m scripts.evals run --suite trigger-gate --concurrency 6
  TRIGGER_GATE_EVAL_GATE=system|authored (default system)
Record: uv run --group backend python -m scripts.evals.record_trigger_gate <run-id> [...]
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import time
from types import MappingProxyType
from typing import Final, TypedDict

import httpx

from app.constants.hil import HIL_JEV_MODEL_NAME
from app.constants.trigger_gates import (
    SYSTEM_GATE_PRESETS,
    TRIGGER_GATE_QUESTION_KEY,
    TRIGGER_GATE_SKIP_PROBABILITY,
    TRIGGER_GATE_URGENT_PROBABILITY,
    TRIGGER_GATE_URGENT_QUESTION_KEY,
    GateAuthor,
    SystemGatePreset,
)
from app.models.jev_models import JevDecisionsResponse
from app.models.trigger_gate_models import AuthoredGate, SystemGate, TriggerGate
from app.services.hil.jev_client import JevUnconfiguredError, post_decisions
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


class EvalGate(StrEnum):
    """Which gate a run asked about, TRIGGER_GATE_EVAL_GATE; journaled on every row."""

    SYSTEM = "system"
    AUTHORED = "authored"


class GateMode(StrEnum):
    """The user's clock when the email arrives: by day, or inside their quiet hours."""

    DAY = "day"
    QUIET = "quiet"


_DESK = SYSTEM_GATE_PRESETS[SystemGatePreset.INBOX_DESK]
# The authored template with the desk's own intent as its condition; both send the desk's job text.
EVAL_GATES: Final[Mapping[EvalGate, TriggerGate]] = MappingProxyType(
    {
        EvalGate.SYSTEM: SystemGate(preset=SystemGatePreset.INBOX_DESK),
        EvalGate.AUTHORED: AuthoredGate(condition=_DESK.condition, author=GateAuthor.GAIA),
    }
)
DESK_AUTOMATION: Final = _DESK.automation
# The setup key that says whether the user sent a message in a continued email's thread.
USER_WROTE_IN_THREAD: Final = "user_wrote_in_thread"


class AskedRequest(TypedDict):
    """One request JEV answered: the hash of the body it read, and its answer."""

    request_sha: str
    response: dict[str, object]


class GateJournalFields(TypedDict):
    """What a row is regraded from: the gate asked, and each mode's request and answer."""

    gate: str
    outcome: str
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


def gate_requests(
    gate: TriggerGate, message: Mapping[str, object]
) -> dict[GateMode, tuple[dict[str, object], dict[str, dict[str, object]]]]:
    """Build both modes' requests for one email with the production gate view and builder."""
    view = gmail_gate_view(message)
    if view is None:
        raise ValueError("corpus message is not a readable Gmail payload")
    return {
        mode: gate_request(gate, view.as_event(), DESK_AUTOMATION, quiet=mode is GateMode.QUIET)
        for mode in GateMode
    }


def day_outcome(gate: TriggerGate, setup: Mapping[str, object], body: JevDecisionsResponse) -> str:
    """Return "skip" or "run" by day; a conversation always runs. The sweep checks decide_gate agrees.

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
    return "skip" if skip_probability(gate, answer) >= TRIGGER_GATE_SKIP_PROBABILITY else "run"


def quiet_wakes(body: JevDecisionsResponse) -> bool:
    """Return whether the quiet-hours answer wakes the user. The sweep checks decide_gate agrees."""
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


class GateTransport:
    """One email: both modes' requests through the production client, journaled whole."""

    def __init__(self) -> None:
        self._gate = EvalGate(os.environ.get("TRIGGER_GATE_EVAL_GATE", EvalGate.SYSTEM))

    async def run(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        del cfg, tracker
        start = time.monotonic()
        gate = EVAL_GATES[self._gate]
        message = case.setup["message"]
        asked: dict[str, AskedRequest] = {}
        answers: dict[GateMode, JevDecisionsResponse] = {}
        for mode, (state, questions) in gate_requests(gate, message).items():
            try:
                body = await post_decisions(state, questions)
            except (JevUnconfiguredError, httpx.HTTPError, ValueError) as e:
                raise ProviderError(provider.name, f"decisions API failed ({mode}): {e}") from e
            answers[mode] = body
            asked[mode] = AskedRequest(
                request_sha=request_sha(jev_body(state, questions)),
                response=body.model_dump(mode="json", exclude_none=True),
            )
        outcome = day_outcome(gate, case.setup, answers[GateMode.DAY])
        duration_s = time.monotonic() - start
        want = str(case.expected.get("outcome"))
        print(f"[{'ok' if outcome == want else 'MISS'}] {case.id}: want={want} got={outcome}")
        fields = GateJournalFields(gate=self._gate.value, outcome=outcome, requests=asked)
        tokens = [body.tokens() for body in answers.values()]
        return CaseRun(
            case_id=case.id,
            provider=provider.name,
            model=HIL_JEV_MODEL_NAME,
            messages=[
                {"role": "user", "content": str(message.get("subject") or "")},
                {"role": "assistant", "content": outcome},
            ],
            end_state=dict(fields),
            text=outcome,
            tokens_in=sum(t[0] for t in tokens),
            tokens_out=sum(t[1] for t in tokens),
            duration_s=duration_s,
        )


@register_suite("trigger-gate")
class TriggerGateSuite(TransportSuite):
    name = "trigger-gate"
    project = "gaia-trigger-gate"
    label = "Trigger gate (Inbox desk)"
    data_dir = DATA_DIR
    extra = EXTRA
    transport_type = GateTransport
