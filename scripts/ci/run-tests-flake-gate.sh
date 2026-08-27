#!/usr/bin/env bash
# Run a pytest command; if it fails, rerun ONLY the failures once and treat a
# pass-on-rerun as a flaky-test failure (CPython's --fail-rerun lesson).
#
# Usage: run-tests-flake-gate.sh <pytest-args...>
# Exit codes: 0 all green; whatever pytest returns on a genuine/coverage
# failure (1 for both); 1 flaky.
set -uo pipefail

# Capture the first run's output (while still streaming it live) so we can
# tell a coverage-threshold failure apart from an actual test failure: both
# exit pytest with 1, but only one of them is a flake-gate concern.
tmp_out="$(mktemp)"
trap 'rm -f "$tmp_out"' EXIT

# Capture the first run's exit code without tripping `set -e` on the `if`.
set +e
"$@" 2>&1 | tee "$tmp_out"
first=${PIPESTATUS[0]}
set -e

if [ "$first" -eq 0 ]; then
  exit 0
fi

# pytest-cov exits 1 on a coverage-threshold miss even when every test
# passed. Rerunning with --lf against an empty/stale lastfailed cache would
# then replay the WHOLE suite (which passes) and get misreported as
# "FLAKY TESTS DETECTED" — while main.yml's diff-cover step, which would
# give the correct diagnosis, never runs because this step already failed.
if grep -qE '^FAIL Required test coverage of [0-9.]+% not reached\.' "$tmp_out" \
  && ! grep -qE '^FAILED ' "$tmp_out" \
  && ! grep -qE '^[0-9]+ failed' "$tmp_out"; then
  echo "::error::Coverage gate failed (coverage below threshold) — not a test failure, not a flake. Write tests covering your changed lines."
  exit "$first"
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
  echo "::error::FLAKY TESTS DETECTED — the following passed only on rerun:"
  echo "       (see the first-run traceback above)"
  exit 1
fi

echo "::error::First run and rerun both failed — genuine failure, exit code $rerun"
exit "$rerun"
