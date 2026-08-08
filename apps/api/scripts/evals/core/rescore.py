"""Re-grade a finished run from its journal, without calling the agent again.

Scoring is a pure function of (case, run), and the journal stores the full run —
messages, tool calls, end state, text. So a gate fix does not need the model: the
existing cases can be re-graded for free, and the delta shows exactly what the
fix changed.

Re-grading has two steps, in this order and never the other way round. First,
*was the test conducted at all* — a case that hit an outage and produced nothing
is not a wrong answer, and re-scoring its empty transcript would only re-affirm
the lie by grading a blank as a miss. Only then is what is left actually graded.

The journal is append-only and is never rewritten. Re-scoring writes a sibling
file and reports; adopting a new score is a separate, deliberate act.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from . import faults
from .journal import RunJournal
from .providers import EvalConfig
from .runner import SUITE_REGISTRY, Suite, _status_from_scores
from .types import CaseRun

# Fields a scorer may need that older journals never stored. Re-scoring a record
# that lacks them would grade a blank and call it a failure.
REQUIRED_FIELDS = ("messages", "tool_calls")

# Gates whose evidence lives in CaseRun.raw — the SSE frame summary — which the
# journal does not store. Re-scoring them reads an empty list and reports a
# perfectly good case as failed, which is the same "nothing to inspect" defect
# the scorers themselves had. A case gating on one of these must be re-run.
GATES_NEEDING_RAW = {"suggestion", "openui"}


@dataclass
class CaseDelta:
    case_id: str
    was: str
    now: str
    old_scores: dict[str, float] = field(default_factory=dict)
    new_scores: dict[str, float] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return self.was != self.now


@dataclass
class Accuracy:
    """Passed over cases that actually produced an answer."""

    passed: int = 0
    graded: int = 0

    @property
    def pct(self) -> float:
        return self.passed / self.graded * 100 if self.graded else 0.0

    def __str__(self) -> str:
        if not self.graded:
            return "no cases graded"
        return f"{self.passed}/{self.graded} ({self.pct:.1f}%)"


def _accuracy(tally: Counter[str]) -> Accuracy:
    return Accuracy(passed=tally["passed"], graded=tally["passed"] + tally["failed"])


@dataclass
class RescoreResult:
    run_id: str
    suite: str
    deltas: list[CaseDelta] = field(default_factory=list)
    reclassified: list[CaseDelta] = field(default_factory=list)
    """Cases re-labelled ``errored`` because they never ran — see :mod:`faults`.

    Kept apart from ``deltas``: those are re-graded answers, these are answers
    that never existed. Averaging the second kind is the defect being undone.
    """

    skipped: list[str] = field(default_factory=list)
    before: Counter[str] = field(default_factory=Counter)
    after: Counter[str] = field(default_factory=Counter)

    @property
    def changed(self) -> list[CaseDelta]:
        return [d for d in self.deltas if d.changed]

    @property
    def accuracy_before(self) -> Accuracy:
        return _accuracy(self.before)

    @property
    def accuracy_after(self) -> Accuracy:
        return _accuracy(self.after)

    def render(self) -> str:
        lines = [
            "",
            "=" * 74,
            f"RESCORE  {self.suite} · {self.run_id}",
            "=" * 74,
            f"  {len(self.deltas)} case(s) re-graded from the journal — no model calls",
            f"  accuracy: {self.accuracy_before}  ->  {self.accuracy_after}",
        ]
        if self.reclassified:
            lines.append(
                f"\n  {len(self.reclassified)} case(s) never ran and were graded as wrong "
                "answers — re-labelled errored and removed from the denominator:"
            )
            for delta in self.reclassified[:15]:
                lines.append(f"    {delta.was:>7} -> {delta.now:<7} {delta.case_id}")
        if self.changed:
            lines.append(f"\n  {len(self.changed)} case(s) changed verdict:")
            for delta in self.changed[:40]:
                lines.append(f"    {delta.was:>7} -> {delta.now:<7} {delta.case_id}")
        if self.skipped:
            lines.append(
                f"\n  {len(self.skipped)} case(s) could not be re-scored — the journal predates "
                f"the fields their gates read; re-run those instead:"
            )
            lines += [f"    {case_id}" for case_id in self.skipped[:15]]
        return "\n".join(lines + [""])


def _run_from_record(record: dict[str, Any]) -> CaseRun:
    tokens = record.get("tokens") or {}
    return CaseRun(
        case_id=str(record["case_id"]),
        messages=record.get("messages") or [],
        tool_calls=record.get("tool_calls") or [],
        end_state=record.get("end_state"),
        text=str(record.get("text") or ""),
        raw=record.get("raw") or [],
        provider=str(record.get("provider") or ""),
        model=str(record.get("model") or ""),
        tokens_in=int(tokens.get("input", 0)),
        tokens_out=int(tokens.get("output", 0)),
        duration_s=float(record.get("duration_s") or 0.0),
        error=record.get("error") if record.get("status") == "errored" else None,
    )


def reclassify(runs_dir: Path, run_id: str) -> RescoreResult:
    """Correct the *status* of a finished run's records — no suite, no cases.

    This is the half of a re-grade that needs nothing but the journal: whether a
    case ran at all is a property of the record, not of the case definition or of
    any gate. Keeping it separate is what lets history be corrected for runs
    whose suite no longer loads, whose dataset is gone, or whose cases have since
    been rewritten — which is most of the runs that need correcting.
    """
    journal = RunJournal(runs_dir, run_id)
    meta = journal.load_meta()
    result = RescoreResult(run_id=run_id, suite=meta.suite if meta else "?")
    for record in journal.latest_per_case().values():
        was = str(record.get("status", "?"))
        result.before[was] += 1
        if was != "errored" and faults.never_conducted(record):
            result.reclassified.append(
                CaseDelta(
                    case_id=str(record["case_id"]),
                    was=was,
                    now="errored",
                    old_scores=record.get("scores") or {},
                )
            )
            result.after["errored"] += 1
        else:
            result.after[was] += 1
    return result


def rescore(runs_dir: Path, run_id: str, cfg: EvalConfig) -> RescoreResult:
    journal = RunJournal(runs_dir, run_id)
    meta = journal.load_meta()
    if meta is None:
        raise SystemExit(f"no run.json for {run_id}")
    factory = SUITE_REGISTRY.get(meta.suite)
    if factory is None:
        raise SystemExit(f"suite {meta.suite!r} is not registered")
    suite: Suite = factory(cfg)
    cases = {c.id: c for c in suite.load_cases(cfg)}

    result = reclassify(runs_dir, run_id)
    never_ran = {d.case_id for d in result.reclassified}
    for record in journal.latest_per_case().values():
        case_id = str(record["case_id"])
        # A case that never ran has no answer to re-grade. Scoring its empty
        # transcript is how an outage gets re-affirmed as a wrong answer by the
        # very tool meant to correct it.
        if case_id in never_ran or record.get("status") == "errored":
            continue
        case = cases.get(case_id)
        if case is None:
            result.skipped.append(f"{case_id} (no longer defined)")
            continue
        if all(not record.get(f) for f in REQUIRED_FIELDS) and not record.get("text"):
            result.skipped.append(f"{case_id} (journal has no transcript)")
            continue
        needs_raw = GATES_NEEDING_RAW.intersection(case.gates)
        if needs_raw and not record.get("raw"):
            result.skipped.append(
                f"{case_id} (gates on {sorted(needs_raw)}, whose evidence is not journaled)"
            )
            continue
        run = _run_from_record(record)
        scores = suite.score(case, run)
        was = str(record.get("status", "?"))
        now = _status_from_scores(case, scores, None)
        result.deltas.append(
            CaseDelta(
                case_id=case_id,
                was=was,
                now=now,
                old_scores=record.get("scores") or {},
                new_scores=scores,
            )
        )
        if now != was:
            result.after[was] -= 1
            result.after[now] += 1
    return result


def _as_json(delta: CaseDelta) -> dict[str, Any]:
    return {
        "case_id": delta.case_id,
        "was": delta.was,
        "now": delta.now,
        "old_scores": delta.old_scores,
        "new_scores": delta.new_scores,
    }


def write_sibling(runs_dir: Path, result: RescoreResult) -> Path:
    """Record the re-grade beside the journal, never over it."""
    path = runs_dir / result.run_id / "rescore.json"
    path.write_text(
        json.dumps(
            {
                "run_id": result.run_id,
                "suite": result.suite,
                "accuracy_before": {
                    "passed": result.accuracy_before.passed,
                    "graded": result.accuracy_before.graded,
                },
                "accuracy_after": {
                    "passed": result.accuracy_after.passed,
                    "graded": result.accuracy_after.graded,
                },
                "reclassified": [_as_json(d) for d in result.reclassified],
                "cases": [_as_json(d) for d in result.deltas],
                "skipped": result.skipped,
            },
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def reclassify_all(runs_dir: Path) -> list[RescoreResult]:
    """Correct every journal on disk, newest run last. No models, no network."""
    return [
        reclassify(runs_dir, run.name)
        for run in sorted(runs_dir.iterdir())
        if (run / "journal.jsonl").exists()
    ]


def render_by_suite(results: list[RescoreResult]) -> str:
    """Corrected accuracy per suite, before vs after — the number to publish."""
    before: dict[str, Counter[str]] = {}
    after: dict[str, Counter[str]] = {}
    contaminated: Counter[str] = Counter()
    for result in results:
        before.setdefault(result.suite, Counter()).update(result.before)
        after.setdefault(result.suite, Counter()).update(result.after)
        contaminated[result.suite] += len(result.reclassified)

    lines = [
        "",
        "=" * 78,
        "CORRECTED ACCURACY — cases that never ran removed from the denominator",
        "=" * 78,
        f"  {'suite':13} {'never ran':>10}   {'published':>18}   {'corrected':>18}",
    ]
    for suite in sorted(before):
        was, now = _accuracy(before[suite]), _accuracy(after[suite])
        lines.append(f"  {suite:13} {contaminated[suite]:>10}   {was!s:>18}   {now!s:>18}")
    total_before: Counter[str] = Counter()
    total_after: Counter[str] = Counter()
    for tally in before.values():
        total_before.update(tally)
    for tally in after.values():
        total_after.update(tally)
    lines.append(
        f"  {'ALL':13} {sum(contaminated.values()):>10}   "
        f"{_accuracy(total_before)!s:>18}   {_accuracy(total_after)!s:>18}"
    )
    return "\n".join(lines + [""])
