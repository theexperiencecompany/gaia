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
LOG="$(mktemp)"
trap 'git worktree remove --force "$WT" 2>/dev/null || true; rm -rf "$WT" "$LOG"' EXIT

git worktree add --detach "$WT" "$BASE" >/dev/null

# Only files that actually claim to pin a bug are worth running here, and
# importing just those keeps an unrelated file's collection error from
# aborting the run.
regression_files=()
for f in "${changed[@]}"; do
  if grep -q 'pytest\.mark\.regression' "$REPO_ROOT/$f"; then
    regression_files+=("$f")
  fi
done
if [ "${#regression_files[@]}" -eq 0 ]; then
  echo "regression-proof: no @pytest.mark.regression tests in this diff — nothing to prove"
  exit 0
fi
echo "regression-proof: ${#regression_files[@]} file(s) with regression-marked tests:"
printf '  %s\n' "${regression_files[@]}"

# Overlay the PR's WHOLE test tree and pytest.ini, not just the changed files.
# The boundary that makes this meaningful is tests-vs-product: the harness
# (conftest fixtures, helpers, registered markers) belongs to the tests, so it
# has to come from the PR too. Copying only test files left the base's
# pytest.ini in place, and --strict-markers then rejected markers this branch
# introduces ('regression', 'stress') — every run aborted during collection.
# The base keeps app/, which is the old product code these tests must catch.
rm -rf "$WT/apps/api/tests"
cp -R "$API_DIR/tests" "$WT/apps/api/tests"
cp -f "$API_DIR/pytest.ini" "$WT/apps/api/pytest.ini"

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

# Run from apps/api, the same working directory the real suite uses. Running
# from the worktree root instead looks harmless — pytest resolves the
# `apps/api/tests/...` paths either way — but app_factory mounts
# StaticFiles(directory="app/static") on a CWD-RELATIVE path, so every test that
# builds the FastAPI app died with "Directory 'app/static' does not exist".
# Those show up as errors rather than failures, and this lane counts an error as
# "did not pass" — so the gate was reporting proof it had not actually obtained.
cd "$WT/apps/api"
export ENV=development PYTHONPATH="$WT/apps/api"
# Paths are repo-root-relative from git diff; make them relative to apps/api.
rel_regression_files=()
for f in "${regression_files[@]}"; do
  rel_regression_files+=("${f#apps/api/}")
done
# Scoped to `@pytest.mark.regression`, not every changed test. "All changed
# tests must fail on base" is only true of bug-fix PRs; a gap-fill or
# restructure branch legitimately adds tests for behavior the base already
# gets right, and blanket-checking them is what kept this lane informational.
# A test claiming to pin a bug opts in by marker, and then must prove it.
set +e
"$VENV_PY" -m pytest "${rel_regression_files[@]}" -m regression -q --tb=no --no-header \
  -p no:cacheprovider -o addopts="--strict-markers" > "$LOG" 2>&1
rc=$?
set -e

# pytest exit 5 = nothing collected: no regression-marked tests in this diff.
if [ "$rc" -eq 5 ]; then
  echo "regression-proof: no @pytest.mark.regression tests among the changed files — nothing to prove"
  exit 0
fi

# A run that never produced a summary line did not execute the tests at all
# (missing interpreter, import error, unwritable log). That must fail loudly:
# a previous version of this script redirected into a directory that does not
# exist on the runner, so pytest never ran, and every branch below was skipped
# on the way to printing success — the lane passed without checking anything.
if ! grep -qE '[0-9]+ (passed|failed|error)' "$LOG"; then
  echo "ERROR: regression-proof — pytest produced no result summary (exit $rc)."
  echo "       The check did not run; treating that as a failure, not a pass."
  tail -30 "$LOG"
  exit 1
fi

# Any PASS means a test that claims to pin a bug already passes without the
# fix — it does not prove what it says it proves.
passed_count=$(grep -oE '[0-9]+ passed' "$LOG" | tail -1 | cut -d' ' -f1 || true)
if [ -n "${passed_count}" ] && [ "${passed_count}" != "0" ]; then
  echo "ERROR: regression-proof — $passed_count regression-marked test(s) PASS on base."
  echo "       A regression test must fail without its fix. Either the fix is not"
  echo "       needed, or the test does not actually exercise the bug."
  tail -30 "$LOG"
  exit 1
fi

# A usage/collection abort (exit 2+) means the tests never really ran — an
# unknown marker, an import error. That is not proof of anything either.
if [ "$rc" -ne 1 ]; then
  echo "ERROR: regression-proof — pytest exited $rc (expected 1 = tests failed)."
  echo "       The tests aborted rather than failing on their assertions, so"
  echo "       nothing was proven. Summary was:"
  grep -E '[0-9]+ (passed|failed|error)' "$LOG" | tail -3
  tail -30 "$LOG"
  exit 1
fi

echo "regression-proof: every regression-marked test fails on base as required"
# Print the per-test outcomes, not just the count: the whole value of this lane
# is being able to see WHICH test proved WHAT. An ERROR counts as "did not
# pass", but it is weaker evidence than a FAILED assertion (it can mean the
# test could not run on base at all rather than catching the bug), so name them
# individually and let review judge.
grep -E '^(FAILED|ERROR) ' "$LOG" | sort -u
grep -E '[0-9]+ (passed|failed|error)' "$LOG" | tail -1
exit 0
