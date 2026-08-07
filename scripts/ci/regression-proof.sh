#!/usr/bin/env bash
# Regression-proof job (FastAPI's lesson): the changed test files must FAIL on
# the base revision — red-first enforced mechanically, per PR.
#
# Usage: regression-proof.sh <base-ref>   (e.g. origin/develop)
# Exit 0: no changed tests, or all changed tests fail on base (as they should).
# Exit 1: a changed test PASSES on base — its fix may no longer be needed.
set -euo pipefail

BASE="${1:?usage: regression-proof.sh <base-ref>}"

# Root-relative resolution, safe regardless of the caller's cwd (the CI job
# runs with working-directory: apps/api; git diff emits root-relative paths).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
API_DIR="$REPO_ROOT/apps/api"

# git pathspecs are cwd-relative — resolve from the repo root or the
# `apps/api/tests/...` patterns match nothing when invoked from apps/api.
cd "$REPO_ROOT"

# git's `**` matches one-or-more dirs, never zero — cover top-level too.
# --diff-filter=ACMR: skip Deleted files (a deleted test has no base copy to
# overlay). No `|| true`: a failed diff must fail the job, not read as "no
# changes". while-read (not mapfile) for macOS bash 3.2 compatibility.
changed=()
while IFS= read -r f; do changed+=("$f"); done < <(git diff --diff-filter=ACMR --name-only "$BASE"...HEAD -- 'apps/api/tests/test_*.py' 'apps/api/tests/**/test_*.py')
if [ "${#changed[@]}" -eq 0 ]; then
  echo "regression-proof: no changed test files"
  exit 0
fi
echo "regression-proof: ${#changed[@]} changed test file(s):"
printf '  %s\n' "${changed[@]}"

WT="$(mktemp -d)"
trap 'git worktree remove --force "$WT" 2>/dev/null || true; rm -rf "$WT"' EXIT

git worktree add --detach "$WT" "$BASE" >/dev/null

# Overlay the PR's test files onto the base worktree (only the tests change —
# the base has the OLD product code they were written to catch).
for f in "${changed[@]}"; do
  mkdir -p "$(dirname "$WT/$f")"
  cp -f "$REPO_ROOT/$f" "$WT/$f"
done

# Run from the worktree ROOT so the repo-root-relative test paths resolve
# (pytest is given paths like apps/api/tests/...). PYTHONPATH points at the
# BASE app code. Use the MAIN checkout's venv (the setup-python-test-env
# action synced deps there; a fresh worktree has no venv and `uv run --no-sync`
# would spawn a bare environment with no pytest — which must NOT read as
# "tests fail on base"). Fail loud if that python is missing.
for candidate in "$REPO_ROOT/.venv/bin/python" "$API_DIR/.venv/bin/python"; do
  if [ -x "$candidate" ]; then
    VENV_PY="$candidate"
    break
  fi
done
if [ -z "${VENV_PY:-}" ]; then
  echo "ERROR: regression-proof — main checkout venv not found under $REPO_ROOT"
  exit 1
fi

cd "$WT"
export ENV=development PYTHONPATH="$WT/apps/api"
set +e
"$VENV_PY" -m pytest "${changed[@]}" -q --tb=no --no-header -p no:cacheprovider -o addopts="--strict-markers" > /tmp/opencode/regression-proof.log 2>&1
rc=$?
set -e

# Any PASS (rc 0, or rc != 0 but some passed) means a fix that's no longer
# needed. Parse the -q summary line: 'N passed' or 'N failed, M passed'.
if [ "$rc" -eq 0 ]; then
  echo "ERROR: regression-proof — ALL changed tests PASS on base."
  echo "       Their fixes may no longer be needed; verify each."
  tail -20 /tmp/opencode/regression-proof.log
  exit 1
fi

summary=$(grep -oE '[0-9]+ passed(, [0-9]+ failed)?' /tmp/opencode/regression-proof.log | tail -1 || true)
passed_count=${summary%% *}
if [ -n "${passed_count}" ] && [ "${passed_count}" != "0" ]; then
  echo "ERROR: regression-proof — $passed_count changed test(s) PASS on base:"
  echo "       the fix may no longer be needed; verify each."
  tail -20 /tmp/opencode/regression-proof.log
  exit 1
fi

echo "regression-proof: all changed tests fail on base (rc=$rc) as required"
exit 0
