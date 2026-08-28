#!/usr/bin/env bash
# Run the FULL mutation gate locally, exactly as the CI lane runs it.
#
#   bash scripts/test/mutation-local.sh              # every changed module
#   bash scripts/test/mutation-local.sh app/x.py ... # only these modules
#
# The CI lane splits the same module list across 12 GitHub jobs; there is no
# second gate here, just the same matrix run on one machine. Modules run
# concurrently (override with MUTATION_JOBS=1 for readable output), each into
# its own log under verify-logs/mutation/.
#
# Why this exists: the lane's own command (`mutation-plan.sh && mutation-shard.sh`)
# is CI-shaped — the plan writes its matrix to $GITHUB_OUTPUT and the shard
# reads $GROUP from the job matrix, so run outside Actions the shard starts
# with no GROUP and mutates nothing. This wires the two together locally.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

LOG_DIR="verify-logs/mutation"
rm -rf "$LOG_DIR"
mkdir -p "$LOG_DIR"

if [ "$#" -gt 0 ]; then
  MATRIX="$(printf '%s\n' "$@" | sed 's|^apps/api/||; s|^|apps/api/|' |
    python3 scripts/ci/mutation-matrix.py)" || exit 1
else
  MATRIX="$(bash scripts/ci/mutation-matrix.sh)" || exit 1
fi

MODULE_COUNT="$(MATRIX="$MATRIX" python3 -c 'import json,os;print(len(json.loads(os.environ["MATRIX"])))')"
if [ "$MODULE_COUNT" = "0" ]; then
  echo "mutation: no changed app modules — nothing to mutate"
  exit 0
fi

# One TSV row per module, the same three fields mutation-shard.sh reads.
TSV="$(mktemp)"
trap 'rm -f "$TSV"' EXIT
MATRIX="$MATRIX" python3 - > "$TSV" <<'PY'
import json
import os

for entry in json.loads(os.environ["MATRIX"]):
    print(
        "\t".join(
            (
                entry["module"],
                json.dumps(entry["testfiles"], separators=(",", ":")),
                json.dumps(entry["changed_lines"], separators=(",", ":")),
            )
        )
    )
PY

echo "mutation: $MODULE_COUNT module(s), logs in $LOG_DIR/"

# Each module is its own single-module shard: same runner as CI, so a local
# pass and a lane pass mean the same thing.
run_one() {
  local module="$1" testfiles="$2" ranges="$3"
  local slug="${module//\//_}"
  GROUP="$(module="$module" testfiles="$testfiles" ranges="$ranges" python3 -c '
import json
import os

print(
    json.dumps(
        [{k: os.environ[k] for k in ("module", "testfiles", "ranges")}],
        separators=(",", ":"),
    )
)')" \
    SHARD_LOG="$LOG_DIR/$slug.log" \
    bash scripts/ci/mutation-shard.sh > "$LOG_DIR/$slug.out" 2>&1
  local rc=$?
  # Recorded to a file, not inferred from the log afterwards: a clean run that
  # generated no mutants at all (decorated functions, changed lines that hold
  # only imports) never prints a verdict line, so grepping for one reports a
  # pass as a crash. The exit code is the only honest signal.
  if [ "$rc" = "0" ]; then
    echo "pass" > "$LOG_DIR/$slug.status"
    echo "  pass      $module"
  elif grep -q "MUTATION FAILED" "$LOG_DIR/$slug.log" 2> /dev/null; then
    echo "survivors" > "$LOG_DIR/$slug.status"
    echo "  SURVIVORS $module  ($LOG_DIR/$slug.log)"
  else
    # mutmut never produced a result — a crash, or the suite's pytest-timeout
    # firing under load. Reporting this as "survivors" would send you hunting
    # for a test gap that does not exist.
    echo "error" > "$LOG_DIR/$slug.status"
    echo "  ERROR     $module  (run produced no result; $LOG_DIR/$slug.log)"
  fi
  return $rc
}

JOBS="${MUTATION_JOBS:-2}"

# Batch-and-wait rather than `wait -n`: macOS ships bash 3.2, where `wait -n`
# does not exist. It fails instantly there, so the scheduler never waits, the
# summary races the jobs still writing their results, and every run reports
# whatever happened to be on disk at that moment.
running=0
while IFS=$'\t' read -r module testfiles ranges; do
  [ -n "$module" ] || continue
  run_one "$module" "$testfiles" "$ranges" &
  running=$((running + 1))
  if [ "$running" -ge "$JOBS" ]; then
    wait
    running=0
  fi
done < "$TSV"
wait

# The verdict comes from the per-module status files the jobs wrote.
failed=""
errored=""
while IFS=$'\t' read -r module _ _; do
  [ -n "$module" ] || continue
  slug="${module//\//_}"
  case "$(cat "$LOG_DIR/$slug.status" 2> /dev/null)" in
    pass) ;;
    survivors) failed="$failed $module" ;;
    *) errored="$errored $module" ;;
  esac
done < "$TSV"

if [ -n "$errored" ]; then
  echo
  echo "mutation: module(s) produced NO result (crash or timeout, not survivors):"
  for m in $errored; do echo "  $m"; done
  echo "  Retry these with MUTATION_JOBS=1 before believing anything about them."
fi
if [ -n "$failed" ]; then
  echo
  echo "mutation: module(s) with survivors on changed lines:"
  for m in $failed; do echo "  $m"; done
fi
if [ -n "$failed" ] || [ -n "$errored" ]; then
  exit 1
fi
echo "mutation: all $MODULE_COUNT module(s) clean"
