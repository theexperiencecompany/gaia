"""Re-grade a finished run from its journal, without calling the agent again.

Scoring is a pure function of (case, run), and the journal stores the full run —
messages, tool calls, end state, text. So a gate fix does not need the model: the
existing cases can be re-graded for free, and the delta shows exactly what the
fix changed.

The journal is append-only and is never rewritten. Re-scoring writes a sibling
file and reports; adopting a new score is a separate, deliberate act.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from .journal import RunJournal
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
class RescoreResult:
    run_id: str
    suite: str
    deltas: list[CaseDelta] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def changed(self) -> list[CaseDelta]:
        return [d for d in self.deltas if d.changed]

    def render(self) -> str:
        was_passed = sum(1 for d in self.deltas if d.was == "passed")
        now_passed = sum(1 for d in self.deltas if d.now == "passed")
        lines = [
            "",
            "=" * 74,
            f"RESCORE  {self.suite} · {self.run_id}",
            "=" * 74,
            f"  {len(self.deltas)} case(s) re-graded from the journal — no model calls",
            f"  passed: {was_passed} -> {now_passed}   changed: {len(self.changed)}",
        ]
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


def rescore(runs_dir: Path, run_id: str, cfg: object) -> RescoreResult:
    journal = RunJournal(runs_dir, run_id)
    meta = journal.load_meta()
    if meta is None:
        raise SystemExit(f"no run.json for {run_id}")
    factory = SUITE_REGISTRY.get(meta.suite)
    if factory is None:
        raise SystemExit(f"suite {meta.suite!r} is not registered")
    suite: Suite = factory(cfg)
    cases = {c.id: c for c in suite.load_cases(cfg)}

    result = RescoreResult(run_id=run_id, suite=meta.suite)
    for record in journal.latest_per_case().values():
        case_id = str(record["case_id"])
        case = cases.get(case_id)
        if case is None:
            result.skipped.append(f"{case_id} (no longer defined)")
            continue
        if record.get("status") == "errored":
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
        result.deltas.append(
            CaseDelta(
                case_id=case_id,
                was=str(record.get("status", "?")),
                now=_status_from_scores(case, scores, None),
                old_scores=record.get("scores") or {},
                new_scores=scores,
            )
        )
    return result


def write_sibling(runs_dir: Path, result: RescoreResult) -> Path:
    """Record the re-grade beside the journal, never over it."""
    path = runs_dir / result.run_id / "rescore.json"
    path.write_text(
        json.dumps(
            {
                "run_id": result.run_id,
                "suite": result.suite,
                "cases": [
                    {
                        "case_id": d.case_id,
                        "was": d.was,
                        "now": d.now,
                        "old_scores": d.old_scores,
                        "new_scores": d.new_scores,
                    }
                    for d in result.deltas
                ],
                "skipped": result.skipped,
            },
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    return path
