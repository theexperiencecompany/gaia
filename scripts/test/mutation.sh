#!/usr/bin/env bash
# Mutation spot-check: inject one bug at a time into a module and require the
# test suite to catch it (mutmut). Run on modules you just changed:
#
#   bash scripts/test/mutation.sh app/services/publish_validator.py
#
# The module's own test file is derived (app/services/foo.py ->
# tests/unit/services/test_foo.py); pass it explicitly if it lives elsewhere.
# Argument 2 also accepts a compact JSON array of paths, which is how the CI
# lane passes every test file that references the module rather than one:
#
#   bash scripts/test/mutation.sh app/x.py '["tests/unit/a.py","tests/unit/b.py"]'
#
# How it works (mutmut 3.x):
#   1. mutmut copies the module into a mutants/ dir with every single-operator
#      bug (a mutant) pre-injected, wrapped in trampolines that record
#      per-test coverage.
#   2. It runs the module's test file once (stats phase) to map tests ->
#      mutants, then runs each mutant against only the tests that cover it.
#   3. A mutant is KILLED if a test fails, SURVIVED if all tests still pass.
#      Zero survivors is the bar — a surviving mutant is a test that runs
#      but asserts nothing meaningful.
#
# Coverage says a line RAN; mutation says the suite would NOTICE if that line
# were wrong. This is the quality-over-quantity instrument: run it on
# money/security/parse modules you touch, not as a CI gate.
#
# Parallel-safety: every invocation works in its own .mutation-$$ workdir
# (symlinked app/tests/scripts + a copied pyproject.toml), so concurrent
# runs — the CI lane uses xargs -P — never race on shared config or the
# mutants/ dir. The workdir is removed on exit no matter what.
#
# Repo integration notes (see [tool.mutmut] in apps/api/pyproject.toml):
# mutmut runs pytest from a mutants/ dir that only contains mutated files —
# our conftest imports the whole app, so also_copy mirrors app/ + tests/ +
# scripts/ into it. The repo's pytest.ini addopts carry -n 4 (xdist), but
# mutmut's trampoline stats are collected by in-process pytest plugins —
# xdist workers would run the tests where the collector does not exist — so
# the run forces a single process with the standard markers minus xdist.
set -euo pipefail

