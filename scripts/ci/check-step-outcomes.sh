#!/usr/bin/env bash
#
# check-step-outcomes.sh — fail a job if any of its `continue-on-error` steps
# did not pass, naming every one that failed.
#
# A job that runs several independent tools (see code-quality.yml's
# python-static lane) marks each tool step `continue-on-error: true` so one red
# tool does not hide the rest, then calls this with one "<name>=<outcome>" pair
# per step. Outcome values are GitHub's own step outcomes: success, failure,
# cancelled, skipped.
#
# Usage: check-step-outcomes.sh "ruff=success" "bandit=failure" ...
set -euo pipefail

failed=0
for pair in "$@"; do
  name="${pair%%=*}"
  outcome="${pair#*=}"
  printf '  %-16s %s\n' "$name:" "$outcome"
  if [[ "$outcome" != "success" ]]; then
    echo "::error::$name did not pass (outcome: $outcome)"
    failed=$((failed + 1))
  fi
done

if [[ "$failed" -gt 0 ]]; then
  echo "::error::$failed of $# step(s) failed — expand the groups above for each"
  exit 1
fi
echo "All $# steps passed"
