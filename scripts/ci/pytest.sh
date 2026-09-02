#!/usr/bin/env bash
# pytest.sh — everything about RUNNING the Python suite in CI.
#
# Subcommands:
#   slice                    Run one test-python slice, either whole or on the
#                            test-impact selection this job's `test_impact.py
#                            select` wrote. Reads its inputs from the env.
#   flake-gate <cmd...>      Run a pytest command; on failure rerun ONLY the
#                            failures once and fail the build if they pass on
#                            rerun (CPython's --fail-rerun lesson).
#   regression-proof <base>  Prove the NEW @pytest.mark.regression tests in this
#                            diff FAIL on <base-ref> — red-first, mechanically.
#
# Env contract:
#   slice             SLICE_NAME, SLICE_PATHS, XDIST_N (all required);
#                     SLICE_IGNORE, COVERAGE, COV_CONTEXT, RUNNER_TEMP.
#   flake-gate        none — the arguments ARE the pytest command line.
#   regression-proof  none, but needs a fetch-depth: 0 checkout (it does
#                     `git worktree add <base>`) and a synced .venv in the main
#                     checkout (setup-python-test-env leaves one).
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"
# shellcheck source=scripts/ci/lib/cpu-slots.sh
source "$(dirname "$0")/lib/cpu-slots.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── slice ─────────────────────────────────────────────────────────────────
# Node ids can contain spaces and brackets (parametrised tests), so the
# selection is read into a bash array and never round-tripped through an
# unquoted shell expansion or a workflow expression.
cmd_slice() {
  cd "$REPO_ROOT/apps/api"

  local SLICE SELECTED SCRATCH SELECTION
  SLICE="${SLICE_NAME:?SLICE_NAME required}"
  SELECTED=".test-impact/selected-$SLICE.txt"
  # Per-runner scratch: /tmp is shared by every runner instance on the home
  # box, and twenty lanes writing /tmp/pytest-<slice>.time clobber each other.
  SCRATCH="${RUNNER_TEMP:-/tmp}"

  # The selection is trusted only when this job's `test_impact.py select` wrote
  # it. No file means the selector did not run (or was skipped) — that is ALL,
  # stated explicitly. A file that predates this job by hours is a leftover in
  # a persistent workspace and is ignored for the same reason: a stale
  # selection silently skips tests, running everything never does.
  SELECTION="ALL"
  if [ ! -f "$SELECTED" ]; then
    echo "Python tests ($SLICE): no $SELECTED — running ALL (no test-impact selection for this job)"
  elif [ -n "$(find "$SELECTED" -mmin +360 -print -quit 2>/dev/null)" ]; then
    ci_warn "$SELECTED is older than 6h (stale from a previous job?) — ignoring it and running ALL"
  elif [ "$(head -n1 "$SELECTED")" = "ALL" ]; then
    echo "Python tests ($SLICE): selection says ALL"
  else
    SELECTION="FILE"
  fi

  local TARGETS=()
  if [ "$SELECTION" = "FILE" ]; then
    while IFS= read -r line; do [ -n "$line" ] && TARGETS+=("$line"); done <"$SELECTED"
    if [ ${#TARGETS[@]} -eq 0 ]; then
      ci_ok "Python tests ($SLICE): SKIPPED (test impact selected 0 tests)"
      exit 0
    fi
    echo "Python tests ($SLICE): running ${#TARGETS[@]} selected targets"
  else
    # shellcheck disable=SC2206 # deliberate word splitting: a space-separated path list
    TARGETS=(${SLICE_PATHS:?SLICE_PATHS required})
  fi

  local EXTRA=()
  if [ -n "${SLICE_IGNORE:-}" ]; then
    # shellcheck disable=SC2206 # same: SLICE_IGNORE is a flag list, not one argument
    EXTRA=(${SLICE_IGNORE})
  fi
  # Plugin auto-discovery off, explicit list on. Every xdist worker imports every
  # installed pytest plugin at startup; measured on the box for tests/unit:
  # collection 116s with a cold bytecode cache and all 16 auto-loaded plugins,
  # 52s warm, 24s warm with only the plugins the suite uses. opik alone is ~4s
  # of import per worker, schemathesis ~2s; neither is used by these lanes.
  # If a fixture goes missing after a dependency change, the plugin belongs in
  # this list — that is a visible error, unlike the silent per-worker cost.
  export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
  EXTRA+=(-p asyncio -p xdist -p timeout -p pytest_mock -p randomly
          -p hypothesis.extra.pytestplugin -p respx.plugin -p time_machine -p anyio.pytest_plugin -p pytest_check)
  # Coverage only where something reads it: the master gate and the test-impact
  # map. A PR run is report-only by design (selection makes the total
  # meaningless), and tracing costs ~35 CPU-points per lane — pure waste there.
  if [ -n "${COVERAGE:-}" ]; then
    EXTRA+=(-p pytest_cov --cov=app --cov-report= --cov-fail-under=0)
    if [ -n "${COV_CONTEXT:-}" ]; then
      EXTRA+=(--cov-context="${COV_CONTEXT}")
    fi
  fi

  # Host CPU governor: this slice's real appetite is its xdist worker count, so
  # take that many tokens for the duration of the run. On the shared box this is
  # what makes the four slices, the nx build and the mutation shards queue to the
  # physical-core budget instead of oversubscribing 16 threads ~2.3x. A no-op off
  # the box, and the serial bridge slice (XDIST_N=0) takes nothing. Released after
  # the run; the lib's EXIT trap is the safety net for a failed or cancelled job.
  local N_SLOTS="${XDIST_N:?XDIST_N required}"
  cpu_slots_acquire "$N_SLOTS"
  # Re-entered as a subprocess on purpose: /usr/bin/time -v measures the whole
  # pytest tree, and the gate needs its own exit status through the pipe.
  /usr/bin/time -v bash "$SCRIPT_DIR/pytest.sh" flake-gate \
    uv run --frozen pytest -n "$N_SLOTS" --dist worksteal \
    "${TARGETS[@]}" ${EXTRA[@]+"${EXTRA[@]}"} \
    -m 'not composio and not model_onboarding and not schemathesis' \
    --tb=short -q --override-ini=addopts=--strict-markers --timeout=300 \
    --junitxml="test-results/pytest-$SLICE.xml" --durations=30 2>&1 \
    | cut -c-20000 | tee "${SCRATCH}/pytest-${SLICE}.time"
  # cut: the Actions runner handles step output line by line (regex matchers,
  # console upload); a single multi-MB line — a parametrize id carrying a 2 MB
  # string in --durations, measured 2026-08-29 — spun Runner.Worker at 100 %
  # CPU until the job timeout. 20k chars keeps every real traceback intact.
  cpu_slots_release "$N_SLOTS"
  ci_ok "Python tests ($SLICE): OK (xdist=$XDIST_N coverage=${COVERAGE:-off})"
}

# ── flake-gate ────────────────────────────────────────────────────────────
# Exit codes: 0 all green; whatever pytest returns on a genuine/coverage
# failure (1 for both); 1 flaky.
cmd_flake_gate() {
  [ "$#" -gt 0 ] || { echo "usage: pytest.sh flake-gate <pytest-command...>" >&2; exit 2; }

  # Capture the first run's output (while still streaming it live) so we can
  # tell a coverage-threshold failure apart from an actual test failure: both
  # exit pytest with 1, but only one of them is a flake-gate concern.
  local tmp_out first rerun arg
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
  # "FLAKY TESTS DETECTED" — while main.yml's `coverage` job, which would
  # give the correct diagnosis, never runs because this step already failed.
  if grep -qE '^FAIL Required test coverage of [0-9.]+% not reached\.' "$tmp_out" \
    && ! grep -qE '^FAILED ' "$tmp_out" \
    && ! grep -qE '^[0-9]+ failed' "$tmp_out"; then
    printf '::error::%s\n' "Coverage gate failed (coverage below threshold) — not a test failure, not a flake. Write tests covering your changed lines." >&2
    exit "$first"
  fi

  ci_group "First run failed (exit $first) — rerunning only failures once"
  # Strip coverage/junit flags on the rerun: they'd measure/emit for a 2-test
  # subset and the coverage gate would always fail (masking the flake signal).
  local rerun_args=()
  local skip_next=0
  for arg in "$@"; do
    case "$arg" in
      --cov=*|--cov-report=*|--cov-fail-under=*|--junitxml=*|--junitxml)
        # --junitxml takes a value; skip the next arg too.
        [ "$arg" = "--junitxml" ] && skip_next=1
        continue
        ;;
    esac
    if [ "$skip_next" = "1" ]; then
      skip_next=0
      continue
    fi
    rerun_args+=("$arg")
  done
  # One process for the rerun. Measured 2026-08-28 on the integration slice: the
  # rerun of a single 3.7 s test cost 295 s because it replayed "-n 6" — six
  # workers each re-importing conftest and re-collecting 2003 tests. A later
  # "-n" wins in pytest's parser, so this overrides whatever the caller passed.
  rerun_args+=(-n 0 --lf -q)

  set +e
  "${rerun_args[@]}"
  rerun=$?
  set -e
  ci_endgroup

  if [ "$rerun" -eq 0 ]; then
    printf '::error::%s\n' "FLAKY TESTS DETECTED — the following passed only on rerun:" >&2
    echo "       (see the first-run traceback above)"
    exit 1
  fi

  printf '::error::%s\n' "First run and rerun both failed — genuine failure, exit code $rerun" >&2
  exit "$rerun"
}

# ── regression-proof ──────────────────────────────────────────────────────
# Exit 0: no changed tests, or all of this diff's NEW regression tests fail on
# base (as they should). Exit 1: one PASSES on base — its fix may be moot.
cmd_regression_proof() {
  local BASE API_DIR
  BASE="${1:?usage: pytest.sh regression-proof <base-ref>}"
  API_DIR="$REPO_ROOT/apps/api"

  # git pathspecs are cwd-relative — resolve from the repo root or the
  # `apps/api/tests/...` patterns match nothing when invoked from apps/api.
  cd "$REPO_ROOT"

  # git's `**` matches one-or-more dirs, never zero — cover top-level too.
  # --diff-filter=ACMR: skip Deleted files (a deleted test has no base copy to
  # overlay). No `|| true`: a failed diff must fail the job, not read as "no
  # changes". while-read (not mapfile) for macOS bash 3.2 compatibility.
  local changed=()
  while IFS= read -r f; do changed+=("$f"); done < <(git diff --diff-filter=ACMR --name-only "$BASE"...HEAD -- 'apps/api/tests/test_*.py' 'apps/api/tests/**/test_*.py')
  if [ "${#changed[@]}" -eq 0 ]; then
    ci_ok "regression-proof: no changed test files"
    exit 0
  fi
  echo "regression-proof: ${#changed[@]} changed test file(s):"
  printf '  %s\n' "${changed[@]}"

  # NOT `local`: the EXIT trap below runs when the SHELL exits, by which time a
  # function-local is out of scope — under `set -u` the trap then dies with
  # "WT: unbound variable" and fails the job AFTER the verdict has already
  # printed success, which is how this lane reported a pass as a failure.
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
  local regression_files=()
  for f in "${changed[@]}"; do
    if grep -qE '^[[:space:]]*@pytest\.mark\.regression' "$REPO_ROOT/$f"; then
      regression_files+=("$f")
    fi
  done
  if [ "${#regression_files[@]}" -eq 0 ]; then
    ci_ok "regression-proof: no @pytest.mark.regression tests in this diff — nothing to prove"
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
  local VENV_PY="" candidate
  for candidate in "$REPO_ROOT/.venv/bin/python" "$API_DIR/.venv/bin/python"; do
    if [ -x "$candidate" ]; then
      VENV_PY="$candidate"
      break
    fi
  done
  if [ -z "$VENV_PY" ]; then
    ci_die "regression-proof — main checkout venv not found under $REPO_ROOT"
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
  local select_args=() base_copy SELECTED
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
  if ! "$VENV_PY" "$SCRIPT_DIR/report.py" regression-proof-select "${select_args[@]}" > "$SELECTED"; then
    ci_die "regression-proof — could not attribute this diff's regression marks to tests (see above)."
  fi
  local new_regression_ids=()
  while IFS= read -r node_id; do
    [ -n "$node_id" ] && new_regression_ids+=("${node_id#"$API_DIR"/}")
  done < "$SELECTED"
  if [ "${#new_regression_ids[@]}" -eq 0 ]; then
    ci_ok "regression-proof: no NEW @pytest.mark.regression tests in this diff — nothing to prove"
    exit 0
  fi
  echo "regression-proof: ${#new_regression_ids[@]} new regression test(s) to prove on base:"
  printf '  %s\n' "${new_regression_ids[@]}"

  local rc
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
    ci_ok "regression-proof: no @pytest.mark.regression tests among the changed files — nothing to prove"
    exit 0
  fi

  # No report at all means pytest never ran (missing interpreter, unwritable path,
  # a collection abort). That is a failure, not a pass — an earlier version of
  # this script redirected into a directory absent on the runner, so pytest never
  # executed and every check below was skipped on the way to printing success.
  if [ ! -s "$JUNIT" ]; then
    echo "       The check did not run; treating that as a failure, not a pass."
    tail -40 "$LOG"
    ci_die "regression-proof — pytest wrote no JUnit report (exit $rc)."
  fi

  # The verdict is per-test and structural (JUnit), not a count scraped from the
  # summary line: a run can be "0 passed" while proving nothing, because a test
  # that ERRORS never reached its assertions. See `report.py regression-proof-verdict`.
  if ! uv run --no-project "$SCRIPT_DIR/report.py" regression-proof-verdict "$JUNIT"; then
    echo "--- pytest output (base revision) ---"
    tail -40 "$LOG"
    exit 1
  fi
}

usage() {
  sed -n '2,20p' "$0" >&2
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    slice)            cmd_slice "$@" ;;
    flake-gate)       cmd_flake_gate "$@" ;;
    regression-proof) cmd_regression_proof "$@" ;;
    *)
      echo "pytest.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
