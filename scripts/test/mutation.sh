#!/usr/bin/env bash
# Mutation spot-check: inject one bug at a time into a module and require the
# test suite to catch it (mutmut). Run on modules you just changed:
#
#   bash scripts/test/mutation.sh app/services/publish_validator.py
#
# The module's own test file is derived (app/services/foo.py ->
# tests/unit/services/test_foo.py); pass it explicitly if it lives elsewhere.
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

TESTFILE="${2:-}"
if [ -z "$TESTFILE" ]; then
  # Derive the natural test file: unit tests mirror app/ with a test_ prefix.
  REL="${MODULE#app/}"
  TESTFILE="tests/unit/$(dirname "$REL")/test_$(basename "$REL" .py).py"
fi
# PR-changed line ranges for this module ([[start,end],...], compact JSON).
# The gate is diff-driven: survivors on lines the PR did not touch are
# noted, not failures. Passed by the CI lane; empty locally.
CHANGED_RANGES="${3:-[]}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT/apps/api"

if [ ! -f "$TESTFILE" ]; then
  echo "test file not found: $TESTFILE — pass it explicitly as the second argument." >&2
  exit 2
fi

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
#
# Placed on tmpfs when the machine offers one. Each invocation copies ~65 MB
# of app + tests + scripts and then has mutmut write a whole mutants/ tree
# beside it; with several modules in flight those writes, not the mutation
# work, set the pace. /dev/shm keeps all of it in RAM. Falls back to the
# working directory on machines without tmpfs (macOS) or when it is nearly
# full, so a constrained box degrades in speed rather than failing.
#
# Real copies, not hardlinks (`cp -al`): the changed-line scoping below
# rewrites $MODULE in place, and a hardlink shares its inode with the file in
# the developer's checkout — the pragma stamping would edit the real source.
# Not symlinks either: a symlinked workdir/app resolves to the SAME inode as
# apps/api/app — if both ever land on sys.path, CPython raises "cannot load
# module more than once per process" when the same file is imported under two
# paths (observed in CI for app.db.chroma).
WORKDIR_BASE="${MUTMUT_WORKDIR_BASE:-}"
if [ -z "$WORKDIR_BASE" ]; then
  WORKDIR_BASE="$(pwd)"
  if [ -d /dev/shm ] && [ -w /dev/shm ]; then
    # Need room for the copy plus mutmut's mutants/ tree; 1 GiB is a
    # comfortable ceiling for a single module.
    SHM_FREE_KB="$(df -Pk /dev/shm 2>/dev/null | awk 'NR==2{print $4}')"
    if [ -n "${SHM_FREE_KB:-}" ] && [ "$SHM_FREE_KB" -gt 1048576 ]; then
      WORKDIR_BASE=/dev/shm
    fi
  fi
fi
WORKDIR="$WORKDIR_BASE/gaia-mutation-$$"
trap '[ -z "${MUTMUT_KEEP_WORKDIR:-}" ] && rm -rf "$WORKDIR"' EXIT
mkdir -p "$WORKDIR"
cp -r app "$WORKDIR/app"
cp -r tests "$WORKDIR/tests"
cp -r scripts "$WORKDIR/scripts"
cp -f pyproject.toml "$WORKDIR/pyproject.toml"
cd "$WORKDIR"

# mutmut 3.x scopes mutation and test selection only via config — point both
# at the module + its test file for this run (the workdir copy is disposable).
python3 - "$MODULE" "$TESTFILE" << 'EOF'
import pathlib
import re
import sys

module, testfile = sys.argv[1], sys.argv[2]
path = pathlib.Path("pyproject.toml")
text = path.read_text()
replacement = (
    f'[tool.mutmut]\n'
    f'source_paths = ["{module}"]\n'
    f'also_copy = ["app", "tests", "scripts"]\n'
    f'max_stack_depth = 8\n'
    f'pytest_add_cli_args_test_selection = ["{testfile}"]\n'
    f'pytest_add_cli_args = ["-p", "no:xdist", "-o", '
    f'\'addopts=-m "not composio and not model_onboarding and not schemathesis" --strict-markers --timeout=300\']\n'
)
text = re.sub(r"(?ms)^\[tool\.mutmut\].*?(?=^\[|\Z)", replacement, text)
path.write_text(text)
EOF

echo "mutating $MODULE (tests: $TESTFILE) ..."

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
    if "$VENV_PY" -m pytest -q "$TESTFILE" -p no:randomly -p no:random-order \
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
  if [ ! -f "$WORKDIR/mutants/mutmut-stats.json" ]; then
    echo "MUTATION RUN FAILED (no state produced) — see mutmut's output above." >&2
    exit 1
  fi
fi

