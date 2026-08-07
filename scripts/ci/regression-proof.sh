#!/usr/bin/env bash
# Regression-proof job (FastAPI's lesson): the changed test files must FAIL on
# the base revision — red-first enforced mechanically, per PR.
#
# Usage: regression-proof.sh <base-ref>   (e.g. origin/develop)
# Exit 0: no changed tests, or all changed tests fail on base (as they should).
# Exit 1: a changed test PASSES on base — its fix may no longer be needed.
set -euo pipefail

BASE="${1:?usage: regression-proof.sh <base-ref>}"

# git's `**` matches one-or-more dirs, never zero — cover top-level too.
mapfile -t changed < <(git diff --name-only "$BASE"...HEAD -- 'apps/api/tests/test_*.py' 'apps/api/tests/**/test_*.py' || true)
if [ "${#changed[@]}" -eq 0 ]; then
  echo "regression-proof: no changed test files"
  exit 0
fi
echo "regression-proof: ${#changed[@]} changed test file(s):"
printf '  %s\n' "${changed[@]}"

WT="$(mktemp -d)"
trap 'git worktree remove --force "$WT" 2>/dev/null || true; rm -rf "$WT"' EXIT

git worktree add --detach "$WT" "$BASE" >/dev/null 2>&1

# Overlay the PR's test files onto the base worktree (only the tests change —
# the base has the OLD product code they were written to catch).
for f in "${changed[@]}"; do
  mkdir -p "$(dirname "$WT/$f")"
  cp -f "$f" "$WT/$f"
done

cd "$WT/apps/api"
export ENV=development PYTHONPATH="$WT/apps/api"
set +e
uv run --no-sync --frozen pytest "${changed[@]}" -q --tb=no --no-header -p no:cacheprovider -o addopts="--strict-markers" > /tmp/opencode/regression-proof.log 2>&1
rc=$?
set -e

# Any PASS (rc 0, or rc != 0 but some passed) means a fix that's no longer
# needed. Parse the JUnit-less output: pytest -q prints 'N passed' or
# 'N passed, M failed'.
if [ "$rc" -eq 0 ]; then
  echo "ERROR: regression-proof — ALL changed tests PASS on base."
  echo "       Their fixes may no longer be needed; verify each."
  cat /tmp/opencode/regression-proof.log | tail -20
  exit 1
fi

# Partial: count passed cases from the pytest summary line.
summary=$(grep -oE '[0-9]+ passed(, [0-9]+ failed)?' /tmp/opencode/regression-proof.log | tail -1 || true)
passed_count=${summary%% *}
if [ "${passed_count:-0}" != "0" ] && [ -n "${passed_count}" ]; then
  echo "ERROR: regression-proof — $passed_count changed test(s) PASS on base:"
  echo "       the fix may no longer be needed; verify each."
  cat /tmp/opencode/regression-proof.log | tail -20
  exit 1
fi

echo "regression-proof: all changed tests fail on base (rc=$rc) as required"
exit 0
