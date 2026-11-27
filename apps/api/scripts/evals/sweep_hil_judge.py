"""Offline threshold sweep over a hil-judge run journal. Free — no model calls.

Usage: uv run --group backend python -m scripts.evals.sweep_hil_judge [run-id]
Without run-id, sweeps the newest hil-judge run under scripts/evals/runs/.
"""

from __future__ import annotations

import argparse

from scripts.evals.core.paths import RUNS_DIR, latest_suite_run
from scripts.evals.suites.hil_judge import HilJudgeSuite, sweep_journal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", nargs="?", help="the run to sweep (default: the newest)")
    run_id = parser.parse_args().run_id or latest_suite_run(RUNS_DIR, HilJudgeSuite.name)
    print(f"sweeping run {run_id}")
    print(sweep_journal(RUNS_DIR / run_id))


if __name__ == "__main__":
    main()
