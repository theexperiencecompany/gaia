"""Offline approve-line sweep over a hil-reply run journal. Free — no model calls.

Usage: uv run --group backend python -m scripts.evals.sweep_hil_reply [run-id]
Without run-id, sweeps the newest hil-reply run under scripts/evals/runs/.
"""

from __future__ import annotations

import sys

from scripts.evals.core.paths import RUNS_DIR, latest_suite_run
from scripts.evals.suites.hil_reply import HilReplySuite, sweep_journal


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else latest_suite_run(RUNS_DIR, HilReplySuite.name)
    print(f"sweeping run {run_id}")
    print(sweep_journal(RUNS_DIR / run_id))


if __name__ == "__main__":
    main()
