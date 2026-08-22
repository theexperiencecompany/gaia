"""Find cases whose verdict changes between runs.

The agent is non-deterministic, and every case is asked exactly once per run, so
a suite score is one sample of a random process. A case that has both passed and
failed across history is not noise to average away — it is a finding: an agent
that does the right thing two thirds of the time is a real product problem, and
a case that flips is one that cannot support a regression verdict.

Computed entirely from journals already on disk, so it costs nothing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path


@dataclass
class CaseHistory:
    suite: str
    case_id: str
    passed: int = 0
    failed: int = 0
    errored: int = 0
    runs: list[str] = field(default_factory=list)
    by_version: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    unstamped: set[str] = field(default_factory=set)
    """Outcomes from runs that never recorded which build produced them."""

    @property
    def graded(self) -> int:
        return self.passed + self.failed

    @property
    def flaky(self) -> bool:
        """Both outcomes observed for the same case within ONE harness version.

        Scoping by version is the whole point. Across versions a case that flips
        is usually a fix landing, not the agent wavering — gmail-label-q3 reads
        fail, fail, then pass on every run since, and hard-compose-birthday-plan
        failed five times before the create_reminder typo was corrected. Counting
        those as flaky inflated the figure from 26 to 69 and pointed at the wrong
        cause entirely.
        """
        return any({"passed", "failed"} <= outcomes for outcomes in self.by_version.values())

    @property
    def changed_across_versions(self) -> bool:
        """Flipped between two RECORDED versions: a fix landing, not flakiness.

        Both outcomes have to be witnessed by a stamped run. A flip where either
        side came from an unstamped run demonstrates nothing about a code change
        — see ``undetermined``.
        """
        stamped = set[str]().union(*self.by_version.values()) if self.by_version else set[str]()
        return not self.flaky and len(self.by_version) >= 2 and {"passed", "failed"} <= stamped

    @property
    def undetermined(self) -> bool:
        """Flipped, but at least one side has no version stamp to attribute it to.

        Calling these "a fix landing" is a claim the journals cannot support, and
        it is the reassuring half of the sentence — so a genuinely flaky case
        recorded before version stamping would be filed away as fixed and never
        looked at again.
        """
        return (
            self.passed > 0
            and self.failed > 0
            and not self.flaky
            and not self.changed_across_versions
        )

    @property
    def pass_rate(self) -> float:
        return self.passed / self.graded if self.graded else 0.0


def history(runs_dir: Path) -> dict[tuple[str, str], CaseHistory]:
    """Per-case outcomes across every run that is not excluded."""
    seen: dict[tuple[str, str], CaseHistory] = {}
    for run_dir in sorted(runs_dir.iterdir()):
        meta_path, journal_path = run_dir / "run.json", run_dir / "journal.jsonl"
        if not (run_dir.is_dir() and meta_path.exists() and journal_path.exists()):
            continue
        meta = json.loads(meta_path.read_text())
        if meta.get("excluded"):
            continue
        suite = str(meta.get("suite", "?"))
        # No stamp means the run predates version tracking. Its outcomes are
        # pooled apart from the versioned ones so they can neither manufacture a
        # flake out of a code change nor be credited to one.
        version = str(meta.get("app_version") or "")
        # One verdict per case per run: a retry within a run supersedes rather
        # than counting as a second observation.
        latest: dict[str, str] = {}
        for line in journal_path.read_text().splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            latest[str(record["case_id"])] = str(record.get("status", ""))
        for case_id, status in latest.items():
            entry = seen.setdefault((suite, case_id), CaseHistory(suite, case_id))
            if status == "passed":
                entry.passed += 1
            elif status == "failed":
                entry.failed += 1
            elif status == "errored":
                entry.errored += 1
            if status in ("passed", "failed"):
                if version:
                    entry.by_version[version].add(status)
                else:
                    entry.unstamped.add(status)
            entry.runs.append(run_dir.name)
    return seen


def report(runs_dir: Path) -> str:
    entries = history(runs_dir)
    repeated = [e for e in entries.values() if e.graded >= 2]
    flaky = sorted(
        (e for e in repeated if e.flaky), key=lambda e: (e.pass_rate, e.suite, e.case_id)
    )
    moved = [e for e in repeated if e.changed_across_versions]
    undetermined = [e for e in repeated if e.undetermined]
    lines = [
        "",
        "=" * 74,
        f"FLAKY CASES  {len(flaky)} of {len(repeated)} repeated cases flip within one version",
        "=" * 74,
        f"  {len(moved)} changed between RECORDED versions — a fix landing, not flakiness",
        f"  {len(undetermined)} flipped across runs with no version stamp — undetermined, "
        f"neither\n    figure can claim them",
    ]
    if not repeated:
        lines.append("  no case has been graded twice yet — run a suite again to build history")
        return "\n".join(lines + [""])
    if not flaky:
        lines.append("  no repeated case disagreed with itself inside one version")
        return "\n".join(lines + [""])

    by_suite: dict[str, int] = defaultdict(int)
    for entry in flaky:
        by_suite[entry.suite] += 1
    lines.append("  by suite: " + " · ".join(f"{s} {n}" for s, n in sorted(by_suite.items())))
    lines.append("")
    lines.append(f"  {'suite':<12} {'case':<46} {'pass rate':>10}  observations")
    for entry in flaky[:40]:
        lines.append(
            f"  {entry.suite:<12} {entry.case_id:<46} "
            f"{entry.passed}/{entry.graded} = {entry.pass_rate:>4.0%}  "
            f"{'errored ' + str(entry.errored) if entry.errored else ''}"
        )
    lines.append("")
    lines.append(
        "  A flaky case cannot support a regression verdict, and an agent that "
        "works\n  only sometimes is a product finding rather than noise."
    )
    return "\n".join(lines + [""])