# mutmut results prints every non-killed mutant; only SURVIVED ones are a
# test weakness. "no tests" mutants are uncovered code — informational, not
# a failure. "not checked" mutants mean the run was interrupted — that IS a
# failure (incomplete evidence). Survivors are then classified: cast()-arg
# changes are provably equivalent (typing.cast returns its argument
# unchanged at runtime), and — the diff-driven gate — survivors on lines the
# PR did not change are noted, not failures.
RESULTS="$("$VENV_PY" -m mutmut results 2>/dev/null || true)"
SURVIVORS="$(printf '%s\n' "$RESULTS" | grep "survived" || true)"
NO_TESTS="$(printf '%s\n' "$RESULTS" | grep -c "no tests" || true)"
NOT_CHECKED="$(printf '%s\n' "$RESULTS" | grep -c "not checked" || true)"
if [ "${NOT_CHECKED:-0}" -gt 0 ]; then
  echo "MUTATION RUN INCOMPLETE — $NOT_CHECKED mutant(s) were never checked;" >&2
  echo "the run was interrupted. See mutmut's output above." >&2
  exit 1
fi
REAL_SURVIVORS=""
EQUIVALENT=""
UNCHANGED=""
if [ -n "$SURVIVORS" ]; then
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    # The classifier exits 1 for real (changed/unchanged) survivors — under
    # set -e that would kill the whole gate mid-classification, so the
    # assignment swallows it; the VERDICT value is what matters.
    VERDICT="$("$VENV_PY" - "$line" "$WORKDIR" "$CHANGED_RANGES" << 'EOF' 2>/dev/null
import json
import re
import sys

survivor, workdir, changed_ranges = sys.argv[1].strip().split(": ", 1)[0], sys.argv[2], sys.argv[3]
module, mutant_name = survivor.rsplit(".", 1)
mutant_file = f"{workdir}/mutants/{module.replace('.', '/')}.py"
src = open(mutant_file).read()
# The mutants dict is per function, named without the mutant id:
# mutants_<base>__mutmut['_mutmut_orig'] = <base>__mutmut_orig
base = re.sub(r"__mutmut_\d+$", "", mutant_name)
dict_name = f"mutants_{base}__mutmut"
orig_match = re.search(
    rf"^{re.escape(dict_name)}\['_mutmut_orig'\]\s*=\s*(\w+)", src, re.MULTILINE
)
if not orig_match:
    sys.exit(1)
orig_name = orig_match.group(1)
blocks = re.split(r"^(?:async )?def ", src, flags=re.MULTILINE)
orig_line = None
for i, block in enumerate(blocks):
    if block.split("(", 1)[0].strip() == orig_name:
        orig_line = sum(b.count("\n") for b in blocks[: i + 1])
        break
if orig_line is None:
    sys.exit(1)


def _body(name: str) -> list[str]:
    for block in blocks:
        if block.split("(", 1)[0].strip() == name:
            return block.splitlines()[1:]
    return []


def _normalized(lines: list[str]) -> list[str]:
    # typing.cast(T, x) is documented to return x unchanged at runtime, so a
    # mutant that only changes the type argument is behaviorally identical.
    return [re.sub(r"cast\(\s*[^,)]+,\s*", "cast(_, ", ln) for ln in lines]


orig_lines = _normalized(_body(orig_name))
mut_lines = _normalized(_body(mutant_name))
if orig_lines == mut_lines:
    print("EQUIV")
    sys.exit(0)
# Find the first differing line in the ORIGINAL file.
for i, (a, b) in enumerate(zip(orig_lines, mut_lines)):
    if a != b:
        ranges = json.loads(changed_ranges) if changed_ranges else []
        in_changed = any(start <= orig_line + i <= end for start, end in ranges)
        print(f"CHANGED:{orig_line + i}" if in_changed else f"UNCHANGED:{orig_line + i}")
        sys.exit(1)
print("EQUIV")
sys.exit(0)
EOF
)" || true
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
    esac
  done <<< "$SURVIVORS"
fi
if [ -n "$REAL_SURVIVORS" ]; then
  echo "MUTATION FAILED — the suite would not notice if this code were wrong:" >&2
  echo "$REAL_SURVIVORS" >&2
  exit 1
fi
if [ "${NO_TESTS:-0}" -gt 0 ]; then
  echo "NOTE: $NO_TESTS mutant(s) had no covering tests (uncovered branches)." >&2
fi
if [ -n "$UNCHANGED" ]; then
  echo "NOTE: survivor(s) on lines the PR did not touch (diff-driven gate):" >&2
  echo "$UNCHANGED" >&2
fi
if [ -n "$EQUIVALENT" ]; then
  echo "NOTE: equivalent mutant(s) (cast()-arg changes only — runtime no-ops by" >&2
  echo "      typing.cast's contract):" >&2
  echo "$EQUIVALENT" >&2
fi
echo "Mutation: OK — no survivors on changed lines in $MODULE"
