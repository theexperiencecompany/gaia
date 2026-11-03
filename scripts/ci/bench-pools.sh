#!/usr/bin/env bash
# bench-pools.sh — time each check in $CHECKS through mise ci:local, one at a time.
# Throwaway benchmark for the bench/m4-pools branch; never merged.
set -euo pipefail
summary="${GITHUB_STEP_SUMMARY:-/dev/stdout}"
echo "| check | seconds | result |" >> "$summary"
echo "|---|---|---|" >> "$summary"
for check in $CHECKS; do
  start=$(date +%s)
  if uv run --no-project python scripts/dev/gaia_verify.py --all --with-heavy --only "$check" > "/tmp/bench-$check.log" 2>&1; then
    result=pass
  else
    result="FAIL (exit $?)"
    tail -n 30 "/tmp/bench-$check.log"
  fi
  seconds=$(( $(date +%s) - start ))
  echo "bench: $check ${seconds}s $result"
  echo "| $check | $seconds | $result |" >> "$summary"
done
