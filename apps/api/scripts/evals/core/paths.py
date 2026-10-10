"""Where an eval script may read and write files it does not journal.

One directory, gitignored (apps/api/.gitignore), instead of /tmp: a
world-writable directory is where another process can plant or replace the
file a script reads back, and a path taken straight from the command line is
the one input an eval script must not trust.
"""

import json
from pathlib import Path

#: Raw transcripts, probe dumps and anything else a script keeps between runs.
RUNS_DIR = Path(__file__).resolve().parents[1] / "runs"


def under_runs(candidate: Path) -> Path:
    """Candidate resolved, provided it lives under :data:RUNS_DIR.

    Anything outside is refused with the directory named, so a wrong path is a
    one-line fix rather than a script quietly reading somewhere it should not.
    """
    resolved = candidate.resolve()
    if not resolved.is_relative_to(RUNS_DIR.resolve()):
        raise SystemExit(f"{candidate}: eval inputs must live under {RUNS_DIR}")
    return resolved


def latest_suite_run(runs_dir: Path, suite: str) -> str:
    """Return the id of the newest journaled run of suite under runs_dir."""
    candidates = sorted(
        (
            p
            for p in runs_dir.iterdir()
            if (p / "run.json").exists()
            and (p / "journal.jsonl").exists()
            and str(json.loads((p / "run.json").read_text()).get("suite")) == suite
        ),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        raise SystemExit(f"no {suite} runs found under {runs_dir}")
    return candidates[-1].name
