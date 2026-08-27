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
# Bare mktemp, no -t template: BSD/macOS appends the random suffix for you, GNU
# requires the template to spell out at least three X's and errors otherwise —
# which is exactly how this failed on the Linux runner while working locally.
JUNIT="$(mktemp)"
BASE_COPIES="$(mktemp -d)"
trap 'git worktree remove --force "$WT" 2>/dev/null || true; rm -rf "$WT" "$LOG" "$JUNIT" "$BASE_COPIES"' EXIT

git worktree add --detach "$WT" "$BASE" >/dev/null

# Only files that actually claim to pin a bug are worth running here, and
# importing just those keeps an unrelated file's collection error from
# aborting the run.
#
# Anchored on the DECORATOR, not on any mention of it. A plain substring match
# enlists a file that merely names the marker in prose: it picked up
# tests/unit/agents/test_llm_helper_output_cap.py, which holds no marked test
# but whose docstring spells the decorator out while explaining this very lane
# — the file documenting the trap tripped it. The lane then ran that file on
# base, where the symbol under test does not exist, and reported an ERROR.
# This stays a pre-filter; the authoritative selection is pytest's own
# `-m regression` below, which reports "nothing collected" (exit 5) if the
# grep were ever over-eager again.
regression_files=()
for f in "${changed[@]}"; do
  if grep -qE '^[[:space:]]*@pytest\.mark\.regression' "$REPO_ROOT/$f"; then
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
# BASE app and shared code. Use the MAIN checkout's venv (the
# setup-python-test-env action synced deps there; a fresh worktree has no venv
# and `uv run --no-sync` would spawn a bare environment with no pytest — which
# must NOT read as "tests fail on base"). Fail loud if that python is missing.
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
# $WT/libs comes first so `shared.*` resolves to the BASE worktree too, not just
# `app.*`. The venv is the MAIN checkout's, and gaia-shared is installed there as
# an editable pointing at the main checkout's libs/ — so without this entry a PR
# that fixes something in libs/shared/ runs BASE app code against its OWN fixed
# shared code, the pinned bug is absent, and the test passes on base for a reason
# that has nothing to do with the fix being unnecessary. This wins because the
# editable install appends its finder to sys.meta_path, i.e. after the sys.path
# PathFinder that PYTHONPATH feeds.
export ENV=development PYTHONPATH="$WT/libs:$WT/apps/api"
# Scoped to the `@pytest.mark.regression` tests this PR ADDS, not every marked
# test in a touched file. "All changed tests must fail on base" is only true of
# bug-fix PRs; a gap-fill or restructure branch legitimately adds tests for
# behavior the base already gets right, and blanket-checking them is what kept
# this lane informational. And a marked test whose fix already merged is green
# on base by design — re-proving it here would fail every later PR that edits
# the same file. A test claiming to pin a bug opts in by marker, and then must
# prove it once: in the PR that introduces it. Paths are repo-root-relative from
# git diff; node ids are made relative to apps/api for pytest.
select_args=()
for f in "${regression_files[@]}"; do
  base_copy="$(mktemp -p "$BASE_COPIES")"
  if git -C "$REPO_ROOT" show "$BASE:$f" > "$base_copy" 2>/dev/null; then
    select_args+=("$API_DIR/${f#apps/api/}" "$base_copy")
  else
    select_args+=("$API_DIR/${f#apps/api/}" "$base_copy.missing")
    rm -f "$base_copy"
  fi
done
SELECTED="$(mktemp -p "$BASE_COPIES")"
if ! "$VENV_PY" "$SCRIPT_DIR/regression_proof_select.py" "${select_args[@]}" > "$SELECTED"; then
  echo "ERROR: regression-proof — could not attribute this diff's regression marks to tests (see above)."
  exit 1
fi
new_regression_ids=()
while IFS= read -r node_id; do
  [ -n "$node_id" ] && new_regression_ids+=("${node_id#"$API_DIR"/}")
done < "$SELECTED"
if [ "${#new_regression_ids[@]}" -eq 0 ]; then
  echo "regression-proof: no NEW @pytest.mark.regression tests in this diff — nothing to prove"
  exit 0
fi
echo "regression-proof: ${#new_regression_ids[@]} new regression test(s) to prove on base:"
printf '  %s
' "${new_regression_ids[@]}"
set +e
# -W ignore::DeprecationWarning: this lane runs the BRANCH's pytest.ini
# (filterwarnings included) against the BASE's product code. Base code
# legitimately predates this branch's deprecation fixes (e.g. the
# mcp_use.exceptions import fixed on this branch), so warning-as-error here
# measures base deprecations, not whether the pinned bug exists. The
# warnings policy's job is policing the branch's code — that happens in the
# main test-python run. This lane's job is assertion-level proof on base.
"$VENV_PY" -m pytest "${new_regression_ids[@]}" -m regression -q --tb=no --no-header \
  -p no:cacheprovider -o addopts="--strict-markers" -W ignore::DeprecationWarning \
  --junitxml="$JUNIT" > "$LOG" 2>&1
rc=$?
set -e

# pytest exit 5 = nothing collected: no regression-marked tests in this diff.
if [ "$rc" -eq 5 ]; then
  echo "regression-proof: no @pytest.mark.regression tests among the changed files — nothing to prove"
  exit 0
fi

# No report at all means pytest never ran (missing interpreter, unwritable path,
# a collection abort). That is a failure, not a pass — an earlier version of
# this script redirected into a directory absent on the runner, so pytest never
# executed and every check below was skipped on the way to printing success.
if [ ! -s "$JUNIT" ]; then
  echo "ERROR: regression-proof — pytest wrote no JUnit report (exit $rc)."
  echo "       The check did not run; treating that as a failure, not a pass."
  tail -40 "$LOG"
  exit 1
fi

# The verdict is per-test and structural (JUnit), not a count scraped from the
# summary line: a run can be "0 passed" while proving nothing, because a test
# that ERRORS never reached its assertions. See regression_proof_verdict.py.
if ! uv run --no-project "$SCRIPT_DIR/regression_proof_verdict.py" "$JUNIT"; then
  echo "--- pytest output (base revision) ---"
  tail -40 "$LOG"
  exit 1
fi
exit 0
