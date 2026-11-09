"""Record finished trigger-gate or email-verdict runs as the journal the CI sweep regrades. Free, no model calls.

Usage: uv run --group backend python -m scripts.evals.record_trigger_gate <run-id> [run-id ...]
Writes data/trigger-gate/recorded/<run-id>.jsonl, or recorded-verdicts/ for an email-verdict
run; commit it with the corpus it was asked about.
"""

from __future__ import annotations

import sys

from scripts.evals.core.paths import RUNS_DIR
from scripts.evals.suites.trigger_gate import (
    RECORDED_DIR,
    VERDICTS_RECORDED_DIR,
    EmailVerdictSuite,
    record,
)


def main() -> None:
    for run_id in sys.argv[1:]:
        verdicts = run_id.startswith(EmailVerdictSuite.name)
        out_dir = VERDICTS_RECORDED_DIR if verdicts else RECORDED_DIR
        print(f"recorded {record(RUNS_DIR / run_id, out_dir)}")


if __name__ == "__main__":
    main()
