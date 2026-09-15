"""Where an eval script may read and write files it does not journal.

One directory, gitignored (``apps/api/.gitignore``), instead of ``/tmp``: a
world-writable directory is where another process can plant or replace the
file a script reads back, and a path taken straight from the command line is
the one input an eval script must not trust.
"""

from pathlib import Path

#: Raw transcripts, probe dumps and anything else a script keeps between runs.
RUNS_DIR = Path(__file__).resolve().parents[1] / "runs"


def under_runs(candidate: Path) -> Path:
    """``candidate`` resolved, provided it lives under :data:`RUNS_DIR`.

    Anything outside is refused with the directory named, so a wrong path is a
    one-line fix rather than a script quietly reading somewhere it should not.
    """
    resolved = candidate.resolve()
    if not resolved.is_relative_to(RUNS_DIR.resolve()):
        raise SystemExit(f"{candidate}: eval inputs must live under {RUNS_DIR}")
    return resolved
