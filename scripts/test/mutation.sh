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
# mutants/ dir, and the pytest run. Symlinks keep the copies cheap. Absolute
# path: the trap runs after `cd "$WORKDIR"`, so a relative path would delete
# the wrong directory (or nothing).
WORKDIR="$(pwd)/.mutation-$$"
trap 'rm -rf "$WORKDIR"' EXIT
mkdir -p "$WORKDIR"
ln -s ../app "$WORKDIR/app"
ln -s ../tests "$WORKDIR/tests"
ln -s ../scripts "$WORKDIR/scripts"
cp -f pyproject.toml "$WORKDIR/pyproject.toml"
cd "$WORKDIR"

# mutmut 3.x scopes mutation and test selection only via config — point both
# at the module + its test file for this run (the workdir copy is disposable).
# mutate_only_covered_lines: never waste mutants on lines the tests do not
# run — and if the module's lines are uncovered, zero mutants are created
# and the run fails loudly instead of silently "passing".
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
    f'mutate_only_covered_lines = true\n'
    f'pytest_add_cli_args_test_selection = ["{testfile}"]\n'
    f'pytest_add_cli_args = ["-p", "no:xdist", "-o", '
    f'\'addopts=-m "not composio and not model_onboarding and not schemathesis" --strict-markers --timeout=300\']\n'
)
text = re.sub(r"(?ms)^\[tool\.mutmut\].*?(?=^\[|\Z)", replacement, text)
path.write_text(text)
EOF

echo "mutating $MODULE (tests: $TESTFILE) ..."
if ! "$VENV_PY" -m mutmut run; then
  echo "MUTATION RUN FAILED — see mutmut's output above. Likely causes:" >&2
  echo "  - zero mutants created: the tests do not cover $MODULE's lines" >&2
  echo "    (mutate_only_covered_lines) — the tests may exist but never run this code." >&2
  echo "  - a mutant killed the test run itself (a real bug the tests surface)." >&2
  exit 1
fi

# mutmut results prints nothing when every mutant is killed; any output is a
# survivor (or suspicious/timeout) table — a test the suite would not catch.
RESULTS="$("$VENV_PY" -m mutmut results 2>/dev/null || true)"
if [ -n "$RESULTS" ]; then
  echo "MUTATION FAILED — the suite would not notice if this code were wrong:" >&2
  echo "$RESULTS" >&2
  exit 1
fi
echo "Mutation: OK — no survivors in $MODULE"
