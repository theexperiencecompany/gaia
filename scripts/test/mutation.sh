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
#   1. mutmut copies the module into mutants/ with every single-operator bug
#      (a mutant) pre-injected, wrapped in trampolines that record per-test
#      coverage.
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
# Repo integration notes (why the config looks the way it does, see
# [tool.mutmut] in apps/api/pyproject.toml): mutmut runs pytest from a
# mutants/ dir that only contains mutated files — our conftest imports the
# whole app, so also_copy mirrors app/ + tests/ + scripts/ into it. The
# repo's pytest.ini addopts carry -n 4 (xdist), but mutmut's trampoline
# stats are collected by in-process pytest plugins — xdist workers would run
# the tests where the collector does not exist — so the run forces a single
# process with the standard markers minus xdist.
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

cd "$(dirname "$0")/../.." # repo root
cd apps/api

if [ ! -f "$TESTFILE" ]; then
  echo "test file not found: $TESTFILE — pass it explicitly as the second argument." >&2
  exit 2
fi

PYPROJECT="pyproject.toml"
backup="$(mktemp)"
cp -f "$PYPROJECT" "$backup"
restore() { cp -f "$backup" "$PYPROJECT"; rm -f "$backup"; rm -rf mutants; }
trap restore EXIT

# Fresh state every run: a stale mutants/ dir (e.g. after editing the module
# or its tests) triggers mutmut's dependency-change handling and aborts.
rm -rf mutants

# mutmut 3.x scopes mutation and test selection only via config — point both
# at the module + its test file for this run; restored on exit.
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
    f'pytest_add_cli_args_test_selection = ["{testfile}"]\n'
    f'pytest_add_cli_args = ["-p", "no:xdist", "-o", '
    f'\'addopts=-m "not composio and not model_onboarding and not schemathesis" --strict-markers --timeout=300\']\n'
)
text = re.sub(r"(?ms)^\[tool\.mutmut\].*?(?=^\[|\Z)", replacement, text)
path.write_text(text)
EOF

echo "mutating $MODULE (tests: $TESTFILE) ..."
uv run --group backend --group dev mutmut run

# mutmut results prints nothing when every mutant is killed; any output is a
# survivor (or suspicious/timeout) table — a test the suite would not catch.
RESULTS="$(uv run --group backend --group dev mutmut results 2>/dev/null || true)"
if [ -n "$RESULTS" ]; then
  echo "MUTATION FAILED — the suite would not notice if this code were wrong:"
  echo "$RESULTS"
  exit 1
fi
echo "Mutation: OK — no survivors in $MODULE"
