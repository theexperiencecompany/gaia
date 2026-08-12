"""Compare a finished run against the suite's recorded baseline.

The baseline files existed and nothing ever read them for a verdict, so a run
produced a number floating in space and a regression shipped silently. This is
the comparison: it answers "did this change make it worse", which is the only
question an eval suite exists to answer.

Re-baselining is deliberate (``--rebaseline``). A baseline that updates itself
absorbs every regression it was meant to catch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from .journal import RunJournal, RunMeta

BASELINES_DIR = Path(__file__).resolve().parent.parent / "baselines"

# Pass rates move on their own: the agent is non-deterministic and providers
# drift. This is the drop that means something rather than noise.
REGRESSION_MARGIN = 0.05

# Below this many graded cases a rate is an anecdote, so a "drop" is one case
# flipping. Reported, never failed on.
MIN_CASES_FOR_VERDICT = 8


@dataclass
class Comparison:
    suite: str
    accuracy: float
    graded: int
    errored: int
    baseline_accuracy: float | None
    baseline_run: str = ""
    per_category: dict[str, tuple[int, int]] = field(default_factory=dict)
    regressions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    provisional: str = ""
    """Why the recorded baseline is not a trustworthy reference point, if it isn't.

    A baseline is a claim about the agent, so it is only as good as the stack the
    run was made against. Every baseline on disk today was recorded from a native
    API with no JuiceFS mount — an agent with no working file ops, sandbox or
    artifact streaming — which makes a later comparison report an improvement
    that is really just a working stack. Recording the reason keeps that visible
    at the moment of comparison instead of in someone's memory.
    """

    @property
    def ok(self) -> bool:
        return not self.regressions

    @property
    def delta(self) -> float | None:
        if self.baseline_accuracy is None:
            return None
        return self.accuracy - self.baseline_accuracy

    def render(self) -> str:
        lines = ["", "=" * 74]
        if self.baseline_accuracy is None:
            lines.append(
                f"BASELINE  {self.suite}: none recorded — run with --rebaseline to set one"
            )
            lines.append("=" * 74)
            lines.append(f"  this run: {self.accuracy:.1%} over {self.graded} graded")
            return "\n".join(lines + [""])
        arrow = "▲" if (self.delta or 0) >= 0 else "▼"
        if self.provisional:
            headline = "PROVISIONAL BASELINE"
        else:
            headline = "REGRESSION" if self.regressions else "BASELINE OK"
        lines.append(
            f"{headline}  {self.suite}: {self.accuracy:.1%} vs {self.baseline_accuracy:.1%} "
            f"{arrow} {abs(self.delta or 0):.1%}"
        )
        lines.append("=" * 74)
        if self.provisional:
            lines.append(f"  ⚠ this comparison means little: {self.provisional}")
        lines.append(
            f"  graded {self.graded} · errored {self.errored} · baseline from {self.baseline_run}"
        )
        for regression in self.regressions:
            lines.append(f"  ▼ {regression}")
        for note in self.notes:
            lines.append(f"    {note}")
        return "\n".join(lines + [""])


#: What counts in the denominator.
#:
#: ``skipped`` is in it. A skip means the benchmark asked something we have no way
#: to answer, which is a wrong answer worth zero — dropping it from the denominator
#: is how a 36/165 became a published 40.4%. ``errored`` stays out: an outage
#: measured nothing, so there is no answer to be wrong.
GRADED_STATUSES = ("passed", "failed", "skipped")


def _accuracy(records: list[dict[str, Any]]) -> tuple[float, int, int]:
    graded = [r for r in records if r.get("status") in GRADED_STATUSES]
    errored = sum(1 for r in records if r.get("status") == "errored")
    if not graded:
        return 0.0, 0, errored
    passed = sum(1 for r in graded if r.get("status") == "passed")
    return passed / len(graded), len(graded), errored


def _by_category(records: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for record in records:
        if record.get("status") not in GRADED_STATUSES:
            continue
        category = str(record.get("category") or "uncategorised")
        passed, total = out.get(category, (0, 0))
        out[category] = (passed + (record.get("status") == "passed"), total + 1)
    return out


def path_for(suite: str) -> Path:
    return BASELINES_DIR / f"{suite}.json"


def compare(suite: str, records: list[dict[str, Any]]) -> Comparison:
    """Score this run against the stored baseline, per suite and per category."""
    accuracy, graded, errored = _accuracy(records)
    comparison = Comparison(
        suite=suite,
        accuracy=accuracy,
        graded=graded,
        errored=errored,
        baseline_accuracy=None,
        per_category=_by_category(records),
    )
    stored_path = path_for(suite)
    if not stored_path.exists():
        return comparison
    stored = json.loads(stored_path.read_text())
    comparison.baseline_accuracy = float(stored.get("baseline_accuracy", 0.0))
    comparison.baseline_run = str(stored.get("run_id", "?"))
    comparison.provisional = str(stored.get("provisional") or "")

    if graded < MIN_CASES_FOR_VERDICT:
        comparison.notes.append(
            f"only {graded} graded case(s) — too few to call a regression, reporting only"
        )
        return comparison

    previous_graded = int(stored.get("graded", 0) or 0)
    if previous_graded and abs(graded - previous_graded) > previous_graded * 0.05:
        # Making a benchmark more honest moves the denominator, and a bigger
        # denominator with the same numerator reads exactly like the agent got
        # worse. It didn't; the measurement did. Say so before the rate is read.
        comparison.notes.append(
            f"denominator moved {previous_graded} -> {graded} case(s): the rate is over a "
            f"different set, so this comparison measures the harness, not the agent"
        )

    # Rounded: accuracies are ratios of small integers, and 0.9 - 0.05 is
    # 0.8500000000000001 in binary floating point — so a drop of exactly the
    # margin, which this check is written to allow, was reported as a
    # regression. The tolerance is the only thing float noise may not decide.
    if round(comparison.accuracy, 9) < round(comparison.baseline_accuracy - REGRESSION_MARGIN, 9):
        comparison.regressions.append(
            f"suite accuracy {comparison.accuracy:.1%} is more than "
            f"{REGRESSION_MARGIN:.0%} below the baseline {comparison.baseline_accuracy:.1%}"
        )

    stored_categories = stored.get("per_category") or {}
    for category, (passed, total) in sorted(comparison.per_category.items()):
        previous = stored_categories.get(category)
        if not previous or total < MIN_CASES_FOR_VERDICT:
            continue
        was = float(previous[0]) / float(previous[1]) if previous[1] else 0.0
        now = passed / total
        # Rounded like the suite check above: an exact-margin drop must not be
        # reported as a regression because binary floating point rounds the
        # subtraction differently.
        if round(now, 9) < round(was - REGRESSION_MARGIN, 9):
            comparison.regressions.append(
                f"{category}: {passed}/{total} ({now:.0%}) vs baseline {was:.0%}"
            )
    return comparison


def _reject_unbaselineable(meta: RunMeta, run_id: str) -> None:
    """Refuse to enshrine a run whose numbers are known not to mean anything.

    Both of these have already happened: a run whose token accounting was wrong
    was kept for the record with ``excluded`` set, and a run aborted by a dead
    backend holds only the cases that ran before the outage. Either one, made
    the baseline, becomes the bar every later run is judged against.
    """
    if meta.excluded:
        raise SystemExit(
            f"refusing to baseline {run_id}: the run is excluded from aggregation — {meta.excluded}"
        )
    if meta.status != "finished":
        raise SystemExit(
            f"refusing to baseline {run_id}: status is {meta.status!r}, not 'finished'. "
            f"A partial run's case set is not the suite."
        )


def for_run(journal: RunJournal, *, rebaseline: bool = False, provisional: str = "") -> Comparison:
    """Judge a run against its suite's baseline, or record it as the new one.

    The single path both the live run loop and the offline ``compare`` command
    take, so a verdict cannot differ depending on which one asked.
    """
    run_id = journal.dir.name
    meta = journal.load_meta()
    if meta is None:
        raise SystemExit(f"no run.json for {run_id}")
    records = list(journal.latest_per_case().values())
    if rebaseline:
        _reject_unbaselineable(meta, run_id)
        written = write(meta.suite, records, run_id, meta.app_version, provisional)
        print(f"[baseline] recorded {written}")
    return compare(meta.suite, records)


def write(
    suite: str,
    records: list[dict[str, Any]],
    run_id: str,
    app_version: str,
    provisional: str = "",
) -> Path:
    """Record this run as the suite's baseline. Only ever called explicitly."""
    accuracy, graded, errored = _accuracy(records)
    stored_path = path_for(suite)
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path.write_text(
        json.dumps(
            {
                "suite": suite,
                "run_id": run_id,
                "app_version": app_version,
                "baseline_accuracy": round(accuracy, 4),
                "graded": graded,
                "errored": errored,
                "per_category": {k: list(v) for k, v in sorted(_by_category(records).items())},
                "provisional": provisional or None,
                "captured_at": datetime.now(UTC).date().isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return stored_path
