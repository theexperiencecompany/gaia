"""Find every errored case across finished runs, and re-run the retryable ones.

The manual loop this replaces was run by hand a dozen times today: list a run's
errored cases, judge whether the error is transient, resume, repeat. Each of
those judgements is now written down once, and the sweep stops after MAX_PASSES
so a persistent fault surfaces as a loud finding instead of an infinite loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

#: A second resume of the same run retries what the first left; beyond that the
#: error is reproducing, not transient, and belongs in front of a human.
MAX_PASSES = 2

#: Error shapes worth retrying: the test never conducted, for a reason that can
#: pass. Anything else (a graded failure, a skip, a deterministic crash) re-runs
#: to the same result and only burns spend.
RETRYABLE_SIGNATURES = (
    "timeout",
    "timed out",
    "connection refused",
    "connection reset",
    "broken pipe",
    "server disconnected",
    "502",
    "503",
    "504",
    "internal_server_error",
    "remoteprotocolerror",
    "connecterror",
)


@dataclass
class RunSweep:
    run_id: str
    suite: str
    retryable: list[str] = field(default_factory=list)
    persistent: list[str] = field(default_factory=list)


def _latest(journal_path: Path) -> dict[str, dict[str, object]]:
    latest: dict[str, dict[str, object]] = {}
    for line in journal_path.read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            latest[str(record["case_id"])] = record
    return latest


def _passes(journal_path: Path, case_id: str) -> int:
    return sum(
        1
        for line in journal_path.read_text().splitlines()
        if line.strip() and json.loads(line).get("case_id") == case_id
    )


def plan(runs_dir: Path) -> list[RunSweep]:
    """Every non-excluded run that still holds errored cases, classified."""
    sweeps: list[RunSweep] = []
    for run_dir in sorted(runs_dir.iterdir()):
        meta_path, journal_path = run_dir / "run.json", run_dir / "journal.jsonl"
        if not (meta_path.exists() and journal_path.exists()):
            continue
        meta = json.loads(meta_path.read_text())
        if meta.get("excluded"):
            continue
        entry = RunSweep(run_id=run_dir.name, suite=str(meta.get("suite", "?")))
        for case_id, record in _latest(journal_path).items():
            if record.get("status") != "errored":
                continue
            error = str(record.get("error") or "").lower()
            retryable = any(sig in error for sig in RETRYABLE_SIGNATURES)
            exhausted = _passes(journal_path, case_id) > MAX_PASSES
            if retryable and not exhausted:
                entry.retryable.append(case_id)
            else:
                entry.persistent.append(case_id)
        if entry.retryable or entry.persistent:
            sweeps.append(entry)
    return sweeps


def render(sweeps: list[RunSweep]) -> str:
    if not sweeps:
        return "\nSWEEP  every non-excluded run is free of errored cases\n"
    lines = ["", "=" * 74, "SWEEP  runs still holding errored cases", "=" * 74]
    for entry in sweeps:
        lines.append(f"  {entry.suite:<12} {entry.run_id}")
        if entry.retryable:
            lines.append(f"    retryable ({len(entry.retryable)}): {entry.retryable[:6]}")
            lines.append(f"    -> evals run --suite {entry.suite} --resume {entry.run_id}")
        if entry.persistent:
            lines.append(
                f"    PERSISTENT ({len(entry.persistent)}): {entry.persistent[:6]} — "
                f"retries exhausted or error is deterministic; needs a human"
            )
    return "\n".join(lines + [""])
