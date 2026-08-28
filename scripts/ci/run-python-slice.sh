#!/usr/bin/env bash
# Run one test-python slice, on the whole slice or on a test-impact selection.
#
# Node ids can contain spaces and brackets (parametrised tests), so the
# selection is read into a bash array and never round-tripped through an
# unquoted shell expansion or a workflow expression.
#
# Env: SLICE_NAME, SLICE_PATHS, SLICE_IGNORE, XDIST_N, COV_CONTEXT (optional)
set -euo pipefail
cd "$(dirname "$0")/../../apps/api"

SLICE="${SLICE_NAME:?SLICE_NAME required}"
SELECTED=".test-impact/selected-$SLICE.txt"
# Per-runner scratch: /tmp is shared by every runner instance on the home
# box, and twenty lanes writing /tmp/pytest-<slice>.time clobber each other.
SCRATCH="${RUNNER_TEMP:-/tmp}"

# The selection is trusted only when this job's test-impact-select.sh wrote
# it. No file means the selector did not run (or was skipped) — that is ALL,
# stated explicitly. A file that predates this job by hours is a leftover in
# a persistent workspace and is ignored for the same reason: a stale
# selection silently skips tests, running everything never does.
SELECTION="ALL"
if [ ! -f "$SELECTED" ]; then
  echo "Python tests ($SLICE): no $SELECTED — running ALL (no test-impact selection for this job)"
elif [ -n "$(find "$SELECTED" -mmin +360 -print -quit 2>/dev/null)" ]; then
  echo "::warning::$SELECTED is older than 6h (stale from a previous job?) — ignoring it and running ALL"
elif [ "$(head -n1 "$SELECTED")" = "ALL" ]; then
  echo "Python tests ($SLICE): selection says ALL"
else
  SELECTION="FILE"
fi

TARGETS=()
if [ "$SELECTION" = "FILE" ]; then
  while IFS= read -r line; do [ -n "$line" ] && TARGETS+=("$line"); done <"$SELECTED"
  if [ ${#TARGETS[@]} -eq 0 ]; then
    echo "Python tests ($SLICE): SKIPPED (test impact selected 0 tests)"
    exit 0
  fi
  echo "Python tests ($SLICE): running ${#TARGETS[@]} selected targets"
else
  # shellcheck disable=SC2206 # deliberate word splitting: a space-separated path list
  TARGETS=(${SLICE_PATHS:?SLICE_PATHS required})
fi

EXTRA=()
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

/usr/bin/time -v bash ../../scripts/ci/run-tests-flake-gate.sh \
  uv run --frozen pytest -n "${XDIST_N:?XDIST_N required}" --dist worksteal \
  "${TARGETS[@]}" ${EXTRA[@]+"${EXTRA[@]}"} \
  -m 'not composio and not model_onboarding and not schemathesis' \
  --tb=short -q --override-ini=addopts=--strict-markers --timeout=300 \
  --junitxml="test-results/pytest-$SLICE.xml" --durations=30 2>&1 | tee "${SCRATCH}/pytest-${SLICE}.time"
echo "Python tests ($SLICE): OK (xdist=$XDIST_N coverage=${COVERAGE:-off})"
