"""Record finished trigger-gate runs as the journal the CI sweep regrades. Free, no model calls.

Usage: uv run --group backend python -m scripts.evals.record_trigger_gate <run-id> [run-id ...]
Writes data/trigger-gate/recorded/<run-id>.jsonl; commit it with the corpus it was asked about.
"""

from __future__ import annotations

import sys

from scripts.evals.core.paths import RUNS_DIR
from scripts.evals.suites.trigger_gate import record


def main() -> None:
    for run_id in sys.argv[1:]:
        print(f"recorded {record(RUNS_DIR / run_id)}")


if __name__ == "__main__":
    main()
