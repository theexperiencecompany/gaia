#!/usr/bin/env bash
# Run a pytest command; if it fails, rerun ONLY the failures once and treat a
# pass-on-rerun as a flaky-test failure (CPython's --fail-rerun lesson).
#
# Usage: run-tests-flake-gate.sh <pytest-args...>
# Exit codes: 0 all green; 7 genuine failure (same code as the rerun); 1 flaky.
set -uo pipefail

# Capture the first run's exit code without tripping `set -e` on the `if`.
set +e
"$@"
first=$?
set -e

if [ "$first" -eq 0 ]; then
  exit 0
fi

echo "::group::First run failed (exit $first) — rerunning only failures once"
# Strip coverage/junit flags on the rerun: they'd measure/emit for a 2-test
# subset and the coverage gate would always fail (masking the flake signal).
rerun_args=()
for arg in "$@"; do
  case "$arg" in
    --cov=*|--cov-report=*|--cov-fail-under=*|--junitxml=*|--junitxml)
      # --junitxml takes a value; skip the next arg too.
      [ "$arg" = "--junitxml" ] && skip_next=1
      continue
      ;;
  esac
  if [ "${skip_next:-0}" = "1" ]; then
    skip_next=0
    continue
  fi
  rerun_args+=("$arg")
done
rerun_args+=(--lf -q)

set +e
"${rerun_args[@]}"
rerun=$?
set -e
echo "::endgroup::"

if [ "$rerun" -eq 0 ]; then
  echo "ERROR: FLAKY TESTS DETECTED — the following passed only on rerun:"
  echo "       (see the first-run traceback above)"
  exit 1
fi

echo "First run and rerun both failed — genuine failure, exit code $rerun"
exit "$rerun"