MODULE="${1:?usage: mutation.sh <module> [test-file] (e.g. app/services/foo.py)}"
case "$MODULE" in
  apps/api/app/*) MODULE="${MODULE#apps/api/}" ;;
  app/*) : ;;
  *) echo "module must be under app/ (e.g. app/services/foo.py)" >&2; exit 2 ;;
esac

TESTFILE_ARG="${2:-}"
if [ -z "$TESTFILE_ARG" ]; then
  # Derive the natural test file: unit tests mirror app/ with a test_ prefix.
  REL="${MODULE#app/}"
  TESTFILE_ARG="tests/unit/$(dirname "$REL")/test_$(basename "$REL" .py).py"
fi
# PR-changed line ranges for this module ([[start,end],...], compact JSON).
# The gate is diff-driven: survivors on lines the PR did not touch are
# noted, not failures. Passed by the CI lane; empty locally.
CHANGED_RANGES="${3:-[]}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT/apps/api"

# Argument 2 is either ONE path — what a human types, and what the derived
# default above produces — or a compact JSON array of them, which is how the CI
# lane passes every test file that references the module instead of whichever
# one happened to sort first. A leading '[' is the discriminator; no real path
# starts with one. Both forms are supported on purpose: the single-path form is
# the documented local usage, and breaking it to serve CI would be the trade
# backwards.
TESTFILES=()
case "$TESTFILE_ARG" in
  \[*)
    TESTFILES_RAW="$(python3 - "$TESTFILE_ARG" << 'EOF'
import json
import sys

try:
    files = json.loads(sys.argv[1])
except json.JSONDecodeError as exc:
    raise SystemExit(f"argument 2 starts with '[' but is not valid JSON: {exc}")
if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
    raise SystemExit("argument 2 must be a JSON array of path strings")
if not files:
    raise SystemExit("argument 2 is an empty JSON array — no test file to run")
print("\n".join(files))
EOF
)" || exit 2
    while IFS= read -r testfile; do
      if [ -n "$testfile" ]; then
        TESTFILES+=("$testfile")
      fi
    done <<< "$TESTFILES_RAW"
    ;;
  *) TESTFILES=("$TESTFILE_ARG") ;;
esac
# Named individually: "one of these does not exist" is useless when the list
# came from a generator.
for testfile in "${TESTFILES[@]}"; do
  if [ ! -f "$testfile" ]; then
    echo "test file not found: $testfile — pass it explicitly as the second argument." >&2
    exit 2
  fi
done

VENV_PY=""
for candidate in "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/apps/api/.venv/bin/python"; do
  if [ -x "$candidate" ]; then
    VENV_PY="$candidate"
    break
  fi
done
if [ -z "$VENV_PY" ]; then
  echo "ERROR: mutation.sh — venv python not found (run nx run api:sync first)." >&2
  exit 1
fi

# Per-invocation workdir: parallel-safe isolation for the config swap, the
# mutants/ dir, and the pytest run. Absolute path: the trap runs after
# `cd "$WORKDIR"`, so a relative path would delete the wrong directory.
# Real copies, not symlinks: a symlinked workdir/app resolves to the SAME
# inode as apps/api/app — if both ever land on sys.path, CPython raises
# "cannot load module more than once per process" when the same file is
# imported under two paths (observed in CI for app.db.chroma).
WORKDIR="$(pwd)/.mutation-$$"
trap '[ -z "${MUTMUT_KEEP_WORKDIR:-}" ] && rm -rf "$WORKDIR"' EXIT
mkdir -p "$WORKDIR"
cp -r app "$WORKDIR/app"
cp -r tests "$WORKDIR/tests"
cp -r scripts "$WORKDIR/scripts"
cp -f pyproject.toml "$WORKDIR/pyproject.toml"
cd "$WORKDIR"

# mutmut 3.x scopes mutation and test selection only via config — point both
# at the module + its test file(s) for this run (the workdir copy is disposable).
python3 - "$MODULE" "${TESTFILES[@]}" << 'EOF'
import json
import pathlib
import re
import sys

module, testfiles = sys.argv[1], sys.argv[2:]
path = pathlib.Path("pyproject.toml")
text = path.read_text()
selection = ", ".join(json.dumps(testfile) for testfile in testfiles)
replacement = (
    f'[tool.mutmut]\n'
    f'source_paths = ["{module}"]\n'
    f'also_copy = ["app", "tests", "scripts"]\n'
    f'max_stack_depth = 8\n'
    f'pytest_add_cli_args_test_selection = [{selection}]\n'
    f'pytest_add_cli_args = ["-p", "no:xdist", "-o", '
    f'\'addopts=-m "not composio and not model_onboarding and not schemathesis" --strict-markers --timeout=300\']\n'
)
text = re.sub(r"(?ms)^\[tool\.mutmut\].*?(?=^\[|\Z)", replacement, text)
path.write_text(text)
EOF

echo "mutating $MODULE (tests: ${TESTFILES[*]}) ..."

# Diff-driven scoping: mutmut has no "mutate only these lines" config, but
# it honors `# pragma: no mutate` comments. Stamp the pragma onto every line
# OUTSIDE the PR's changed ranges in the workdir copy, so only the changed
# lines' constructs get mutants — a 1-line import change then costs seconds,
# not a 30-minute full-module run. Blank/comment/backslash-continuation
# lines are skipped (the pragma would break a line continuation). The
# survivor-verdict layer below stays as defense-in-depth.
if [ "$CHANGED_RANGES" != "[]" ]; then
  python3 - "$MODULE" "$CHANGED_RANGES" << 'EOF'
import json
import sys

module, ranges_json = sys.argv[1], sys.argv[2]
changed = {ln for start, end in json.loads(ranges_json) for ln in range(start, end + 1)}
lines = open(module).read().splitlines()
out = []
for i, line in enumerate(lines, 1):
    stripped = line.strip()
    if (
        i not in changed
        and stripped
        and not stripped.startswith("#")
        and not line.rstrip().endswith("\\")
    ):
        out.append(line + "  # pragma: no mutate")
    else:
        out.append(line)
open(module, "w").write("\n".join(out) + "\n")
EOF
fi
MUTMUT_RC=0
# timeout: mutmut can finish its work and then hang at interpreter teardown
# (threads from C-extension-heavy test runs keep the process alive — seen
# with the chroma tests), so the pipeline never completes and the lane
# hangs. 15 minutes covers even a full-module local run; scoped CI runs
# finish in well under a minute. A hang past the cap leaves the state for
# the verdict below to judge (not-checked mutants fail it loudly). The
# wrapper is a portable `timeout`: GNU coreutils' binary is missing on
# macOS, and the process-group kill takes mutmut's mutant children with it.
# The decorated-function patch (mutmut_decorated_patch.py) is imported
# first so endpoints and other decorated functions become mutation targets.
MUTMUT_PATCH_DIR="$REPO_ROOT/scripts/test"
# Absolute: the run cd's into $WORKDIR, so a relative path resolves nowhere.
CLASSIFIER="$REPO_ROOT/scripts/test/mutation_classify.py"
"$VENV_PY" -c "
import os
import signal
import subprocess
import sys

env = dict(os.environ)
patch_dir = sys.argv[1]
env['PYTHONPATH'] = patch_dir + os.pathsep + env.get('PYTHONPATH', '')
max_children = os.environ.get('MUTMUT_MAX_CHILDREN', '')
run_args = ['run'] + (['--max-children', max_children] if max_children else [])
# Pre-import the C-extension-heavy modules in the MUTMUT process BEFORE it
# starts: the covered-lines coverage pass unloads every module imported
# during the stats run, and numpy/PyO3 extensions cannot be re-imported in
# one process. Anything imported here is in the baseline snapshot and never
# unloaded.
child_code = (
    'import mutmut_decorated_patch; '
    'import sys as _sys; '
    f'_sys.argv += {run_args!r}; '
    'from mutmut.__main__ import cli; cli()'
)
proc = subprocess.Popen(
    [sys.executable, '-c', child_code],
    env=env,
    start_new_session=True,
)
try:
    proc.communicate(timeout=900)
except subprocess.TimeoutExpired:
    os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()
    sys.exit(124)
sys.exit(proc.returncode)
" "$MUTMUT_PATCH_DIR" 2>&1 | tee "$WORKDIR/mutmut.log" >&2 || MUTMUT_RC=$?
if [ "$MUTMUT_RC" -ne 0 ]; then
  # mutmut 3.7 cannot mutate decorated functions (verified in its source:
  # file_mutation.py skips every FunctionDef with decorators — FastAPI
  # endpoints, @Cacheable wrappers, etc. are never mutated). When the
  # module's exercised code is all decorated, the stats phase finds no
  # mutant with covering tests and stops early. That is a tool limitation,
  # not a test weakness — the endpoint tests + diff-cover carry that
  # surface. Skip with a reason instead of failing the lane.
  if grep -q "could not find any test case for any mutant" "$WORKDIR/mutmut.log"; then
    echo "SKIP: $MODULE — no mutant had covering tests. Causes:" >&2
    echo "      mutmut 3.7 cannot mutate decorated functions (FastAPI" >&2
    echo "      endpoints, @Cacheable, ...), and with the diff-driven scoping" >&2
    echo "      the changed lines may hold nothing mutatable (imports," >&2
    echo "      decorators, strings). The changed behavior is covered by the" >&2
    echo "      module's tests + diff-cover." >&2
    exit 0
  fi
  # mutmut's stats/clean/mutant phases share ONE process, so module-level
  # state (singletons, caches) can leak between phases and break the clean
  # run even though the tests are fine. Self-verify: run the same selection
  # in the plain workdir copy. Passes there -> mutmut-phase artifact, skip
  # with a reason. Fails there too -> a real breakage, fail loudly.
  if grep -q "Failed to run clean test" "$WORKDIR/mutmut.log"; then
    if "$VENV_PY" -m pytest -q "${TESTFILES[@]}" -p no:randomly -p no:random-order \
        -o 'addopts=-m "not composio and not model_onboarding and not schemathesis" --strict-markers --timeout=300' \
        > "$WORKDIR/plain-check.log" 2>&1; then
      echo "SKIP: $MODULE — the tests pass in the plain copy but fail under"
      echo "      mutmut's single-process phase transitions. Module-level state"
      echo "      (singletons/caches) does not survive stats->clean->mutants in"
      echo "      one process — a documented mutmut 3.7 limitation for such modules."
      exit 0
    fi
    echo "REAL FAILURE: $MODULE's tests fail in the plain copy too — see" >&2
    echo "  $WORKDIR/plain-check.log (and mutmut's output above)." >&2
    exit 1
  fi
  # A nonzero exit AFTER the mutants ran is usually the loguru teardown
  # crash (forked children + the app's loop-bound redis client write to a
  # closed stream at interpreter shutdown) — the verdict below is the
  # source of truth, and an incomplete run is caught by the not-checked
  # check. Fail only if mutmut produced nothing at all.
  # mutmut's trampoline resolves the CALLER frame with
  # Path(filename).resolve(strict=True). A module that calls one of its own
  # mutated functions at import time is entered from <frozen
  # importlib._bootstrap>, which is not a real path, so the stats phase dies
  # before a single test runs. Same class of tool limitation as the two above —
  # the module's own tests pass normally — so skip with a reason rather than
  # reporting a test weakness that is not there.
  if grep -q "No such file or directory: '<frozen importlib._bootstrap>'" "$WORKDIR/mutmut.log"; then
    echo "SKIP: $MODULE — mutmut cannot collect stats for a module that invokes its" >&2
    echo "      own function at import time: the trampoline resolves the calling" >&2
    echo "      frame, which during import is <frozen importlib._bootstrap>." >&2
    exit 0
  fi
  if [ ! -f "$WORKDIR/mutants/mutmut-stats.json" ]; then
    echo "MUTATION RUN FAILED (no state produced) — see mutmut's output above." >&2
    exit 1
  fi
fi

# Only two of mutmut's statuses are a VERDICT: killed (the suite caught the
# bug) and survived (it did not). Everything else — suspicious, no tests,
# timeout, skipped, not checked — means no verdict was reached, which is not
# the same thing as no failure. "not checked" mutants mean the run was
# interrupted; that IS a failure (incomplete evidence). Survivors are then
# classified: cast()-arg changes are provably equivalent (typing.cast returns
# its argument unchanged at runtime), so are falsy .get() defaults nothing
# but a truthiness test consumes (see _unobservable_get_default), and — the
# diff-driven gate — survivors on lines the PR did not change are noted,
# not failures.
#
# `results --all True` lists EVERY mutant with its status, one line each;
# plain `results` omits the killed ones, and whether anything was killed at
# all is exactly what says the run proved something. Its failure is NOT
# swallowed: an unreadable read used to be indistinguishable from a clean
# run, which is the same silence-read-as-success bug the no-verdict guard
# below exists to stop.
if ! RESULTS="$("$VENV_PY" -m mutmut results --all True 2>"$WORKDIR/results-err.log")"; then
  echo "MUTATION RESULTS UNREADABLE — 'mutmut results' failed for $MODULE:" >&2
  cat "$WORKDIR/results-err.log" >&2
  exit 1
fi
# Anchored on the status suffix: with killed mutants now in the listing, a
# bare substring match would miscount any mutant whose own name contains a
# status word.
TOTAL="$(printf '%s\n' "$RESULTS" | grep -c . || true)"
KILLED="$(printf '%s\n' "$RESULTS" | grep -c ": killed$" || true)"
SUSPICIOUS="$(printf '%s\n' "$RESULTS" | grep -c ": suspicious$" || true)"
SURVIVORS="$(printf '%s\n' "$RESULTS" | grep ": survived$" || true)"
SURVIVED="$(printf '%s\n' "$SURVIVORS" | grep -c . || true)"
NO_TESTS_LIST="$(printf '%s\n' "$RESULTS" | grep ": no tests$" || true)"
NO_TESTS="$(printf '%s\n' "$NO_TESTS_LIST" | grep -c . || true)"
NOT_CHECKED="$(printf '%s\n' "$RESULTS" | grep -c ": not checked$" || true)"
if [ "${NOT_CHECKED:-0}" -gt 0 ]; then
  echo "MUTATION RUN INCOMPLETE — $NOT_CHECKED mutant(s) were never checked;" >&2
  echo "the run was interrupted. See mutmut's output above." >&2
  exit 1
fi
if [ "${SUSPICIOUS:-0}" -gt 0 ]; then
  echo "NOTE: $SUSPICIOUS of $TOTAL mutant(s) came back 'suspicious' — mutmut's" >&2
  echo "      bucket for a test process that exited in none of the ways it knows" >&2
  echo "      how to read. A suspicious mutant proves NOTHING: it was neither" >&2
  echo "      killed nor shown to survive. Do not read this count as good or bad." >&2
  echo "      It is NOT a timeout — mutmut buckets those separately, and does so" >&2
  echo "      correctly. The observed cause is the forked child dying on SIGTRAP" >&2
  echo "      (exit code -5) before writing a byte, when the test file is re-run" >&2
  echo "      inside the fork. Reproducible without mutmut: fork at" >&2
  echo "      pytest_sessionfinish and call pytest.main() on the same file — the" >&2
  echo "      bare fork is clean, the re-run is what dies. Seen only with" >&2
  echo "      tests/integration/agents/test_harness_completion.py; every tests/unit" >&2
  echo "      file measured so far forks and re-runs cleanly. WHICH library makes" >&2
  echo "      the child fork-unsafe is still unidentified." >&2
fi
# The no-verdict guard. Reaching zero survivors because every mutant was
# killed and reaching it because no mutant reached a verdict at all are
# opposite outcomes, and the old check — which counted only survivors — could
# not tell them apart. Observed on app/override/langgraph_bigtool/create_agent.py
# against tests/integration/agents/test_harness_completion.py: 210 mutants,
# 0 killed, 0 survived, 210 suspicious, and the gate printed OK with rc=0.
if [ "${KILLED:-0}" -eq 0 ] && [ "${SURVIVED:-0}" -eq 0 ] && [ "${TOTAL:-0}" -gt 0 ]; then
  echo "MUTATION PROVED NOTHING — all $TOTAL mutant(s) of $MODULE ran and not one" >&2
  echo "was killed or survived, so the suite was never shown to catch OR miss a" >&2
  echo "bug here. Buckets: $SUSPICIOUS suspicious, $NO_TESTS no tests," >&2
  echo "$((TOTAL - SUSPICIOUS - NO_TESTS)) other. Passing this as OK is the false" >&2
  echo "green this guard exists to stop — fix the run or pick a test file that" >&2
  echo "actually exercises the module." >&2
  exit 1
fi
REAL_SURVIVORS=""
EQUIVALENT=""
UNCHANGED=""
LOGGING=""
if [ -n "$SURVIVORS" ]; then
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    # The classifier exits 1 for a verdict the lane must act on and 0 for
    # EQUIV, so set -e would kill the gate mid-classification: capture the
    # status instead of swallowing it. An unrecognised verdict is a classifier
    # failure and fails the lane below — a mutant that quietly leaves every
    # bucket is the same silence-read-as-success this gate exists to stop.
    CLASSIFIER_RC=0
    VERDICT="$("$VENV_PY" "$CLASSIFIER" "$line" "$WORKDIR" "$CHANGED_RANGES" "$MODULE")" || CLASSIFIER_RC=$?
    case "$VERDICT" in
      EQUIV)
        EQUIVALENT="$EQUIVALENT
$line" ;;
      CHANGED:*)
        REAL_SURVIVORS="$REAL_SURVIVORS
$line" ;;
      UNCHANGED:*)
        UNCHANGED="$UNCHANGED
$line" ;;
      LOGGING:*)
        LOGGING="$LOGGING
$line" ;;
      *)
        echo "MUTATION CLASSIFIER FAILED on: $line" >&2
        echo "  exit=$CLASSIFIER_RC verdict='$VERDICT'" >&2
        echo "  A survivor with no verdict must not vanish from every bucket." >&2
        echo "  Re-run: $VENV_PY $CLASSIFIER '$line' '$WORKDIR' '$CHANGED_RANGES' '$MODULE'" >&2
        exit 1 ;;
    esac
  done <<< "$SURVIVORS"
fi
NO_TESTS_CHANGED=""
if [ -n "$NO_TESTS_LIST" ]; then
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    CLASSIFIER_RC=0
    VERDICT="$("$VENV_PY" "$CLASSIFIER" "$line" "$WORKDIR" "$CHANGED_RANGES" "$MODULE")" || CLASSIFIER_RC=$?
    case "$VERDICT" in
      CHANGED:*)
        NO_TESTS_CHANGED="$NO_TESTS_CHANGED
$line" ;;
      UNCHANGED:*|LOGGING:*|EQUIV) ;;
      *)
        echo "MUTATION CLASSIFIER FAILED on: $line" >&2
        echo "  exit=$CLASSIFIER_RC verdict='$VERDICT'" >&2
        echo "  A survivor with no verdict must not vanish from every bucket." >&2
        echo "  Re-run: $VENV_PY $CLASSIFIER '$line' '$WORKDIR' '$CHANGED_RANGES' '$MODULE'" >&2
        exit 1 ;;
    esac
  done <<< "$NO_TESTS_LIST"
fi
if [ -n "$NO_TESTS_CHANGED" ]; then
  NO_TESTS_CHANGED_COUNT=$(printf '%s\n' "$NO_TESTS_CHANGED" | grep -c . || true)
  echo "NOTE: $NO_TESTS_CHANGED_COUNT mutant(s) ON CHANGED LINES have NO covering test." >&2
  echo "      Not survivors, and not a pass either: nothing exercises them, so this" >&2
  echo "      lane can say nothing about that code. A changed line landing here is a" >&2
  echo "      coverage hole wearing a clean result. Printed before the verdict" >&2
  echo "      because a FAILING run is when it is easiest to miss:" >&2
  echo "$NO_TESTS_CHANGED" >&2
fi
if [ "${NO_TESTS:-0}" -gt 0 ]; then
  echo "NOTE: $NO_TESTS mutant(s) had no covering test across the WHOLE module" >&2
  echo "      (the line above is the subset on changed lines, which is the one" >&2
  echo "      this PR owns; the rest are pre-existing and reach the run only" >&2
  echo "      because the no-mutate pragma leaks on multi-line statements)." >&2
fi
if [ -n "$UNCHANGED" ]; then
  echo "NOTE: survivor(s) on lines the PR did not touch (diff-driven gate):" >&2
  echo "$UNCHANGED" >&2
fi
if [ -n "$EQUIVALENT" ]; then
  echo "NOTE: provably equivalent mutant(s) — a cast() type argument (a runtime" >&2
  echo "      no-op by typing.cast contract), or a falsy .get() default that only" >&2
  echo "      ever reaches a truthiness test ('x or y', 'if x:', 'x if x else y'," >&2
  echo "      or code such a test guards), where every falsy value takes the same" >&2
  echo "      branch. Truthy defaults are NOT covered: d.get(k, 1) or 0 really" >&2
  echo "      does return 1 when the key is missing. One further one-off:" >&2
  echo "      json.dumps' ensure_ascii, which json documents as a truth value." >&2
  echo "$EQUIVALENT" >&2
fi
if [ -n "$LOGGING" ]; then
  LOGGING_COUNT=$(printf '%s\n' "$LOGGING" | grep -c . || true)
  echo "NOTE: $LOGGING_COUNT mutant(s) excluded as logging-only — the mutation lands" >&2
  echo "      inside a log.debug/log.info call, the only two levels that never reach" >&2
  echo "      the wide event (wide_events.py: they emit a loguru line and stop, while" >&2
  echo "      warning/error/critical/exception _append msg AND kwargs to" >&2
  echo "      warnings[]/errors[], where a test can and should assert them). Counted" >&2
  echo "      only for mutants on lines the PR changed, and printed before the" >&2
  echo "      verdict so an exclusion is never invisible, including on a failing run:" >&2
  echo "$LOGGING" >&2
fi
if [ -n "$REAL_SURVIVORS" ]; then
  echo "MUTATION FAILED — the suite would not notice if this code were wrong:" >&2
  echo "$REAL_SURVIVORS" >&2
  exit 1
fi
echo "Mutation: OK — no survivors on changed lines in $MODULE"
